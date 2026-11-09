import tempfile
import unittest
from pathlib import Path

from browser_runtime import resolve_browser_path


class BrowserPathResolutionTests(unittest.TestCase):
    def test_explicit_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            explicit = root / "custom" / "browser.exe"
            bundled = root / "app" / "browser" / "chrome.exe"
            explicit.parent.mkdir()
            bundled.parent.mkdir(parents=True)
            explicit.touch()
            bundled.touch()

            resolved = resolve_browser_path(
                str(explicit),
                app_dir=root / "app",
                resource_dir=root / "resources",
                environ={},
                which=lambda _name: None,
            )

            self.assertEqual(resolved, explicit.resolve())

    def test_bundled_browser_is_used_before_installed_browsers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundled = root / "app" / "browser" / "chrome.exe"
            bundled.parent.mkdir(parents=True)
            bundled.touch()

            resolved = resolve_browser_path(
                app_dir=root / "app",
                resource_dir=root / "resources",
                environ={"PROGRAMFILES": str(root / "program-files")},
                which=lambda _name: None,
            )

            self.assertEqual(resolved, bundled.resolve())

    def test_edge_is_discovered_when_chrome_is_not_installed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            edge = (
                root / "Program Files" / "Microsoft" / "Edge"
                / "Application" / "msedge.exe"
            )
            edge.parent.mkdir(parents=True)
            edge.touch()

            resolved = resolve_browser_path(
                app_dir=root / "app",
                resource_dir=root / "resources",
                environ={"PROGRAMFILES": str(root / "Program Files")},
                which=lambda _name: None,
            )

            self.assertEqual(resolved, edge.resolve())

    def test_missing_browser_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(FileNotFoundError, "Chrome 或 Edge"):
                resolve_browser_path(
                    app_dir=root / "app",
                    resource_dir=root / "resources",
                    environ={},
                    which=lambda _name: None,
                )


if __name__ == "__main__":
    unittest.main()
