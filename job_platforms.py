"""Platform identities and search settings shared by the panel and worker."""

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlencode, urlparse

from platform_locations import load_city_codes


PLATFORM_LABELS = {
    "boss": "BOSS 直聘",
    "zhilian": "智联招聘",
    "liepin": "猎聘",
}
PAUSED_PLATFORMS = {
    "liepin": "猎聘自动化已暂停：已反馈账号风险，需完成猎聘独立流程核验后再恢复；请取消勾选猎聘。",
}
BOSS_ONLY_FIELDS = (
    "PLATFORM_AREA_FILTER", "PLATFORM_JOB_TYPE", "PLATFORM_PAY_TYPE",
    "PLATFORM_PART_TIME", "PLATFORM_EXPERIENCE", "PLATFORM_DEGREE",
    "PLATFORM_INDUSTRY", "PLATFORM_SCALE",
)

# These are independent platform codes, never converted arithmetically from BOSS.
CITY_CODES = {
    "zhilian": {"北京": "530", "上海": "538", "深圳": "489"},
    "liepin": {"北京": "010", "上海": "020", "广州": "050020", "深圳": "050090"},
}


def parse_platforms(value=None):
    if value is None:
        return ["boss"]
    items = value if isinstance(value, (list, tuple)) else str(value).replace("，", ",").split(",")
    aliases = {**{key: key for key in PLATFORM_LABELS},
               **{label: key for key, label in PLATFORM_LABELS.items()},
               "zhaopin": "zhilian", "智联": "zhilian", "BOSS直聘": "boss"}
    result = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        platform = aliases.get(text, aliases.get(text.lower()))
        if platform is None:
            raise ValueError(f"不支持的招聘平台：{text}")
        if platform not in result:
            result.append(platform)
    if not result:
        raise ValueError("请至少选择一个招聘平台")
    return result


def ensure_platform_available(platform):
    if platform not in PLATFORM_LABELS:
        raise ValueError(f"不支持的招聘平台：{platform}")
    if platform in PAUSED_PLATFORMS:
        raise ValueError(PAUSED_PLATFORMS[platform])


def city_name(config):
    code = str(config.get("city_code") or "101280600").strip()
    names = {value: name for name, value in load_city_codes().items()}
    if code not in names:
        raise ValueError("工作城市无效，请重新选择城市")
    return names[code].removesuffix("市")


def platform_city_code(platform, config):
    name = city_name(config)
    override = str(config.get(f"{platform}_city_code") or "").strip()
    if override and not re.fullmatch(r"\d+", override):
        raise ValueError(f"{PLATFORM_LABELS[platform]}城市代码需要为数字")
    code = override or CITY_CODES[platform].get(name)
    if not code:
        raise ValueError(
            f"尚未收录{PLATFORM_LABELS[platform]}的{name}城市代码，"
            "请在高级设置填写该平台搜索页的城市代码"
        )
    return code


def build_platform_search_url(platform, config, keyword="", page=1):
    code = platform_city_code(platform, config)
    if platform == "zhilian":
        return f"https://www.zhaopin.com/sou/jl{code}/?" + urlencode({
            "kw": keyword, "p": max(1, int(page)),
        })
    return "https://www.liepin.com/zhaopin/?" + urlencode({
        "key": keyword, "dqs": code, "curPage": max(0, int(page) - 1),
        "pageSize": 40,
    })


def platform_profile_dir(platform):
    if platform not in PLATFORM_LABELS:
        raise ValueError(f"Unknown platform: {platform}")
    if platform == "boss":
        return Path.home() / ".boss-zhipin-scraper" / "chrome-profile"
    return Path.home() / f".autodeliver-{platform}" / "chrome-profile"


@dataclass(frozen=True)
class JobIdentity:
    platform: str
    native_id: str
    url: str

    @property
    def key(self):
        if self.platform == "boss":
            return self.native_id
        return f"{self.platform}:{self.native_id}"


def job_identity(platform, url):
    """Accept only canonical job routes on the platform's own HTTPS hosts."""
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or parsed.username or parsed.password \
                or parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    if platform == "boss" and parsed.hostname == "www.zhipin.com":
        match = re.fullmatch(r"/job_detail/([A-Za-z0-9_-]+)\.html", parsed.path)
        native_id = match[1] if match else ""
    elif platform == "liepin" and parsed.hostname == "www.liepin.com":
        match = re.fullmatch(r"/(job|a)/([A-Za-z0-9_-]+)\.shtml", parsed.path)
        native_id = f"{match[1]}:{match[2]}" if match else ""
    elif platform == "zhilian" and parsed.hostname in {"jobs.zhaopin.com", "www.zhaopin.com"}:
        pattern = r"/([A-Za-z0-9_-]+)\.htm" if parsed.hostname == "jobs.zhaopin.com" \
            else r"/jobdetail/([A-Za-z0-9_-]+)\.htm"
        match = re.fullmatch(pattern, parsed.path)
        native_id = match[1] if match else ""
    else:
        return None
    if not native_id:
        return None
    return JobIdentity(platform, native_id, f"https://{parsed.hostname}{parsed.path}")
