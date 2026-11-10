import csv
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import desktop_panel
from auto_deliver import AutoDeliverer
from boss_spider import PlatformAccessStopped
from job_platforms import (
    build_platform_search_url, job_identity, parse_platforms, platform_city_code,
    platform_profile_dir,
)
from panel_config_logic import validate_config_values
from panel_result_logic import filter_result_rows, summarize_result_rows
from platform_browser import BrowserJobPlatform, PlatformPageChanged
from platform_deliverer import BrowserPlatformDeliverer
from platform_job_parser import (
    candidate_row, parse_job_cards, parse_job_detail, zhilian_state_description,
)
import platform_worker
from result_store import ResultRecorder


LIEPIN_CARD = """
<div class="jobDetailBox">
  <a data-nick="job-detail-job-info" href="https://www.liepin.com/job/123.shtml?tracking=ignored">
    <div><div class="jobTitleBox"><div title="Python开发">Python开发</div>
      <div><span>【</span><span>深圳-南山区</span><span>】</span></div></div><span>15-30k</span></div>
    <div><span>3-5年</span><span>本科</span></div>
  </a>
  <div><span class="companyName">测试科技</span></div>
</div>
"""
ZHILIAN_CARD = """
<div class="joblist-box__item">
  <a class="jobinfo__name joblist-box__title" href="https://jobs.zhaopin.com/ABC123.htm">AI实习生</a>
  <span class="company-name">示例公司</span><span class="joblist-box__salary">200-300元/天</span>
  <span class="joblist-box__job-location">深圳-福田区</span><span>本科</span><span>经验不限</span>
</div>
"""


