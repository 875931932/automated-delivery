"""Opt-in headless smoke test using only a local HTTP server and temporary profile."""

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boss_spider import BossDP, Config, PlatformAccessStopped
from browser_runtime import resolve_browser_path
from DrissionPage import ChromiumOptions, ChromiumPage


RESTRICTION = "\u64cd\u4f5c\u8fc7\u4e8e\u9891\u7e41\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5"


class LocalPage(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/visible":
            content = f'<div role="alert">{RESTRICTION}</div>'
        elif self.path == "/hidden":
            content = f'<div role="alert" style="display:none">{RESTRICTION}</div>'
        else:
            content = f'<div class="job-sec-text">{RESTRICTION}</div>'
        body = ('<!doctype html><meta charset="utf-8">'
                '<div class="nav-figure">Local avatar</div>' + content).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPage)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    checks = {}
    try:
        with tempfile.TemporaryDirectory(prefix="autodeliver-platform-stop-") as profile:
            options = ChromiumOptions()
            options.set_browser_path(str(resolve_browser_path()))
            options.set_local_port(BossDP._pick_free_port())
            options.set_user_data_path(profile)
            options.set_argument("--no-first-run")
            options.set_argument("--no-default-browser-check")
            options.headless(True)
            page = ChromiumPage(options)
            try:
                spider = BossDP.__new__(BossDP)
                spider.page = page
                spider.stop_event = threading.Event()
                spider.urgent_event = threading.Event()
                spider._platform_stop_reason = None
                with patch.dict(Config, base_url=base_url):
                    for path in ("/ordinary", "/hidden"):
                        page.get(base_url + path)
                        spider._check_platform_page(page)
                        assert not spider.stop_event.is_set(), path
                        checks[path[1:]] = "no false stop"
                    for path in ("/visible", "/web/common/security-check.html"):
                        spider._platform_stop_reason = None
                        spider.stop_event.clear()
                        spider.urgent_event.clear()
                        page.get(base_url + path)
                        try:
                            spider._check_platform_page(page)
                        except PlatformAccessStopped:
                            assert spider.stop_event.is_set()
                            assert page.url == base_url + path
                            checks[path] = "stopped without navigation"
                        else:
                            raise AssertionError(f"Restriction was missed: {path}")
                print(json.dumps(checks, ensure_ascii=True, indent=2))
            finally:
                page.quit(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
