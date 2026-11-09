import csv
import io
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DrissionPage.common import make_session_ele

from ai_chains import JobMatchResponse, ProfileAssessment
from auto_deliver import AutoDeliverer, RESULT_FIELDS
from candidate_profiles import CandidateProfile, RoleFamily
from job_profiles import JobProfile


class JobDeduplicationTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.result_path = self.root / "results.csv"
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch("auto_deliver.time.sleep"))

    def write_history(self, rows):
        with self.result_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            writer.writerows({"投递时间": "2000-01-01 00:00:00", **row} for row in rows)

    @staticmethod
    def listing(job_id):
        return {
            "encryptJobId": job_id, "jobName": "Python 后端工程师",
            "brandName": "示例公司", "jobTypeName": "实习",
            "jobDegree": "本科", "jobExperience": "在校生",
        }

    def make_deliverer(self, dry_run=True):
        profile = JobProfile(
            id="backend", name="后端开发", role_family_id="backend",
            search_keywords=["后端"], threshold=70,
        )
        context = {
            "candidate": CandidateProfile(
                confirmed=True, revision=1, primary_direction="后端开发",
                allowed_role_families=[RoleFamily(
                    id="backend", name="后端开发", title_terms=["后端工程师"],
                )],
            ),
            "profiles": [profile], "rules": "评分规则",
            "allocations": [{"keyword": "后端", "profile_ids": [profile.id], "pages": [1]}],
        }
        cfg = {
            "result_file": str(self.result_path),
            "log_file": str(self.root / "delivery.json"),
            "resume_file": str(self.root / "resume.md"),
            "dry_run": dry_run, "humanize_enable": False,
            "test_limit": 1, "deliver_max_pages": 3, "daily_limit": 10,
            "match_threshold": 70, "area_filter": [], "job_delay": (0, 0),
            "detail_delay": (0, 0), "job_type_preference": "实习",
        }
        with patch("auto_deliver.BossDP.__init__", autospec=True,
                   side_effect=lambda instance: setattr(instance, "seen_job_ids", set())), \
                patch.object(AutoDeliverer, "_load_resume", return_value="使用 Python 开发后端接口"), \
                patch.object(AutoDeliverer, "_scoring_resume_prompt", side_effect=lambda text: text), \
                patch("auto_deliver.AIClient"), patch("auto_deliver.JobScoringChain"):
            deliverer = AutoDeliverer(cfg, matching_context=context)
        deliverer.browser_lock = threading.RLock()
        deliverer._human_navigate_interlude = Mock()
        deliverer._is_blacklisted_company = Mock(return_value=False)
        deliverer._work_condition_reject = Mock(return_value=None)
        deliverer._fetch_jd_dom = Mock(return_value={
            "desc": "负责 Python 后端接口开发。", "skills": ["Python"],
            "welfare_tags": [], "company_url": "",
        })
        deliverer.scoring_chain.invoke.return_value = JobMatchResponse(profile_results=[
            ProfileAssessment(profile_id=profile.id, score=88, role_fit=90, reason="后端项目经验匹配。"),
        ])
        deliverer.ai.gen_greeting.return_value = "您好，我有 Python 后端项目经验。"
        deliverer.deliver_one = Mock(side_effect=AssertionError("must not send a real greeting"))
        return deliverer

    def test_history_is_skipped_before_detail_and_ai_across_restarts(self):
        rows = [{"encryptJobId": status, "投递状态": status} for status in (
            "delivered", "already_contacted", "dry_run", "below_threshold", "out_of_scope",
        )]
        self.write_history(rows)
        original = self.result_path.read_bytes()
        for _ in range(2):
            deliverer = self.make_deliverer()
            deliverer.api_job_list = Mock(side_effect=[
                {"zpData": {"jobList": [self.listing(row["encryptJobId"]) for row in rows]}},
                {"zpData": {"jobList": []}},
            ])

            deliverer._run_profiled_pipeline()

            deliverer._fetch_jd_dom.assert_not_called()
            deliverer.scoring_chain.invoke.assert_not_called()
            deliverer.ai.gen_greeting.assert_not_called()
            self.assertEqual(deliverer.tracker.data["count"], 0)
            self.assertEqual(self.result_path.read_bytes(), original)

    def test_duplicate_page_does_not_consume_target_and_new_job_is_persisted(self):
        self.write_history([{"encryptJobId": "old-job", "投递状态": "dry_run"}])
        deliverer = self.make_deliverer()
        deliverer.api_job_list = Mock(side_effect=[
            {"zpData": {"jobList": [self.listing("old-job")]}},
            {"zpData": {"jobList": [self.listing("new-job")]}},
        ])

        deliverer._run_profiled_pipeline()

        deliverer._fetch_jd_dom.assert_called_once()
        self.assertEqual(deliverer._fetch_jd_dom.call_args.args[0]["encryptJobId"], "new-job")
        deliverer.scoring_chain.invoke.assert_called_once()
        deliverer.ai.gen_greeting.assert_called_once()
        self.assertEqual(deliverer.api_job_list.call_count, 2)
        with self.result_path.open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual([row["encryptJobId"] for row in csv.DictReader(f)], ["old-job", "new-job"])
        restored = self.make_deliverer()
        self.assertEqual(restored._filter_jobs([self.listing("new-job")]), [])

    def test_real_delivery_can_follow_preview_and_failures_remain_retryable(self):
        terminal = ("delivered", "already_contacted", "below_threshold", "out_of_scope", "role_reject")
        previews = ("dry_run", "dry_run_ready")
        retries = ("match_failed", "greeting_failed", "send_failed", "chat_failed", "no_button", "error", "failed")
        self.write_history([{"encryptJobId": status, "投递状态": status}
                            for status in (*terminal, *previews, *retries)])
        for dry_run, expected in ((True, retries), (False, (*previews, *retries))):
            with self.subTest(dry_run=dry_run):
                deliverer = self.make_deliverer(dry_run=dry_run)
                candidates = deliverer._filter_jobs([
                    self.listing(status) for status in (*terminal, *previews, *retries)
                ])
                self.assertEqual({job["encryptJobId"] for job in candidates}, set(expected))

    def test_successful_contact_is_not_undone_by_a_later_preview_or_failure(self):
        self.write_history([
            {"encryptJobId": "same-job", "投递状态": "delivered"},
            {"encryptJobId": "same-job", "投递状态": "dry_run"},
            {"encryptJobId": "same-job", "投递状态": "match_failed"},
            {"encryptJobId": "", "投递状态": "delivered"},
        ])
        deliverer = self.make_deliverer(dry_run=False)
        self.assertEqual(deliverer._filter_jobs([self.listing("same-job")]), [])
        self.assertEqual(len(deliverer._filter_jobs([self.listing("different-job")])), 1)

    def test_contacted_detail_never_reaches_scoring_or_greeting(self):
        for container, action in (
            ("job-op", '<a class="btn-startchat">已沟通</a>'),
            ("detail-op", '<button class="chat-action">继续<span>沟通</span></button>'),
            ("job-op", '<a class="btn-startchat" data-isfriend="1">立即沟通</a>'),
            ("job-detail-op clearfix", '<a class="op-btn op-btn-chat">继续沟通</a>'),
        ):
            with self.subTest(action=action):
                deliverer = self.make_deliverer()
                dom = make_session_ele(f'<div class="{container}">' + action + '</div>')
                tab = SimpleNamespace(
                    wait=SimpleNamespace(doc_loaded=Mock()), eles=dom.eles,
                    ele=Mock(side_effect=[SimpleNamespace(text="负责 Python 后端开发。"), None]),
                )
                deliverer._detail_tab_get = Mock(return_value=tab)
                del deliverer._fetch_jd_dom
                deliverer.api_job_list = Mock(side_effect=[
                    {"zpData": {"jobList": [self.listing("contacted-job")]}},
                    {"zpData": {"jobList": []}},
                ])

                deliverer._run_profiled_pipeline()

                deliverer.scoring_chain.invoke.assert_not_called()
                deliverer.ai.gen_greeting.assert_not_called()
                deliverer.deliver_one.assert_not_called()
                self.assertEqual(deliverer.tracker.data["count"], 0)
                self.assertEqual(deliverer.results[0]["投递状态"], "already_contacted")
                self.assertEqual(deliverer.results[0]["AI匹配分数"], "")
                self.assertEqual(deliverer.results[0]["打招呼语"], "")
                self.result_path.unlink()
                Path(deliverer.cfg["log_file"]).unlink()

    def test_contact_check_ignores_navigation_and_other_jobs(self):
        for target in (
            "/web/geek/chat?jobId=other-job",
            "/web/geek/chat?encryptJobId=other-job",
            "/job_detail/other-job.html",
        ):
            with self.subTest(target=target):
                dom = make_session_ele(
                    '<nav><a>已沟通</a></nav>'
                    '<div class="job-detail-op">'
                    f'<a href="{target}">继续沟通</a>'
                    '<a class="op-btn-chat" href="/web/geek/chat?jobId=current-job">立即沟通</a>'
                    '</div><aside><button>继续沟通</button></aside>'
                )
                self.assertEqual(AutoDeliverer._job_contact_state(dom, "current-job"), "new_contact")

    def test_unreadable_history_stops_before_browser_startup(self):
        with patch("auto_deliver.BossDP.__init__") as browser_init, \
                patch("result_store.open", side_effect=PermissionError("locked")), \
                patch.object(AutoDeliverer, "_load_resume", return_value="Python 项目经验"):
            with self.assertRaisesRegex(OSError, "历史结果无法读取"):
                AutoDeliverer({
                    "result_file": str(self.result_path), "resume_file": "resume.md", "dry_run": True,
                }, matching_context={"candidate": object()})
        browser_init.assert_not_called()

    def test_late_contact_status_is_checked_after_detail_content_loads(self):
        deliverer = self.make_deliverer()
        tab = SimpleNamespace(
            wait=SimpleNamespace(doc_loaded=Mock()), eles=Mock(return_value=[]),
            ele=Mock(side_effect=[SimpleNamespace(text="负责 Python 后端开发。"), None]),
        )
        deliverer._detail_tab_get = Mock(return_value=tab)
        deliverer._job_contact_state = Mock(side_effect=["unknown", "unknown", "already_contacted"])
        del deliverer._fetch_jd_dom

        result = deliverer._fetch_jd_dom({
            "encryptJobId": "late-job", "详情链接": "https://www.zhipin.com/job_detail/late-job.html",
        })

        self.assertTrue(result.get("already_contacted"))


if __name__ == "__main__":
    unittest.main()
