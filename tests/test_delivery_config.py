import ast
import copy
import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import boss_spider
import delivery_config
import desktop_panel
import platform_locations


class DeliveryConfigTransmissionTests(unittest.TestCase):
    def test_saved_environment_values_reach_runtime_configuration(self):
        values = {
            "AI_BASE_URL": "https://model.example/v1",
            "AI_API_KEY": "test-model-key",
            "AI_MODEL": "test-model",
            "AI_REASONING_EFFORT": "HIGH",
            "AI_TIMEOUT": "41",
            "AI_MAX_RETRIES": "3",
            "GREETING_PROMPT": "自定义招呼语 ${岗位名}\n第二行",
            "TAVILY_ENABLED": "false",
            "TAVILY_API_KEY": "test-search-key",
            "TAVILY_TIMEOUT": "8",
            "RESUME_FILE": "test-resume.md",
            "MATCH_THRESHOLD": "81",
            "DELIVER_KEYWORD": "测试岗位",
            "DELIVER_MAX_PAGES": "4",
            "JOB_TYPE_PREFERENCE": "全职",
            "PLATFORM_AREA_FILTER": "南山区,福田区",
            "PLATFORM_JOB_TYPE": "实习",
            "PLATFORM_PAY_TYPE": "日结",
            "PLATFORM_PART_TIME": "寒暑假",
            "PLATFORM_EXPERIENCE": "在校生",
            "PLATFORM_DEGREE": "大专",
            "PLATFORM_INDUSTRY": "100020",
            "PLATFORM_SCALE": "20-99人",
            "DAILY_LIMIT": "12",
            "JOB_DELAY_MIN": "4",
            "JOB_DELAY_MAX": "9",
            "HUMAN_EVERY_N": "0",
            "HUMANIZE_ENABLE": "false",
            "FAVORITE_SCORE": "88",
            "KEEP_LOGIN": "false",
            "DETAIL_DELAY_MIN": "5",
            "DETAIL_DELAY_MAX": "10",
            "REST_DAY_REQUIRE": "双休",
            "WELFARE_REQUIRE": "五险一金,带薪年假",
            "WORK_TIME_START": "09:00",
            "WORK_TIME_END": "18:30",
            "AREA_FILTER": "南山,福田",
            "DRY_RUN": "true",
            "TEST_LIMIT": "2",
            "LOGIN_WAIT": "15",
            "CITY_CODE": "101280600",
            "BROWSER_PATH": "",
            "BROWSER_BACKGROUND": "false",
        }
        expected = {
            "ai_base_url": values["AI_BASE_URL"],
            "ai_api_key": values["AI_API_KEY"],
            "ai_model": values["AI_MODEL"],
            "greeting_prompt": values["GREETING_PROMPT"],
            "ai_reasoning_effort": "high",
            "ai_timeout": 41,
            "ai_max_retries": 3,
            "tavily_enabled": False,
            "tavily_api_key": values["TAVILY_API_KEY"],
            "tavily_timeout": 8,
            "resume_file": "test-resume.md",
            "match_threshold": 81,
            "deliver_keyword": "测试岗位",
            "deliver_max_pages": 4,
            "job_type_preference": "全职",
            "platform_area_filter": ["南山区", "福田区"],
            "platform_job_type": "实习",
            "platform_pay_type": "日结",
            "platform_part_time": "寒暑假",
            "platform_experience": "在校生",
            "platform_degree": "大专",
            "platform_industry": "100020",
            "platform_scale": "20-99人",
            "daily_limit": 12,
            "job_delay": (4, 9),
            "human_every_n": 0,
            "humanize_enable": False,
            "favorite_score": 88,
            "keep_login": False,
            "browser_background": False,
            "detail_delay": (5, 10),
            "rest_day_require": "双休",
            "welfare_require": ["五险一金", "带薪年假"],
            "work_time_start": "09:00",
            "work_time_end": "18:30",
            "area_filter": ["南山", "福田"],
            "dry_run": True,
            "test_limit": 2,
            "login_wait": 15,
        }
        # Retain old favorite thresholds when loading saved configs, without
        # presenting an automatic-favorite control in the current workflow.
        self.assertEqual(
            {field[0] for field in desktop_panel.FIELDS},
            set(values) - {"FAVORITE_SCORE"},
        )

        original_config = delivery_config.DELIVER_CONFIG
        original_spider_config = copy.deepcopy(boss_spider.Config)
        spider_config = boss_spider.Config
        try:
            with patch.dict(os.environ, values, clear=False), patch.object(
                platform_locations,
                "fetch_platform_districts",
                return_value=[
                    {"name": "南山区", "code": "440305"},
                    {"name": "福田区", "code": "440304"},
                ],
            ):
                loaded = importlib.reload(delivery_config)
                config = dict(loaded.DELIVER_CONFIG)
                self.assertEqual(config["greeting_prompt"], values["GREETING_PROMPT"])
                spider_config = boss_spider.Config
                loaded.apply_search_settings(config, spider_config)
                self.assertFalse(spider_config["browser_background"])
                self.assertEqual(spider_config["city_id"], "101280600")
                self.assertEqual(
                    parse_qs(urlparse(spider_config["start_url"]).query)["city"],
                    ["101280600"],
                )
                self.assertEqual(
                    parse_qs(urlparse(spider_config["start_url"]).query)[
                        "multiBusinessDistrict"
                    ],
                    ["440305,440304"],
                )
                self.assertEqual(
                    parse_qs(urlparse(spider_config["start_url"]).query),
                    {
                        "city": ["101280600"],
                        "multiBusinessDistrict": ["440305,440304"],
                        "jobType": ["1902"],
                        "payType": ["2501"],
                        "experience": ["108"],
                        "degree": ["202"],
                        "industry": ["100020"],
                        "scale": ["302"],
                        "query": ["测试岗位"],
                    },
                )
                # 兼职时段只在平台求职类型为「兼职」时下发，避免非兼职被误杀
                self.assertNotIn("partTime", parse_qs(urlparse(
                    spider_config["start_url"]).query))
        finally:
            delivery_config.DELIVER_CONFIG = original_config
            spider_config.clear()
            spider_config.update(original_spider_config)

        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(config[key], value)

    def test_importing_saved_platform_areas_does_not_make_network_requests(self):
        original_config = delivery_config.DELIVER_CONFIG
        original_spider_config = copy.deepcopy(boss_spider.Config)
        try:
            with patch.dict(os.environ, {
                "PLATFORM_AREA_FILTER": "440305",
                "CITY_CODE": "101280600",
            }, clear=False), patch.object(
                platform_locations, "fetch_platform_districts"
            ) as fetch_districts:
                loaded = importlib.reload(delivery_config)
                self.assertEqual(
                    loaded.DELIVER_CONFIG["platform_area_filter"], ["440305"]
                )
                fetch_districts.assert_not_called()
        finally:
            delivery_config.DELIVER_CONFIG = original_config
            boss_spider.Config.clear()
            boss_spider.Config.update(original_spider_config)

    def test_default_page_cap_is_dynamic_safety_ceiling_and_clamps_env_values(self):
        original_config = delivery_config.DELIVER_CONFIG
        original_spider_config = copy.deepcopy(boss_spider.Config)
        try:
            for raw, expected in (("", 10), ("99", 50), ("0", 1)):
                with self.subTest(raw=raw), patch.dict(
                    os.environ, {"DELIVER_MAX_PAGES": raw}, clear=False
                ), patch("dotenv.load_dotenv"):
                    if not raw:
                        os.environ.pop("DELIVER_MAX_PAGES", None)
                    loaded = importlib.reload(delivery_config)
                    self.assertEqual(loaded.DELIVER_CONFIG["deliver_max_pages"], expected)
        finally:
            delivery_config.DELIVER_CONFIG = original_config
            boss_spider.Config.clear()
            boss_spider.Config.update(original_spider_config)


if __name__ == "__main__":
    unittest.main()
