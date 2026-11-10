import csv
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

import boss_spider
from auto_deliver import AutoDeliverer
from boss_spider import BossDP


SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?query=test&jobType=1902"
JOB = {"encryptJobId": "test-job"}


def make_spider(cls=BossDP, url=SEARCH_URL):
    spider = cls.__new__(cls)
    spider.browser_lock = threading.RLock()
    spider._session_lock = threading.RLock()
    spider._heartbeat_lock = threading.Lock()
    spider._heartbeat_thread = None
    spider.stop_event = threading.Event()
    spider.urgent_event = threading.Event()
    spider.humanize_enabled = True
    spider._browser_headless = False
    spider._last_human_browse_at = None
    spider.user_agent = "test-agent"
    spider.session = requests.Session()
    spider.current_cookies = {"session": "old"}
    spider.current_headers = {"referer": SEARCH_URL}
    spider.session.cookies.update(spider.current_cookies)
    spider.api_request_count = 0
    spider.max_api_requests = 10
    spider.page = SimpleNamespace(
        url=url, get=Mock(), quit=Mock(), scroll=Mock(), ele=Mock(), eles=Mock(),
    )

    def run_cdp(command, **kwargs):
        if command == "Target.getTargetInfo":
            return {"targetInfo": {"url": spider.page.url}}
        if command == "Network.getCookies":
            return {"cookies": [{"name": "session", "value": "fresh"}]}
        raise AssertionError(command)

    spider.page.run_cdp = Mock(side_effect=run_cdp)
    return spider


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_syncs_cookies_without_navigation_or_random_actions(self):
        for url in (SEARCH_URL, "https://www.zhipin.com/job_detail/test.html",
                    "https://www.zhipin.com/web/geek/chat"):
            with self.subTest(url=url):
                spider = make_spider(url=url)
                with patch("boss_spider.random.choices") as choose:
                    spider._heartbeat_once()
                self.assertEqual(spider.session.cookies.get("session"), "fresh")
                spider.page.get.assert_not_called()
                spider.page.ele.assert_not_called()
                spider.page.eles.assert_not_called()
                self.assertEqual(spider.page.scroll.mock_calls, [])
                choose.assert_not_called()

    def test_only_homepage_is_restored_with_bounded_navigation(self):
        for url in ("https://www.zhipin.com", "https://www.zhipin.com/?source=test"):
            with self.subTest(url=url):
                spider = make_spider(url=url)
                spider.humanize_enabled = False
                with patch.dict(boss_spider.Config, start_url=SEARCH_URL):
                    spider._heartbeat_once()
                spider.page.get.assert_called_once_with(SEARCH_URL, retry=0, timeout=5)

    def test_login_verification_and_external_pages_are_left_alone(self):
        for url in ("https://www.zhipin.com/web/user/?ka=login",
                    "https://www.zhipin.com/web/common/security-check.html",
                    "https://example.invalid/"):
            with self.subTest(url=url):
                spider = make_spider(url=url)
                spider._heartbeat_once()
                spider.page.get.assert_not_called()
                self.assertEqual(spider.current_cookies, {"session": "old"})

    def test_busy_browser_or_session_causes_heartbeat_to_skip(self):
        for lock_name in ("browser_lock", "_session_lock"):
            with self.subTest(lock=lock_name):
                spider = make_spider()
                done = threading.Event()

                def probe():
                    try:
                        spider._heartbeat_once()
                    finally:
                        done.set()

                with getattr(spider, lock_name):
                    worker = threading.Thread(target=probe)
                    worker.start()
                    skipped = done.wait(1)
                worker.join(1)
                self.assertTrue(skipped, "heartbeat queued behind a busy operation")
                spider.page.run_cdp.assert_not_called()
                self.assertTrue(spider.browser_lock.acquire(blocking=False))
                spider.browser_lock.release()

    def test_stopped_probe_and_failed_probe_leave_browser_available(self):
        spider = make_spider()
        spider.stop_event.set()
        spider._heartbeat_once()
        spider.page.run_cdp.assert_not_called()
        spider.stop_event.clear()
        spider.page.run_cdp.side_effect = RuntimeError("browser disconnected")
        worker = threading.Thread(target=spider._heartbeat_once)
        worker.start()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(spider.browser_lock.acquire(blocking=False))
        spider.browser_lock.release()
        self.assertTrue(spider._session_lock.acquire(blocking=False))
        spider._session_lock.release()

    def test_start_is_idempotent_and_stop_wakes_a_waiting_heartbeat(self):
        spider = make_spider()
        waiting = threading.Event()
        original_wait = spider.urgent_event.wait

        def wait(timeout):
            waiting.set()
            return original_wait(timeout)

        with patch.object(spider.urgent_event, "wait", side_effect=wait):
            first = spider.start_heartbeat()
            try:
                self.assertTrue(waiting.wait(1))
                self.assertIs(spider.start_heartbeat(), first)
            finally:
                spider.stop_heartbeat()
        self.assertFalse(first.is_alive())
        self.assertIsNone(spider._heartbeat_thread)
        spider.page.run_cdp.assert_not_called()
        self.assertIsNone(spider.start_heartbeat())

    def test_urgent_signal_probes_without_waiting_for_period(self):
        spider = make_spider()
        probed = threading.Event()
        spider._heartbeat_once = Mock(side_effect=probed.set)
        spider.start_heartbeat()
        try:
            spider.urgent_event.set()
            self.assertTrue(probed.wait(1))
        finally:
            spider.stop_heartbeat()
        spider._heartbeat_once.assert_called_once_with()

    def test_shutdown_waits_for_active_probe_before_closing_page(self):
        spider = make_spider(AutoDeliverer)
        entered = threading.Event()
        release = threading.Event()
        stop_called = threading.Event()
        order = []

        def probe():
            entered.set()
            if not release.wait(2):
                raise AssertionError("test probe was not released")
            order.append("probe_finished")

        def start(_timeout):
            spider.start_heartbeat()
            spider.urgent_event.set()
            if not entered.wait(1):
                raise AssertionError("heartbeat did not start")
            raise RuntimeError("end test run")

        real_stop = spider.stop_heartbeat

        def stop():
            stop_called.set()
            real_stop()

        spider._heartbeat_once = probe
        spider.stop_heartbeat = stop
        spider.cfg = {"dry_run": False, "test_limit": 0, "login_wait": 0}
        spider.wait_login = start
        spider.deliver_count = 0
        spider.save_results = Mock()
        spider._print_stage_summary = Mock()
        spider.page.quit.side_effect = lambda: order.append("quit")
        worker = threading.Thread(target=spider.run)
        with redirect_stdout(StringIO()), patch("traceback.print_exc"):
            worker.start()
            try:
                self.assertTrue(stop_called.wait(1))
                spider.page.quit.assert_not_called()
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(order, ["probe_finished", "quit"])


