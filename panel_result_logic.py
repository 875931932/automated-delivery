# -*- coding: utf-8 -*-
"""投递结果页纯逻辑：筛选/排序/状态着色/详情 HTML/人工标记写回。"""
import csv
import hashlib
import html
import io
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path

from delivery_config import RESULT_FIELDS

# 状态 -> (展示文案, 前景色, 背景色)
_GREEN = ("#05603A", "#ECFDF3")
_GRAY = ("#475467", "#F2F4F7")
_YELLOW = ("#93370D", "#FFFAEB")
_RED = ("#B42318", "#FEF3F2")

STATUS_DISPLAY = {
    "delivered": ("投递成功", *_GREEN),
    "already_contacted": ("已沟通（跳过）", *_GRAY),
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
    "delivery_unconfirmed": ("投递待核对", *_YELLOW),
    "manual_required": ("需人工投递", *_YELLOW),
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


def summarize_result_rows(rows) -> dict[str, int]:
    """汇总结果页首屏指标，区分真实投递与干跑状态。"""
    statuses = [str(row.get("投递状态", "")).strip().lower() for row in rows]
    return {
        "total": len(statuses),
        "delivered": sum(status == "delivered" for status in statuses),
        "dry_run": sum(status in {"dry_run", "dry_run_ready"} for status in statuses),
        "review": sum(status in {"scope_review", "delivery_unconfirmed", "manual_required"} for status in statuses),
        "failed": sum("fail" in status for status in statuses),
    }


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
        if review_only and row.get("职业范围状态", "").strip() != "scope_review" \
                and row.get("投递状态", "").strip() not in {"delivery_unconfirmed", "manual_required"}:
            continue
        if keyword:
            haystack = (
                row.get("工作名称", "") + "\n" + row.get("公司", "")
                + "\n" + row.get("平台", "")
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


def read_result_snapshot(path) -> tuple[list, str]:
    """Read rows and a fingerprint of the exact file displayed by the panel."""
    data = Path(path).read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    return list(reader), hashlib.sha256(data).hexdigest()


def delete_result_rows(path, selected_rows, *, expected_digest=None) -> tuple[int, str | None]:
    """Delete job histories, matching ID-less records by full content and count.

    Preserve original columns and back up exact bytes before atomic replacement.
    """
    selected_rows = list(selected_rows)
    if not selected_rows:
        return 0, None
    path = Path(path)
    original = path.read_bytes()
    if expected_digest is not None and hashlib.sha256(original).hexdigest() != expected_digest:
        raise ValueError("结果文件已变化，请刷新后重新选择要删除的记录。")
    reader = csv.DictReader(
        io.StringIO(original.decode("utf-8-sig"), newline=""), strict=True,
    )
    rows = list(reader)
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or any(
        None in row or any(value is None for value in row.values()) for row in rows
    ):
        raise ValueError("结果文件的列结构异常，未执行删除，请先检查 CSV 文件。")
    job_ids = {str(row.get("encryptJobId", "") or "").strip() for row in selected_rows}
    job_ids.discard("")
    idless = [row for row in selected_rows if not str(row.get("encryptJobId", "") or "").strip()]
    if any(not set(fields).issubset(row) for row in idless):
        raise ValueError("无岗位 ID 的记录内容不完整，请刷新后重新选择。")
    remaining_matches = Counter(tuple(row[field] for field in fields) for row in idless)
    kept = []
    for row in rows:
        job_id = str(row.get("encryptJobId", "") or "").strip()
        if job_id and job_id in job_ids:
            continue
        key = tuple(row[field] for field in fields)
        if not job_id and remaining_matches[key]:
            remaining_matches[key] -= 1
            continue
        kept.append(row)
    removed = len(rows) - len(kept)
    if not removed:
        return 0, None

    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent,
        prefix=f"{path.name}.delete-{time.strftime('%Y%m%d-%H%M%S')}-",
        suffix=".bak", delete=False,
    ) as backup:
        backup.write(original)
        backup.flush()
        os.fsync(backup.fileno())
        backup_path = backup.name
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=f"{path.name}.delete-", suffix=".tmp", delete=False,
        ) as output:
            temp_path = output.name
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(kept)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != original:
            raise ValueError("结果文件在删除期间发生变化，未执行删除，请刷新后重新选择。")
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
    return removed, backup_path


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


