"""Verify result-link login storage using localhost and an isolated browser profile."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DrissionPage import ChromiumOptions, ChromiumPage

from browser_runtime import resolve_browser_path
from job_platforms import JobIdentity
from platform_browser import BrowserJobPlatform
import result_browser


class LocalPage(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>Result browser fixture</title><p>Local job fixture</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/job"
    browser_path = resolve_browser_path()
    checks = {}
    try:
        with tempfile.TemporaryDirectory(prefix="autodeliver-result-browser-") as temp:
            profile = Path(temp) / "profile"
            options = ChromiumOptions()
            options.set_browser_path(str(browser_path))
            options.set_local_port(free_port())
            options.set_user_data_path(str(profile))
            options.headless(True)
            first = ChromiumPage(options)
            try:
                first.get(url)
                first.run_js("""
                    document.cookie = 'fixture_persistent=present; Max-Age=3600; path=/';
                    document.cookie = 'fixture_session=present; path=/';
                    localStorage.setItem('fixture_login', 'present');
                """)
            finally:
                first.quit(timeout=5)

            launched = []
            original_popen = subprocess.Popen
            debug_port = free_port()

            def launch_with_debugging(command, **kwargs):
                checks["project_profile_argument"] = f"--user-data-dir={profile}" in command
                checks["visible_window_requested"] = "--new-window" in command
                command = [*command[:-1], f"--remote-debugging-port={debug_port}",
                           "--remote-allow-origins=*", command[-1]]
                process = original_popen(command, **kwargs)
                launched.append(process)
                return process

            identity = JobIdentity("zhilian", "fixture", url)
            visible = None
            try:
                with patch.object(result_browser, "result_job_target", return_value=identity), \
                        patch.object(result_browser, "platform_profile_dir", return_value=profile), \
                        patch.object(result_browser.subprocess, "Popen", side_effect=launch_with_debugging):
                    result_browser.open_result_job({"详情链接": url}, {"BROWSER_PATH": str(browser_path)})

                attached = ChromiumOptions()
                attached.set_local_port(debug_port)
                attached.headless(False)
                attached.existing_only(True)
                visible = ChromiumPage(attached)
                visible.get(url)
                cookies = visible.run_js("return document.cookie")
                checks["persistent_cookie_reused"] = "fixture_persistent=present" in cookies
                checks["session_cookie_reused"] = "fixture_session=present" in cookies
                checks["local_storage_reused"] = visible.run_js(
                    "return localStorage.getItem('fixture_login')"
                ) == "present"
                checks["project_profile_reused"] = result_browser._profile_process(profile) is not None
                with patch.object(result_browser, "platform_profile_dir", return_value=profile):
                    try:
                        result_browser.ensure_task_profiles_available({"JOB_PLATFORMS": "zhilian"})
                    except ValueError:
                        checks["task_start_detects_open_profile"] = True
                    else:
                        checks["task_start_detects_open_profile"] = False
                visible.quit(timeout=5)
                visible = None
                for process in launched:
                    process.wait(timeout=10)
                adapter = BrowserJobPlatform.__new__(BrowserJobPlatform)
                adapter.profile = profile
                adapter.headless = True
                with patch("platform_browser.resolve_browser_path", return_value=browser_path):
                    task = adapter._open_browser()
                try:
                    task.get(url)
                    checks["session_reused_when_returning_to_task"] = "fixture_session=present" in task.run_js(
                        "return document.cookie"
                    )
                finally:
                    task.quit(timeout=5)
                print(json.dumps(checks, indent=2))
                assert all(checks.values()), checks
            finally:
                if visible is not None:
                    visible.quit(timeout=5)
                for process in launched:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
