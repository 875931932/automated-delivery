import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import panel_runner


class TaskRunnerEnvironmentTests(unittest.TestCase):
    def test_saved_env_overrides_parent_values_but_keeps_injected_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / ".env").write_text(
                'AI_TIMEOUT=45\nAI_API_KEY="panel-key"\n', encoding="utf-8"
            )
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, "BASE_DIR", base_dir), \
                    patch.dict(os.environ, {
                        "AI_TIMEOUT": "999",
                        "AI_API_KEY": "stale-parent-key",
                        "INJECTED_SECRET": "preserved",
                    }), \
                    patch.object(panel_runner.subprocess, "Popen", return_value=process) as popen, \
                    patch.object(panel_runner.threading, "Thread"):
                runner = panel_runner.TaskRunner()
                self.assertEqual(runner.start(), "已启动")

        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["AI_TIMEOUT"], "45")
        self.assertEqual(child_env["AI_API_KEY"], "panel-key")
        self.assertEqual(child_env["INJECTED_SECRET"], "preserved")


if __name__ == "__main__":
    unittest.main()
