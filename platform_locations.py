# -*- coding: utf-8 -*-
"""BOSS city and administrative-district data used by search settings."""
import json
import re
from pathlib import Path

import requests

from app_paths import get_resource_dir

BASE_DIR = get_resource_dir()
CITY_CODES_PATH = BASE_DIR / "city_codes.json"
BUSINESS_DISTRICT_URL = "https://www.zhipin.com/wapi/zpgeek/businessDistrict.json"


def load_city_codes(path: Path | str = CITY_CODES_PATH) -> dict[str, str]:
    """Load the provided city-name to BOSS city-code mapping."""
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("city_codes.json must contain a JSON object")
    cities = {}
    for name, code in raw.items():
        name = str(name).strip()
        code = str(code).strip()
        if name and re.fullmatch(r"\d{9}", code):
            cities[name] = code
    if not cities:
        raise ValueError("city_codes.json contains no valid BOSS city codes")
    return cities


def fetch_platform_districts(city_code: str, timeout: int = 8) -> list[dict[str, str]]:
    """Fetch the administrative districts that BOSS accepts as multiBusinessDistrict."""
    city_code = str(city_code or "").strip()
    if not re.fullmatch(r"\d{9}", city_code):
        raise ValueError("invalid BOSS city code")
    response = requests.get(
        BUSINESS_DISTRICT_URL,
        params={"cityCode": city_code},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_platform_districts(response.json(), city_code)


def parse_platform_districts(payload: dict, city_code: str) -> list[dict[str, str]]:
    """Validate and normalize the nested BOSS district response."""
    city_code = str(city_code or "").strip()
    if payload.get("code") != 0:
        raise ValueError(payload.get("message") or "BOSS district lookup failed")
    root = (payload.get("zpData") or {}).get("businessDistrict") or {}
    if str(root.get("code", "")) != city_code:
        raise ValueError("BOSS returned districts for a different city")
    districts = []
    for item in root.get("subLevelModelList") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if name and re.fullmatch(r"\d{6,10}", code):
            districts.append({"name": name, "code": code})
    return districts


def resolve_platform_area_codes(areas, city_code: str) -> str:
    """Resolve saved district IDs or legacy names against the selected city only."""
    selected = [str(area).strip() for area in (areas or []) if str(area).strip()]
    if not selected:
        return ""
    districts = fetch_platform_districts(city_code)
    code_by_name = {item["name"]: item["code"] for item in districts}
    allowed_codes = {item["code"] for item in districts}
    codes = []
    for area in selected:
        code = area if area in allowed_codes else code_by_name.get(area)
        if code is None:
            print(f"[配置] 区域「{area}」不属于当前城市或已失效，已忽略")
            continue
        if code not in codes:
            codes.append(code)
    if not codes:
        raise ValueError("所选工作区域无法在当前城市中验证，请刷新区域或清空区域筛选。")
    return ",".join(codes)
