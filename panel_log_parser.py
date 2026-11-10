# -*- coding: utf-8 -*-
"""运行日志行解析（纯函数，供日志页着色/过滤/状态区使用）。

识别 auto_deliver.py 输出的行前缀：
  [筛选统计] / [岗位 n/m | 本轮第k个] / [优先队列 n/m | ...] / [AI]
  [跳过] [过滤] [硬性过滤] [本地拦截] [范围待复核] [职能影子] 等过滤类
  [结果] / 错误（traceback、失败、异常）
"""
import re

# 行类别常量
CATEGORY_AI = "ai"            # AI 评分/招呼语
CATEGORY_FILTER = "filter"    # 跳过 / 过滤 / 拦截 / 待复核 / 影子
CATEGORY_ERROR = "error"      # 失败 / 异常 / traceback
CATEGORY_RESULT = "result"    # [结果] 落盘
CATEGORY_JOB = "job"          # [岗位 n/m] 当前岗位进度
CATEGORY_STATS = "stats"      # [筛选统计]
CATEGORY_NORMAL = "normal"    # 其他

# 类别 -> 日志着色（深色日志区上的前景色）
CATEGORY_COLORS = {
    CATEGORY_AI: "#7DD3FC",      # 蓝
    CATEGORY_FILTER: "#FBBF24",  # 黄
    CATEGORY_ERROR: "#F87171",   # 红
    CATEGORY_RESULT: "#34D399",  # 绿
    CATEGORY_JOB: "#E2E8F0",
    CATEGORY_STATS: "#A5B4FC",
    CATEGORY_NORMAL: "#94A3B8",  # 灰
}

FILTER_TAGS = (
    "[跳过]", "[过滤]", "[硬性过滤]", "[本地拦截]", "[范围待复核]", "[职能影子]",
    "[区域过滤]", "[条件过滤]", "[职能预筛]", "[本地预判]", "[经验观察]",
)

_ERROR_MARKERS = (
    "traceback", "程序异常", "配置错误", "失败", "异常", "错误", "error", "exception",
    "[平台限制]",
)

_JOB_LINE_RE = re.compile(
    r"^\s*\[(?:岗位|优先队列)\s*(\d+)\s*/\s*(\d+)\s*\|\s*本轮第(\d+)个\]\s*(.*)$"
)
_AI_SCORE_RE = re.compile(r"\[AI\][^0-9]*(?:最高评估|匹配分)[:\s]*(\d+(?:\.\d+)?)")
_STATS_SEGMENT_RE = re.compile(r"^(.+?)\s+(\d+)$")


def classify_log_line(line: str) -> str:
    """返回日志行类别常量。"""
    text = (line or "").strip()
    if not text:
        return CATEGORY_NORMAL
    if text.startswith("[筛选统计]"):
        return CATEGORY_STATS
    if "[AI]" in text:
        return CATEGORY_AI
    if "[结果]" in text:
        return CATEGORY_RESULT
    if parse_job_line(text) is not None:
        return CATEGORY_JOB
    if any(tag in text for tag in FILTER_TAGS):
        return CATEGORY_FILTER
    lowered = text.lower()
    if "traceback" in lowered or any(marker in lowered for marker in _ERROR_MARKERS):
        return CATEGORY_ERROR
    return CATEGORY_NORMAL


def parse_job_line(line: str) -> dict | None:
    """解析 `[岗位 n/m | 本轮第k个] 性质 | 名称 | 公司` 行。

    返回 {"index": n, "total": m, "round": k, "type": ..., "name": ..., "company": ...}；
    不是岗位行时返回 None。
    """
    match = _JOB_LINE_RE.match(line or "")
    if not match:
        return None
    index, total, round_no, rest = match.groups()
    parts = [part.strip() for part in rest.split("|")]
    return {
        "index": int(index),
        "total": int(total),
        "round": int(round_no),
        "type": parts[0] if len(parts) > 0 else "",
        "name": parts[1] if len(parts) > 1 else "",
        "company": parts[2] if len(parts) > 2 else "",
    }


def parse_ai_score(line: str) -> float | None:
    """从 `[AI] 最高评估 85 | ...` / `[AI] 匹配分: 72.5 | ...` 提取得分。"""
    match = _AI_SCORE_RE.search(line or "")
    if not match:
        return None
    return float(match.group(1))


def parse_filter_stats(line: str) -> dict | None:
    """解析 `[筛选统计] 列表岗位 10 | ... | 投递成功 2` 为 {标签: 计数}。"""
    text = (line or "").strip()
    if not text.startswith("[筛选统计]"):
        return None
    counts = {}
    for segment in text[len("[筛选统计]"):].split("|"):
        segment = segment.strip()
        if not segment:
            continue
        item = _STATS_SEGMENT_RE.match(segment)
        if item:
            counts[item.group(1).strip()] = int(item.group(2))
    return counts
