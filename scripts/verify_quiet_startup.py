"""Opt-in Windows VBS/pythonw startup smoke test with isolated panel data."""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def visible_windows():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    result = {}

    @callback_type
    def collect(hwnd, _data):
        if user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, len(name))
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            result[hwnd] = (owner.value, name.value)
        return True

    user32.EnumWindows(collect, 0)
    return result


def main():
    if os.name != "nt":
        raise SystemExit("This smoke test requires Windows")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    before = visible_windows()
    console_windows = set()
    observed_windows = {}
    child = None
    marker = None
    with tempfile.TemporaryDirectory(prefix="autodeliver-startup-smoke-") as data_dir:
        env = os.environ.copy()
        env.pop("QT_QPA_PLATFORM", None)
        env.update({
            "APPDATA": data_dir,
            "AUTODELIVER_PYTHONW": str(pythonw),
            "AUTODELIVER_STARTUP_SMOKE": "1",
            "PYTHONPATH": os.pathsep.join([str(ROOT / "scripts" / "startup_smoke_support"), str(ROOT)]),
        })
        launcher = subprocess.Popen(
            ["wscript.exe", str(ROOT / "\u542f\u52a8\u9762\u677f.vbs")],
            cwd=str(ROOT), env=env, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 30
            log_path = Path(data_dir) / "AutoDeliver" / "panel-startup.log"
            while time.monotonic() < deadline:
                current = visible_windows()
                observed_windows.update(current)
                console_windows.update(
                    hwnd for hwnd, (_pid, name) in current.items()
                    if hwnd not in before and name in {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}
                )
                if marker is None and log_path.exists():
                    for line in log_path.read_text(encoding="utf-8").splitlines():
                        if line.startswith("STARTUP_SMOKE "):
                            marker = json.loads(line.split(" ", 1)[1])
                            child = psutil.Process(marker["pid"])
                if child is not None and not child.is_running():
                    break
                time.sleep(0.01)
            assert marker is not None, "Panel did not reach ready state"
            assert not child.is_running(), "Test panel did not close automatically"
            assert marker["background_default"], "Background browser setting is not enabled"
            assert marker["unexpected_top_level_windows"] == 0, marker
            assert any(pid == child.pid and name.startswith("Qt")
                       for pid, name in observed_windows.values()), "Panel window was not shown"
            assert not console_windows, "A new visible console appeared during startup"
            print(json.dumps({**marker, "visible_console_windows": 0, "panel_window_observed": True}))
        finally:
            if child is not None and child.is_running():
                child.terminate()
                child.wait(timeout=5)
            launcher.wait(timeout=5)


if __name__ == "__main__":
    main()
