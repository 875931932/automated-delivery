import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import desktop_panel
from panel_config_logic import (
    config_warnings,
    parse_hhmm,
    validate_config_values,
)


def valid_values(**overrides):
    values = {
        "WORK_TIME_START": "09:30",
        "WORK_TIME_END": "19:00",
        "MATCH_THRESHOLD": "70",
        "DAILY_LIMIT": "50",
        "JOB_DELAY_MIN": "25",
        "JOB_DELAY_MAX": "50",
        "RESUME_FILE": "resume.md",
    }
    values.update(overrides)
    return values


class ParseHhmmTests(unittest.TestCase):
    def test_valid_times(self):
        self.assertEqual(parse_hhmm("09:30"), 9 * 60 + 30)
        self.assertEqual(parse_hhmm("9:05"), 9 * 60 + 5)
        self.assertEqual(parse_hhmm("23:59"), 23 * 60 + 59)
        self.assertEqual(parse_hhmm("00:00"), 0)

    def test_invalid_times(self):
        for value in ("9:3", "24:00", "12:60", "abc", "09-30", "09:30:00"):
            self.assertIsNone(parse_hhmm(value), value)

    def test_empty_is_none(self):
        self.assertIsNone(parse_hhmm(""))
        self.assertIsNone(parse_hhmm(None))


