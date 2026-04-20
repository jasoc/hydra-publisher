#!/usr/bin/env python3
"""
hydra-publisher Python provider server.

Started by the Rust backend. Communicates via HTTP on localhost.

Usage:
    python3 server.py [--port PORT]

    PORT defaults to 0 (OS picks a free port).
    Once ready the server prints "LISTENING:<port>" to stdout so the Rust
    caller can discover which port was assigned.

Endpoints:
    POST /<provider_id>/publish   body: article JSON
    POST /<provider_id>/update    body: article JSON
    POST /stop                    graceful shutdown (closes browser sessions)
"""

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

# Ensure the directory containing this script is on sys.path so that the
# provider modules are importable regardless of the working directory from
# which the process is spawned.
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
# In dev mode the providers live in providers/; in the bundled app everything
# is flattened into the same directory, so this is a no-op there.
_providers_dir = os.path.join(_script_dir, "providers")
if os.path.isdir(_providers_dir):
    sys.path.insert(0, _providers_dir)

# Import provider classes directly (the bundle flattens all files into python/)
from base import SeleniumProvider  # noqa: E402
from subito import SubitoProvider  # noqa: E402
from local_test_selenium import LocalTestSeleniumProvider  # noqa: E402
from facebook_marketplace import FacebookMarketplaceProvider  # noqa: E402
from vinted import VintedProvider  # noqa: E402

# Registry: maps platform id (used by Rust) → provider instance.
# Add new providers here.
PROVIDERS = {
    "subito": SubitoProvider(),
    "local_test_selenium": LocalTestSeleniumProvider(),
    "facebook_marketplace": FacebookMarketplaceProvider(),
    "vinted": VintedProvider(),
}

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Mozilla/5.0 (iPhone14,3; U; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/19A346 Safari/602.1"
]

# Active Selenium WebDriver instances, keyed by provider id.
# Each entry is created on the first call to a SeleniumProvider and reused
# for all subsequent calls so the user only needs to log in once per session.
_selenium_sessions: Dict[str, Any] = {}
_shutdown_event = threading.Event()


