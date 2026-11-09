# -*- coding: utf-8 -*-
"""Resolve application, bundled-resource, and writable user-data directories."""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_dir() -> Path:
    """Directory containing the installed executables, or the source tree."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    """Directory where bundled read-only files are stored."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if is_frozen() and bundle_dir:
        return Path(bundle_dir).resolve()
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    """Keep mutable app data outside the source tree and install directory."""
    root = (
        os.environ.get("APPDATA")
        or os.environ.get("LOCALAPPDATA")
        or str(Path.home())
    )
    return Path(root) / "AutoDeliver"
