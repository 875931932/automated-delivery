# -*- coding: utf-8 -*-
"""投递结果页纯逻辑：筛选/排序/状态着色/详情 HTML/人工标记写回。"""
import csv
import html
import json
import os

from delivery_config import RESULT_FIELDS

# 状态 -> (展示文案, 前景色, 背景色)
_GREEN = ("#05603A", "#ECFDF3")
_GRAY = ("#475467", "#F2F4F7")
_YELLOW = ("#93370D", "#FFFAEB")
_RED = ("#B42318", "#FEF3F2")

STATUS_DISPLAY = {
    "delivered": ("投递成功", *_GREEN),
    "dry_run": ("干跑可投", *_GREEN),
    "dry_run_ready": ("干跑可投", *_GREEN),
    "below_threshold": ("低于分数线", *_GRAY),
    "scope_review": ("范围待复核", *_YELLOW),
    "prefilter_reject": ("预筛未过", *_RED),
    "role_reject": ("职能不符", *_RED),
    "role_rejected": ("职能拦截", *_RED),
    "condition_rejected": ("条件拦截", *_RED),
    "area_rejected": ("区域拦截", *_RED),
    "hard_rejected": ("硬性拦截", *_RED),
    "local_gate_rejected": ("本地拦截", *_RED),
    "out_of_scope": ("确认范围外", *_RED),
    "match_failed": ("评分失败", *_RED),
    "greeting_failed": ("招呼失败", *_RED),
    "failed": ("投递失败", *_RED),
}

_REJECT_MARKERS = ("reject", "fail", "rejected", "failed")


def score_value(text) -> float | None:
    """把分数文本转 float；无法解析返回 None。"""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def row_score(row: dict) -> float | None:
    """取一行的展示分数：优先 AI匹配分数，预筛未过行回落到匹配分数。"""
    score = score_value(row.get("AI匹配分数", ""))
    if score is not None:
        return score
    if row.get("投递状态") != "prefilter_reject":
        return score_value(row.get("匹配分数", ""))
    return None


def status_display(status: str) -> tuple:
    """返回 (展示文案, 前景色, 背景色)。"""
    key = (status or "").strip()
    if key in STATUS_DISPLAY:
        return STATUS_DISPLAY[key]
    lowered = key.lower()
    if any(marker in lowered for marker in _REJECT_MARKERS):
        return ("已过滤", *_RED)
    return (key or "未知", *_GRAY)


def filter_result_rows(rows, status="全部", score_min=0, score_max=100,
                       keyword="", review_only=False) -> list:
    """按状态/分数区间/关键词/只看待复核筛选结果行（纯函数）。"""
    keyword = (keyword or "").strip().lower()
    status = (status or "全部").strip()
    try:
        score_min = float(score_min)
    except (TypeError, ValueError):
        score_min = 0.0
    try:
        score_max = float(score_max)
    except (TypeError, ValueError):
        score_max = 100.0
    range_active = score_min > 0 or score_max < 100

    filtered = []
    for row in rows:
        if status and status != "全部" and row.get("投递状态", "").strip() != status:
            continue
        if review_only and row.get("职业范围状态", "").strip() != "scope_review":
            continue
        if keyword:
            haystack = (
                row.get("工作名称", "") + "\n" + row.get("公司", "")
            ).lower()
            if keyword not in haystack:
                continue
        score = row_score(row)
        if range_active:
            if score is None or not (score_min <= score <= score_max):
                continue
        filtered.append(row)
    return filtered


