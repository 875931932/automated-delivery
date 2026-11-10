import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import panel_runner


class TaskRunnerEnvironmentTests(unittest.TestCase):
    def setUp(self):
        browser_guard = patch.object(panel_runner, "ensure_task_profiles_available")
        browser_guard.start()
        self.addCleanup(browser_guard.stop)

    def test_open_project_browser_blocks_worker_start_without_killing_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(panel_runner, "BASE_DIR", Path(temp_dir)), \
                    patch.object(panel_runner, "ensure_task_profiles_available",
                                 side_effect=ValueError("请先关闭项目浏览器窗口")), \
                    patch.object(panel_runner.subprocess, "Popen") as popen, \
                    patch.object(panel_runner.subprocess, "run") as run:
                message = panel_runner.TaskRunner().start()
            self.assertIn("请先关闭", message)
            popen.assert_not_called()
            run.assert_not_called()

    def test_source_start_uses_source_script_and_user_data_as_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            data_dir = root / "data"
            app_dir.mkdir()
            data_dir.mkdir()
            script = app_dir / "auto_deliver.py"
            script.touch()
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, "APP_DIR", app_dir), \
                    patch.object(panel_runner, "BASE_DIR", data_dir), \
                    patch.object(panel_runner, "is_frozen", return_value=False), \
                    patch.object(
                        panel_runner.subprocess, "Popen", return_value=process
                    ) as popen, \
                    patch.object(panel_runner.threading, "Thread"):
                runner = panel_runner.TaskRunner()
                self.assertEqual(runner.start(), "已启动")

        self.assertEqual(
            popen.call_args.args[0], [sys.executable, str(script)]
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], str(data_dir))

    def test_saved_env_overrides_parent_values_but_keeps_injected_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            prompt = "按岗位 ${岗位名} 定制招呼语。\n保留引号：'测试'，路径 C:\\work"
            escaped_prompt = prompt.replace("\\", "\\\\").replace("'", "\\'")
            (base_dir / ".env").write_text(
                'AI_TIMEOUT=45\nAI_API_KEY="panel-key"\n'
                'DELIVER_KEYWORD=\n'
                f"GREETING_PROMPT='{escaped_prompt}'\n",
                encoding="utf-8",
            )
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, "BASE_DIR", base_dir), \
                    patch.dict(os.environ, {
                        "AI_TIMEOUT": "999",
                        "AI_API_KEY": "stale-parent-key",
                        "DELIVER_KEYWORD": "stale-parent-keyword",
                        "INJECTED_SECRET": "preserved",
                    }), \
                    patch.object(panel_runner.subprocess, "Popen", return_value=process) as popen, \
                    patch.object(panel_runner.threading, "Thread"):
                runner = panel_runner.TaskRunner()
                self.assertEqual(runner.start(), "已启动")

        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["AI_TIMEOUT"], "45")
        self.assertEqual(child_env["AI_API_KEY"], "panel-key")
        self.assertEqual(child_env["DELIVER_KEYWORD"], "")
        self.assertEqual(child_env["GREETING_PROMPT"], prompt)
        self.assertEqual(child_env["INJECTED_SECRET"], "preserved")

    def test_start_resets_manual_stop_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, "BASE_DIR", Path(temp_dir)), \
                    patch.object(panel_runner.subprocess, "Popen", return_value=process), \
                    patch.object(panel_runner.threading, "Thread"):
                runner = panel_runner.TaskRunner()
                runner.stop_requested = True
                runner.start()

        self.assertFalse(runner.stop_requested)

    def test_frozen_start_uses_sibling_worker_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "install"
            data_dir = Path(temp_dir) / "data"
            app_dir.mkdir()
            data_dir.mkdir()
            worker = app_dir / "auto_deliver_worker.exe"
            worker.touch()
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, "BASE_DIR", data_dir), \
                    patch.object(panel_runner, "APP_DIR", app_dir), \
                    patch.object(panel_runner, "is_frozen", return_value=True), \
                    patch.object(panel_runner.subprocess, "Popen", return_value=process) as popen, \
                    patch.object(panel_runner.threading, "Thread"):
                runner = panel_runner.TaskRunner()
                self.assertEqual(runner.start(), "已启动")

        self.assertEqual(popen.call_args.args[0], [str(worker)])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(data_dir))

    def test_frozen_start_reports_missing_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(panel_runner, "BASE_DIR", root / "data"), \
                    patch.object(panel_runner, "APP_DIR", root / "install"), \
                    patch.object(panel_runner, "is_frozen", return_value=True), \
                    patch.object(panel_runner.subprocess, "Popen") as popen:
                runner = panel_runner.TaskRunner()
                message = runner.start()

        self.assertIn("缺少任务运行文件", message)
        popen.assert_not_called()

    def test_stop_records_manual_stop_state(self):
        process = SimpleNamespace(poll=lambda: None, pid=123)
        runner = panel_runner.TaskRunner()
        runner.proc = process

        with patch.object(panel_runner.subprocess, "run") as kill_process:
            self.assertEqual(runner.stop(), "已停止")

        self.assertTrue(runner.stop_requested)
        kill_process.assert_called_once()

    def test_pump_logs_readable_exit_status_with_exit_code(self):
        process = SimpleNamespace(stdout=["task output\n"], wait=lambda: 2)
        runner = panel_runner.TaskRunner()
        runner.proc = process

        runner._pump()

        self.assertEqual(runner.exit_code, 2)
        self.assertEqual(runner.log_queue.get_nowait(), "task output")
        exit_message = runner.log_queue.get_nowait()
        self.assertIn("运行失败", exit_message)
        self.assertIn("退出码 2", exit_message)

    def test_exit_status_distinguishes_idle_normal_error_and_manual_stop(self):
        self.assertEqual(panel_runner.format_exit_status(None), "空闲")
        self.assertIn("正常结束", panel_runner.format_exit_status(0))
        self.assertIn("运行失败", panel_runner.format_exit_status(2))
        self.assertIn("平台限制", panel_runner.format_exit_status(3))
        self.assertIn("被中断", panel_runner.format_exit_status(130))
        self.assertIn("手动停止", panel_runner.format_exit_status(1, True))


if __name__ == "__main__":
    unittest.main()
