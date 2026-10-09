#!/usr/bin/env python3
"""
hydra-publisher Python provider server.

Started by the Rust backend. Communicates via HTTP on localhost.

Usage:
    python3 server.py [--port PORT]

    PORT defaults to 0 (OS picks a free port).
    Once ready the server prints "LISTENING:<port>" to stdout so the Rust
    caller can discover which port was assigned.

    Set HYDRA_POOL_SIZE=N to control the number of parallel Chrome windows
    (default: 2).

Endpoints:
    POST /<provider_id>/publish   body: article JSON
    POST /<provider_id>/login     open/reuse a browser session
    POST /stop                    graceful shutdown (closes all browser sessions)
    GET  /sessions                list active Chrome pool slots
    DELETE /sessions/<any>        kill all Chrome sessions
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
from socketserver import ThreadingMixIn
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
_providers_dir = os.path.join(_script_dir, "providers")
if os.path.isdir(_providers_dir):
    sys.path.insert(0, _providers_dir)

from base import SeleniumProvider  # noqa: E402
from subito import SubitoProvider  # noqa: E402
from facebook_marketplace import FacebookMarketplaceProvider  # noqa: E402
from vinted import VintedProvider  # noqa: E402

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS = {
    "subito": SubitoProvider(),
    "facebook_marketplace": FacebookMarketplaceProvider(),
    "vinted": VintedProvider(),
}

POOL_SIZE = int(os.environ.get("HYDRA_POOL_SIZE", "2"))

# ---------------------------------------------------------------------------
# Anti-detection
# ---------------------------------------------------------------------------

user_agents = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const p = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
                  description: 'Portable Document Format', length: 1,
                  item: (i) => ({ type: 'application/x-google-chrome-pdf' }) },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                  description: '', length: 1,
                  item: (i) => ({ type: 'application/pdf' }) },
                { name: 'Native Client', filename: 'internal-nacl-plugin',
                  description: '', length: 2,
                  item: (i) => ({ type: 'application/x-nacl' }) },
            ];
            p.length = 3;
            p.item = (i) => p[i];
            p.namedItem = (n) => p.find(pp => pp.name === n) || null;
            p.refresh = () => {};
            return p;
        },
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['it-IT', 'it', 'en-US', 'en'],
    });
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() {},
            sendMessage: function() {},
            onMessage: { addListener: function() {}, removeListener: function() {} },
        };
    }
    const origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(params);
    if (navigator.connection === undefined) {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
        });
    }
    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';
        if (param === 37446) return 'ANGLE (Intel, Mesa Intel(R) Graphics, OpenGL 4.6)';
        return getParameterProto.call(this, param);
    };
    const getParameterProto2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';
        if (param === 37446) return 'ANGLE (Intel, Mesa Intel(R) Graphics, OpenGL 4.6)';
        return getParameterProto2.call(this, param);
    };
    const nativeToString = Function.prototype.toString;
    const proxyHandler = {
        apply: function(target, thisArg, args) {
            if (thisArg === navigator.permissions.query)
                return 'function query() { [native code] }';
            return nativeToString.call(thisArg);
        }
    };
    Function.prototype.toString = new Proxy(nativeToString, proxyHandler);
"""

_shutdown_event = threading.Event()


# ---------------------------------------------------------------------------
# Chrome factory
# ---------------------------------------------------------------------------

