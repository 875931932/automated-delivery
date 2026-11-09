"""Windows process defaults shared by the GUI and delivery worker."""

import os
import subprocess
import sys
from pathlib import Path


def quiet_process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def configure_quiet_processes():
    """Prevent dependency probes (including platform's `ver`) opening consoles."""
    if os.name != "nt" or getattr(subprocess.Popen, "_autodeliver_quiet", False):
        return

    original = subprocess.Popen

    class QuietPopen(original):
        _autodeliver_quiet = True

        def __init__(self, *args, **kwargs):
            flags = kwargs.get("creationflags", 0)
            if not flags & subprocess.CREATE_NEW_CONSOLE:
                kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = QuietPopen


def worker_python():
    """A hidden console interpreter preserves stdout when the GUI uses pythonw."""
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console_python = executable.with_name("python.exe")
        if console_python.is_file():
            return str(console_python)
    return str(executable)