def deduplicate_result_rows(rows) -> list:
    """Keep one newest row per job and enrich scoring failures with prior assessment data."""
    result = []
    index_by_job_id = {}
    assessment_fields = (
        "AI匹配分数", "AI匹配理由", "硬性缺口", "未验证要求", "加分项命中",
        "加分项缺口", "简历证据", "主岗位画像", "岗位画像评估详情",
    )
    for row in rows:
        job_id = str(row.get("encryptJobId", "") or "").strip()
        if not job_id or job_id not in index_by_job_id:
            if job_id:
                index_by_job_id[job_id] = len(result)
            result.append(row)
            continue

        index = index_by_job_id[job_id]
        current = result[index]
        if current.get("投递状态") == "match_failed" and row.get("投递状态") != "match_failed":
            merged = dict(current)
            merged["历史有效评分"] = "true"
            for field in assessment_fields:
                if not str(merged.get(field, "") or "").strip():
                    merged[field] = row.get(field, "")
            result[index] = merged
    return result


def update_result_mark(path, job_id, mark) -> int:
    """按 encryptJobId 把「人工标记」写回结果 CSV，返回更新行数。

    表头保持 RESULT_FIELDS；找不到 job_id 时不改文件返回 0。
    """
    path = str(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    updated = 0
    for row in rows:
        if row.get("encryptJobId", "") == job_id:
            row["人工标记"] = mark
            updated += 1
    if not updated:
        return 0
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in RESULT_FIELDS})
    os.replace(temp_path, path)
    return updated


def _chips_html(items, chip_class="gap") -> str:
    parts = []
    for item in items:
        text = str(item).strip()
        if text:
            parts.append(f'<span class="chip {chip_class}">{html.escape(text)}</span>')
    return " ".join(parts)


def _split_field(value) -> list:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("；", ";").split(";") if part.strip()]


def _profile_details_html(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        items = json.loads(text)
    except (ValueError, TypeError):
        return f'<pre class="json">{html.escape(text)}</pre>'
    if not isinstance(items, list):
        return f'<pre class="json">{html.escape(text)}</pre>'
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr><td>{name}</td><td>{score}</td><td>{fit}</td><td>{reason}</td></tr>".format(
                name=html.escape(str(item.get("profile_name") or item.get("profile_id") or "")),
                score=html.escape(str(item.get("score", ""))),
                fit=html.escape(str(item.get("role_fit", ""))),
                reason=html.escape(str(item.get("reason", ""))),
            )
        )
    if not rows:
        return f'<pre class="json">{html.escape(text)}</pre>'
    return (
        '<table class="mini"><tr><th>画像</th><th>分数</th><th>契合</th><th>理由</th></tr>'
        + "".join(rows) + "</table>"
    )


