import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import os

import boss_spider
from ai_client import AIClient
from auto_deliver import AutoDeliverer
from delivery_config import apply_search_settings
from prefilter import extract_work_info, need_company_welfare, work_condition_reject


def client_config(max_retries):
    return {
        "ai_base_url": "https://example.invalid/v1",
        "ai_api_key": "test-key",
        "ai_model": "test-model",
        "ai_timeout": 1,
        "ai_max_retries": max_retries,
    }


class AIRetrySettingsTests(unittest.TestCase):
    def test_zero_retries_still_makes_the_initial_request(self):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        client = AIClient(client_config(max_retries=0))

        with patch("ai_client.requests.post", return_value=response) as post:
            self.assertEqual(client.chat([{"role": "user", "content": "hello"}]), "ok")

        post.assert_called_once()

    def test_retry_count_means_retries_after_the_initial_request(self):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        client = AIClient(client_config(max_retries=2))
        with patch("ai_client.requests.post", side_effect=[RuntimeError("first"),
                                                           RuntimeError("second"),
                                                           response]) as post, \
                patch("ai_client.time.sleep") as sleep:
            self.assertEqual(client.chat([{"role": "user", "content": "hello"}]), "ok")

        self.assertEqual(post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])


class WorkScheduleSettingsTests(unittest.TestCase):
    def test_flexible_work_does_not_change_the_rest_day_classification(self):
        self.assertEqual(extract_work_info("周末双休，弹性工作时间"), ("", "双休"))

    def test_negated_rest_patterns_are_not_reported_as_actual_schedules(self):
        for text in ("不单休", "非大小周", "不是固定双休"):
            with self.subTest(text=text):
                self.assertEqual(extract_work_info(text)[1], "")

    def test_rest_day_filter_uses_the_schedule_even_when_flexible_work_is_mentioned(self):
        config = {
            "rest_day_require": "双休",
            "work_time_start": "",
            "work_time_end": "",
        }

        self.assertIsNone(work_condition_reject("双休，弹性工作", config))
        self.assertIsNone(work_condition_reject("不单休", config))

    def test_requested_welfare_triggers_company_lookup_only_when_missing_from_jd(self):
        config = {
            "rest_day_require": "不限",
            "work_time_start": "",
            "work_time_end": "",
            "welfare_require": ["五险一金", "带薪年假"],
        }

        self.assertTrue(need_company_welfare("负责接口开发", config))
        self.assertFalse(need_company_welfare("五险一金、带薪年假", config))
        self.assertIsNone(work_condition_reject("不含五险一金", config))


class DeliveryBrowserSettingsTests(unittest.TestCase):
    def test_delivery_detail_dwell_uses_configured_range(self):
        class Button:
            def click(inner_self):
                page.url = "https://example.invalid/chat"

        page = SimpleNamespace(
            url="",
            tab_ids={"main"},
            scroll=SimpleNamespace(down=Mock(), to_top=Mock()),
            get=Mock(),
            ele=Mock(return_value=Button()),
        )
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.page = page
        deliverer.browser_lock = threading.RLock()
        deliverer.cfg = {"detail_delay": (7, 9)}
        deliverer._send_greeting_in_chat = Mock(return_value="delivered")
        page.get.side_effect = lambda url: setattr(page, "url", url)

        with patch("auto_deliver.time.sleep"), \
                patch("auto_deliver.random.uniform", return_value=8) as uniform:
            result = deliverer.deliver_one(
                {"详情链接": "https://example.invalid/job"}, "您好"
            )

        self.assertEqual(result, "delivered")
        self.assertEqual(uniform.call_args_list[0].args, (7, 9))

    def test_post_delivery_browsing_starts_from_the_configured_search_page(self):
        visits = []
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.page = SimpleNamespace(get=visits.append)
        deliverer.browser_lock = threading.RLock()
        deliverer._human_browse_job_list = [{"encryptJobId": "job-1"}]
        deliverer.get_cookie_headers = Mock(return_value=True)
        deliverer._human_navigate_interlude = Mock()

        with patch("auto_deliver.SpiderConfig", {"start_url": "https://example.invalid/search"}), \
                patch("auto_deliver.time.sleep"):
            deliverer._human_browse_after_delivery()

        self.assertEqual(visits, ["https://example.invalid/search"])
        deliverer.get_cookie_headers.assert_called_once_with()
        deliverer._human_navigate_interlude.assert_called_once_with(
            deliverer._human_browse_job_list
        )

    def test_delivery_interval_keeps_session_fresh_without_human_browsing(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {"human_every_n": 2}
        deliverer.deliver_count = 2
        deliverer.humanize_enabled = False
        deliverer.get_cookie_headers = Mock(return_value=True)
        deliverer._human_browse_after_delivery = Mock()

        deliverer._after_successful_delivery()

        deliverer.get_cookie_headers.assert_called_once_with()
        deliverer._human_browse_after_delivery.assert_not_called()

    def test_zero_delivery_interval_disables_session_and_browse_actions(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {"human_every_n": 0}
        deliverer.deliver_count = 2
        deliverer.humanize_enabled = True
        deliverer.get_cookie_headers = Mock(return_value=True)
        deliverer._human_browse_after_delivery = Mock()

        deliverer._after_successful_delivery()

        deliverer.get_cookie_headers.assert_not_called()
        deliverer._human_browse_after_delivery.assert_not_called()


class SearchSettingsTransmissionTests(unittest.TestCase):
    def test_city_setting_reaches_browser_url_and_job_list_api(self):
        spider_config = dict(boss_spider.Config)
        deliver_config = {
            "deliver_keyword": "AI应用开发",
            "keep_login": True,
            "platform_area_filter": [],
            "platform_job_type": "兼职",
            "platform_pay_type": "日结",
            "platform_part_time": "寒暑假",
            "platform_experience": "在校生",
            "platform_degree": "大专",
            "platform_industry": "100020",
            "platform_scale": "20-99人",
        }
        spider = boss_spider.BossDP.__new__(boss_spider.BossDP)

        with patch.dict(os.environ, {"CITY_CODE": "101280100"}), \
                patch.dict(boss_spider.Config, spider_config), \
                patch.object(spider, "_request_json", return_value={}) as request:
            browser_url = apply_search_settings(deliver_config, boss_spider.Config)
            spider.api_job_list(page=1, keyword=deliver_config["deliver_keyword"])

        self.assertIn("city=101280100", browser_url)
        self.assertEqual(request.call_args.kwargs["data"]["city"], "101280100")
        self.assertEqual(
            request.call_args.kwargs["data"],
            {
                "page": 1,
                "pageSize": boss_spider.Config["page_size"],
                "city": "101280100",
                "query": "AI应用开发",
                "scene": 1,
                "jobType": "1903",
                "payType": "2501",
                "partTime": "2702",
                "experience": "108",
                "degree": "202",
                "industry": "100020",
                "scale": "302",
            },
        )
        from urllib.parse import parse_qs, urlparse
        self.assertEqual(
            parse_qs(urlparse(browser_url).query),
            {
                "city": ["101280100"],
                "jobType": ["1903"],
                "payType": ["2501"],
                "partTime": ["2702"],
                "experience": ["108"],
                "degree": ["202"],
                "industry": ["100020"],
                "scale": ["302"],
                "query": ["AI应用开发"],
            },
        )


if __name__ == "__main__":
    unittest.main()
