import csv
import os
import tempfile
import unittest

from delivery_config import RESULT_FIELDS
from panel_result_logic import (
    build_result_evidence_html,
    build_result_detail_html,
    deduplicate_result_rows,
    filter_result_rows,
    row_score,
    score_value,
    status_display,
    summarize_result_rows,
    update_result_mark,
)


def make_row(**overrides):
    row = {field: "" for field in RESULT_FIELDS}
    row.update({
        "encryptJobId": "job-1",
        "工作名称": "AI应用开发实习生",
        "公司": "某某科技",
        "AI匹配分数": "85",
        "投递状态": "delivered",
        "职业范围状态": "in_scope",
    })
    row.update(overrides)
    return row


class ScoreValueTests(unittest.TestCase):
    def test_score_value_parses_int_and_float(self):
        self.assertEqual(score_value("85"), 85.0)
        self.assertEqual(score_value(" 72.5 "), 72.5)

    def test_score_value_returns_none_for_empty_or_text(self):
        self.assertIsNone(score_value(""))
        self.assertIsNone(score_value("暂无"))
        self.assertIsNone(score_value(None))

    def test_row_score_prefers_ai_score_and_falls_back(self):
        self.assertEqual(row_score(make_row()), 85.0)
        self.assertEqual(
            row_score(make_row(AI匹配分数="", 匹配分数="60", 投递状态="below_threshold")),
            60.0,
        )
        self.assertIsNone(
            row_score(make_row(AI匹配分数="", 匹配分数="60", 投递状态="prefilter_reject"))
        )


class StatusDisplayTests(unittest.TestCase):
    def test_already_contacted_is_a_neutral_skip_not_a_new_delivery(self):
        label, color, _bg = status_display("already_contacted")
        self.assertEqual(label, "已沟通（跳过）")
        self.assertEqual(color, "#475467")

    def test_delivered_and_dry_run_are_green(self):
        for status in ("delivered", "dry_run"):
            label, color, bg = status_display(status)
            self.assertEqual(color, "#05603A", status)
            self.assertTrue(label)

    def test_below_threshold_is_gray(self):
        self.assertEqual(status_display("below_threshold")[1], "#475467")

    def test_scope_review_is_yellow(self):
        self.assertEqual(status_display("scope_review")[1], "#93370D")

    def test_reject_and_failed_statuses_are_red(self):
        for status in ("prefilter_reject", "match_failed", "role_reject", "local_gate_rejected"):
            self.assertEqual(status_display(status)[1], "#B42318", status)

    def test_unknown_status_falls_back_without_crash(self):
        label, color, _bg = status_display("")
        self.assertEqual(color, "#475467")
        label, color, _bg = status_display("brand_new_failed_status")
        self.assertEqual(color, "#B42318")


class SummarizeResultRowsTests(unittest.TestCase):
    def test_existing_conversation_does_not_count_as_sent_or_failed(self):
        self.assertEqual(
            summarize_result_rows([make_row(投递状态="already_contacted")]),
            {"total": 1, "delivered": 0, "dry_run": 0, "review": 0, "failed": 0},
        )

    def test_separates_deliveries_dry_runs_reviews_and_failures(self):
        rows = [
            make_row(投递状态="delivered"),
            make_row(投递状态="dry_run"),
            make_row(投递状态="dry_run_ready"),
            make_row(投递状态="scope_review"),
            make_row(投递状态="match_failed"),
            make_row(投递状态="greeting_failed"),
            make_row(投递状态="below_threshold"),
        ]

        self.assertEqual(
            summarize_result_rows(rows),
            {
                "total": 7,
                "delivered": 1,
                "dry_run": 2,
                "review": 1,
                "failed": 2,
            },
        )


class FilterResultRowsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make_row(),
            make_row(encryptJobId="job-2", 工作名称="后端开发", 公司="公司B",
                     AI匹配分数="55", 投递状态="below_threshold"),
            make_row(encryptJobId="job-3", 工作名称="算法工程师", 公司="公司C",
                     AI匹配分数="91", 投递状态="dry_run",
                     职业范围状态="scope_review"),
            make_row(encryptJobId="job-4", 工作名称="销售", 公司="公司D",
                     AI匹配分数="", 投递状态="prefilter_reject"),
        ]

    def test_status_filter(self):
        shown = filter_result_rows(self.rows, status="below_threshold")
        self.assertEqual([r["encryptJobId"] for r in shown], ["job-2"])

    def test_status_all_returns_everything(self):
        self.assertEqual(len(filter_result_rows(self.rows, status="全部")), 4)

    def test_score_range_filter(self):
        shown = filter_result_rows(self.rows, score_min=80, score_max=100)
        self.assertEqual(
            sorted(r["encryptJobId"] for r in shown), ["job-1", "job-3"]
        )

    def test_score_range_excludes_rows_without_score(self):
        shown = filter_result_rows(self.rows, score_min=1, score_max=100)
        self.assertNotIn("job-4", [r["encryptJobId"] for r in shown])

    def test_keyword_matches_name_or_company(self):
        shown = filter_result_rows(self.rows, keyword="公司b")
        self.assertEqual([r["encryptJobId"] for r in shown], ["job-2"])
        shown = filter_result_rows(self.rows, keyword="算法")
        self.assertEqual([r["encryptJobId"] for r in shown], ["job-3"])

    def test_review_only(self):
        shown = filter_result_rows(self.rows, review_only=True)
        self.assertEqual([r["encryptJobId"] for r in shown], ["job-3"])

    def test_combined_filters(self):
        shown = filter_result_rows(
            self.rows, status="全部", score_min=60, score_max=100,
            keyword="公司", review_only=True,
        )
        self.assertEqual([r["encryptJobId"] for r in shown], ["job-3"])


class DeduplicateResultRowsTests(unittest.TestCase):
    def test_keeps_latest_result_per_job_and_falls_back_from_scoring_failure(self):
        rows = [
            make_row(encryptJobId="job-1", 投递状态="match_failed", AI匹配分数=""),
            make_row(encryptJobId="job-2", 投递状态="match_failed", AI匹配分数=""),
            make_row(encryptJobId="job-1", 投递状态="below_threshold", AI匹配分数="35"),
            make_row(encryptJobId="job-2", 投递状态="dry_run", AI匹配分数="92"),
        ]

        shown = deduplicate_result_rows(rows)

        self.assertEqual(
            [(row["encryptJobId"], row["投递状态"], row["AI匹配分数"]) for row in shown],
            [("job-1", "match_failed", "35"), ("job-2", "match_failed", "92")],
        )
        self.assertTrue(all(row["历史有效评分"] == "true" for row in shown))
        self.assertIn("上次有效评分", build_result_detail_html(shown[0]))

    def test_latest_nonfailure_replaces_previous_result(self):
        rows = [
            make_row(encryptJobId="job-1", 投递状态="delivered", AI匹配分数="88"),
            make_row(encryptJobId="job-1", 投递状态="dry_run", AI匹配分数="85"),
        ]

        shown = deduplicate_result_rows(rows)

        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0]["投递状态"], "delivered")

    def test_rows_without_job_id_are_not_collapsed(self):
        rows = [make_row(encryptJobId=""), make_row(encryptJobId="")]

        self.assertEqual(len(deduplicate_result_rows(rows)), 2)

class UpdateResultMarkTests(unittest.TestCase):
    def _write_csv(self, path, rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _read_csv(self, path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows

    def test_mark_is_written_back_by_job_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "results.csv")
            self._write_csv(path, [
                make_row(encryptJobId="job-1"),
                make_row(encryptJobId="job-2", 工作名称="后端开发"),
            ])

            updated = update_result_mark(path, "job-2", "好")

            self.assertEqual(updated, 1)
            fieldnames, rows = self._read_csv(path)
            self.assertEqual(fieldnames, RESULT_FIELDS)
            self.assertEqual(rows[0]["人工标记"], "")
            self.assertEqual(rows[1]["人工标记"], "好")

    def test_unknown_job_id_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "results.csv")
            self._write_csv(path, [make_row(encryptJobId="job-1")])

            updated = update_result_mark(path, "missing", "差")

            self.assertEqual(updated, 0)
            _fieldnames, rows = self._read_csv(path)
            self.assertEqual(rows[0]["人工标记"], "")

    def test_mark_can_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "results.csv")
            self._write_csv(path, [make_row(encryptJobId="job-1", 人工标记="好")])
            update_result_mark(path, "job-1", "误杀")
            _fieldnames, rows = self._read_csv(path)
            self.assertEqual(rows[0]["人工标记"], "误杀")