class BrowserSchedulingTests(unittest.TestCase):
    def test_disabled_and_non_list_pages_never_browse(self):
        for url in (SEARCH_URL, "https://www.zhipin.com/web/geek/chat",
                    "https://www.zhipin.com/job_detail/test.html",
                    "https://www.zhipin.com/web/user/",
                    "https://www.zhipin.com/web/common/security-check.html"):
            with self.subTest(url=url):
                spider = make_spider(url=url)
                spider.humanize_enabled = url != SEARCH_URL
                spider._human_navigate_interlude([JOB])
                self.assertEqual(spider.page.scroll.mock_calls, [])
                spider.page.get.assert_not_called()

    def test_all_browsing_triggers_share_one_cooldown_and_do_not_click(self):
        spider = make_spider()
        with patch("boss_spider.time.sleep"), \
                patch("boss_spider.time.monotonic", return_value=100):
            spider._human_navigate_interlude([JOB])
            spider._human_click_job_action([JOB])
            spider._human_enter_detail_action([JOB])
        spider.page.scroll.down.assert_called_once()
        spider.page.scroll.to_top.assert_not_called()
        spider.page.scroll.up.assert_not_called()
        spider.page.get.assert_not_called()
        spider.page.ele.assert_not_called()
        self.assertEqual(spider.page.scroll.down.call_count, 1)
        with patch("boss_spider.time.sleep"), \
                patch("boss_spider.time.monotonic", return_value=161):
            spider._human_navigate_interlude([JOB])
        self.assertEqual(spider.page.scroll.down.call_count, 2)

    def test_browse_errors_do_not_force_navigation(self):
        spider = make_spider()
        spider.page.scroll.down.side_effect = RuntimeError("page changed")
        spider._human_navigate_interlude([JOB])
        spider.page.get.assert_not_called()

    def test_headless_browsing_never_scrolls_or_reloads(self):
        spider = make_spider(AutoDeliverer)
        spider._browser_headless = True
        spider._human_browse_job_list = [JOB]
        with patch("boss_spider.time.sleep"):
            spider._human_navigate_interlude([JOB])
            spider._human_browse_after_delivery()
        self.assertEqual(spider.page.scroll.mock_calls, [])
        spider.page.get.assert_not_called()

    def test_post_delivery_does_not_reload_an_existing_search_page(self):
        spider = make_spider(AutoDeliverer)
        spider._human_browse_job_list = [JOB]
        with patch("boss_spider.time.sleep"):
            spider._human_browse_after_delivery()
        spider.page.get.assert_not_called()
        spider.page.scroll.down.assert_called_once()

    def test_post_delivery_browse_preserves_login_and_verification_pages(self):
        for url in ("https://www.zhipin.com/web/user/",
                    "https://www.zhipin.com/web/common/security-check.html"):
            with self.subTest(url=url):
                spider = make_spider(AutoDeliverer, url=url)
                spider._human_browse_after_delivery()
                spider.page.get.assert_not_called()

    def test_post_delivery_browse_does_not_reload_during_cooldown(self):
        spider = make_spider(AutoDeliverer)
        spider._last_human_browse_at = 100
        with patch("auto_deliver.time.monotonic", return_value=101):
            spider._human_browse_after_delivery()
        spider.page.get.assert_not_called()

    def test_disabling_humanization_skips_delivery_scrolling_but_still_sends(self):
        spider = make_spider(AutoDeliverer)
        spider.humanize_enabled = False
        spider.cfg = {"detail_delay": (0, 0)}
        spider.page.tab_ids = {"main"}
        button = Mock()
        button.click.side_effect = lambda: setattr(
            spider.page, "url", "https://www.zhipin.com/web/geek/chat",
        )
        button.text = "立即沟通"
        button.attr.return_value = None
        spider.page.eles.return_value = [button]
        spider.page.ele.return_value = button
        spider._send_greeting_in_chat = Mock(return_value="delivered")
        with patch("auto_deliver.time.sleep"):
            status = spider.deliver_one(
                {"详情链接": "https://www.zhipin.com/job_detail/test.html"}, "hello",
            )
        self.assertEqual(status, "delivered")
        self.assertEqual(spider.page.scroll.mock_calls, [])
        spider._send_greeting_in_chat.assert_called_once_with(spider.page, "hello")

    def test_disabling_humanization_uses_normal_text_input(self):
        spider = make_spider(AutoDeliverer)
        spider.humanize_enabled = False
        tab = Mock()
        with patch("auto_deliver.time.sleep"):
            status = spider._send_greeting_in_chat(tab, "hello")
        self.assertEqual(status, "delivered")
        tab.actions.type.assert_called_once_with("hello", interval=0)

    def test_enabled_browsing_does_not_add_delivery_scrolling(self):
        spider = make_spider(AutoDeliverer)
        spider.cfg = {"detail_delay": (7, 9)}
        spider.page.tab_ids = {"main"}
        button = Mock(text="立即沟通")
        button.attr.return_value = None
        button.click.side_effect = lambda: setattr(
            spider.page, "url", "https://www.zhipin.com/web/geek/chat",
        )
        spider._job_contact_buttons = Mock(return_value=[button])
        spider._send_greeting_in_chat = Mock(return_value="delivered")
        with patch("auto_deliver.time.sleep"), \
                patch("auto_deliver.random.uniform", return_value=8) as delay:
            status = spider.deliver_one(
                {"详情链接": "https://www.zhipin.com/job_detail/test.html"}, "hello",
            )
        self.assertEqual(status, "delivered")
        self.assertEqual(spider.page.scroll.mock_calls, [])
        delay.assert_any_call(7, 9)

    def test_enabled_browsing_uses_normal_text_input(self):
        spider = make_spider(AutoDeliverer)
        tab = Mock()
        with patch("auto_deliver.time.sleep"):
            self.assertEqual(spider._send_greeting_in_chat(tab, "hello"), "delivered")
        tab.actions.type.assert_called_once_with("hello", interval=0)

    def test_result_save_failure_still_stops_heartbeat_and_closes_browser(self):
        spider = make_spider(AutoDeliverer)
        spider.cfg = {"dry_run": False, "test_limit": 0, "login_wait": 0}
        spider.wait_login = Mock(side_effect=RuntimeError("end test run"))
        spider.save_results = Mock(side_effect=OSError("disk unavailable"))
        with redirect_stdout(StringIO()), patch("traceback.print_exc"):
            with self.assertRaises(OSError):
                spider.run()
        self.assertTrue(spider.stop_event.is_set())
        spider.page.quit.assert_called_once_with()


