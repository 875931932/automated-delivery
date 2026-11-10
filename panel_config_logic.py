# -*- coding: utf-8 -*-
"""配置页纯逻辑：时间格式解析与配置校验（可单测）。"""
import re

from platform_search_filters import PLATFORM_FILTERS, resolve_platform_filter
from job_platforms import ensure_platform_available, parse_platforms, platform_city_code
from job_profiles import parse_search_keywords

HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

INT_LIMITS = {
    "MATCH_THRESHOLD": (0, 100),
    "DAILY_LIMIT": (0, 99999),
    "AI_TIMEOUT": (1, 3600),
    "AI_MAX_RETRIES": (0, 20),
    "TAVILY_TIMEOUT": (1, 600),
    "DELIVER_MAX_PAGES": (1, 50),
    "JOB_DELAY_MIN": (0, 3600),
    "JOB_DELAY_MAX": (0, 3600),
    "HUMAN_EVERY_N": (0, 1000),
    "DETAIL_DELAY_MIN": (0, 600),
    "DETAIL_DELAY_MAX": (0, 600),
    "TEST_LIMIT": (0, 99999),
    "LOGIN_WAIT": (0, 3600),
}

# 危险配置提示：key -> {值: 提示文案}
CONFIG_WARNINGS = {
    "KEEP_LOGIN": {
        "false": "⚠ 将丢失登录态：每次启动随机 UA，需要重新扫码登录。",
    },
    "DRY_RUN": {
        "true": "干跑模式：只采集与评分，不会真实投递。",
    },
    "HUMANIZE_ENABLE": {
        "false": "已关闭额外浏览动作，仍会同步登录信息。",
    },
}


def parse_hhmm(value):
    """把 hh:mm 转为分钟数；格式非法返回 None。"""
    match = HHMM_RE.match((value or "").strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def config_warnings(values: dict) -> list:
    """按当前取值返回危险项提示列表。"""
    messages = []
    for key, table in CONFIG_WARNINGS.items():
        text = table.get(str(values.get(key, "")).strip().lower())
        if text:
            messages.append(text)
    return messages


def validate_config_values(values: dict, resume_exists=True) -> list:
    """校验配置 dict，返回错误消息列表（空列表表示通过）。

    values: key -> 字符串取值；
    resume_exists: 简历文件是否存在（由调用方注入，保持纯函数）。
    """
    errors = []
    try:
        parse_search_keywords(values.get("DELIVER_KEYWORD", ""))
    except ValueError as exc:
        errors.append(str(exc))
    platforms = ["boss"]
    try:
        platforms = parse_platforms(values.get("JOB_PLATFORMS"))
        for platform in platforms:
            ensure_platform_available(platform)
            if platform != "boss":
                platform_city_code(platform, {
                    "city_code": values.get("CITY_CODE", "101280600"),
                    f"{platform}_city_code": values.get(f"{platform.upper()}_CITY_CODE", ""),
                })
    except ValueError as exc:
        errors.append(str(exc))
    rest_day = str(values.get("REST_DAY_REQUIRE", "不限") or "不限").strip()
    if rest_day not in {"不限", "双休", "单休", "大小周"}:
        errors.append(f"「休息制度」不是支持的选项：{rest_day}")
    for env_key, (_config_key, _param_key, codes) in PLATFORM_FILTERS.items():
        if "boss" not in platforms:
            continue
        raw = str(values.get(env_key, "") or "").strip()
        if raw and raw != "不限" and not resolve_platform_filter(env_key, raw):
            errors.append(f"「{env_key}」不是支持的平台筛选值：{raw}")
    industry = str(values.get("PLATFORM_INDUSTRY", "") or "").strip()
    if "boss" in platforms and industry and not resolve_platform_filter("PLATFORM_INDUSTRY", industry):
        errors.append("「平台行业 ID」需要是数字 ID（多个用逗号分隔），或包含 industry 参数的 BOSS 搜索链接")
    for key, label in (
        ("WORK_TIME_START", "最早可接受上班时间"),
        ("WORK_TIME_END", "最晚下班时间"),
    ):
        value = str(values.get(key, "") or "").strip()
        if value and parse_hhmm(value) is None:
            errors.append(f"「{label}」需要是 hh:mm 格式（如 09:30），当前：{value}")

    start = parse_hhmm(str(values.get("WORK_TIME_START", "") or ""))
    end = parse_hhmm(str(values.get("WORK_TIME_END", "") or ""))
    if start is not None and end is not None and start >= end:
        errors.append("「最早可接受上班时间」需要早于「最晚下班时间」")

    for key, (low, high) in INT_LIMITS.items():
        raw = str(values.get(key, "") or "").strip()
        if not raw:
            continue
        try:
            number = int(raw)
        except ValueError:
            errors.append(f"「{key}」需要是整数，当前：{raw}")
            continue
        if not (low <= number <= high):
            errors.append(f"「{key}」需要在 {low}-{high} 之间，当前：{number}")

    delay_min = str(values.get("JOB_DELAY_MIN", "") or "").strip()
    delay_max = str(values.get("JOB_DELAY_MAX", "") or "").strip()
    if delay_min and delay_max:
        try:
            if int(delay_min) > int(delay_max):
                errors.append("「岗位间隔最小(秒)」不能大于「岗位间隔最大(秒)」")
        except ValueError:
            pass

    detail_min = str(values.get("DETAIL_DELAY_MIN", "") or "").strip()
    detail_max = str(values.get("DETAIL_DELAY_MAX", "") or "").strip()
    if detail_min and detail_max:
        try:
            if int(detail_min) > int(detail_max):
                errors.append("「详情页停留最小(秒)」不能大于「详情页停留最大(秒)」")
        except ValueError:
            pass

    resume = str(values.get("RESUME_FILE", "") or "").strip()
    if not resume:
        errors.append("「简历文件」不能为空")
    elif not resume_exists:
        errors.append(f"「简历文件」不存在：{resume}")
    return errors
