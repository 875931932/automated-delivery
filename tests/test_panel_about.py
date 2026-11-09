import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from app_paths import get_resource_dir
from panel_about import AboutDialog


class AboutDialogTests(unittest.TestCase):
    def test_public_contacts_and_bundled_notice_are_readable(self):
        app = QApplication.instance() or QApplication([])
        info = json.loads((get_resource_dir() / "author_info.json").read_text(encoding="utf-8"))
        dialog = AboutDialog()
        try:
            for key in ("email", "github", "gitee"):
                label = dialog.findChild(QLabel, f"author_{key}")
                self.assertIn(info[key], label.text())
                self.assertTrue(label.openExternalLinks())
            self.assertIn("AI 结果与发送操作", dialog.notice.toPlainText())
            self.assertIn("数据与第三方服务", dialog.notice.toPlainText())
            self.assertIn("责任与反馈", dialog.notice.toPlainText())
            dialog.resize(540, 440)
            dialog.show()
            app.processEvents()
            self.assertGreater(dialog.notice.height(), 100)
            self.assertGreater(dialog.notice.verticalScrollBar().maximum(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()
