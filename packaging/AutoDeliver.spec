# -*- mode: python ; coding: utf-8 -*-
"""Two executables sharing one dependency directory; private files are never data inputs."""

from pathlib import Path
from importlib.metadata import distributions
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
assets = [(str(path), "assets") for path in (root / "assets").iterdir() if path.is_file()]
data = assets + [(str(root / name), ".") for name in (
    "city_codes.json", "screening_rules.md", "author_info.json", "DISCLAIMER.md",
    "README.md", "THIRD_PARTY_NOTICES.md",
)]
data += collect_data_files("DrissionPage")
for package in ("langchain_core", "langchain_openai", "langsmith", "openai", "tiktoken"):
    data += copy_metadata(package)
for package in distributions():
    for item in package.files or []:
        if "license" in item.name.lower() or "copying" in item.name.lower():
            source = Path(package.locate_file(item))
            if source.is_file() and ".dist-info" in str(item):
                data.append((str(source), str(Path("licenses") / package.metadata["Name"] / Path(item).parent.name)))
data += [(str(path), "licenses") for path in (root / "packaging" / "licenses").iterdir() if path.is_file()]
hidden = collect_submodules("tiktoken_ext") + ["PySide6.QtSvg", "PySide6.QtSvgWidgets"]
excluded = ["tkinter", "pytest", "IPython", "matplotlib", "pandas", "scipy", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"]

gui = Analysis(
    [str(root / "launch_panel.pyw")], pathex=[str(root)],
    binaries=[], datas=data, hiddenimports=hidden, hookspath=[],
    runtime_hooks=[], excludes=excluded, noarchive=False,
)
# Qt uses the Windows ICU API. Conda's same-named DLL exports a different ABI.
gui.binaries = [entry for entry in gui.binaries if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]
gui_exe = EXE(
    PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
    name="AutoDeliver", console=False, debug=False, strip=False, upx=False,
    icon=str(root / "assets" / "app.ico"), version=str(root / "packaging" / "version_info.txt"),
)
worker = Analysis(
    [str(root / "auto_deliver.py")], pathex=[str(root)],
    binaries=[], datas=data, hiddenimports=hidden, hookspath=[],
    runtime_hooks=[], excludes=excluded, noarchive=False,
)
worker.binaries = [entry for entry in worker.binaries if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]
worker_exe = EXE(
    PYZ(worker.pure), worker.scripts, [], exclude_binaries=True,
    name="auto_deliver_worker", console=True, debug=False, strip=False, upx=False,
    icon=str(root / "assets" / "app.ico"), version=str(root / "packaging" / "version_info.txt"),
)
COLLECT(
    gui_exe, worker_exe, gui.binaries, gui.datas, worker.binaries, worker.datas,
    strip=False, upx=False, name="AutoDeliver",
)
