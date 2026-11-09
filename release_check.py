"""Offline diagnostics for the frozen GUI and its worker; never contacts a service."""

import json
import os
import sys
import tempfile
from pathlib import Path


def run_release_check(report_path, *, gui):
    report_path = Path(report_path).resolve()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "gui": gui}
    try:
        with tempfile.TemporaryDirectory(prefix="autodeliver-release-check-") as temporary:
            # Redirect before importing application modules, which resolve paths on import.
            os.environ["APPDATA"] = temporary
            os.environ["LOCALAPPDATA"] = temporary
            from app_paths import get_app_dir, get_data_dir, get_resource_dir
            from ai_chains import build_chat_model, CandidateInterviewChain, JobScoringChain, ResumeDigestChain
            from browser_runtime import resolve_browser_path
            from platform_locations import load_city_codes
            from job_profiles import load_screening_rules
            from DrissionPage import ChromiumOptions
            from DrissionPage.common import make_session_ele
            from auto_deliver import AutoDeliverer
            from result_store import ResultRecorder

            resources = get_resource_dir()
            assert load_city_codes(), "City data missing"
            assert load_screening_rules(resources / "screening_rules.md"), "Scoring rules missing"
            assert (resources / "assets" / "app.ico").is_file(), "App icon missing"
            assert (resources / "DISCLAIMER.md").is_file(), "Disclaimer missing"
            assert json.loads((resources / "author_info.json").read_text(encoding="utf-8"))["author"] == "Gnahz"
            assert ChromiumOptions(), "Browser driver settings missing"
            model = build_chat_model({
                "ai_model": "offline-check", "ai_api_key": "offline-check",
                "ai_base_url": "http://127.0.0.1:1/v1", "ai_timeout": 1, "ai_max_retries": 0,
            })
            JobScoringChain(model=model)
            CandidateInterviewChain(model=model)
            ResumeDigestChain(model=model)
            button = make_session_ele('<div class="job-detail-op"><a class="op-btn-chat">继续沟通</a></div>')
            assert AutoDeliverer._job_contact_state(button, "job") == "already_contacted"
            recorder = ResultRecorder()
            recorder.cfg = {"result_file": str(Path(temporary) / "results.csv")}
            recorder.results = []
            recorder._saved_count = 0
            recorder._record(recorder._result_row({"encryptJobId": "offline-job"}, 80, "offline", "dry_run"))
            assert recorder._load_processed_job_ids(recorder.cfg["result_file"], dry_run=True) == {"offline-job"}
            try:
                browser_path = resolve_browser_path()
                report["browser"] = browser_path.name
            except FileNotFoundError:
                browser_path = None
                report["browser"] = None
            if not gui and browser_path is not None:
                from DrissionPage import ChromiumPage
                from boss_spider import BossDP
                options = ChromiumOptions()
                options.set_browser_path(str(browser_path))
                options.set_local_port(BossDP._pick_free_port())
                options.set_user_data_path(str(Path(temporary) / "browser-profile"))
                options.headless(True)
                options.set_argument("--no-first-run")
                options.set_argument("--disable-background-networking")
                page = ChromiumPage(options)
                try:
                    page.get("data:text/html,<html><head><title>AutoDeliver offline check</title></head><body>ready</body></html>")
                    assert page.title == "AutoDeliver offline check", "Browser transport failed"
                    report["browser_launch_ok"] = True
                finally:
                    page.quit(timeout=5)
            report["resources_ok"] = True
            report["ai_chains_ok"] = True
            report["deduplication_ok"] = True
            if gui:
                from unittest.mock import patch
                from PySide6.QtCore import QSettings
                from PySide6.QtGui import QIcon
                from PySide6.QtWidgets import QApplication, QStackedWidget
                from desktop_panel import PanelApp
                from panel_styles import STYLESHEET

                app = QApplication.instance() or QApplication([])
                app.setStyle("Fusion")
                app.setStyleSheet(STYLESHEET)
                settings = QSettings(str(Path(temporary) / "panel.ini"), QSettings.IniFormat)
                with patch("desktop_panel.QSettings", return_value=settings), \
                        patch.object(PanelApp, "_refresh_platform_areas"), \
                        patch.object(PanelApp, "_refresh_platform_industries"):
                    window = PanelApp()
                    assert not QIcon(str(resources / "assets" / "app.ico")).isNull()
                    window.show()
                    app.processEvents()
                    for stack in window.findChildren(QStackedWidget):
                        for index in range(stack.count()):
                            stack.setCurrentIndex(index)
                            app.processEvents()
                    window._show_page("求职设置")
                    shot = report_path.with_suffix(".png")
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    assert window.grab().save(str(shot)), "Screenshot failed"
                    report["screenshot"] = str(shot)
                    from panel_about import AboutDialog
                    about = AboutDialog(window)
                    about.show()
                    app.processEvents()
                    assert "AI 结果与发送操作" in about.notice.toPlainText()
                    about_shot = report_path.with_name(report_path.stem + "-about.png")
                    assert about.grab().save(str(about_shot)), "About screenshot failed"
                    report["about_screenshot"] = str(about_shot)
                    report["about_ok"] = True
                    about.close()
                    window.close()
                    app.processEvents()
                    window.deleteLater()
                if report["frozen"]:
                    worker = get_app_dir() / "auto_deliver_worker.exe"
                    assert worker.is_file(), "Bundled worker missing"
                    import subprocess
                    worker_report = report_path.with_name(report_path.stem + "-worker.json")
                    child = subprocess.run(
                        [str(worker), "--self-check", str(worker_report)],
                        cwd=temporary, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                    )
                    assert child.returncode == 0, child.stdout + child.stderr
                    worker_result = json.loads(worker_report.read_text(encoding="utf-8"))
                    assert worker_result["ok"], worker_result.get("error", "Worker self-check failed")
                    report["worker_ok"] = True
                report["gui_ok"] = True
            assert get_data_dir().parent == Path(temporary), "Data directory is not isolated"
            report["ok"] = True
    except Exception:
        import traceback
        report["error"] = traceback.format_exc()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
