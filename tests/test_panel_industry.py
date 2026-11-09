import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit

import desktop_panel


INDUSTRIES = [
    {
        "code": "100000",
        "name": "互联网/IT",
        "children": [
            {"code": "100020", "name": "互联网"},
            {"code": "100021", "name": "人工智能"},
            {"code": "100022", "name": "电子商务"},
            {"code": "100023", "name": "数据服务"},
        ],
    },
    {
        "code": "200000",
        "name": "教育",
        "children": [{"code": "200010", "name": "职业教育"}],
    },
]


class PanelIndustryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings_path = str(Path(self.temp.name) / "panel.ini")
        self.patches = [
            patch.object(
                desktop_panel, "QSettings",
                side_effect=lambda *_args: QSettings(
                    settings_path, QSettings.IniFormat
                ),
            ),
            patch.object(desktop_panel.PanelApp, "_load_env"),
            patch.object(desktop_panel.PanelApp, "refresh_results"),
            patch.object(desktop_panel.PanelApp, "_restore_window_settings"),
        ]
        for setting in self.patches:
            setting.start()
            self.addCleanup(setting.stop)
        self.panel = desktop_panel.PanelApp()
        self.addCleanup(self._close_panel)
        self.input = self.panel.vars["PLATFORM_INDUSTRY"][0]

    def _close_panel(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _loaded(self):
        self.panel.industry_generation = 1
        self.panel._apply_platform_industries(1, INDUSTRIES, "")

    def _choose_category(self, name):
        selector = self.panel.platform_industry_category
        index = selector.findText(name)
        self.assertGreaterEqual(index, 0)
        selector.setCurrentIndex(index)
        self.app.processEvents()

    def _checkbox(self, name):
        matches = [
            check
            for check in self.panel.platform_industry_choices.values()
            if check.text() == name
        ]
        self.assertEqual(len(matches), 1, name)
        return matches[0]

    def test_picker_stays_lazy_and_keeps_existing_text_field(self):
        self.assertIsInstance(self.input, QLineEdit)
        self.assertTrue(self.panel.platform_industry_refresh.isEnabled())
        self.assertFalse(self.panel.platform_industry_category.isEnabled())

    def test_picker_loads_categories_and_selection_survives_switching(self):
        self.input.setText("100020")
        self._loaded()

        self.assertIn("已加载", self.panel.platform_industry_status.text())
        self._choose_category("互联网/IT")
        self.assertTrue(self._checkbox("互联网").isChecked())
        self._checkbox("人工智能").setChecked(True)
        self.assertEqual(self.input.text(), "100020,100021")
        self._choose_category("教育")
        self._checkbox("职业教育").setChecked(True)
        self.assertEqual(self.panel._read_widget_values()["PLATFORM_INDUSTRY"],
                         "100020,100021,200010")
        self._choose_category("互联网/IT")
        self.assertTrue(self._checkbox("人工智能").isChecked())

    def test_picker_rejects_fourth_selection_without_changing_saved_value(self):
        self._loaded()
        self._choose_category("互联网/IT")
        for name in ("互联网", "人工智能", "电子商务"):
            self._checkbox(name).setChecked(True)
        original = self.input.text()

        fourth = self._checkbox("数据服务")
        fourth.setChecked(True)

        self.assertFalse(fourth.isChecked())
        self.assertEqual(self.input.text(), original)
        self.assertIn("3", self.panel.platform_industry_status.text())

    def test_failed_refresh_preserves_manual_ids_and_enables_retry(self):
        self.input.setText("100020,100021")
        self.panel.industry_generation = 1
        self.panel._apply_platform_industries(1, [], "您的IP地址存在异常行为")

        self.assertEqual(self.input.text(), "100020,100021")
        self.assertTrue(self.panel.platform_industry_refresh.isEnabled())
        self.assertIn("失败", self.panel.platform_industry_status.text())
        self.assertFalse(self.panel.platform_industry_category.isEnabled())

    def test_refresh_fetches_in_background_and_polls_result(self):
        with patch.object(
            desktop_panel, "fetch_platform_industries", return_value=INDUSTRIES
        ) as fetch:
            self.panel._refresh_platform_industries()
            self.assertFalse(self.panel.platform_industry_refresh.isEnabled())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.panel._poll()
                if self.panel.platform_industry_refresh.isEnabled():
                    break
                time.sleep(0.01)

        fetch.assert_called_once()
        self.assertTrue(self.panel.platform_industry_category.isEnabled())
        self.assertTrue(self.panel.platform_industry_refresh.isEnabled())


if __name__ == "__main__":
    unittest.main()
