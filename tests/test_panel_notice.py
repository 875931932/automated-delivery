import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from panel_widgets import ToastNotice


class ToastNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.host.resize(800, 600)
        self.input = QLineEdit(self.host)
        self.notice = ToastNotice(self.host)
        self.host.show()
        self.host.activateWindow()
        self.input.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()

    def test_notice_stays_inside_host_without_changing_focus(self):
        focused = self.app.focusWidget()
        self.notice.show_message("Saved")
        self.app.processEvents()
        self.assertTrue(self.notice.isVisible())
        self.assertFalse(self.notice.isWindow())
        self.assertIs(self.app.focusWidget(), focused)
        self.assertTrue(self.host.rect().contains(self.notice.geometry()))
        self.host.resize(360, 400)
        self.app.processEvents()
        self.assertTrue(self.host.rect().contains(self.notice.geometry()))

    def test_new_message_replaces_and_restarts_timeout(self):
        self.notice.show_message("Saved", duration=30)
        self.notice.show_message("Could not save", kind="error", duration=1000)
        QTest.qWait(70)
        self.assertTrue(self.notice.isVisible())
        self.assertEqual(self.notice.message_label.text(), "Could not save")
        self.assertEqual(self.notice.property("kind"), "error")
        self.assertEqual(len(self.host.findChildren(ToastNotice)), 1)
        self.notice.show_message("Saved", duration=10)
        QTest.qWait(60)
        self.assertFalse(self.notice.isVisible())

    def test_close_cancels_timeout(self):
        self.notice.show_message("Saved")
        self.notice.close_button.click()
        self.assertFalse(self.notice.isVisible())
        self.assertFalse(self.notice.timer.isActive())


if __name__ == "__main__":
    unittest.main()
