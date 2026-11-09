import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
)

import desktop_panel
import panel_candidate_profile
from delivery_config import RESULT_FIELDS


class ResultDrawerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        with patch.object(desktop_panel.PanelApp, "_load_env"), \
                patch.object(desktop_panel.PanelApp, "refresh_results"), \
                patch.object(desktop_panel.PanelApp, "_restore_window_settings"), \
                patch.object(desktop_panel.PanelApp, "_save_window_settings"), \
                patch.object(
                    panel_candidate_profile.CandidateProfilePageMixin,
                    "_refresh_candidate_profile_view",
                ):
            return desktop_panel.PanelApp()

    def test_drawer_uses_one_scroll_area_and_renders_job_text_as_plain_text(self):
        panel = self._new_panel()
        try:
            row = {field: "" for field in RESULT_FIELDS}
            row.update({
                "encryptJobId": "job-1",
                "工作名称": "AI 应用开发实习生",
                "公司": "示例公司",
                "工资": "200-250元/天",
                "区域": "深圳 南山区",
                "AI匹配分数": "88",
                "投递状态": "dry_run",
                "人工标记": "好",
                "打招呼语": "<img src=x onerror=alert(1)>",
                "岗位画像评估详情": (
                    '[{"profile_name":"AI 应用方向","score":88,"role_fit":90,'
                    '"reason":"项目经验相关"}]'
                ),
                "简历证据": "熟悉 Python 与 RAG",
            })
            panel._fill_result_table([row])

            self.assertIsInstance(panel.result_detail, QScrollArea)
            self.assertEqual(panel.result_detail.findChildren(QTextBrowser), [])
            greeting = next(
                label for label in panel.result_detail.findChildren(QLabel)
                if label.objectName() == "resultBodyText"
                and label.text() == row["打招呼语"]
            )
            self.assertEqual(greeting.textFormat(), Qt.TextFormat.PlainText)
            self.assertTrue(greeting.wordWrap())
            self.assertTrue(panel.result_mark_buttons["好"].isChecked())

            panel.result_detail_toggle.click()
            self.assertFalse(panel.result_evidence.isHidden())
            evidence = [
                label.text() for label in panel.result_evidence.findChildren(QLabel)
            ]
            self.assertIn("熟悉 Python 与 RAG", evidence)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_manual_mark_buttons_keep_the_existing_save_action(self):
        panel = self._new_panel()
        try:
            for mark, button in panel.result_mark_buttons.items():
                with self.subTest(mark=mark), patch.object(panel, "_mark_selected") as save:
                    button.click()
                    save.assert_called_once_with(mark)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_drawer_actions_have_visible_icons(self):
        panel = self._new_panel()
        try:
            close_button = panel.result_drawer.findChild(
                QPushButton, "resultIconButton"
            )
            self.assertIsNotNone(close_button)
            buttons = [close_button, *panel.result_mark_buttons.values()]
            for button in buttons:
                with self.subTest(button=button.objectName()):
                    pixmap = button.icon().pixmap(button.iconSize())
                    self.assertFalse(pixmap.isNull())
                    image = pixmap.toImage()
                    self.assertTrue(any(
                        image.pixelColor(x, y).alpha() > 0
                        for x in range(image.width())
                        for y in range(image.height())
                    ))
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