def _chips_html(items, chip_class="chipGap") -> str:
    parts = []
    for item in items:
        text = str(item).strip()
        if text:
            parts.append(f'<span class="chip {chip_class}">{html.escape(text)}</span>')
    # QTextBrowser 不支持 span 的 margin-right，用 &nbsp; 拉开间距
    return "&nbsp;&nbsp;".join(parts)


# 详情页样式。
# 注意：QTextBrowser 只支持有限 CSS —— 可用的是 background-color、margin、
# font 系列、text-align；padding / border / border-radius / flex / line-height 均无效。
# 因此这里的"卡片"用 外层背景 div + 内层 margin div 组合出内边距效果，
# "分段"靠标题字号/颜色差异 + 区块 margin 来拉开层次。
_DETAIL_STYLE = """
<style>
body{color:#101828;}
.sec{margin-bottom:26px;}
.secTitle{font-size:15px;font-weight:bold;color:#1F3DAD;margin-bottom:12px;}
.card{background:#F1F4F9;margin-bottom:18px;}
.cardIn{margin:15px 17px;}
.cardHi{background:#E8F0FE;}
.row{color:#475467;margin-bottom:7px;}
.greeting{color:#101828;font-size:13px;}
.chip{background:#FFFFFF;color:#1F3DAD;}
.chipGap{background:#FEF3F2;color:#B42318;}
.chipWarn{background:#FEF6E7;color:#93370D;}
.tag{background:#DCE4F6;color:#2B3A63;}
.rule{background:#DCE3EF;font-size:2px;}
.k{color:#101828;font-weight:bold;}
.muted{color:#667085;}
.scoreNote{background:#FEF6E7;color:#93370D;margin-bottom:16px;}
.scoreNoteIn{margin:12px 14px;}
a{color:#2F5BEA;text-decoration:none;font-weight:bold;}
</style>
"""


