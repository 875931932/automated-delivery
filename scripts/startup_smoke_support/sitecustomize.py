"""Loaded only by verify_quiet_startup.py's isolated pythonw process."""

import json
import os
import subprocess
import time
from pathlib import Path


if os.environ.get("AUTODELIVER_STARTUP_SMOKE") == "1":
    started = time.perf_counter()
    import desktop_panel
    from PySide6.QtCore import QEvent, QObject, QSettings, QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    settings_path = str(Path(os.environ["APPDATA"]) / "smoke-settings.ini")
    desktop_panel.QSettings = lambda *_args: QSettings(settings_path, QSettings.IniFormat)
    desktop_panel.PanelApp._refresh_platform_areas = lambda _self: None
    original_init = desktop_panel.PanelApp.__init__

    class WindowShowProbe(QObject):
        def __init__(self):
            super().__init__()
            self.unexpected_windows = 0

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                self.unexpected_windows += 1
            return False

    def init_panel(window):
        probe = WindowShowProbe()
        app = QApplication.instance()
        app.installEventFilter(probe)
        try:
            original_init(window)
        finally:
            app.removeEventFilter(probe)

        def ready():
            print("STARTUP_SMOKE " + json.dumps({
                "ready_seconds": round(time.perf_counter() - started, 2),
                "pid": os.getpid(),
                "background_default": window.vars["BROWSER_BACKGROUND"][0].isChecked(),
                "unexpected_top_level_windows": probe.unexpected_windows,
            }), flush=True)
            # Exercise the dependency probe from pythonw as well as the panel.
            subprocess.check_output("ver", shell=True)
            QTimer.singleShot(1500, window.close)

        QTimer.singleShot(100, ready)

    desktop_panel.PanelApp.__init__ = init_panel