class BuildResultDetailHtmlTests(unittest.TestCase):
    def test_renders_priority_fields_in_readable_blocks(self):
        html_text = build_result_detail_html(make_row(
            打招呼语="您好，我用 Python 独立开发过 AI 应用。\n方便的话可以聊聊。",
            搜索来源关键词="AI应用开发",
            岗位画像评估详情=(
                '[{"profile_id": "auto-target", "score": 72, "role_fit": 75, '
                '"reason": "项目经验匹配，Java与RPA经验未验证"}]'
            ),
            详情链接="https://example.com/job",
            工作性质="实习",
            区域="深圳 南山区 科技园",
            上班时间="09:00-18:00",
            主岗位画像="auto-target",
            职业范围状态="in_scope",
            投递时间="2026-11-09 01:01:42",
        ))

        self.assertIn("打招呼语", html_text)
        self.assertIn("您好，我用 Python 独立开发过 AI 应用。", html_text)
        self.assertIn("搜索关键词", html_text)
        self.assertIn("AI应用开发", html_text)
        self.assertIn("auto-target", html_text)
        self.assertIn("岗位匹配 72", html_text)
        self.assertIn("职能契合 75", html_text)
        self.assertIn("Java与RPA经验未验证", html_text)
        self.assertIn('href="https://example.com/job"', html_text)
        self.assertIn("工作地点：深圳 南山区 科技园", html_text)
        self.assertIn("记录时间：2026-11-09 01:01:42", html_text)
        self.assertNotIn("<table", html_text)

    def test_escapes_html_in_visible_fields(self):
        html_text = build_result_detail_html(make_row(
            打招呼语="<script>alert(1)</script>",
            岗位画像评估详情=(
                '[{"profile_id": "p1", "score": 82, "role_fit": 80, '
                '"reason": "<img src=x onerror=alert(1)>"}]'
            ),
        ))

        self.assertNotIn("<script>", html_text)
        self.assertNotIn("<img", html_text)
        self.assertIn("&lt;script&gt;", html_text)
        self.assertIn("&lt;img", html_text)

    def test_keeps_evidence_in_the_separate_expanded_section(self):
        row = make_row(
            AI匹配理由="岗位职责与项目经历相关。",
            硬性缺口="缺少Java经验",
            未验证要求="实习时长未确认",
            JD要求分层="必须熟悉Java",
            加分项命中="具备Python项目经验",
            简历证据="候选人独立开发AI应用",
            筛选原因="范围待复核",
            技能匹配诊断="技能标签仅供参考",
            本地预判="pass:未发现硬性冲突",
        )

        primary_html = build_result_detail_html(row)
        evidence_html = build_result_evidence_html(row)

        self.assertNotIn("简历证据", primary_html)
        self.assertNotIn("必须熟悉Java", primary_html)
        self.assertNotIn("岗位职责与项目经历相关", evidence_html)
        self.assertIn("缺少Java经验", evidence_html)
        self.assertIn("实习时长未确认", evidence_html)
        self.assertIn("必须熟悉Java", evidence_html)
        self.assertIn("候选人独立开发AI应用", evidence_html)
        self.assertIn("本地预判（仅供参考）", evidence_html)

    def test_only_renders_http_job_links(self):
        html_text = build_result_detail_html(make_row(详情链接="javascript:alert(1)"))

        self.assertNotIn("javascript:", html_text)
        self.assertNotIn("href=", html_text)

    def test_renders_gap_chips(self):
        html_text = build_result_evidence_html(make_row(
            硬性缺口="缺少大模型经验；未写微调"
        ))
        self.assertIn("缺少大模型经验", html_text)
        self.assertIn("未写微调", html_text)

    def test_profile_assessment_handles_invalid_json_as_text(self):
        html_text = build_result_detail_html(make_row(
            岗位画像评估详情="评估数据暂不可用"
        ))

        self.assertIn("评估数据暂不可用", html_text)


if __name__ == "__main__":
    unittest.main()