class PlatformSettingsTests(unittest.TestCase):
    def test_platform_labels_ids_aliases_and_duplicates(self):
        self.assertEqual(parse_platforms(), ["boss"])
        self.assertEqual(parse_platforms("BOSS 直聘,智联招聘,liepin,zhilian"), ["boss", "zhilian", "liepin"])
        for value in ("", [], "unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_platforms(value)

    def test_platform_urls_keep_independent_codes_and_page_numbering(self):
        config = {"city_code": "101280600"}
        zhilian = urlparse(build_platform_search_url("zhilian", config, "AI 开发", 2))
        liepin = urlparse(build_platform_search_url("liepin", config, "AI 开发", 2))
        self.assertEqual(zhilian.path, "/sou/jl489/")
        self.assertEqual(parse_qs(zhilian.query), {"kw": ["AI 开发"], "p": ["2"]})
        self.assertEqual(parse_qs(liepin.query), {
            "key": ["AI 开发"], "dqs": ["050090"], "curPage": ["1"], "pageSize": ["40"],
        })

    def test_unmapped_city_requires_explicit_platform_code(self):
        config = {"city_code": "101210100"}
        with self.assertRaisesRegex(ValueError, "城市代码"):
            platform_city_code("zhilian", config)
        config["zhilian_city_code"] = "653"
        self.assertEqual(platform_city_code("zhilian", config), "653")
        config["zhilian_city_code"] = "not-a-number"
        with self.assertRaises(ValueError):
            platform_city_code("zhilian", config)

    def test_profile_directories_are_isolated(self):
        self.assertNotEqual(platform_profile_dir("zhilian"), platform_profile_dir("liepin"))
        self.assertNotIn("boss-zhipin-scraper", str(platform_profile_dir("liepin")))

    def test_platform_identity_accepts_only_exact_official_job_routes(self):
        zhilian = job_identity("zhilian", "https://jobs.zhaopin.com/123.htm?x=1")
        liepin = job_identity("liepin", "https://www.liepin.com/job/123.shtml?x=2")
        self.assertNotEqual(zhilian.key, liepin.key)
        self.assertNotEqual(liepin.key, "123")
        self.assertNotEqual(liepin, job_identity("liepin", "https://www.liepin.com/a/123.shtml"))
        self.assertEqual(zhilian.key, job_identity("zhilian", "https://www.zhaopin.com/jobdetail/123.htm").key)
        for url in ("https://www.liepin.com.evil.test/job/123.shtml", "http://www.liepin.com/job/123.shtml",
                    "https://user" + chr(64) + "www.liepin.com/job/123.shtml", "https://www.liepin.com:444/job/123.shtml",
                    "https://www.liepin.com/zhaopin/123.shtml"):
            with self.subTest(url=url):
                self.assertIsNone(job_identity("liepin", url))

    def test_panel_validation_handles_platforms_and_unmapped_cities(self):
        base = {"RESUME_FILE": "resume.md", "CITY_CODE": "101280600"}
        self.assertEqual(validate_config_values({**base, "JOB_PLATFORMS": "智联招聘"}), [])
        errors = validate_config_values({**base, "JOB_PLATFORMS": "猎聘"})
        self.assertTrue(any("暂停" in error and "账号风险" in error for error in errors))
        self.assertTrue(validate_config_values({**base, "JOB_PLATFORMS": ""}))
        self.assertTrue(validate_config_values({**base, "JOB_PLATFORMS": "智联招聘", "CITY_CODE": "101210100"}))


class PlatformParserTests(unittest.TestCase):
    def test_current_liepin_card_retains_salary_location_and_company(self):
        jobs = parse_job_cards("liepin", LIEPIN_CARD + LIEPIN_CARD)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["jobName"], "Python开发")
        self.assertEqual(jobs[0]["salaryDesc"], "15-30k")
        self.assertEqual(jobs[0]["brandName"], "测试科技")
        self.assertEqual(jobs[0]["areaDistrict"], "南山区")
        self.assertEqual(jobs[0]["jobDegree"], "本科")
        row = candidate_row(jobs[0])
        self.assertEqual(row["详情链接"], "https://www.liepin.com/job/123.shtml")
        self.assertEqual(row["平台"], "猎聘")

    def test_zhilian_card_does_not_use_boss_detail_links(self):
        raw = parse_job_cards("zhilian", ZHILIAN_CARD)[0]
        self.assertEqual(raw["encryptJobId"], "zhilian:ABC123")
        row = candidate_row(raw)
        self.assertEqual(row["详情链接"], "https://jobs.zhaopin.com/ABC123.htm")
        worker = AutoDeliverer.__new__(AutoDeliverer)
        worker.stage_counts = {}
        worker.seen_job_ids = set()
        worker.profile_mode = True
        worker.tracker = SimpleNamespace(already_done=lambda _: False)
        worker.cfg = {"area_filter": []}
        self.assertEqual(worker._filter_jobs([raw])[0]["详情链接"], row["详情链接"])

    def test_unrecognized_card_or_external_link_cannot_become_a_job(self):
        self.assertEqual(parse_job_cards("liepin", LIEPIN_CARD.replace(
            "https://www.liepin.com/job/123.shtml", "https://example.test/job/123.shtml",
        )), [])
        self.assertEqual(parse_job_cards("zhilian", "<p>Security Verification</p>"), [])

    def test_descriptions_are_scoped_to_the_job(self):
        html = '<article>unrelated</article><dd data-selector="job-intro-content">岗位职责：开发服务</dd>'
        self.assertEqual(parse_job_detail("liepin", html)["desc"], "岗位职责：开发服务")
        state = {"jobDetail": {"detailedPosition": {
            "positionNumber": "ABC123", "description": "<p>Python服务开发</p>",
        }}}
        html = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
        self.assertEqual(zhilian_state_description(html, "ABC123"), "Python服务开发")
        self.assertEqual(zhilian_state_description(html, "OTHER"), "")


