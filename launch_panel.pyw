"""Console-free entry point; startup errors remain available in the data folder."""

from process_runtime import configure_quiet_processes

configure_quiet_processes()

import ctypes
import os
import sys
import traceback

from app_paths import get_data_dir


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from release_check import run_release_check
        return run_release_check(sys.argv[2], gui=True)
    log_path = get_data_dir() / "panel-startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            from desktop_panel import main as start_panel
            start_panel()
        except Exception:
            traceback.print_exc()
            if os.name == "nt":
                ctypes.windll.user32.MessageBoxW(
                    0, f"Startup failed. Details: {log_path}", "AutoDeliver", 0x10,
                )
            return 1
        finally:
            sys.stdout = sys.stderr = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
