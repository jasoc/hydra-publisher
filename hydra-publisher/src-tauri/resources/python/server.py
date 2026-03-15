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
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

# Ensure the directory containing this script is on sys.path so that the
# provider modules are importable regardless of the working directory from
# which the process is spawned.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import provider classes directly (the bundle flattens all files into python/)
from base import SeleniumProvider  # noqa: E402
from subito import SubitoProvider  # noqa: E402
from local_test_selenium import LocalTestSeleniumProvider  # noqa: E402

# Registry: maps platform id (used by Rust) → provider instance.
# Add new providers here.
PROVIDERS = {
    "subito": SubitoProvider(),
    "local_test_selenium": LocalTestSeleniumProvider(),
}


# Active Selenium WebDriver instances, keyed by provider id.
# Each entry is created on the first call to a SeleniumProvider and reused
# for all subsequent calls so the user only needs to log in once per session.
_selenium_sessions: Dict[str, Any] = {}
_shutdown_event = threading.Event()


def _get_or_create_driver(provider_id: str, provider: SeleniumProvider) -> Any:
    """
    Return the cached WebDriver for this provider, or start a new browser
    session. If a new session is started, provider.login() is called so the
    user can authenticate before any article is published.
    """
    if provider_id in _selenium_sessions:
        return _selenium_sessions[provider_id]

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    # Keep the browser window open between calls
    options.add_experimental_option("detach", True)

    driver = webdriver.Chrome(options=options)
    _selenium_sessions[provider_id] = driver

    # Give the provider a chance to navigate to the login page and wait for
    # the user to authenticate before processing any article.
    provider.login(driver)
    return driver


def _close_all_sessions() -> None:
    for provider_id, driver in list(_selenium_sessions.items()):
        try:
            driver.quit()
        except Exception:
            pass
    _selenium_sessions.clear()


def _dispatch(provider_id: str, method: str, article: dict) -> None:
    """
    Route a publish/update call to the correct provider.
    Raises ValueError / NotImplementedError on failure.
    """
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id!r}")

    if isinstance(provider, SeleniumProvider):
        driver = _get_or_create_driver(provider_id, provider)
        if method == "publish":
            provider.publish(article, driver)
        elif method == "update":
            provider.update(article, driver)
        else:
            raise ValueError(f"Unknown method: {method!r}")
    else:
        if method == "publish":
            provider.publish(article)
        elif method == "update":
            provider.update(article)
        else:
            raise ValueError(f"Unknown method: {method!r}")


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

    def do_POST(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        # POST /stop — graceful shutdown
        if parts == ["stop"]:
            _close_all_sessions()
            self._send_json(200, {"ok": True})
            _shutdown_event.set()
            return

        # POST /<provider_id>/publish  or  /<provider_id>/update
        if len(parts) == 2:
            provider_id, method = parts
            if method not in ("publish", "update"):
                self._send_json(400, {"error": f"Unknown method: {method!r}"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                article = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return

            try:
                _dispatch(provider_id, method, article)
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
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