class PlatformRuntimeTests(unittest.TestCase):
    def test_zhilian_login_page_uses_first_keyword_or_recommendations(self):
        for value, expected in (("Python  API，AI应用开发", "Python API"), (" ", "")):
            with self.subTest(value=value):
                adapter = self.adapter(url="https://www.zhaopin.com/sou/jl765/")
                adapter.platform = "zhilian"
                adapter.label = "智联招聘"
                adapter.config["deliver_keyword"] = value
                adapter.logged_in = Mock(return_value=True)
                adapter.check_page = Mock()
                adapter.wait_login(1)
                url = adapter.page.get.call_args.args[0]
                self.assertEqual(parse_qs(urlparse(url).query, keep_blank_values=True)["kw"], [expected])
                self.assertEqual(adapter.config["deliver_keyword"], value)

    def adapter(self, html="", url="https://www.liepin.com/job/123.shtml"):
        adapter = BrowserJobPlatform.__new__(BrowserJobPlatform)
        adapter.platform = "liepin"
        adapter.label = "猎聘"
        adapter.config = {"city_code": "101280600", "job_delay": (0, 0), "detail_delay": (0, 0)}
        adapter.lock = __import__("threading").RLock()
        adapter.stop_reason = ""
        adapter._page_signatures = {}
        adapter._modern_queries = {}
        adapter._last_navigation_at = 0
        adapter.page = Mock(url=url, title="深圳招聘", html=html)
        adapter.page.eles.return_value = []
        adapter._main_page = adapter.page
        adapter._detail_page = adapter.page
        return adapter

    def test_security_title_and_route_stop_without_retry(self):
        for title, url in (("Security Verification", "https://www.zhaopin.com/sou/jl489/"),
                           ("安全中心-验证码", "https://safe.liepin.com/page/liepin/captchaPage_ip_PC")):
            adapter = self.adapter()
            adapter.page.title = title
            adapter.page.url = url
            with self.subTest(title=title), self.assertRaises(PlatformAccessStopped):
                adapter.check_page()
            adapter.page.get.assert_not_called()

    def test_liepin_start_is_blocked_before_any_browser_or_profile_is_opened(self):
        with patch.object(BrowserJobPlatform, "_open_browser") as open_browser, \
                patch("platform_browser.platform_profile_dir") as profile:
            with self.assertRaisesRegex(ValueError, "账号风险"):
                BrowserJobPlatform("liepin", {})
        open_browser.assert_not_called()
        profile.assert_not_called()

    def test_liepin_saved_config_is_blocked_before_matching_or_worker_creation(self):
        with patch.object(platform_worker, "create_deliverer") as create, \
                patch.object(platform_worker, "load_matching_config") as matching:
            code = platform_worker.run_platforms({"platforms": "boss,liepin"})
        self.assertEqual(code, 2)
        create.assert_not_called()
        matching.assert_not_called()

    def test_liepin_direct_worker_creation_is_blocked_before_shared_initialization(self):
        with patch.object(AutoDeliverer, "__init__") as initialize:
            with self.assertRaisesRegex(ValueError, "账号风险"):
                platform_worker.create_deliverer("liepin", {}, {})
            with self.assertRaisesRegex(ValueError, "账号风险"):
                BrowserPlatformDeliverer("liepin", {})
        initialize.assert_not_called()

    def test_list_page_repeating_jobs_raises_instead_of_looping(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        adapter._wait_results = Mock(return_value=[{
            "encryptJobId": "liepin:job:123", "cityName": "深圳",
        }])
        adapter.search(1, "Python")
        with self.assertRaises(PlatformPageChanged):
            adapter.search(2, "Python")

    def test_modern_search_keeps_query_progress_after_opening_a_detail(self):
        adapter = self.adapter(url="https://www.zhaopin.com/sou/jl489/?kw=Python&p=1")
        adapter.platform = "zhilian"
        adapter._navigate = Mock()
        first = {"encryptJobId": "zhilian:first", "cityName": "深圳"}
        second = {"encryptJobId": "zhilian:second", "cityName": "深圳"}
        adapter._wait_results = Mock(return_value=[first])
        adapter.page.ele.return_value = True
        adapter.page.run_js.return_value = "loading"
        search_tab = adapter.page
        adapter.search(1, "Python")
        adapter._detail_page = Mock(url="https://jobs.zhaopin.com/first.htm")
        adapter._activate_detail_page()
        adapter._read_jobs = Mock(return_value=[first, second])
        self.assertEqual(adapter.search(2, "Python")["zpData"]["jobList"], [second])
        self.assertIs(adapter.page, search_tab)
        self.assertEqual(adapter._navigate.call_count, 1)
        self.assertEqual(adapter._modern_queries["Python"]["seen"], {"zhilian:first", "zhilian:second"})

    def test_modern_queries_keep_independent_tabs_and_seen_ids(self):
        adapter = self.adapter()
        adapter.platform = "zhilian"
        tabs = [Mock(url=f"https://www.zhaopin.com/sou/jl489/?kw={keyword}", title="深圳")
                for keyword in ("Python", "AI")]
        for tab in tabs:
            tab.eles.return_value = []
        for keyword, tab in zip(("Python", "AI"), tabs):
            adapter._modern_queries[keyword] = {"tab": tab, "url": tab.url, "page": 1,
                                                "seen": {f"zhilian:{keyword}"}}
        adapter._load_more_modern = Mock(return_value=[])
        adapter.search(2, "AI")
        self.assertIs(adapter.page, tabs[1])
        adapter._load_more_modern.assert_called_with({"zhilian:AI"})
        adapter.search(2, "Python")
        self.assertIs(adapter.page, tabs[0])
        adapter._load_more_modern.assert_called_with({"zhilian:Python"})

    def test_modern_scroll_stops_at_end_or_unknown_state(self):
        adapter = self.adapter()
        adapter._read_jobs = Mock()
        adapter.page.run_js.return_value = "end"
        self.assertEqual(adapter._load_more_modern(set()), [])
        adapter._read_jobs.assert_not_called()
        adapter.page.run_js.return_value = "unknown"
        with self.assertRaises(PlatformPageChanged):
            adapter._load_more_modern(set())
        adapter._read_jobs.assert_not_called()

    def test_modern_search_rejects_changed_query_url(self):
        adapter = self.adapter()
        adapter.platform = "zhilian"
        adapter._modern_queries["Python"] = {"tab": adapter.page, "url": "https://www.zhaopin.com/",
                                              "page": 1, "seen": set()}
        with self.assertRaises(PlatformPageChanged):
            adapter.search(2, "Python")
        adapter.page.run_js.assert_not_called()

    def test_apply_requires_job_identity_and_explicit_receipt(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        button = Mock(text="立即投递")
        adapter._job_buttons = Mock(return_value=[button])
        adapter.already_applied = Mock(side_effect=[False, True])
        job = {"详情链接": "https://www.liepin.com/job/123.shtml"}
        with patch("platform_browser.time.sleep"):
            self.assertEqual(adapter.apply(job), "delivered")
        button.click.assert_called_once()
        adapter.page.url = "https://www.liepin.com/job/999.shtml"
        with self.assertRaises(PlatformPageChanged):
            adapter.apply(job)
        self.assertEqual(button.click.call_count, 1)

    def test_apply_rechecks_identity_after_waiting_for_controls(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        adapter._job_buttons = Mock()
        job = {"详情链接": adapter.page.url}
        def redirect(_delay):
            adapter.page.url = "https://www.liepin.com/job/999.shtml"
        with patch("platform_browser.time.sleep", side_effect=redirect), self.assertRaises(PlatformPageChanged):
            adapter.apply(job)
        adapter._job_buttons.assert_not_called()

    def test_missing_application_control_requires_manual_action_without_clicking_chat(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        button = Mock(text="聊一聊")
        adapter._job_buttons = Mock(return_value=[button])
        with patch("platform_browser.time.sleep"):
            self.assertEqual(adapter.apply({"详情链接": adapter.page.url}), "manual_required")
        button.click.assert_not_called()
        self.assertFalse(adapter.submission_started)

    def test_click_without_receipt_is_never_reported_as_delivered(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        button = Mock(text="立即投递")
        adapter._job_buttons = Mock(return_value=[button])
        with patch("platform_browser.time.sleep"), \
                patch("platform_browser.time.monotonic", side_effect=[0, 0, 11]):
            self.assertEqual(adapter.apply({"详情链接": adapter.page.url}), "delivery_unconfirmed")
        button.click.assert_called_once()
        with self.assertRaises(PlatformAccessStopped):
            adapter.check_stopped()

    def test_already_applied_never_clicks(self):
        adapter = self.adapter()
        adapter._navigate = Mock()
        adapter.already_applied = Mock(return_value=True)
        adapter._job_buttons = Mock()
        with patch("platform_browser.time.sleep"):
            self.assertEqual(adapter.apply({"详情链接": adapter.page.url}), "already_contacted")
        adapter._job_buttons.assert_not_called()

    def test_unconfirmed_delivery_is_persisted_before_platform_stop(self):
        worker = BrowserPlatformDeliverer.__new__(BrowserPlatformDeliverer)
        worker.adapter = Mock()
        worker.adapter.apply.return_value = "delivery_unconfirmed"
        worker.adapter.check_stopped.side_effect = PlatformAccessStopped("needs review")
        worker._record = Mock()
        worker.match_scores = {"后端开发": 86}
        worker.tracker = Mock()
        with self.assertRaises(PlatformAccessStopped):
            worker.deliver_one({"encryptJobId": "liepin:job:123", "平台": "猎聘", "工作名称": "后端开发"}, "draft")
        self.assertEqual(worker._record.call_args.args[0]["投递状态"], "delivery_unconfirmed")
        self.assertEqual(worker._record.call_args.args[0]["AI匹配分数"], 86)
        self.assertEqual(worker._record.call_args.args[0]["打招呼语"], "draft")
        worker.tracker.mark.assert_called_once_with("liepin:job:123", "后端开发", "draft", "delivery_unconfirmed")

    def test_interruption_after_click_preserves_uncertain_submission(self):
        worker = BrowserPlatformDeliverer.__new__(BrowserPlatformDeliverer)
        worker.adapter = Mock(submission_started=True)
        worker.adapter.apply.side_effect = KeyboardInterrupt()
        worker.match_scores = {}
        worker.tracker = Mock()
        worker._record = Mock()
        with self.assertRaises(KeyboardInterrupt):
            worker.deliver_one({"encryptJobId": "zhilian:123"}, "draft")
        self.assertEqual(worker._record.call_args.args[0]["投递状态"], "delivery_unconfirmed")
        worker.tracker.mark.assert_called_once()

    def test_worker_runs_selected_platforms_in_order_and_continues_after_restriction(self):
        calls = []
        def create(platform, config, context):
            calls.append(platform)
            return SimpleNamespace(run=lambda: 3 if platform == "boss" else 0)
        with patch.object(platform_worker, "create_deliverer", side_effect=create), \
                patch.object(platform_worker, "load_matching_config", return_value={"profiles": []}):
            code = platform_worker.run_platforms({"platforms": "boss,zhilian", "city_code": "101280600"})
        self.assertEqual(calls, ["boss", "zhilian"])
        self.assertEqual(code, 3)

    def test_worker_validates_all_cities_before_starting_any_browser(self):
        with patch.object(platform_worker, "create_deliverer") as create:
            code = platform_worker.run_platforms({"platforms": "boss,zhilian", "city_code": "101210100"})
        self.assertEqual(code, 2)
        create.assert_not_called()

    def test_worker_shares_evaluation_budget_across_platforms(self):
        targets = []
        def create(platform, config, context):
            targets.append(config["test_limit"])
            count = 1 if platform == "boss" else config["test_limit"]
            return SimpleNamespace(run=lambda: 0, stage_counts={"ai_called": count})
        with patch.object(platform_worker, "create_deliverer", side_effect=create), \
                patch.object(platform_worker, "load_matching_config", return_value={}):
            code = platform_worker.run_platforms({
                "platforms": "boss,zhilian", "city_code": "101280600", "test_limit": 10,
            })
        self.assertEqual(code, 0)
        self.assertEqual(targets, [5, 9])


class PlatformHistoryTests(unittest.TestCase):
    def test_history_keeps_identical_native_ids_on_different_platforms_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["encryptJobId", "投递状态"])
                writer.writeheader()
                writer.writerows([
                    {"encryptJobId": "123", "投递状态": "delivered"},
                    {"encryptJobId": "liepin:job:123", "投递状态": "delivery_unconfirmed"},
                    {"encryptJobId": "zhilian:123", "投递状态": "match_failed"},
                ])
            self.assertEqual(ResultRecorder._load_processed_job_ids(path, dry_run=False),
                             {"123", "liepin:job:123"})

    def test_result_migration_keeps_old_rows_and_adds_platform_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.csv"
            path.write_text("encryptJobId,投递状态\nlegacy,delivered\n", encoding="utf-8-sig")
            before = path.read_bytes()
            ResultRecorder._migrate_result_file(path)
            backups = list(Path(temp).glob("*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), before)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["平台"], "BOSS 直聘")
            self.assertEqual(row["平台岗位ID"], "legacy")

    def test_pending_delivery_appears_in_review_filter(self):
        rows = [{"投递状态": status, "平台": "猎聘"}
                for status in ("delivery_unconfirmed", "manual_required")]
        self.assertEqual(summarize_result_rows(rows)["delivered"], 0)
        self.assertEqual(summarize_result_rows(rows)["review"], 2)
        self.assertEqual(filter_result_rows(rows, review_only=True), rows)
        self.assertEqual(filter_result_rows(rows, keyword="猎聘"), rows)


class PlatformPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_platform_selection_roundtrips_and_disables_boss_only_filters(self):
        with patch.object(desktop_panel.PanelApp, "refresh_results"), \
                patch.object(desktop_panel.PanelApp, "_restore_window_settings"), \
                patch.object(desktop_panel.PanelApp, "_save_window_settings"), \
                patch.object(desktop_panel.PanelApp, "_refresh_platform_areas"), \
                patch.object(desktop_panel, "QSettings", return_value=Mock(
                    value=lambda _key, default=None: default,
                )), \
                patch.object(desktop_panel, "read_env_dict", return_value={
                    "JOB_PLATFORMS": "zhilian,liepin", "CITY_CODE": "101280600",
                    "PLATFORM_JOB_TYPE": "全职", "JOB_TYPE_PREFERENCE": "实习",
                }):
            panel = desktop_panel.PanelApp()
            try:
                self.assertEqual(panel._selected_platforms(), ["zhilian", "liepin"])
                self.assertEqual(panel._read_widget_values()["JOB_PLATFORMS"], "智联招聘,猎聘")
                self.assertEqual(panel._read_widget_values()["JOB_TYPE_PREFERENCE"], "实习")
                self.assertTrue(panel.vars["JOB_TYPE_PREFERENCE"][0].isEnabled())
                liepin = next(check for option, check in panel.multiselect_checks["JOB_PLATFORMS"]
                              if option == "猎聘")
                self.assertIn("暂停", liepin.text())
                self.assertTrue(liepin.isEnabled())
                self.assertIn("账号风险", liepin.toolTip())
                self.assertFalse(panel.field_blocks["LIEPIN_CITY_CODE"].isEnabled())
                liepin.setChecked(False)
                self.assertFalse(liepin.isEnabled())
                self.assertEqual(panel._read_widget_values()["JOB_PLATFORMS"], "智联招聘")
                self.assertFalse(panel.field_blocks["LIEPIN_CITY_CODE"].isEnabled())
                self.assertFalse(panel.field_blocks["PLATFORM_INDUSTRY"].isEnabled())
                self.assertTrue(panel.field_blocks["ZHILIAN_CITY_CODE"].isEnabled())
                for option, check in panel.multiselect_checks["JOB_PLATFORMS"]:
                    if option == "BOSS 直聘":
                        check.setChecked(True)
                self.assertTrue(panel.field_blocks["PLATFORM_INDUSTRY"].isEnabled())
                self.assertEqual(panel._read_widget_values()["JOB_TYPE_PREFERENCE"], "全职")
                for option, check in panel.multiselect_checks["JOB_PLATFORMS"]:
                    if option == "BOSS 直聘":
                        check.setChecked(False)
                self.assertEqual(panel._read_widget_values()["JOB_TYPE_PREFERENCE"], "实习")
            finally:
                panel.close()
                panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
