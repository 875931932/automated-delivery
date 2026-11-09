import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths


class AppPathResolutionTests(unittest.TestCase):
    def test_source_mode_stores_data_in_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "Roaming"
            with patch.object(app_paths.sys, "frozen", False, create=True), \
                    patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=True):
                self.assertEqual(app_paths.get_data_dir(), appdata / "AutoDeliver")

    def test_source_mode_falls_back_to_local_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = Path(temp_dir) / "Local"
            with patch.object(app_paths.sys, "frozen", False, create=True), \
                    patch.dict(
                        os.environ, {"LOCALAPPDATA": str(local_appdata)}, clear=True
                    ):
                self.assertEqual(
                    app_paths.get_data_dir(), local_appdata / "AutoDeliver"
                )

    def test_frozen_mode_stores_data_in_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "Roaming"
            with patch.object(app_paths.sys, "frozen", True, create=True), \
                    patch.object(app_paths.sys, "executable", str(Path(temp_dir) / "app.exe")), \
                    patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=True):
                self.assertEqual(app_paths.get_data_dir(), appdata / "AutoDeliver")

    def test_frozen_resources_use_pyinstaller_bundle_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app_paths.sys, "frozen", True, create=True), \
                    patch.object(app_paths.sys, "_MEIPASS", temp_dir, create=True):
                self.assertEqual(
                    app_paths.get_resource_dir(),
                    Path(temp_dir).resolve(),
                )


if __name__ == "__main__":
    unittest.main()