def build_result_detail_html(row: dict) -> str:
    """把结果行渲染为详情区 HTML（评估摘要 / 缺口 chips / 画像评估 / 详情链接）。"""
    title = html.escape(row.get("工作名称", "") or "未命名岗位")
    company = html.escape(row.get("公司", ""))
    salary = html.escape(row.get("工资", ""))
    label, color, bg = status_display(row.get("投递状态", ""))
    score = row_score(row)
    score_text = f"{score:g}" if score is not None else "-"
    score_source = (
        '<span class="sub">（上次有效评分，本次评分失败）</span>'
        if str(row.get("历史有效评分", "")).lower() == "true"
        else ""
    )

    sections = [
        f'<div class="head"><span class="title">{title}</span> '
        f'<span class="sub">{company} · {salary}</span> '
        f'<span class="chip status" style="color:{color};background:{bg}">'
        f'{html.escape(label)}</span> '
        f'<span class="chip score">AI 匹配分 {score_text}</span> {score_source}</div>'
    ]

    summary = html.escape(str(row.get("AI匹配理由", "")).strip())
    if summary:
        sections.append(f'<div class="sec"><div class="secTitle">评估摘要</div>{summary}</div>')

    gaps = _split_field(row.get("硬性缺口", ""))
    unverified = _split_field(row.get("未验证要求", ""))
    if gaps or unverified:
        body = ""
        if gaps:
            body += '<div class="row"><span class="label">硬性缺口</span>' + _chips_html(gaps, "gap") + "</div>"
        if unverified:
            body += '<div class="row"><span class="label">未验证要求</span>' + _chips_html(unverified, "warn") + "</div>"
        sections.append(f'<div class="sec"><div class="secTitle">缺口与未验证</div>{body}</div>')

    extras = []
    for key, label in (
        ("JD要求分层", "JD 原文要求（模型提取）"), ("加分项命中", "加分项命中"),
        ("加分项缺口", "加分项缺口"), ("简历证据", "简历证据"),
        ("筛选原因", "筛选结果"), ("技能匹配诊断", "标签诊断（仅供参考）"),
        ("打招呼语", "打招呼语"), ("搜索来源关键词", "搜索关键词"),
    ):
        text = str(row.get(key, "")).strip()
        if text:
            extras.append(
                f'<div class="row"><span class="label">{label}</span>'
                f'<span class="text">{html.escape(text)}</span></div>'
            )
    if extras:
        sections.append('<div class="sec"><div class="secTitle">补充信息</div>' + "".join(extras) + "</div>")

    profile_html = _profile_details_html(row.get("岗位画像评估详情", ""))
    if profile_html:
        sections.append(
            '<div class="sec"><div class="secTitle">岗位画像评估详情（简化）</div>'
            + profile_html + "</div>"
        )

    link = str(row.get("详情链接", "")).strip()
    if link:
        safe_link = html.escape(link, quote=True)
        sections.append(
            f'<div class="sec"><div class="secTitle">详情链接</div>'
            f'<a href="{safe_link}">{safe_link}</a></div>'
        )

    meta_bits = []
    for key, label in (
        ("encryptJobId", "岗位 ID"), ("工作性质", "工作性质"), ("区域", "工作地点"),
        ("上班时间", "上班时间"), ("休息制度", "休息制度"), ("主岗位画像", "主岗位画像"),
        ("职业范围状态", "职业范围状态"), ("人工标记", "人工标记"),
        ("投递时间", "记录时间"), ("来源岗位画像", "来源岗位画像"),
    ):
        text = str(row.get(key, "")).strip()
        if text:
            meta_bits.append(f"{label}：{html.escape(text)}")
    if meta_bits:
        sections.append('<div class="sec meta">' + " ｜ ".join(meta_bits) + "</div>")

    return (
        '<style>'
        'body{color:#101828;}'
        '.head{font-size:14px;margin-bottom:2px;} '
        '.title{font-weight:bold;font-size:16px;color:#101828;} '
        '.sub{color:#667085;font-size:12px;} '
        '.chip{border-radius:10px;padding:3px 10px;font-size:11px;margin-left:6px;'
        'display:inline-block;border:1px solid transparent;} '
        '.chip.score{background:#EEF3FE;color:#1F3DAD;border-color:#D9E3FD;} '
        '.chip.gap{background:#FEF3F2;color:#B42318;border-color:#FBD5D1;margin-right:5px;} '
        '.chip.warn{background:#FFFAEB;color:#93370D;border-color:#FDE3A7;margin-right:5px;} '
        '.sec{margin-top:16px;padding-top:12px;border-top:1px solid #ECEEF2;} '
        '.secTitle{font-weight:bold;color:#344054;margin-bottom:8px;font-size:13px;} '
        '.row{margin-bottom:6px;line-height:1.6;} '
        '.label{color:#667085;font-size:12px;margin-right:8px;} '
        '.text{color:#101828;font-size:13px;} '
        '.meta{color:#667085;font-size:12px;line-height:1.7;} '
        'pre.json{background:#FAFBFC;border:1px solid #E7E9EE;border-radius:8px;padding:10px;'
        'font-size:11px;white-space:pre-wrap;color:#344054;} '
        'table.mini{border-collapse:collapse;font-size:12px;width:100%;} '
        'table.mini td,table.mini th{border:1px solid #E7E9EE;padding:6px 8px;'
        'text-align:left;color:#344054;background:#FAFBFC;} '
        'table.mini th{font-weight:bold;color:#101828;} '
        'a{color:#2F5BEA;text-decoration:none;} a:hover{text-decoration:underline;}'
        "</style>"
        + "".join(sections)
    )