class PlatformStopTests(unittest.TestCase):
    def test_restricted_http_stops_after_one_request_and_blocks_later_requests(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                spider = make_spider()
                spider.session.request = Mock(return_value=Mock(status_code=status))
                with patch("boss_spider.time.sleep"):
                    with self.assertRaises(InterruptedError):
                        spider.api_job_list(keyword="first")
                    with self.assertRaises(InterruptedError):
                        spider.api_job_list(keyword="second")
                spider.session.request.assert_called_once()
                self.assertTrue(spider.stop_event.is_set())

    def test_explicit_business_limits_stop_without_logging_response_secrets(self):
        for message in ("操作过于频繁，请稍后再试", "当前访问受限", "请完成安全验证",
                        "您的账号存在异常", "请重新登录"):
            with self.subTest(message=message):
                spider = make_spider()
                response = Mock(status_code=200)
                response.json.return_value = {
                    "code": 999, "message": message + " token=private-test-value",
                }
                spider.session.request = Mock(return_value=response)
                output = StringIO()
                with patch("boss_spider.time.sleep"), redirect_stdout(output):
                    with self.assertRaises(InterruptedError) as stopped:
                        spider.api_job_list()
                self.assertNotIn("private-test-value", str(stopped.exception) + output.getvalue())
                spider.session.request.assert_called_once()

    def test_transient_http_and_timeout_still_retry(self):
        for first in (requests.Timeout("temporary timeout"), Mock(status_code=503)):
            with self.subTest(first=type(first).__name__):
                spider = make_spider()
                success = Mock(status_code=200)
                success.json.return_value = {"code": 0, "zpData": {"jobList": []}}
                spider.session.request = Mock(side_effect=[first, success])
                with patch("boss_spider.time.sleep"):
                    self.assertEqual(spider.api_job_list(), success.json.return_value)
                self.assertEqual(spider.session.request.call_count, 2)
                self.assertFalse(spider.stop_event.is_set())

    def test_successful_job_content_and_ordinary_errors_are_not_limits(self):
        for payload in (
            {"code": 0, "zpData": {"jobList": [{"jobName": "账号安全验证开发"}]}},
            {"code": 999, "message": "职位已下线"},
        ):
            with self.subTest(payload=payload):
                spider = make_spider()
                response = Mock(status_code=200)
                response.json.return_value = payload
                spider.session.request = Mock(return_value=response)
                with patch("boss_spider.time.sleep"):
                    result = spider.api_job_list()
                self.assertEqual(result, payload if payload["code"] == 0 else None)
                self.assertFalse(spider.stop_event.is_set())

    def test_security_redirect_is_not_followed(self):
        spider = make_spider()
        response = Mock(status_code=302)
        response.headers = {"Location": "/web/common/security-check.html?token=private-test-value"}
        spider.session.request = Mock(return_value=response)
        with patch("boss_spider.time.sleep"):
            with self.assertRaises(InterruptedError):
                spider.api_job_list()
        spider.session.request.assert_called_once()
        self.assertFalse(spider.session.request.call_args.kwargs["allow_redirects"])

    def test_heartbeat_verification_stops_requests_without_navigation(self):
        spider = make_spider(url="https://www.zhipin.com/web/common/security-check.html")
        spider.session.request = Mock()
        spider._heartbeat_once()
        self.assertTrue(spider.stop_event.is_set())
        with self.assertRaises(InterruptedError):
            spider.api_job_list()
        spider.session.request.assert_not_called()
        spider.page.get.assert_not_called()

    def test_security_page_with_avatar_is_not_treated_as_logged_in(self):
        spider = make_spider(url="https://www.zhipin.com/web/common/security-check.html")
        spider.browser_background = False
        spider.page.ele.return_value = object()
        with patch("boss_spider.time.sleep"):
            with self.assertRaises(InterruptedError):
                spider._wait_for_login(20)
        spider.page.ele.assert_not_called()

    def test_visible_limit_dialog_prevents_typing_and_sending(self):
        spider = make_spider(AutoDeliverer)
        tab = Mock(url="https://www.zhipin.com/web/geek/chat")
        alert = Mock(text="操作过于频繁，请稍后再试")
        alert.states.is_displayed = True
        tab.eles.return_value = [alert]
        with patch("auto_deliver.time.sleep"):
            with self.assertRaises(InterruptedError):
                spider._send_greeting_in_chat(tab, "hello")
        tab.actions.type.assert_not_called()
        tab.ele.assert_not_called()

    def test_limit_appearing_after_typing_prevents_the_send(self):
        spider = make_spider(AutoDeliverer)
        tab = Mock(url="https://www.zhipin.com/web/geek/chat")
        alert = Mock(text="操作过于频繁，请稍后再试")
        alert.states.is_displayed = True
        tab.eles.side_effect = [[], [alert]]
        with patch("auto_deliver.time.sleep"):
            with self.assertRaises(InterruptedError):
                spider._send_greeting_in_chat(tab, "hello")
        tab.actions.type.assert_called_once_with("hello", interval=0)
        self.assertEqual(tab.ele.call_count, 1)
        tab.actions.key_down.assert_not_called()

    def test_background_delivery_keeps_cookie_sync_without_extra_browsing(self):
        spider = make_spider(AutoDeliverer)
        spider._browser_headless = True
        spider.cfg = {"human_every_n": 2}
        spider.deliver_count = 2
        spider.get_cookie_headers = Mock()
        spider._human_browse_after_delivery = Mock()
        spider._after_successful_delivery()
        spider.get_cookie_headers.assert_called_once_with()
        spider._human_browse_after_delivery.assert_not_called()

    def test_limit_after_send_does_not_report_delivery_success(self):
        spider = make_spider(AutoDeliverer)
        tab = Mock(url="https://www.zhipin.com/web/geek/chat")
        alert = Mock(text="操作过于频繁，请稍后再试")
        alert.states.is_displayed = True
        tab.eles.side_effect = [[], [], [alert]]
        output = StringIO()
        with patch("auto_deliver.time.sleep"), redirect_stdout(output):
            with self.assertRaises(InterruptedError):
                spider._send_greeting_in_chat(tab, "hello")
        self.assertNotIn("打招呼语已发送", output.getvalue())
        self.assertTrue(spider.stop_event.is_set())

    def test_hidden_limit_dialog_does_not_stop_a_normal_page(self):
        spider = make_spider()
        alert = Mock(text="操作过于频繁，请稍后再试")
        alert.states.is_displayed = False
        spider.page.eles.return_value = [alert]
        self.assertFalse(spider._check_browser_attention(spider.page))
        self.assertFalse(spider.stop_event.is_set())

    def test_platform_stop_ends_all_queries_and_saves_partial_results(self):
        spider = make_spider(AutoDeliverer)
        output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(output_dir.cleanup)
        result_path = Path(output_dir.name) / "results.csv"
        spider.cfg = {"dry_run": True, "test_limit": 0, "login_wait": 20,
                      "deliver_max_pages": 2, "result_file": str(result_path)}
        spider.matching_context = {"allocations": [
            {"keyword": keyword, "pages": [1], "profile_ids": []}
            for keyword in ("first", "second")
        ]}
        spider.profile_mode = True
        spider.deliver_count = 0
        spider.wait_login = Mock()
        spider.get_cookie_headers = Mock(return_value=True)
        spider.start_heartbeat = Mock()
        spider.results = [{"encryptJobId": "completed-job", "投递状态": "dry_run"}]
        spider._saved_count = 0
        spider._print_stage_summary = Mock()
        spider.session.request = Mock(return_value=Mock(status_code=429))
        output = StringIO()
        with patch("boss_spider.time.sleep"), redirect_stdout(output):
            exit_code = spider.run()
        self.assertEqual(exit_code, 3)
        spider.session.request.assert_called_once()
        with result_path.open(encoding="utf-8-sig", newline="") as saved:
            rows = list(csv.DictReader(saved))
        self.assertEqual([(row["encryptJobId"], row["投递状态"]) for row in rows],
                         [("completed-job", "dry_run")])
        self.assertEqual(spider._saved_count, 1)
        spider.page.quit.assert_called_once_with()
        self.assertTrue(spider.stop_event.is_set())
        self.assertIn("[平台限制]", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


class SessionCoordinationTests(unittest.TestCase):
    def test_first_detail_request_keeps_fresh_headers_and_local_referer(self):
        spider = make_spider(AutoDeliverer)
        spider.current_cookies = {}
        spider.current_headers = {}
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0}
        spider.session.request = Mock(return_value=response)
        with patch("boss_spider.time.sleep"):
            spider.api_job_detail("test-security", "test-job")
        sent_headers = spider.session.request.call_args.kwargs["headers"]
        self.assertEqual(sent_headers["User-Agent"], "test-agent")
        self.assertEqual(sent_headers["referer"],
                         "https://www.zhipin.com/job_detail/test-job.html")
        self.assertEqual(spider.current_headers["referer"], boss_spider.Config["start_url"])

    def test_heartbeat_does_not_mutate_an_in_flight_http_request(self):
        spider = make_spider()
        entered = threading.Event()
        release = threading.Event()
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0}
        snapshots = []

        def request(*args, **kwargs):
            snapshots.append(spider.session.cookies.get_dict())
            entered.set()
            release.wait(2)
            snapshots.append(spider.session.cookies.get_dict())
            return response

        spider.session.request = Mock(side_effect=request)
        with patch("boss_spider.time.sleep"):
            worker = threading.Thread(
                target=lambda: spider._request_json("get", "https://example.invalid", "test"),
            )
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                spider._heartbeat_once()
                spider.page.run_cdp.assert_not_called()
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(snapshots, [{"session": "old"}, {"session": "old"}])
        spider._heartbeat_once()
        self.assertEqual(spider.session.cookies.get("session"), "fresh")

    def test_detail_referer_is_request_local_and_does_not_pollute_list_requests(self):
        spider = make_spider(AutoDeliverer)
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0}
        spider.session.request = Mock(return_value=response)
        with patch("boss_spider.time.sleep"):
            spider.api_job_detail("test-security", "test-job")
            spider.api_job_list(keyword="test")
        calls = spider.session.request.call_args_list
        self.assertEqual(calls[0].kwargs["headers"]["referer"],
                         "https://www.zhipin.com/job_detail/test-job.html")
        self.assertEqual(calls[1].kwargs["headers"]["referer"], SEARCH_URL)
        self.assertEqual(spider.current_headers["referer"], SEARCH_URL)


if __name__ == "__main__":
    unittest.main()
