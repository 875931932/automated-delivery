"""Opt-in local browser smoke test. Opens one temporary login window, never BOSS."""

import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boss_spider import BossDP, Config


def visible_browser_windows(process_id):
    if os.name != "nt":
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    result = []

    @callback_type
    def collect(hwnd, _data):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, len(name))
            if name.value == "Chrome_WidgetWin_1":
                result.append(hwnd)
        return True

    if not user32.EnumWindows(collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return result


class LocalLoginPage(BaseHTTPRequestHandler):
    def do_GET(self):
        logged_in = "smoke_session=local" in self.headers.get("Cookie", "")
        body = (
            '<html><body><div class="nav-figure">Local test login</div></body></html>'
            if logged_in else '<html><body>Local login fixture</body></html>'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalLoginPage)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    spider = None
    simulate_stop = threading.Event()
    simulation_errors = []
    simulator = None
    try:
        with tempfile.TemporaryDirectory(prefix="autodeliver-browser-smoke-") as profile:
            with patch.dict(Config, chrome_profile_dir=profile, browser_background=True,
                            keep_login=True, start_url=url):
                try:
                    spider = BossDP()
                    profile_path = spider.page.browser.user_data_path
                    first_pid = spider.page.browser.process_id
                    assert not visible_browser_windows(first_pid), "Background browser is visible"
                    tab = spider.page.new_tab(url, background=True)
                    tab.run_js('document.title = "background fixture"')
                    assert not visible_browser_windows(first_pid), "New tab exposed the browser"
                    tab.close()

                    def simulate_login():
                        deadline = time.monotonic() + 40
                        while not simulate_stop.wait(0.1) and time.monotonic() < deadline:
                            if not spider.browser_lock.acquire(blocking=False):
                                continue
                            try:
                                if spider._browser_headless:
                                    continue
                                pid = spider.page.browser.process_id
                                assert visible_browser_windows(pid), "Login browser is not visible"
                                spider.page.run_js(
                                    'document.cookie = "smoke_session=local; path=/";'
                                    'localStorage.setItem("smoke-storage", "preserved");'
                                )
                                spider.page.get(url)
                                return
                            except Exception as exc:
                                simulation_errors.append(repr(exc))
                                return
                            finally:
                                spider.browser_lock.release()
                        simulation_errors.append("Interactive login was not reached")

                    simulator = threading.Thread(target=simulate_login, daemon=True)
                    simulator.start()
                    spider._wait_for_login(45)
                    assert not simulation_errors, simulation_errors
                    assert spider._browser_headless, "Login did not return to background"
                    assert spider.page.browser.user_data_path == profile_path, "Profile changed"
                    assert spider.page.ele('.nav-figure', timeout=2), "Session cookie was lost"
                    assert spider.page.run_js('return localStorage.getItem("smoke-storage")') == "preserved"
                    assert not visible_browser_windows(spider.page.browser.process_id)
                    spider.page.new_tab(url, background=True)
                    assert not visible_browser_windows(spider.page.browser.process_id)
                    print(json.dumps({
                        "headless_initial": True,
                        "headless_after_new_tab": True,
                        "interactive_login": True,
                        "headless_after_login": True,
                        "session_cookie_preserved": True,
                        "local_storage_preserved": True,
                        "profile_preserved": True,
                    }))
                finally:
                    simulate_stop.set()
                    if simulator:
                        simulator.join(timeout=10)
                    if spider:
                        spider.stop_heartbeat()
                        spider.page.quit(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
