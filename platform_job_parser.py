"""Read job cards and descriptions without executing page scripts."""

import json
import re
from urllib.parse import urljoin

from DrissionPage.common import make_session_ele

from job_platforms import PLATFORM_LABELS, job_identity


CARD_SELECTORS = {
    "liepin": ".jobDetailBox, .job-card-pc-container, .jobCardPcContainer, .sojob-item-main",
    "zhilian": ".joblist-box__item, .joblist-box-item, .job-card, .positionlist .contentpile",
}
DETAIL_SELECTORS = {
    "liepin": '[data-selector="job-intro-content"], .job-intro-content, .job-intro-container dd',
    "zhilian": ".describtion__detail-content, .job-detail-description, .job-detail__description, .pos-ul",
}


def text_at(node, selectors):
    for selector in selectors:
        found = node.ele(f"css:{selector}")
        if found and found.text.strip():
            return found.text.strip()
    return ""


def normalized_job(platform, identity, *, name, company="", salary="", location="",
                   degree="", experience="", skills=None, description=""):
    parts = re.split(r"[-·\s]+", location.strip("【】 "))
    return {
        "encryptJobId": identity.key,
        "platform": platform,
        "platformJobId": identity.native_id,
        "jobUrl": identity.url,
        "jobName": name.strip(),
        "brandName": company.strip(),
        "salaryDesc": salary.strip(),
        "cityName": parts[0] if parts else "",
        "areaDistrict": " ".join(parts[1:]),
        "jobDegree": degree.strip(),
        "jobExperience": experience.strip(),
        "skills": skills or [],
        "description": description,
    }


def parse_job_cards(platform, document):
    root = make_session_ele(document)
    cards = root.eles(f"css:{CARD_SELECTORS[platform]}")
    jobs = {}
    for card in cards:
        links = card.eles("css:a[href]")
        identity = next((identity for link in links if (
            identity := job_identity(platform, urljoin(
                "https://www.liepin.com" if platform == "liepin" else "https://www.zhaopin.com",
                link.attr("href") or "",
            ))
        )), None)
        if identity is None:
            continue
        name = text_at(card, (
            ".jobTitleBox [title]", ".job-title", ".job-info-title", ".joblist-box__title", ".jobinfo__name",
            ".job-card__title-clamp", ".job-title-box", "h3",
        ))
        if not name:
            continue
        company = text_at(card, (".companyName", ".company-name", ".job-card__company-name",
                                 ".company-name-box", ".company_name", ".joblist-box__company-name"))
        salary = text_at(card, (".job-salary", ".salary", ".jobTitleBox + span",
                                ".joblist-box__salary", ".job-card__salary"))
        location = text_at(card, (".job-area", ".job-dq-box", ".joblist-box__job-location",
                                  ".job-card__location", ".job-address", ".job-info-city"))
        # Current Liepin cards retain stable title/company hooks but hash other classes.
        if platform == "liepin":
            title_box = card.ele("css:.jobTitleBox")
            spans = title_box.eles("css:span") if title_box else []
            location = location or "".join(ele.text for ele in spans).strip("【】 ")
        lines = [line.strip() for line in card.text.splitlines() if line.strip()]
        lines.extend(ele.text.strip() for ele in card.eles("css:span, li") if ele.text.strip())
        salary = salary or next((line for line in lines if re.fullmatch(
            r"(?:\d+(?:\.\d+)?[-~]\d+(?:\.\d+)?\s*[kK千万](?:.*薪)?|面议)", line
        )), "")
        degree = next((line for line in lines if re.fullmatch(
            r"(?:统招)?(?:本科|大专|硕士|博士|高中|中专|学历不限)(?:及以上)?", line
        )), "")
        experience = next((line for line in lines if re.fullmatch(
            r"(?:\d+(?:-\d+)?年(?:以上|以下|以内)?|经验不限|应届生|实习生)", line
        )), "")
        jobs[identity.key] = normalized_job(
            platform, identity, name=name, company=company, salary=salary,
            location=location, degree=degree, experience=experience,
        )
    return list(jobs.values())


def parse_job_detail(platform, document):
    root = make_session_ele(document)
    desc = text_at(root, DETAIL_SELECTORS[platform].split(", "))
    tags = [ele.text.strip() for ele in root.eles(
        'css:.job-labels span, .job-welfare span, .job-advantage span, .job-tags span'
    ) if ele.text.strip()]
    return {"desc": desc, "skills": [], "welfare_tags": list(dict.fromkeys(tags)),
            "company_url": ""}


def zhilian_state_description(document, native_id):
    """Read only JSON tied to the exact job, never evaluate inline JavaScript."""
    root = make_session_ele(document)
    for script in root.eles("css:script"):
        source = script.raw_text
        match = re.search(r"(?:window\.)?__INITIAL_STATE__\s*=\s*(?=\{)", source)
        if not match:
            continue
        try:
            state, _ = json.JSONDecoder().raw_decode(source[match.end():])
        except (ValueError, TypeError):
            continue
        if not isinstance(state, dict):
            continue
        detail = state.get("jobDetail")
        detail = detail.get("detailedPosition") if isinstance(detail, dict) else None
        if not isinstance(detail, dict) or str(detail.get("positionNumber") or "") != native_id:
            continue
        description = detail.get("description") or detail.get("jobDesc")
        if isinstance(description, str) and description.strip():
            return make_session_ele(f"<div>{description}</div>").text.strip()
    return ""


def candidate_row(raw):
    """Keep the shared scoring/result schema while retaining platform provenance."""
    platform = raw["platform"]
    return {
        "平台": PLATFORM_LABELS[platform], "平台岗位ID": raw["platformJobId"],
        "encryptJobId": raw["encryptJobId"], "securityId": "",
        "工作名称": raw.get("jobName", ""), "公司": raw.get("brandName", ""),
        "工资": raw.get("salaryDesc", ""),
        "区域": " ".join(filter(None, (raw.get("cityName"), raw.get("areaDistrict")))),
        "学历要求": raw.get("jobDegree", ""), "工作经验要求": raw.get("jobExperience", ""),
        "技术要求": "; ".join(raw.get("skills") or []),
        "工作介绍": raw.get("description", ""), "详情链接": raw["jobUrl"],
    }
