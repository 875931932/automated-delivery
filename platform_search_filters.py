"""BOSS web/geek/jobs filter labels and query codes."""

import re

JOB_TYPE_CODES = {"全职": "1901", "实习": "1902", "兼职": "1903"}
JOB_TYPE_LABELS = {code: label for label, code in JOB_TYPE_CODES.items()}


PLATFORM_FILTERS = {
    "PLATFORM_PAY_TYPE": (
        "platform_pay_type",
        "payType",
        {
            "日结": "2501",
            "周结": "2502",
            "月结": "2503",
            "完工结": "2504",
        },
    ),
    "PLATFORM_PART_TIME": (
        "platform_part_time",
        "partTime",
        {
            "周末/节假日": "2701",
            "寒暑假": "2702",
            "短期": "2703",
            "长期": "2704",
            "工作日": "2705",
            "夜班": "2706",
        },
    ),
    "PLATFORM_EXPERIENCE": (
        "platform_experience",
        "experience",
        {
            "经验不限": "101",
            "应届生": "102",
            "1年以内": "103",
            "1-3年": "104",
            "3-5年": "105",
            "5-10年": "106",
            "10年以上": "107",
            "在校生": "108",
        },
    ),
    "PLATFORM_DEGREE": (
        "platform_degree",
        "degree",
        {
            "初中及以下": "209",
            "中专/中技": "208",
            "高中": "206",
            "大专": "202",
            "本科": "203",
            "硕士": "204",
            "博士": "205",
        },
    ),
    "PLATFORM_SCALE": (
        "platform_scale",
        "scale",
        {
            "0-20人": "301",
            "20-99人": "302",
            "100-499人": "303",
            "500-999人": "304",
            "1000-9999人": "305",
            "10000人以上": "306",
        },
    ),
    "PLATFORM_INDUSTRY": (
        "platform_industry",
        "industry",
        None,
    ),
}

PLATFORM_FILTER_PARAMS = ("jobType", *(item[1] for item in PLATFORM_FILTERS.values()))


def platform_filter_options(field_key):
    """Return UI labels for a known filter field, with an unrestricted choice."""
    options = PLATFORM_FILTERS.get(field_key)
    return ["不限", *options[2]] if options and options[2] else []


def resolve_platform_filter(field_key, value):
    """Resolve a saved UI label or already-coded value to its BOSS query ID."""
    raw = str(value or "").strip()
    if not raw or raw == "不限":
        return ""
    if field_key == "PLATFORM_INDUSTRY":
        return raw if re.fullmatch(r"\d+", raw) else ""
    definition = PLATFORM_FILTERS.get(field_key)
    if not definition or not definition[2]:
        return ""
    codes = definition[2]
    if raw in codes:
        return codes[raw]
    return raw if raw in codes.values() else ""


def platform_filter_label(field_key, value):
    """Convert saved BOSS codes to the corresponding visible UI label."""
    raw = str(value or "").strip()
    if field_key == "PLATFORM_JOB_TYPE":
        return JOB_TYPE_LABELS.get(raw, raw)
    definition = PLATFORM_FILTERS.get(field_key)
    if definition and definition[2]:
        return next((label for label, code in definition[2].items() if code == raw), raw)
    return raw
