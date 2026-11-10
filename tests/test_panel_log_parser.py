import unittest

from panel_log_parser import (
    CATEGORY_AI,
    CATEGORY_ERROR,
    CATEGORY_FILTER,
    CATEGORY_JOB,
    CATEGORY_NORMAL,
    CATEGORY_RESULT,
    CATEGORY_STATS,
    classify_log_line,
    parse_ai_score,
    parse_filter_stats,
    parse_job_line,
)


class ClassifyLogLineTests(unittest.TestCase):
    def test_stats_line_is_stats(self):
        self.assertEqual(
            classify_log_line("[筛选统计] 列表岗位 10 | AI评分完成 5"), CATEGORY_STATS
        )

    def test_ai_line_is_ai_even_when_it_reports_a_failure(self):
        self.assertEqual(
            classify_log_line("  [AI] 多画像评分失败: timeout"), CATEGORY_AI
        )
        self.assertEqual(
            classify_log_line("  [AI] 最高评估 85 | 画像: 后端 | 理由"), CATEGORY_AI
        )

    def test_result_line_is_result(self):
        self.assertEqual(
            classify_log_line("[结果] 已累计保存 3 条到 deliver_results.csv"),
            CATEGORY_RESULT,
        )

    def test_job_progress_lines_are_job(self):
        self.assertEqual(
            classify_log_line("[岗位 3/12 | 本轮第2个] 实习 | AI实习生 | 某公司"),
            CATEGORY_JOB,
        )
        self.assertEqual(
            classify_log_line("[优先队列 1/5 | 本轮第1个] 实习 | AI实习生 | 某公司"),
            CATEGORY_JOB,
        )

    def test_filter_and_skip_lines_are_filter(self):
        for line in (
            "  [跳过] 今日已处理: 某岗位",
            "  [硬性过滤] 某岗位: 学历不符",
            "  [本地拦截] 某岗位: 硬性冲突",
            "  [范围待复核] 某岗位：无法归类",
            "  [职能影子] 某岗位: 教学职责（仅记录不拦截）",
            "  [过滤] 某岗位: 不相关",
        ):
            self.assertEqual(classify_log_line(line), CATEGORY_FILTER, line)

    def test_error_lines_are_error(self):
        for line in (
            "Traceback (most recent call last):",
            "程序异常: connection reset",
            "[配置错误] 缺少 API key",
            "  [投递] 发送失败: element not found",
            "[平台限制] 接口返回 HTTP 429；本轮已停止。",
        ):
            self.assertEqual(classify_log_line(line), CATEGORY_ERROR, line)

    def test_plain_line_is_normal(self):
        self.assertEqual(classify_log_line("开始处理，今日已投 0/50"), CATEGORY_NORMAL)
        self.assertEqual(classify_log_line(""), CATEGORY_NORMAL)


class ParseJobLineTests(unittest.TestCase):
    def test_parses_index_total_round_and_job_fields(self):
        info = parse_job_line(
            "[岗位 3/12 | 本轮第2个] 实习 | AI应用开发实习生 | 某某科技"
        )
        self.assertEqual(info["index"], 3)
        self.assertEqual(info["total"], 12)
        self.assertEqual(info["round"], 2)
        self.assertEqual(info["type"], "实习")
        self.assertEqual(info["name"], "AI应用开发实习生")
        self.assertEqual(info["company"], "某某科技")

    def test_parses_priority_queue_line(self):
        info = parse_job_line("[优先队列 1/5 | 本轮第1个] 全职 | 后端工程师 | 公司A")
        self.assertEqual(info["index"], 1)
        self.assertEqual(info["total"], 5)
        self.assertEqual(info["name"], "后端工程师")

    def test_non_job_line_returns_none(self):
        self.assertIsNone(parse_job_line("  [AI] 最高评估 85 | 画像: X"))
        self.assertIsNone(parse_job_line(""))


class ParseAiScoreTests(unittest.TestCase):
    def test_parses_top_assessment_score(self):
        self.assertEqual(
            parse_ai_score("  [AI] 最高评估 85 | 画像: 后端 | 理由"), 85.0
        )

    def test_parses_match_score_with_decimal(self):
        self.assertEqual(parse_ai_score("  [AI] 匹配分: 72.5 | 理由"), 72.5)

    def test_unrelated_line_returns_none(self):
        self.assertIsNone(parse_ai_score("  [AI] 打招呼语: 你好"))
        self.assertIsNone(parse_ai_score("[岗位 1/2 | 本轮第1个] 实习 | A | B"))


class ParseFilterStatsTests(unittest.TestCase):
    def test_parses_stage_counts(self):
        counts = parse_filter_stats(
            "[筛选统计] 列表岗位 10 | 进入AI评分 6 | AI评分完成 5 | 投递成功 2"
        )
        self.assertEqual(
            counts,
            {"列表岗位": 10, "进入AI评分": 6, "AI评分完成": 5, "投递成功": 2},
        )

    def test_non_stats_line_returns_none(self):
        self.assertIsNone(parse_filter_stats("[结果] 已累计保存 1 条"))


if __name__ == "__main__":
    unittest.main()
