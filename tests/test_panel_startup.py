import os
import unittest
from collections import Counter
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

import desktop_panel
from panel_widgets import EmptyState, FieldBlock, SectionCard, ToggleRow


class WindowShowProbe(QObject):
    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(obj.objectName() or type(obj).__name__)
        return False


class PanelStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.probe = WindowShowProbe()
        self.app.installEventFilter(self.probe)

    def tearDown(self):
        self.app.removeEventFilter(self.probe)

    def test_field_and_section_construction_never_shows_detached_labels(self):
        widgets = [
            FieldBlock('Title', QLineEdit(), 'Note'),
            ToggleRow('Toggle', 'Note'),
            SectionCard('Section', 'Subtitle'),
            EmptyState('Empty', 'Hint'),
        ]
        try:
            self.assertEqual(Counter(self.probe.windows), {})
        finally:
            for widget in widgets:
                widget.close()
                widget.deleteLater()

    def test_complete_panel_has_only_its_main_window_show_event(self):
        with patch.object(desktop_panel.PanelApp, '_load_env'), \
                patch.object(desktop_panel.PanelApp, 'refresh_results'), \
                patch.object(desktop_panel.PanelApp, '_restore_window_settings'), \
                patch.object(desktop_panel.PanelApp, '_save_window_settings'):
            panel = desktop_panel.PanelApp()
            try:
                self.assertEqual(Counter(self.probe.windows), {})
                panel.show()
                self.app.processEvents()
                self.assertEqual(self.probe.windows, ['PanelApp'])
            finally:
                panel.close()
                panel.deleteLater()


if __name__ == '__main__':
    unittest.main()