def _get_or_create_driver(provider_id: str, provider: SeleniumProvider) -> Any:
    """
    Return the cached WebDriver for this provider, or start a new browser
    session if none exists or the previous one died (user closed Chrome).
    On first creation, provider.login(driver) is called.
    """
    if provider_id in _selenium_sessions:
        driver = _selenium_sessions[provider_id]
        # Check if the browser is still alive
        try:
            _ = driver.title  # will throw if the session is dead
            return driver
        except Exception:
            print(f"[server] Session for {provider_id!r} is dead, recreating...")
            _selenium_sessions.pop(provider_id, None)

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    # Persistent Chrome profile per provider so sessions survive restarts
    profile_dir = os.path.expanduser(f"~/.hydra-publisher/chrome-profiles/{provider_id}")
    os.makedirs(profile_dir, exist_ok=True)

    def _build_options(user_data_dir: str | None) -> Options:
        opts = Options()
        if user_data_dir:
            opts.add_argument(f"--user-data-dir={user_data_dir}")
        # UI providers expect an interactive browser for manual login.
        # Enable headless only when explicitly requested.
        if os.environ.get("HYDRA_SELENIUM_HEADLESS", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        random_user_agent = random.choice(user_agents)
        opts.add_argument(f"--user-agent={random_user_agent}")

        chrome_binary = os.environ.get("HYDRA_CHROME_BINARY", "").strip()
        if not chrome_binary:
            chrome_binary = (
                shutil.which("google-chrome")
                or shutil.which("chromium")
                or shutil.which("chromium-browser")
                or ""
            )
        if chrome_binary:
            opts.binary_location = chrome_binary
        return opts

    print(f"[server] Starting Chrome for provider={provider_id!r}, profile={profile_dir}")
    try:
        driver = webdriver.Chrome(options=_build_options(profile_dir))
    except Exception as exc:
        message = str(exc).lower()
        if "user data directory is already in use" in message:
            fallback_profile = tempfile.mkdtemp(prefix=f"hydra-{provider_id}-")
            print(
                "[server] Chrome profile locked, retrying with temporary profile "
                f"{fallback_profile}"
            )
            driver = webdriver.Chrome(options=_build_options(fallback_profile))
        else:
            display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or ""
            chrome_guess = (
                os.environ.get("HYDRA_CHROME_BINARY", "").strip()
                or shutil.which("google-chrome")
                or shutil.which("chromium")
                or shutil.which("chromium-browser")
                or "not-found"
            )
            raise RuntimeError(
                "Failed to start Chrome WebDriver. "
                f"display={display or 'none'}, chrome={chrome_guess}, error={exc}"
            ) from exc

    try:
        driver.set_page_load_timeout(60)
    except Exception:
        pass
    _selenium_sessions[provider_id] = driver

    # Give the provider a chance to navigate to the login page and wait for
    # the user to authenticate before processing any article.
    # (Two-step login providers override login() as a no-op and use
    # start_login/confirm_login instead.)
    provider.login(driver)
    return driver


def _close_all_sessions() -> None:
    """Quit all browser sessions so Chrome releases the profile lock."""
    for provider_id, driver in list(_selenium_sessions.items()):
        try:
            driver.quit()
        except Exception:
            pass
    _selenium_sessions.clear()


def _dispatch(provider_id: str, method: str, body: dict):
    """
    Route a call to the correct provider.
    Returns None for publish/update, or a dict for login.
    Raises ValueError / NotImplementedError on failure.
    """
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id!r}")

    started = time.time()
    print(f"[server] -> {provider_id}/{method}")

    if isinstance(provider, SeleniumProvider):
        driver = _get_or_create_driver(provider_id, provider)
        if method == "publish":
            provider.publish(body, driver)
        elif method == "update":
            provider.update(body, driver)
        elif method == "login":
            # Session is now created/reused by _get_or_create_driver and provider.login(driver)
            # is called there. This endpoint intentionally does not automate credentials.
            result = {"status": "ready"}
            elapsed = time.time() - started
            print(f"[server] <- {provider_id}/{method} ok ({elapsed:.1f}s)")
            return result
        else:
            raise ValueError(f"Unknown method: {method!r}")
    else:
        if method == "publish":
            provider.publish(body)
        elif method == "update":
            provider.update(body)
        else:
            raise ValueError(f"Unknown method: {method!r}")

    elapsed = time.time() - started
    print(f"[server] <- {provider_id}/{method} ok ({elapsed:.1f}s)")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        # Suppress default access log to keep stdout clean for Rust caller
        pass

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        # GET /sessions — list active Selenium sessions
        if parts == ["sessions"]:
            alive = []
            for pid, driver in list(_selenium_sessions.items()):
                try:
                    _ = driver.title
                    alive.append(pid)
                except Exception:
                    _selenium_sessions.pop(pid, None)
            self._send_json(200, {"sessions": alive})
            return

        self._send_json(404, {"error": f"Unknown path: {self.path!r}"})

    def do_DELETE(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        # DELETE /sessions/<provider_id> — kill a specific Selenium session
        if len(parts) == 2 and parts[0] == "sessions":
            provider_id = parts[1]
            driver = _selenium_sessions.pop(provider_id, None)
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
                self._send_json(200, {"ok": True, "killed": provider_id})
            else:
                self._send_json(404, {"error": f"No active session for {provider_id!r}"})
            return

        self._send_json(404, {"error": f"Unknown path: {self.path!r}"})

    def do_POST(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        # POST /stop — graceful shutdown
        if parts == ["stop"]:
            _close_all_sessions()
            self._send_json(200, {"ok": True})
            _shutdown_event.set()
            return

        # POST /<provider_id>/<method>
        if len(parts) == 2:
            provider_id, method = parts
            if method not in ("publish", "update", "login"):
                self._send_json(400, {"error": f"Unknown method: {method!r}"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return

            try:
                result = _dispatch(provider_id, method, body)
                if isinstance(result, dict):
                    self._send_json(200, result)
                else:
                    self._send_json(200, {"ok": True})
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[server] !! {provider_id}/{method} failed: {exc}\n{tb}")
                self._send_json(500, {"error": str(exc), "traceback": tb})
            return

        self._send_json(404, {"error": f"Unknown path: {self.path!r}"})


def main() -> None:
    parser = argparse.ArgumentParser(description="hydra-publisher Python provider server")
    parser.add_argument("--port", type=int, default=0,
                        help="TCP port to listen on (0 = OS-assigned, default)")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), _Handler)
    actual_port = server.server_address[1]

    # Signal to the Rust caller that we are ready
    print(f"LISTENING:{actual_port}", flush=True)

    # Serve requests until /stop is received
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    _shutdown_event.wait()
    server.shutdown()


if __name__ == "__main__":
    main()
