import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
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
        with patch("boss_spider.random.choice", return_value="quick_scan"), \
                patch("boss_spider.time.sleep"), \
                patch("boss_spider.time.monotonic", return_value=100):
            spider._human_navigate_interlude([JOB])
            spider._human_click_job_action([JOB])
            spider._human_enter_detail_action([JOB])
        spider.page.scroll.to_top.assert_called_once_with()
        spider.page.get.assert_not_called()
        spider.page.ele.assert_not_called()
        spider.page.eles.assert_not_called()
        with patch("boss_spider.random.choice", return_value="quick_scan"), \
                patch("boss_spider.time.sleep"), \
                patch("boss_spider.time.monotonic", return_value=161):
            spider._human_navigate_interlude([JOB])
        self.assertEqual(spider.page.scroll.to_top.call_count, 2)

    def test_browse_errors_do_not_force_navigation(self):
        spider = make_spider()
        spider.page.scroll.to_top.side_effect = RuntimeError("page changed")
        with patch("boss_spider.random.choice", return_value="quick_scan"):
            spider._human_navigate_interlude([JOB])
        spider.page.get.assert_not_called()

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
