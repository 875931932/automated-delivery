"""Open result links with the same browser and persistent platform profile."""

import os
from pathlib import Path
import subprocess

import psutil

from browser_runtime import resolve_browser_path
from job_platforms import PLATFORM_LABELS, job_identity, parse_platforms, platform_profile_dir
from process_runtime import quiet_process_options


def result_job_target(row):
    url = str(row.get("详情链接") or "").strip()
    if any(ord(character) < 32 for character in url):
        raise ValueError("该记录的岗位链接包含无效字符，无法打开。")
    identity = next((identity for platform in PLATFORM_LABELS
                     if (identity := job_identity(platform, url))), None)
    if identity is None:
        raise ValueError("该记录缺少有效的官方岗位链接，无法打开。")
    saved_platform = str(row.get("平台") or "").strip()
    if saved_platform and parse_platforms(saved_platform) != [identity.platform]:
        raise ValueError("岗位链接与记录的平台不一致，请核对该条结果。")
    return identity


def _profile_process(profile_dir):
    expected = os.path.normcase(str(Path(profile_dir).resolve()))
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if str(process.info["name"] or "").lower() not in {
                "chrome.exe", "msedge.exe", "chromium.exe", "chrome", "chromium", "msedge",
            }:
                continue
            arguments = process.info["cmdline"] or []
            if any(argument.startswith("--type=") for argument in arguments):
                continue
            for index, argument in enumerate(arguments):
                if argument.startswith("--user-data-dir="):
                    profile = argument.partition("=")[2]
                elif argument == "--user-data-dir" and index + 1 < len(arguments):
                    profile = arguments[index + 1]
                else:
                    continue
                observed = os.path.normcase(str(Path(profile.strip('"')).resolve()))
                if observed == expected:
                    return arguments
        except (psutil.Error, OSError, ValueError):
            continue
    return None


def ensure_task_profiles_available(config):
    if str(config.get("KEEP_LOGIN", "true")).strip().lower() != "true":
        return
    for platform in parse_platforms(config.get("JOB_PLATFORMS")):
        if _profile_process(platform_profile_dir(platform)) is not None:
            raise ValueError(
                f"{PLATFORM_LABELS[platform]}项目浏览器仍在使用登录资料，"
                "请先关闭该平台的浏览器窗口，再启动投递任务。"
            )


def open_result_job(row, config):
    identity = result_job_target(row)
    if str(config.get("KEEP_LOGIN", "true")).strip().lower() != "true":
        raise ValueError("当前未开启“保留登录信息”，无法复用任务的临时登录状态；请开启并完成一次登录。")
    profile_dir = platform_profile_dir(identity.platform)
    arguments = _profile_process(profile_dir)
    if arguments is not None and any(argument.startswith("--headless") for argument in arguments):
        raise ValueError("该平台的项目浏览器正在后台运行，请先结束投递任务，再打开岗位链接。")
    browser = resolve_browser_path(config.get("BROWSER_PATH"))
    command = [
        str(browser), f"--user-data-dir={profile_dir}", "--profile-directory=Default",
        "--no-first-run", "--no-default-browser-check", "--restore-last-session", "--new-window",
    ]
    # Preserve the BOSS profile's saved UA along with its login storage.
    if identity.platform == "boss":
        user_agent_path = profile_dir / "user_agent.txt"
        if user_agent_path.is_file():
            user_agent = user_agent_path.read_text(encoding="utf-8").strip()
            if user_agent:
                command.append(f"--user-agent={user_agent}")
    command.append(str(row["详情链接"]).strip())
    return subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, **quiet_process_options(),
    )
