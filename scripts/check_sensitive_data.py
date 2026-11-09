"""Scan repository text files for common personal data and credential patterns."""

from __future__ import annotations

import os
import re
from pathlib import Path


EXCLUDED_DIRS = {
    ".codegraph",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "网页示例",
    "venv",
    "build",
    "dist",
    "release",
}

TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

SENSITIVE_PATTERNS = {
    "mainland_phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "email": re.compile(
        r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
        r"(?![A-Z0-9.-])"
    ),
    "mainland_id": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    "windows_user_path": re.compile(
        r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"<>]+"
    ),
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "credential_token": re.compile(
        r"(?i)(?:\bsk-[A-Za-z0-9_-]{20,}\b|\bAKIA[0-9A-Z]{16}\b|"
        r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bBearer\s+[A-Za-z0-9._-]{20,})"
    ),
}


# Explicitly published by the author; all other addresses are still reported.
PUBLIC_CONTACT_FILES = {"author_info.json", "README.md"}
PUBLIC_EMAILS = {"875931932" + "@qq.com"}


def scan_text(text: str) -> list[str]:
    """Return matching risk categories without returning matched values."""
    return [
        category
        for category, pattern in SENSITIVE_PATTERNS.items()
        if pattern.search(text)
    ]


def _project_files(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        for name in sorted(files):
            yield Path(current) / name


def scan_repository(root: Path) -> list[tuple[str, str]]:
    findings = []
    for path in _project_files(root):
        if path.relative_to(root).as_posix().startswith("packaging/licenses/"):
            continue
        is_env_file = path.name == ".env" or path.name.startswith(".env.")
        if not path.is_file():
            continue
        if not is_env_file and path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_bytes()
            if b"\0" in content:
                continue
            text = content.decode("utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in PUBLIC_CONTACT_FILES:
            text = SENSITIVE_PATTERNS["email"].sub(
                lambda match: "" if match.group().lower() in PUBLIC_EMAILS else match.group(), text,
            )
        for category in scan_text(text):
            findings.append((relative, category))
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = scan_repository(root)
    if findings:
        for relative_path, category in findings:
            print(f"{relative_path}: {category}")
        return 1
    print("Sensitive-data scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
