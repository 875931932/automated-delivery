"""BOSS industry choices for the search filter."""

import re

import requests


INDUSTRY_URL = "https://www.zhipin.com/wapi/zpCommon/data/industry.json"


def fetch_platform_industries(timeout: int = 8) -> list[dict]:
    response = requests.get(INDUSTRY_URL, timeout=timeout)
    response.raise_for_status()
    return parse_platform_industries(response.json())


def parse_platform_industries(payload: dict) -> list[dict]:
    """Normalize the first-party parent/child industry taxonomy."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid BOSS industry response")
    if payload.get("code") != 0:
        raise ValueError(payload.get("message") or "BOSS industry lookup failed")
    data = payload.get("zpData")
    if not isinstance(data, list):
        raise ValueError("Invalid BOSS industry data")

    industries = []
    seen_parents = set()
    seen_children = set()
    for parent in data:
        if not isinstance(parent, dict):
            continue
        parent_code = str(parent.get("code") or "").strip()
        parent_name = str(parent.get("name") or "").strip()
        if (not re.fullmatch(r"\d+", parent_code) or not parent_name
                or parent_code in seen_parents):
            continue
        raw_children = parent.get("subLevelModelList")
        if not isinstance(raw_children, list):
            continue
        children = []
        for child in raw_children:
            if not isinstance(child, dict):
                continue
            code = str(child.get("code") or "").strip()
            name = str(child.get("name") or "").strip()
            if not re.fullmatch(r"\d+", code) or not name or code in seen_children:
                continue
            seen_children.add(code)
            children.append({"code": code, "name": name})
        if children:
            seen_parents.add(parent_code)
            industries.append({"code": parent_code, "name": parent_name, "children": children})
    return industries
