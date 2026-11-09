# -*- coding: utf-8 -*-
"""结果落盘（增量写入，随时中断不丢已评结果）。
ResultRecorder 为混入类，依赖宿主提供的 self.results / self._saved_count / self.cfg。"""
import os
import csv
import time
import shutil
import tempfile

from delivery_config import RESULT_FIELDS
from prefilter import _format_jd_requirements


class ResultRecorder:
    """结果行构造与 CSV 落盘混入（AutoDeliverer 继承使用）。"""

    @staticmethod
    def _load_processed_job_ids(path, *, dry_run):
        """历史已完成结果参与跨轮去重；失败记录可重试，干跑仍可转正式投递。"""
        completed = {
            "delivered", "already_contacted", "below_threshold", "out_of_scope",
            "prefilter_reject", "role_reject", "role_rejected", "condition_rejected",
            "area_rejected", "hard_rejected", "local_gate_rejected",
        }
        if dry_run:
            completed.update({"dry_run", "dry_run_ready"})
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                return {
                    job_id
                    for row in csv.DictReader(f)
                    if (job_id := str(row.get("encryptJobId") or "").strip())
                    and str(row.get("投递状态") or "").strip().lower() in completed
                }
        except FileNotFoundError:
            return set()
        except (OSError, UnicodeError, csv.Error) as exc:
            raise OSError(f"历史结果无法读取，已停止任务以避免重复处理: {path}") from exc

    # ---------- 结果落盘（增量写入，随时中断不丢已评结果） ----------
    def _record(self, row: dict):
        """记一条结果并立刻落盘。"""
        self.results.append(row)
        self.save_results()

    def save_results(self):
        pending = self.results[self._saved_count:]
        if not pending:
            return
        path = self.cfg["result_file"]
        exists = os.path.isfile(path)
        if exists:  # 表头变化时备份并迁移历史行，避免丢失结果或错列
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    header = next(csv.reader(f), [])
                if header != RESULT_FIELDS:
                    self._migrate_result_file(path)
                    exists = True
            except OSError as exc:
                raise OSError(f"结果文件无法读取或迁移，已停止写入: {path}") from exc
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerows(pending)
        self._saved_count = len(self.results)
        print(f"[结果] 已累计保存 {self._saved_count} 条到 {path}")

    @staticmethod
    def _migrate_result_file(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            old_rows = list(csv.DictReader(f))

        timestamp = time.strftime("%Y%m%d%H%M%S")
        backup = f"{path}.{timestamp}.bak"
        suffix = 1
        while os.path.exists(backup):
            backup = f"{path}.{timestamp}.{suffix}.bak"
            suffix += 1
        shutil.copy2(path, backup)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="", delete=False,
                dir=os.path.dirname(os.path.abspath(path)),
            ) as f:
                temp_path = f.name
                writer = csv.DictWriter(
                    f, fieldnames=RESULT_FIELDS, extrasaction="ignore"
                )
                writer.writeheader()
                for old in old_rows:
                    row = {field: old.get(field, "") for field in RESULT_FIELDS}
                    if "匹配分数" in old:
                        if old.get("投递状态") == "prefilter_reject":
                            row["预筛命中率"] = old.get("匹配分数", "")
                            row["技能匹配诊断"] = old.get(
                                "AI匹配理由", ""
                            ).removeprefix("预筛未通过: ")
                            row["AI匹配理由"] = ""
                        else:
                            row["AI匹配分数"] = old.get("匹配分数", "")
                    writer.writerow(row)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            print(f"[结果] 历史记录已迁移，原文件备份为 {os.path.basename(backup)}")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _result_row(job, score, reason, status, greeting="", filter_reason="",
                    match_data=None):
        match_data = match_data or {}
        def join_match_field(name):
            value = match_data.get(name, "")
            if isinstance(value, list):
                return "；".join(str(item) for item in value)
            return value

        jd_requirements = match_data.get("jd_requirements", "")
        if isinstance(jd_requirements, dict):
            jd_requirements = _format_jd_requirements(jd_requirements)

        return {
            "encryptJobId": job.get("encryptJobId", ""),
            "工作名称": job.get("工作名称", ""),
            "公司": job.get("公司", ""),
            "工资": job.get("工资", ""),
            "区域": job.get("区域", ""),
            "上班时间": job.get("上班时间", ""),
            "休息制度": job.get("休息制度", ""),
            "工作性质": job.get("工作性质", ""),
            "预筛命中率": "",
            "技能匹配诊断": job.get("技能匹配诊断", ""),
            "本地预判": job.get("本地预判", ""),
            "AI匹配分数": score,
            "AI匹配理由": reason,
            "JD要求分层": jd_requirements,
            "硬性缺口": join_match_field("hard_gaps"),
            "未验证要求": join_match_field("unverified_requirements"),
            "加分项命中": join_match_field("preferred_matches"),
            "加分项缺口": join_match_field("preferred_gaps"),
            "简历证据": join_match_field("evidence"),
            "打招呼语": greeting,
            "投递状态": status,
            "投递时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "详情链接": job.get("详情链接", ""),
            "筛选原因": "；".join(filter(None, [
                filter_reason, str(job.get("筛选观察", "") or ""),
            ])),
            "人工标记": job.get("人工标记", ""),
            "主岗位画像": match_data.get("primary_profile", ""),
            "岗位画像评估详情": match_data.get("profile_results", ""),
            "职业范围状态": job.get("职业范围状态", ""),
            "搜索来源关键词": "；".join(job.get("搜索来源关键词", []))
                if isinstance(job.get("搜索来源关键词", []), list)
                else job.get("搜索来源关键词", ""),
            "来源岗位画像": "；".join(job.get("来源岗位画像", []))
                if isinstance(job.get("来源岗位画像", []), list)
                else job.get("来源岗位画像", ""),
        }