def _create_chrome(profile_dir: str) -> Any:
    """Create a fresh Chrome WebDriver with anti-detection patches."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir}")

    if os.environ.get("HYDRA_SELENIUM_HEADLESS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        opts.add_argument("--headless=new")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--user-agent={random.choice(user_agents)}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

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

    driver = webdriver.Chrome(options=opts)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_SCRIPT},
        )
    except Exception as exc:
        print(f"[server] Warning: could not inject stealth script: {exc}")

    try:
        driver.set_page_load_timeout(60)
    except Exception:
        pass

    return driver


# ---------------------------------------------------------------------------
# Driver Pool
# ---------------------------------------------------------------------------

class DriverPool:
    """
    Pool of N Chrome WebDriver instances for parallel publishing.

    Slot 0 uses the master profile (~/.hydra-publisher/chrome-profile).
    Slots 1..N-1 copy the master profile on first use so they inherit saved
    sessions/cookies.  Each slot has its own lock — only one HTTP request at
    a time can drive a given Chrome window.
    """

    def __init__(self, pool_size: int = 2) -> None:
        self._pool_size = pool_size
        self._drivers: List[Optional[Any]] = [None] * pool_size
        self._slot_locks = [threading.Lock() for _ in range(pool_size)]
        self._master_profile = os.path.expanduser("~/.hydra-publisher/chrome-profile")
        os.makedirs(self._master_profile, exist_ok=True)
        self._acquire_cv = threading.Condition()

    # ── public API ────────────────────────────────────────────────────────

    def acquire(self, provider_id: str, provider: SeleniumProvider):
        """
        Acquire a free Chrome slot.  Blocks until one is available.
        Returns ``(slot_id, driver)``.
        """
        while True:
            for i in range(self._pool_size):
                if self._slot_locks[i].acquire(blocking=False):
                    try:
                        driver = self._ensure_driver(i, provider_id, provider)
                        return (i, driver)
                    except Exception:
                        self._slot_locks[i].release()
                        raise

            # All slots busy — wait briefly and retry
            with self._acquire_cv:
                self._acquire_cv.wait(timeout=1.0)

    def release(self, slot_id: int) -> None:
        """Release a slot back to the pool."""
        self._slot_locks[slot_id].release()
        with self._acquire_cv:
            self._acquire_cv.notify_all()

    def get_active_slots(self) -> List[str]:
        """Return list of slot names with live drivers."""
        alive = []
        for i in range(self._pool_size):
            d = self._drivers[i]
            if d is not None:
                try:
                    _ = d.title
                    alive.append(f"chrome-{i}")
                except Exception:
                    pass
        return alive

    def close_all(self) -> None:
        """Gracefully quit every Chrome in the pool (used at shutdown)."""
        for i in range(self._pool_size):
            self._slot_locks[i].acquire(blocking=True)
            try:
                self._quit_slot(i)
            finally:
                self._slot_locks[i].release()

    def kill_all(self) -> List[str]:
        """Best-effort kill of all sessions.  Returns names of killed slots."""
        killed: List[str] = []
        for i in range(self._pool_size):
            if self._slot_locks[i].acquire(blocking=False):
                try:
                    if self._drivers[i] is not None:
                        self._quit_slot(i)
                        killed.append(f"chrome-{i}")
                finally:
                    self._slot_locks[i].release()
        return killed

    @property
    def pool_size(self) -> int:
        return self._pool_size

    # ── internals ─────────────────────────────────────────────────────────

    def _profile_dir(self, slot: int) -> str:
        if slot == 0:
            return self._master_profile
        return f"{self._master_profile}-{slot}"

    def _ensure_driver(self, slot: int, provider_id: str, provider: SeleniumProvider) -> Any:
        """Return a live driver for *slot*, creating one if needed."""
        driver = self._drivers[slot]
        if driver is not None:
            try:
                _ = driver.title
                return driver
            except Exception:
                print(f"[pool] Slot {slot} driver died, recreating...")
                self._drivers[slot] = None

        profile = self._profile_dir(slot)

        # For non-master slots, seed from master to inherit cookies/sessions
        if slot > 0 and not os.path.exists(profile):
            if os.path.exists(self._master_profile):
                print(f"[pool] Seeding slot {slot} from master profile")
                shutil.copytree(
                    self._master_profile,
                    profile,
                    ignore=shutil.ignore_patterns(
                        "SingletonLock", "SingletonCookie", "SingletonSocket",
                    ),
                )

        os.makedirs(profile, exist_ok=True)
        print(f"[pool] Starting Chrome slot {slot} for {provider_id!r}, profile={profile}")

        try:
            driver = _create_chrome(profile)
        except Exception as exc:
            message = str(exc).lower()
            if "user data directory is already in use" in message:
                fallback = tempfile.mkdtemp(prefix=f"hydra-slot{slot}-")
                print(f"[pool] Profile locked, using temp dir: {fallback}")
                driver = _create_chrome(fallback)
            else:
                raise

        self._drivers[slot] = driver
        provider.login(driver)
        return driver

    def _quit_slot(self, slot: int) -> None:
        d = self._drivers[slot]
        if d is not None:
            try:
                d.quit()
            except Exception:
                pass
            self._drivers[slot] = None


_pool: Optional[DriverPool] = None


def _get_pool() -> DriverPool:
    global _pool
    if _pool is None:
        _pool = DriverPool(pool_size=POOL_SIZE)
    return _pool


# ---------------------------------------------------------------------------
# Request dispatch
# ---------------------------------------------------------------------------

def _dispatch(provider_id: str, method: str, body: dict):
    """
    Route a call to the correct provider.
    Returns None for publish, or a dict for login.
    """
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id!r}")

    started = time.time()
    print(f"[server] -> {provider_id}/{method}")

    if isinstance(provider, SeleniumProvider):
        pool = _get_pool()
        if method == "publish":
            slot_id, driver = pool.acquire(provider_id, provider)
            try:
                provider.publish(body, driver)
            finally:
                pool.release(slot_id)
        elif method == "login":
            # Ensure a session exists (uses first available slot)
            slot_id, driver = pool.acquire(provider_id, provider)
            pool.release(slot_id)
            result = {"status": "ready"}
            elapsed = time.time() - started
            print(f"[server] <- {provider_id}/{method} ok ({elapsed:.1f}s)")
            return result
        else:
            raise ValueError(f"Unknown method: {method!r}")
    else:
        if method == "publish":
            provider.publish(body)
        else:
            raise ValueError(f"Unknown method: {method!r}")

    elapsed = time.time() - started
    print(f"[server] <- {provider_id}/{method} ok ({elapsed:.1f}s)")


# ---------------------------------------------------------------------------
# Threaded HTTP server
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a new thread."""
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
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

        if parts == ["sessions"]:
            pool = _get_pool()
            alive = pool.get_active_slots()
            self._send_json(200, {
                "sessions": alive,
                "poolSize": pool.pool_size,
            })
            return

        self._send_json(404, {"error": f"Unknown path: {self.path!r}"})

    def do_DELETE(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        if len(parts) == 2 and parts[0] == "sessions":
            pool = _get_pool()
            killed = pool.kill_all()
            if killed:
                self._send_json(200, {"ok": True, "killed": killed})
            else:
                self._send_json(404, {"error": "No active sessions"})
            return

        self._send_json(404, {"error": f"Unknown path: {self.path!r}"})

    def do_POST(self):  # noqa: N802
        path = self.path.strip("/")
        parts = path.split("/")

        if parts == ["stop"]:
            pool = _get_pool()
            pool.close_all()
            self._send_json(200, {"ok": True})
            _shutdown_event.set()
            return

        if len(parts) == 2:
            provider_id, method = parts
            if method not in ("publish", "login"):
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="hydra-publisher Python provider server")
    parser.add_argument("--port", type=int, default=0,
                        help="TCP port to listen on (0 = OS-assigned, default)")
    args = parser.parse_args()

    server = ThreadedHTTPServer(("127.0.0.1", args.port), _Handler)
    actual_port = server.server_address[1]

    print(f"LISTENING:{actual_port}", flush=True)
    print(f"[server] Chrome pool size: {POOL_SIZE}", file=sys.stderr)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    _shutdown_event.wait()
    server.shutdown()


if __name__ == "__main__":
    main()
