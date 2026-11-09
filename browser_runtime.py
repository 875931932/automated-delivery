# -*- coding: utf-8 -*-
"""Browser executable discovery for Chrome, Edge, and bundled Chromium."""

import os
import shutil
from pathlib import Path

from app_paths import get_app_dir, get_resource_dir


def resolve_browser_path(
    configured_path=None,
    *,
    app_dir=None,
    resource_dir=None,
    environ=None,
    exists=None,
    which=None,
) -> Path:
    """Find a Chromium executable, preferring explicit and bundled paths."""
    app_dir = Path(app_dir or get_app_dir())
    resource_dir = Path(resource_dir or get_resource_dir())
    environ = os.environ if environ is None else environ
    exists = Path.is_file if exists is None else exists
    which = shutil.which if which is None else which

    configured_path = str(
        configured_path or environ.get("BROWSER_PATH", "")
    ).strip()
    candidates = []
    if configured_path:
        configured = Path(os.path.expandvars(configured_path)).expanduser()
        if not configured.is_absolute():
            configured = app_dir / configured
        candidates.append(configured)

    executable_names = ("chrome.exe", "msedge.exe", "chromium.exe")
    for root in (app_dir, resource_dir):
        for folder in ("browser", "chromium", "chrome", "edge"):
            for executable in executable_names:
                candidates.append(root / folder / executable)

    program_roots = [
        environ.get("PROGRAMFILES"),
        environ.get("PROGRAMFILES(X86)"),
        environ.get("LOCALAPPDATA"),
    ]
    for root in filter(None, program_roots):
        root = Path(root)
        candidates.extend([
            root / "Google" / "Chrome" / "Application" / "chrome.exe",
            root / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ])

    for executable in executable_names:
        located = which(executable)
        if located:
            candidates.append(Path(located))

    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if exists(candidate):
            return candidate

    raise FileNotFoundError(
        "没有找到可用的 Chromium 浏览器。请安装 Chrome 或 Edge，"
        "或在高级设置中填写 BROWSER_PATH。"
    )