class ValidateConfigValuesTests(unittest.TestCase):
    def test_multiple_keywords_and_recommendation_mode_are_valid(self):
        for keyword in ("", "Python API；AI应用开发,python api"):
            with self.subTest(keyword=keyword):
                self.assertEqual(validate_config_values(valid_values(DELIVER_KEYWORD=keyword)), [])

    def test_invalid_keyword_list_is_reported_before_start(self):
        for keyword in ("，；;", ";".join(f"term-{i}" for i in range(51))):
            with self.subTest(keyword=keyword):
                errors = validate_config_values(valid_values(DELIVER_KEYWORD=keyword))
                self.assertTrue(any("搜索关键词" in error for error in errors))

    def test_valid_config_has_no_errors(self):
        self.assertEqual(validate_config_values(valid_values(), resume_exists=True), [])

    def test_invalid_time_format_is_reported(self):
        errors = validate_config_values(
            valid_values(WORK_TIME_START="9点30"), resume_exists=True
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("最早可接受上班时间", errors[0])

    def test_start_must_be_before_end(self):
        errors = validate_config_values(
            valid_values(WORK_TIME_START="19:00", WORK_TIME_END="09:30"),
            resume_exists=True,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("早于", errors[0])

    def test_empty_time_is_allowed(self):
        errors = validate_config_values(
            valid_values(WORK_TIME_START="", WORK_TIME_END=""), resume_exists=True
        )
        self.assertEqual(errors, [])

    def test_int_out_of_range_is_reported(self):
        errors = validate_config_values(
            valid_values(MATCH_THRESHOLD="120"), resume_exists=True
        )
        self.assertTrue(any("MATCH_THRESHOLD" in error for error in errors))

    def test_zero_human_interval_is_valid_and_disables_interleaved_browsing(self):
        self.assertEqual(
            validate_config_values(valid_values(HUMAN_EVERY_N="0"), resume_exists=True),
            [],
        )

    def test_non_integer_value_is_reported(self):
        errors = validate_config_values(valid_values(DAILY_LIMIT="abc"), resume_exists=True)
        self.assertTrue(any("DAILY_LIMIT" in error for error in errors))

    def test_delay_range_inversion_is_reported(self):
        errors = validate_config_values(
            valid_values(JOB_DELAY_MIN="60", JOB_DELAY_MAX="30"), resume_exists=True
        )
        self.assertTrue(any("岗位间隔" in error for error in errors))

    def test_missing_resume_file_is_reported(self):
        errors = validate_config_values(valid_values(), resume_exists=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("简历文件", errors[0])

    def test_empty_resume_path_is_reported(self):
        errors = validate_config_values(valid_values(RESUME_FILE=""), resume_exists=False)
        self.assertEqual(len(errors), 1)

    def test_multiple_errors_are_all_reported(self):
        errors = validate_config_values(
            valid_values(WORK_TIME_START="bad", MATCH_THRESHOLD="999"),
            resume_exists=False,
        )
        self.assertGreaterEqual(len(errors), 3)


class ConfigWarningsTests(unittest.TestCase):
    def test_keep_login_off_warns_about_lost_session(self):
        messages = config_warnings({"KEEP_LOGIN": "false"})
        self.assertEqual(len(messages), 1)
        self.assertIn("登录态", messages[0])

    def test_keep_login_on_has_no_warning(self):
        self.assertEqual(config_warnings({"KEEP_LOGIN": "true"}), [])

    def test_dry_run_notice(self):
        messages = config_warnings({"DRY_RUN": "true"})
        self.assertTrue(any("干跑" in message for message in messages))


class PanelSettingTransmissionTests(unittest.TestCase):
    def test_every_config_field_is_in_exactly_one_settings_section(self):
        source_path = Path(__file__).parents[1] / "desktop_panel.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        assignments = {}
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "FIELDS":
                    assignments[target.id] = desktop_panel.FIELDS
                elif target.id in {"SETTINGS_SECTIONS", "ADVANCED_SECTIONS"}:
                    assignments[target.id] = ast.literal_eval(node.value)
        field_keys = {field[0] for field in assignments["FIELDS"]}
        section_keys = [key for _, keys in (
            assignments["SETTINGS_SECTIONS"] + assignments["ADVANCED_SECTIONS"]
        ) for key in keys]

        self.assertEqual(set(section_keys), field_keys)
        self.assertEqual(len(section_keys), len(set(section_keys)))

        settings = dict(assignments["SETTINGS_SECTIONS"])
        advanced = dict(assignments["ADVANCED_SECTIONS"])
        self.assertEqual(
            [title for title, _keys in assignments["SETTINGS_SECTIONS"]],
            [
                "模型接口（必填）",
                "简历与搜索",
                "本轮任务",
                "在哪儿找工作",
                "作息与福利",
                "打招呼语",
                "可选画像搜索",
            ],
        )
        self.assertIn("TEST_LIMIT", settings["本轮任务"])
        self.assertEqual(
            settings["本轮任务"],
            ["DRY_RUN", "TEST_LIMIT", "MATCH_THRESHOLD", "DAILY_LIMIT"],
        )
        self.assertEqual(
            settings["在哪儿找工作"][:3],
            ["CITY_CODE", "PLATFORM_AREA_FILTER", "AREA_FILTER"],
        )
        self.assertIn("AREA_FILTER", settings["在哪儿找工作"])
        self.assertIn("DELIVER_MAX_PAGES", advanced["采集细节"])
        self.assertNotIn("AREA_FILTER", advanced["采集细节"])
        self.assertIn("GREETING_PROMPT", settings["打招呼语"])
        self.assertEqual(settings["可选画像搜索"], ["TAVILY_ENABLED", "TAVILY_API_KEY"])


class SettingsFeedbackTests(unittest.TestCase):
    def test_save_config_shows_temporary_non_modal_confirmation(self):
        messages = []
        app = SimpleNamespace(
            _collect_values=lambda: {"CITY_CODE": "101280600"},
            append_log=lambda _message: None,
            config_notice=Mock(),
            runner=SimpleNamespace(running=lambda: False),
            statusBar=lambda: SimpleNamespace(
                showMessage=lambda *args: messages.append(args)
            ),
        )
        app._persist_config = lambda values: desktop_panel.PanelApp._persist_config(app, values)

        with patch.object(desktop_panel, "write_env_file") as write_env, patch.object(
            desktop_panel.QMessageBox, "information"
        ) as show_modal:
            desktop_panel.PanelApp.save_config(app)

        write_env.assert_called_once_with({"CITY_CODE": "101280600"})
        self.assertEqual(messages, [("配置已保存", 2500)])
        app.config_notice.show_message.assert_called_once_with("配置已保存")
        show_modal.assert_not_called()

    def test_failed_write_shows_error_and_never_confirms_success(self):
        notice = Mock()
        app = SimpleNamespace(
            _collect_values=lambda: {"CITY_CODE": "101280600"},
            append_log=Mock(),
            config_notice=notice,
            statusBar=Mock(),
        )
        app._persist_config = lambda values: desktop_panel.PanelApp._persist_config(app, values)

        with patch.object(desktop_panel, "write_env_file", side_effect=PermissionError("read only")):
            desktop_panel.PanelApp.save_config(app)

        notice.show_message.assert_called_once()
        self.assertIn("配置保存失败", notice.show_message.call_args.args[0])
        self.assertEqual(notice.show_message.call_args.kwargs, {"kind": "error"})
        app.statusBar.assert_not_called()

    def test_invalid_values_clear_previous_confirmation_without_writing(self):
        app = SimpleNamespace(_collect_values=lambda: None, config_notice=Mock())
        with patch.object(desktop_panel, "write_env_file") as write_env:
            desktop_panel.PanelApp.save_config(app)
        write_env.assert_not_called()
        app.config_notice.dismiss.assert_called_once()
        app.config_notice.show_message.assert_not_called()

    def test_running_task_save_describes_when_new_settings_take_effect(self):
        app = SimpleNamespace(
            _collect_values=lambda: {"CITY_CODE": "101280600"},
            _persist_config=lambda _values: True,
            config_notice=Mock(),
            append_log=Mock(),
            statusBar=Mock(),
            runner=SimpleNamespace(running=lambda: True),
        )
        desktop_panel.PanelApp.save_config(app)
        app.config_notice.show_message.assert_called_once_with("配置已保存，下次启动任务时生效")


if __name__ == "__main__":
    unittest.main()