def _escape_lines(text: str) -> str:
    """把多行文本拆成独立 div —— <br> 会让后续行脱离父级缩进。"""
    lines = [line for line in str(text).splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    return "".join(f'<div>{html.escape(line)}</div>' for line in lines)


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
        return (
            '<div class="card"><div class="cardIn">'
            f'<div class="row">{_escape_lines(text)}</div></div></div>'
        )
    if not isinstance(items, list):
        return (
            '<div class="card"><div class="cardIn">'
            f'<div class="row">{_escape_lines(text)}</div></div></div>'
        )

    blocks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("profile_name") or item.get("profile_id") or "未命名画像"
        metrics = []
        for label, key in (("岗位匹配", "score"), ("职能契合", "role_fit")):
            value = item.get(key)
            if value is not None and str(value).strip():
                metrics.append(f"{label} {html.escape(str(value))}")
        reason = str(item.get("reason") or "").strip()

        inner = f'<div class="tag">{html.escape(str(name))}</div>'
        if metrics:
            chips = "&nbsp;&nbsp;".join(
                f'<span class="chip">{m}</span>' for m in metrics
            )
            inner += f'<div style="margin-top:10px;">{chips}</div>'
        if reason:
            inner += (
                f'<div class="row" style="margin-top:11px;">'
                f'{_escape_lines(reason)}</div>'
            )
        blocks.append(
            '<div class="card"><div class="cardIn">' + inner + "</div></div>"
        )
    return "".join(blocks)


def _join_sections(sections) -> str:
    """把各分区拼起来，之间插入细分隔线，形成清晰的段落层次。"""
    if not sections:
        return ""
    parts = []
    for index, section in enumerate(sections):
        if index:
            parts.append('<div class="rule">&nbsp;</div>')
        parts.append(section)
    return "".join(parts)


def build_result_detail_html(row: dict) -> str:
    """渲染选中岗位的主要信息；评估证据由 build_result_evidence_html 单独渲染。"""
    sections = []
    if str(row.get("历史有效评分", "")).lower() == "true":
        score = row_score(row)
        score_text = f" {score:g}" if score is not None else ""
        sections.append(
            '<div class="scoreNote"><div class="scoreNoteIn">'
            f'本次评分失败，当前匹配分沿用上次有效评分{score_text}</div></div>'
        )

    greeting = str(row.get("打招呼语", "")).strip()
    greeting_html = (
        f'<div class="greeting">{_escape_lines(greeting)}</div>'
        if greeting else '<div class="muted">暂无生成的招呼语</div>'
    )
    sections.append(
        '<div class="sec"><div class="secTitle">打招呼语</div>'
        '<div class="card cardHi"><div class="cardIn">'
        f'{greeting_html}</div></div></div>'
    )

    profile_html = _profile_details_html(row.get("岗位画像评估详情", ""))
    if profile_html:
        sections.append(
            '<div class="sec"><div class="secTitle">岗位画像评估</div>'
            + profile_html + "</div>"
        )
    else:
        note = str(row.get("AI匹配理由") or row.get("筛选原因") or "").strip()
        note_html = (
            f'<div class="row">{_escape_lines(note)}</div>'
            if note else '<div class="muted">当前记录未生成岗位画像评估</div>'
        )
        sections.append(
            '<div class="sec"><div class="secTitle">岗位画像评估</div>'
            '<div class="card"><div class="cardIn">'
            f'{note_html}</div></div></div>'
        )

    keyword = str(row.get("搜索来源关键词", "")).strip()
    if keyword:
        sections.append(
            '<div class="sec"><div class="secTitle">搜索关键词</div>'
            '<div class="card"><div class="cardIn">'
            f'<div class="row">{html.escape(keyword)}</div></div></div></div>'
        )

    link = str(row.get("详情链接", "")).strip()
    if link.lower().startswith(("https://", "http://")):
        safe_link = html.escape(link, quote=True)
        sections.append(
            '<div class="sec"><div class="secTitle">岗位链接</div>'
            '<div class="card"><div class="cardIn">'
            f'<a href="{safe_link}">打开岗位详情</a></div></div></div>'
        )

    meta_bits = []
    for key, label in (
        ("平台", "招聘平台"), ("encryptJobId", "岗位 ID"), ("工作性质", "工作性质"), ("区域", "工作地点"),
        ("上班时间", "上班时间"), ("休息制度", "休息制度"), ("主岗位画像", "主岗位画像"),
        ("职业范围状态", "职业范围状态"), ("人工标记", "人工标记"),
        ("投递时间", "记录时间"), ("来源岗位画像", "来源岗位画像"),
    ):
        text = str(row.get(key, "")).strip()
        if text:
            # 标签与值保持同一段文本，便于复制与检索
            meta_bits.append(
                f'<div class="row">{label}：{html.escape(text)}</div>'
            )
    if meta_bits:
        sections.append(
            '<div class="sec"><div class="secTitle">岗位信息</div>'
            '<div class="card"><div class="cardIn">'
            f'{"".join(meta_bits)}</div></div></div>'
        )

    return _DETAIL_STYLE + _join_sections(sections)


def build_result_evidence_html(row: dict) -> str:
    """渲染非首要评估信息，供用户主动展开查看。"""
    sections = []
    gaps = _split_field(row.get("硬性缺口", ""))
    unverified = _split_field(row.get("未验证要求", ""))
    if gaps or unverified:
        body = ""
        if gaps:
            body += (
                '<div class="row"><span class="k">硬性缺口：</span>'
                + _chips_html(gaps, "chipGap") + "</div>"
            )
        if unverified:
            body += (
                '<div class="row"><span class="k">未验证要求：</span>'
                + _chips_html(unverified, "chipWarn") + "</div>"
            )
        sections.append(
            '<div class="sec"><div class="secTitle">缺口与未验证</div>'
            '<div class="card"><div class="cardIn">'
            + body + "</div></div></div>"
        )

    for key, label in (
        ("JD要求分层", "JD 要求分层"),
        ("加分项命中", "加分项命中"),
        ("加分项缺口", "加分项缺口"),
        ("简历证据", "简历证据"),
        ("筛选原因", "筛选结果"),
        ("技能匹配诊断", "标签诊断（仅供参考）"),
        ("本地预判", "本地预判（仅供参考）"),
    ):
        text = str(row.get(key, "")).strip()
        if text:
            sections.append(
                f'<div class="sec"><div class="secTitle">{label}</div>'
                '<div class="card"><div class="cardIn">'
                f'<div class="row">{_escape_lines(text)}</div></div></div></div>'
            )

    if not sections:
        sections.append(
            '<div class="sec"><div class="card"><div class="cardIn">'
            '<div class="muted">暂无其他评估证据</div></div></div></div>'
        )
    return _DETAIL_STYLE + _join_sections(sections)
