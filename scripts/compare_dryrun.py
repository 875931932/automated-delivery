"""只读统计脚本：汇总自动投递结果 CSV 的筛选漏斗与 AI 分数分布，用于优化前后对比。

用法：
    python scripts/compare_dryrun.py deliver_results.csv [more.csv ...]
"""
import csv
import sys
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    print(f"\n=== {path.name} ===")
    if not rows:
        print("（空文件）")
        return

    print(f"总记录数: {len(rows)}")

    status = Counter(row.get("投递状态", "") or "(空)" for row in rows)
    print("投递状态分布:")
    for key, count in status.most_common():
        print(f"  {key}: {count}")

    scope = Counter(row.get("职业范围状态", "") or "(无)" for row in rows)
    if any(key != "(无)" for key in scope):
        print("职业范围状态分布:")
        for key, count in scope.most_common():
            print(f"  {key}: {count}")

    scores = []
    for row in rows:
        raw = str(row.get("AI匹配分数", "") or "").strip()
        try:
            scores.append(float(raw))
        except ValueError:
            pass
    if scores:
        scores.sort()
        mean = sum(scores) / len(scores)
        p50 = scores[len(scores) // 2]
        below = sum(1 for s in scores if s < 70)
        print(
            f"AI 分数: n={len(scores)} min={scores[0]:.0f} p50={p50:.0f} "
            f"max={scores[-1]:.0f} mean={mean:.1f} | <70 占比 {below}/{len(scores)}"
        )
    else:
        print("AI 分数: 无有效记录")

    ai_called = sum(1 for row in rows if str(row.get("AI匹配分数", "")).strip())
    print(f"AI 实际评分记录数: {ai_called}")

    reasons = Counter(
        (row.get("筛选原因", "") or "").split("（")[0][:30]
        for row in rows if (row.get("筛选原因", "") or "").strip()
    )
    if reasons:
        print("筛选原因分布:")
        for key, count in reasons.most_common(10):
            print(f"  {key}: {count}")


def main() -> None:
    paths = [Path(arg) for arg in sys.argv[1:]]
    if not paths:
        print(__doc__)
        sys.exit(1)
    for path in paths:
        if not path.exists():
            print(f"[跳过] 文件不存在: {path}")
            continue
        summarize(path)


if __name__ == "__main__":
    main()
