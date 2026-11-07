import ast
import unittest
from pathlib import Path

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
    def test_valid_config_has_no_errors(self):
        self.assertEqual(validate_config_values(valid_values(), resume_exists=True), [])

    def test_invalid_time_format_is_reported(self):
        errors = validate_config_values(
            valid_values(WORK_TIME_START="9点30"), resume_exists=True
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("最早上班时间", errors[0])

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
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
            and target.id in {"FIELDS", "SETTINGS_SECTIONS", "ADVANCED_SECTIONS"}
        }
        field_keys = {field[0] for field in assignments["FIELDS"]}
        section_keys = [key for _, keys in (
            assignments["SETTINGS_SECTIONS"] + assignments["ADVANCED_SECTIONS"]
        ) for key in keys]

        self.assertEqual(set(section_keys), field_keys)
        self.assertEqual(len(section_keys), len(set(section_keys)))


if __name__ == "__main__":
    unittest.main()
