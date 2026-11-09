# -*- coding: utf-8 -*-
"""
BOSS 直聘自动投递程序
复用 boss_spider.py 的 BossDP（浏览器环境、登录态与被动心跳），新增：
  1. AI 岗位匹配：简历 vs JD 打分，低于阈值不投
  2. AI 生成个性化打招呼语
  3. 浏览器自动投递：打开详情 -> 立即沟通 -> 发送打招呼语
  4. 每日投递上限（可配置，跨重启持久化）
"""
from process_runtime import configure_quiet_processes

configure_quiet_processes()

if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from release_check import run_release_check
        raise SystemExit(run_release_check(sys.argv[2], gui=False))

import re
import json
import time
import random
from urllib.parse import parse_qs, urlparse

from candidate_profiles import CandidateProfile, CandidateProfileStore, ResumeDigestStore
from ai_chains import JobMatchResponse, JobScoringChain
from job_profiles import (
    DEFAULT_SCREENING_RULES_PATH,
    JobProfile,
    JobProfileStore,
    build_unique_queries,
    eligible_profiles,
    load_screening_rules,
)

from boss_spider import (
    BossDP,
    Config as SpiderConfig,
    JOB_TYPE_CODES,
    build_job_search_url,
    resolve_platform_area_codes,
)

# ---------- 拆分模块 re-export（保持 auto_deliver 命名空间兼容） ----------
from delivery_config import (
    DELIVER_CONFIG,
    RESULT_FIELDS,
    apply_search_settings,
    configure_platform_search,
    load_matching_config,
)
from prefilter import (
    LANGUAGE_TAGS,
    ROLE_RULES,
    SCOPE_SYNONYMS,
    SKILL_SYNONYMS,
    _explicit_absence_for_requirement,
    _extract_ordered_skill_tags,
    _format_jd_requirements,
    _format_resume_evidence,
    _matching_resume_lines,
    _normalize_scope_text,
    _primary_duty_text,
    _requirement_item,
    _resume_evidence_level,
    _scope_term_variants,
    _scope_text_hits,
    _skill_key_in_text,
    choose_primary_assessment,
    classify_job_scope,
    classify_jd_requirements,
    exp_soft_banded,
    extract_resume_evidence,
    extract_skill_tags,
    extract_work_info,
    hard_reject,
    local_feasibility,
    need_company_welfare,
    role_function_reject,
    to_minutes,
    work_condition_reject,
)
from ai_client import AIClient, _truncate_reason
from delivery_tracker import DeliveryTracker
from result_store import ResultRecorder
from job_type_logic import effective_job_type_preference


# ========================= 自动投递主类 =========================
class AutoDeliverer(BossDP, ResultRecorder):
    """继承 BossDP，复用浏览器/登录态/被动心跳，新增投递流程。"""

    def __init__(self, deliver_cfg: dict, matching_context: dict | None = None):
        matching_context = matching_context or load_matching_config(deliver_cfg)
        resume_text = self._load_resume(deliver_cfg["resume_file"])
        if not resume_text.strip() or resume_text == "（未提供简历）":
            raise ValueError("简历文件不可用，已在启动浏览器前停止。")
        history_ids = self._load_processed_job_ids(
            deliver_cfg["result_file"], dry_run=deliver_cfg["dry_run"],
        )
        super().__init__()
        self.seen_job_ids.update(history_ids)
        print(f"[去重] 已载入历史已处理岗位 {len(history_ids)} 个")
        self.cfg = deliver_cfg
        self.matching_context = matching_context
        # profile_mode=True 启用 _run_profiled_pipeline（支持多画像、范围过滤、降级重试）。
        # 基础模式（无候选人画像）与增强模式（已确认画像）均走此路径，差异由
        # matching_context["base_mode"] 决定，不需要手动切换此开关。
        self.profile_mode = True
        self.tracker = DeliveryTracker(deliver_cfg["log_file"])
        self.ai = AIClient(deliver_cfg)
        self.scoring_chain = JobScoringChain()
        self.resume_text = resume_text
        self.scoring_resume_prompt = self._scoring_resume_prompt(resume_text)
        self.results = []
        self._saved_count = 0  # 已落盘的结果条数（增量写入用）
        self.deliver_count = 0
        self.stage_counts = {
            "duplicate_rejected": 0,
            "irrelevant_rejected": 0,
            "blacklist_rejected": 0,
            "already_done": 0,
            "already_contacted": 0,
            "detail_unavailable": 0,
            "condition_rejected": 0,
            "role_rejected": 0,
            "out_of_scope": 0,
            "scope_review": 0,
            "eligible_for_ai": 0,
            "ai_called": 0,
            "ai_scored": 0,
            "match_failed": 0,
            "below_threshold": 0,
            "greeting_generated": 0,
            "greeting_failed": 0,
            "dry_run_ready": 0,
            "delivery_attempted": 0,
            "delivered": 0,
        }
        # 拟人浏览只在主流程的安全节点执行。
        self.humanize_enabled = deliver_cfg["humanize_enable"]
        self.match_scores = {}   # 岗位名 -> AI 匹配分
        self.company_welfare_cache = {}   # 公司主页URL -> 工作时间及福利文本
        self._detail_tab = None   # 复用的详情页标签（后台标签，避免每开一个岗位就弹窗）
        self._human_browse_job_list = []

    @staticmethod
    def _load_resume(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            print(f"简历文件读取失败({path}): {exc}\n将使用空简历（AI匹配会失真）")
            return "（未提供简历）"

    @staticmethod
    def _scoring_resume_prompt(resume_text: str) -> str:
        """评分提示词优先使用简历结构化摘要（逐字摘录）；证据引用校验始终对照简历原文。"""
        try:
            digest = ResumeDigestStore().load_for(resume_text)
            return digest.prompt_text() if digest else resume_text
        except Exception:
            return resume_text

    # ---------- 工作时间/休息制度筛选（规则实现在 prefilter，类内保留原名委托） ----------
    @staticmethod
    def _to_minutes(text):
        return to_minutes(text)

    @classmethod
    def _extract_work_info(cls, text):
        return extract_work_info(text)

    def _need_company_welfare(self, jd_text: str) -> bool:
        return need_company_welfare(jd_text, self.cfg)

    def _work_condition_reject(self, jd_text: str):
        return work_condition_reject(jd_text, self.cfg)

    # ---------- 岗位画像诊断关键词对照（不参与筛选或 AI 评分） ----------
    @staticmethod
    def _hard_reject(job, hard_limit=5, soft_limit=3):
        return hard_reject(job, hard_limit=hard_limit, soft_limit=soft_limit)

    @staticmethod
    def _exp_soft_banded(job, hard_limit=5, soft_limit=3):
        return exp_soft_banded(job, hard_limit=hard_limit, soft_limit=soft_limit)

    def _prioritize_jobs_by_type(self, jobs):
        """Stable ordering only: unknown and non-target jobs remain in the queue."""
        preferred = effective_job_type_preference(
            self.cfg.get("platform_job_type", "不限"),
            self.cfg.get("job_type_preference", "实习"),
        )
        if preferred is None:
            return list(jobs)
        other = "全职" if preferred == "实习" else "实习"
        rank = {preferred: 0, other: 1}
        return sorted(
            jobs,
            key=lambda job: rank.get(job.get("工作性质", "待确认"), 2),
        )

    def _diagnose_profile_terms(self, job_data):
        """Show profile-owned evidence terms only; never calculate a global skill score."""
        jd_text = ' '.join(filter(None, (
            job_data.get('工作名称', ''),
            job_data.get('技术要求', ''),
            job_data.get('工作介绍', ''),
        )))
        profiles = getattr(self, "matching_context", {}).get("profiles", [])
        terms = list(dict.fromkeys(
            term for profile in profiles for term in profile.diagnostic_terms
        ))
        if not terms:
            return None, "岗位画像未配置诊断关键词；不计算通用技能重合率"
        resume = str(getattr(self, "resume_text", "") or "")
        jd_hits = [term for term in terms if _scope_text_hits(jd_text, term)]
        resume_hits = [term for term in terms if _scope_text_hits(resume, term)]
        return None, (
            f"画像诊断关键词: {', '.join(terms)} | "
            f"JD出现: {', '.join(jd_hits) or '未出现'} | "
            f"简历出现: {', '.join(resume_hits) or '未出现'}；"
            "仅供查看，不代表硬性缺口或匹配分"
        )

    @staticmethod
    def _role_function_reject(job_data):
        return role_function_reject(job_data)

    def _count_stage(self, stage, amount=1):
        counts = getattr(self, "stage_counts", None)
        if counts is None:
            self.stage_counts = counts = {}
        counts[stage] = counts.get(stage, 0) + amount

    def _print_stage_summary(self):
        labels = (
            ("jobs_listed", "列表岗位"),
            ("duplicate_rejected", "重复岗位（含历史结果）"),
            ("irrelevant_rejected", "关键词不相关"),
            ("blacklist_rejected", "黑名单公司"),
            ("already_done", "今日已处理"),
            ("already_contacted", "平台已沟通"),
            ("hard_rejected", "学历/年限拦截"),
            ("exp_soft_banded", "年限软区间放行"),
            ("area_rejected", "区域拦截"),
            ("candidate_ready", "通过列表筛选"),
            ("detail_unavailable", "详情不可用"),
            ("condition_rejected", "作息条件拦截"),
            ("role_rejected", "岗位职能拦截"),
            ("role_shadowed", "职能影子命中"),
            ("out_of_scope", "确认范围外"),
            ("scope_review", "职业范围待复核"),
            ("scope_review_ai_called", "待复核进AI"),
            ("scope_review_delivered", "待复核可投"),
            ("eligible_for_ai", "进入AI评分"),
            ("local_gate_conflict", "本地预判冲突"),
            ("local_gate_rejected", "本地拦截"),
            ("ai_called", "AI实际调用"),
            ("ai_retry_single_profile", "单画像降级重试"),
            ("ai_scored", "AI评分完成"),
            ("match_failed", "AI调用失败"),
            ("below_threshold", "低于分数线"),
            ("greeting_generated", "生成招呼语"),
            ("greeting_failed", "招呼生成失败"),
            ("dry_run_ready", "干跑可投预览"),
            ("delivery_attempted", "真实投递尝试"),
            ("delivered", "投递成功"),
        )
        counts = getattr(self, "stage_counts", {})
        summary = " | ".join(
            f"{label} {counts.get(key, 0)}" for key, label in labels
        )
        print(f"[筛选统计] {summary}")

    # ---------- 岗位收集：复用爬虫的 API 与过滤 ----------
    def api_job_detail(self, security_id, job_id=""):
        """复用爬虫详情接口，但 referer 指向对应职位详情页，更贴近真实浏览行为"""
        request_headers = None
        if job_id:
            request_headers = {
                "referer": f"{SpiderConfig['base_url']}/job_detail/{job_id}.html",
            }
        return super().api_job_detail(
            security_id=security_id, request_headers=request_headers,
        )

    def _filter_jobs(self, job_list):
        """单页轻量筛选：去重/相关/黑名单/已处理/区域，不做详情抓取。
        返回候选岗位列表，详情在 _prepare_job 里按需拉取（避免上限触发后白抓一堆详情）。"""
        self._count_stage("jobs_listed", len(job_list))
        fresh = [j for j in job_list
                 if j.get('encryptJobId') not in self.seen_job_ids]
        duplicates = len(job_list) - len(fresh)
        self._count_stage("duplicate_rejected", duplicates)
        if duplicates:
            print(f"[去重] 本页跳过 {duplicates} 个已处理岗位（含历史结果）")
        profile_mode = getattr(self, "profile_mode", False)
        relevant = fresh if profile_mode else [
            j for j in fresh if self.is_relevant(j.get('jobName'), j.get('skills'))
        ]
        self._count_stage("irrelevant_rejected", len(fresh) - len(relevant))
        print(f"[采集] 本页候选岗位 {len(relevant)}/{len(job_list)}")

        candidates = []
        for job in relevant:
            job_id = job.get('encryptJobId')
            company = job.get('brandName', '')
            if self._is_blacklisted_company(company) or \
                    self._is_truncated_name(company):
                self._count_stage("blacklist_rejected")
                continue
            if self.tracker.already_done(job_id):
                print(f"  [跳过] 今日已处理: {job.get('jobName', '')}")
                self._count_stage("already_done")
                continue

            if not profile_mode:
                # Legacy mode retains its global education and experience gates.
                # Profile mode leaves these role-dependent requirements to AI scoring.
                hard_reason = self._hard_reject(
                    job,
                    hard_limit=self.cfg.get("experience_hard_limit", 5),
                    soft_limit=self.cfg.get("experience_soft_limit", 3),
                )
                if hard_reason:
                    print(f"  [硬性过滤] {job.get('jobName', '')}: {hard_reason}")
                    self._count_stage("hard_rejected")
                    self.seen_job_ids.add(job_id)
                    continue
                soft_note = self._exp_soft_banded(
                    job,
                    hard_limit=self.cfg.get("experience_hard_limit", 5),
                    soft_limit=self.cfg.get("experience_soft_limit", 3),
                )
                if soft_note:
                    print(f"  [经验观察] {job.get('jobName', '')}: {soft_note}")
                    self._count_stage("exp_soft_banded")

            # 区域筛选（行政区/商圈，多个关键词任一命中即通过；无区域信息时放行）
            city_name = str(job.get('cityName', '') or '')
            district_text = ' '.join(filter(None, (
                str(job.get('areaDistrict', '') or ''),
                str(job.get('businessDistrict', '') or ''),
            )))
            area_text = f"{city_name} {district_text}".strip()
            if self.cfg["area_filter"] and district_text and \
                    not any(k in district_text for k in self.cfg["area_filter"]):
                print(f"  [区域过滤] {job.get('jobName', '')} ({district_text})")
                self._count_stage("area_rejected")
                self.seen_job_ids.add(job_id)
                continue

            candidates.append({
                'encryptJobId': job_id,
                'securityId': job.get('securityId', ''),
                '工作名称': job.get('jobName', ''),
                '工资': job.get('salaryDesc', ''),
                '公司': company,
                '区域': area_text.strip(),
                '学历要求': job.get('jobDegree', ''),
                '工作经验要求': job.get('jobExperience', ''),
                '工作性质': self._classify_job_type(job),
                '技术要求': self._format_list(job.get('skills', [])),
                '工作介绍': '',
                '详情链接': f"https://www.zhipin.com/job_detail/{job_id}.html",
            })
            self._count_stage("candidate_ready")
        return candidates

    def _prepare_job(self, job_data):
        """按需拉取详情页 + 公司福利并做条件筛选。通过返回 True，被过滤返回 False。
        只有真正轮到处理（未超本轮上限/每日上限）的岗位才会走到这里。"""
        job_id = job_data['encryptJobId']
        if self.cfg.get("welfare_require"):
            # 期望福利作为 AI 评分的加分参考（平台 API 无福利筛选参数，只做软匹配）
            job_data["期望福利"] = "、".join(self.cfg["welfare_require"])
        info = self._fetch_jd_dom(job_data)
        if info.get("already_contacted"):
            print(f"  [跳过] 平台已沟通: {job_data.get('工作名称', '')}")
            self.seen_job_ids.add(job_id)
            self._count_stage("already_contacted")
            self._record(self._result_row(
                job_data, "", "", "already_contacted",
                filter_reason="平台显示已沟通或继续沟通，已跳过评分和招呼语生成",
            ))
            self.tracker.mark(
                job_id, job_data.get("工作名称", ""), "", "already_contacted",
                count_delivery=False,
            )
            return False
        desc, skills = info['desc'], info['skills']
        welfare_tags = info['welfare_tags']
        company_url = info['company_url']
        if desc:
            job_data['工作介绍'] = desc
            if skills:
                job_data['技术要求'] = "; ".join(skills) or job_data['技术要求']
        else:
            # 详情拿不到就直接跳过，不原地冷却（调研结论：别硬刚风控）
            print("  [详情] DOM 获取失败，跳过该岗位")
            self._count_stage("detail_unavailable")
            return False
        job_data["工作性质"] = self._classify_job_type(job_data)
        if welfare_tags:  # 详情页顶部福利标签（可能直接含「双休」）
            job_data['公司福利'] = "; ".join(welfare_tags)
            job_data['工作介绍'] += f"\n【公司福利标签】{job_data['公司福利']}"

        role_reason = (
            None if getattr(self, "profile_mode", False)
            else self._role_function_reject(job_data)
        )
        if role_reason:
            if self.cfg.get("role_reject_shadow", False):
                # 影子模式：只记录不拦截，观察误杀面后再决定收紧或恢复拦截
                note = f"role_rule_shadow: {role_reason}"
                print(f"  [职能影子] {job_data['工作名称']}: {note}（仅记录不拦截）")
                self._count_stage("role_shadowed")
                job_data["筛选观察"] = note
            else:
                print(f"  [职能预筛] {job_data['工作名称']}: {role_reason}")
                self.seen_job_ids.add(job_id)
                self._count_stage("role_rejected")
                self._record(self._result_row(
                    job_data, "", "", "role_reject", filter_reason=role_reason
                ))
                return False
        time.sleep(random.uniform(1.0, 2.5))

        # 公司主页「工作时间及福利」卡片（双休/上班时间不一定写在JD里）
        # JD 里已经能判断作息和休息制度时跳过公司页，省一半浏览时间
        if company_url and self._need_company_welfare(job_data.get('工作介绍', '')):
            welfare = self._fetch_company_welfare(company_url)
            if welfare:
                job_data['工作介绍'] += f"\n【工作时间及福利】{welfare}"
        elif not company_url:
            print("  [福利] 未找到公司主页链接，跳过公司福利")

        # 提取作息时间与休息制度（用于结果导出展示）
        work_time, rest_day = self._extract_work_info(
            job_data.get('工作介绍', ''))
        job_data['上班时间'] = work_time
        job_data['休息制度'] = rest_day

        # 工作时间/休息制度筛选（基于详情 JD 文本）
        reject_reason = self._work_condition_reject(
            job_data.get('工作介绍', ''))
        if reject_reason:
            print(f"  [条件过滤] {job_data['工作名称']}: {reject_reason}")
            self.seen_job_ids.add(job_id)
            self._count_stage("condition_rejected")
            return False

        self.seen_job_ids.add(job_id)
        self._count_stage("eligible_for_ai")
        return True

    # ---------- 详情 DOM 获取（替代详情接口，避免触发风控） ----------
    @staticmethod
    def _job_contact_buttons(tab):
        """只查看当前职位主操作区和吸顶操作区的沟通按钮。"""
        locate = getattr(tab, "eles", None)
        if not callable(locate):
            return []
        try:
            return list(locate(
                "css:.job-op .btn-startchat, .detail-op .btn-startchat, "
                ".job-op .op-btn-chat, .detail-op .op-btn-chat, "
                ".job-op a, .detail-op a, .job-op button, .detail-op button, "
                ".job-op [role='button'], .detail-op [role='button'], "
                ".job-detail-op .btn-startchat, .job-detail-op .op-btn-chat, "
                ".job-detail-op a, .job-detail-op button, .job-detail-op [role='button']",
                timeout=1,
            ) or [])
        except (TimeoutError, InterruptedError):
            raise
        except Exception:
            return []

    @staticmethod
    def _button_targets_job(button, job_id):
        if not job_id:
            return True
        attr = getattr(button, "attr", None)
        redirect = str((attr("redirect-url") or attr("data-url") or attr("href") or "")
                       if callable(attr) else "")
        target = urlparse(redirect)
        params = parse_qs(target.query)
        target_ids = params.get("jobId") or params.get("encryptJobId") or []
        if not target_ids:
            match = re.fullmatch(r"/job_detail/([^/]+)\.html", target.path)
            if match:
                target_ids = [match.group(1)]
        return not target_ids or target_ids[0] == job_id

    @staticmethod
    def _contact_button_state(button):
        attr = getattr(button, "attr", None)
        friend = str(attr("data-isfriend") or "").strip().lower() if callable(attr) else ""
        text = re.sub(r"\s+", "", str(getattr(button, "text", "") or ""))
        if friend in {"true", "1"} or text in {"继续沟通", "已沟通", "已沟通过", "沟通过"}:
            return "already_contacted"
        if text == "立即沟通":
            return "new_contact"
        return "unknown"

    @classmethod
    def _job_contact_state(cls, tab, job_id):
        states = [
            cls._contact_button_state(button)
            for button in cls._job_contact_buttons(tab)
            if cls._button_targets_job(button, job_id)
        ]
        if "already_contacted" in states:
            return "already_contacted"
        return "new_contact" if "new_contact" in states else "unknown"

    def _detail_tab_get(self, url: str):
        """复用同一个后台标签页导航，避免每个岗位都新建标签并抢焦点（窗口反复弹出）。"""
        self._resume_browser_if_needed()
        if self._detail_tab is not None:
            try:
                self._detail_tab.get(url)
                if self._check_browser_attention(self._detail_tab):
                    self._detail_tab = self.page.new_tab(url, background=True)
                return self._detail_tab
            except (TimeoutError, InterruptedError):
                raise
            except Exception:
                self._detail_tab = None
        try:
            self._detail_tab = self.page.new_tab(url, background=True)
            if self._check_browser_attention(self._detail_tab):
                self._detail_tab = self.page.new_tab(url, background=True)
            return self._detail_tab
        except (TimeoutError, InterruptedError):
            raise
        except Exception as exc:
            print(f"  [详情] 打开标签页失败: {exc}")
            self._detail_tab = None
            return None

    def _fetch_jd_dom(self, job: dict):
        """新标签页打开详情页，从 DOM 读取职位描述、技能标签、福利标签、公司主页链接。
        模拟真实用户浏览行为，稳定不触发「环境异常」。"""
        url = job["详情链接"]
        if job.get("securityId"):
            url += f"?securityId={job['securityId']}"
        tab = None
        try:
            with self.browser_lock:
                tab = self._detail_tab_get(url)
                if tab is None:
                    return {'desc': '', 'skills': [], 'welfare_tags': [], 'company_url': ''}
                try:
                    tab.wait.doc_loaded(timeout=15)
                except Exception:
                    pass
                if self._job_contact_state(tab, job.get("encryptJobId", "")) == "already_contacted":
                    return {"already_contacted": True}
                dwell_range = self.cfg.get("detail_delay", (3, 6))
                time.sleep(random.uniform(*dwell_range))  # 模拟阅读详情
                if self._job_contact_state(tab, job.get("encryptJobId", "")) == "already_contacted":
                    return {"already_contacted": True}

                desc = ''
                desc_ele = (tab.ele('.job-sec-text', timeout=6)
                            or tab.ele('.job-detail-section', timeout=3))
                if desc_ele:
                    desc = self._clean_text(desc_ele.text)

                # 技能标签：旧版 .job-keyword-list，新版结构多变，多选择器兜底
                # 注意：DrissionPage 原生语法不认 CSS 属性/后代选择器，必须加 css: 前缀
                skills = []
                for sel in ('css:.job-keyword-list li',
                            'css:.job-detail-section .tag-list li',
                            'css:.job-advantage span'):
                    for ele in tab.eles(sel, timeout=1):
                        t = (ele.text or '').strip()
                        if t and len(t) <= 15 and t not in skills:
                            skills.append(t)
                    if skills:
                        break

                # 福利标签（详情页顶部 .job-tags，如「双休、五险一金、带薪年假」）
                welfare_tags = []
                for ele in tab.eles('css:.job-tags span', timeout=2):
                    t = (ele.text or '').strip()
                    if t and len(t) <= 15 and t not in welfare_tags:
                        welfare_tags.append(t)

                # 公司主页链接：优先「公司主页」专用入口，排除 /gongsi/job/（那是公司职位列表页）
                company_url = ''
                link = tab.ele('css:a[ka="job-detail-company_custompage"]', timeout=3)
                if not link:
                    for a in tab.eles('css:a[href*="/gongsi/"]', timeout=3):
                        href = (a.attr('href') or '').strip()
                        href = re.sub(r'^https?://[^/]+', '', href)  # 去掉域名前缀
                        if re.match(r'^/gongsi/[^/]+\.html', href):
                            link = a
                            break
                if link:
                    company_url = (link.attr('href') or '').strip()
                    company_url = re.sub(r'^https?://[^/]+', '', company_url)
                    if company_url.startswith('/'):
                        company_url = SpiderConfig['base_url'] + company_url

                # 沟通状态可能晚于职位正文渲染，返回 AI 流程前再确认一次。
                if self._job_contact_state(tab, job.get("encryptJobId", "")) == "already_contacted":
                    return {"already_contacted": True}
                if desc:
                    print(f"  [详情] DOM 获取成功（{len(desc)} 字，技能 {len(skills)} 个，"
                          f"福利 {len(welfare_tags)} 个）")
                return {
                    'desc': desc, 'skills': skills,
                    'welfare_tags': welfare_tags, 'company_url': company_url,
                }
        except (TimeoutError, InterruptedError):
            raise
        except Exception as exc:
            print(f"  [详情] DOM 获取异常: {exc}")
            return {'desc': '', 'skills': [], 'welfare_tags': [], 'company_url': ''}

    def _fetch_company_welfare(self, company_url: str) -> str:
        """打开公司主页，读取「工作时间及福利」卡片文本（含双休/上班时间/福利）。
        双休和上班时间不一定写在 JD 里，多在这里；按公司缓存，失败返回空串。"""
        if company_url in self.company_welfare_cache:
            return self.company_welfare_cache[company_url]
        tab = None
        try:
            with self.browser_lock:
                tab = self._detail_tab_get(company_url)
                if tab is None:
                    return ''
                try:
                    tab.wait.doc_loaded(timeout=15)
                except Exception:
                    pass
                time.sleep(random.uniform(*self.cfg["detail_delay"]))  # 模拟浏览公司页
                # 公司页部分卡片懒加载，轻滚几下再取文本
                try:
                    tab.scroll.down(400)
                    time.sleep(random.uniform(0.6, 1.2))
                    tab.scroll.down(400)
                    time.sleep(random.uniform(0.6, 1.2))
                except Exception:
                    pass
                body = tab.ele('tag:body', timeout=5)
                page_text = body.text if body else ''
                snippet = ''
                # 精确结构：div.job-sec.work-time > h3「工作时间及福利」
                #              > p>span 作息/休息制度 + ul.work-tags>li 福利标签
                card = tab.ele('css:.job-sec.work-time', timeout=5)
                if card:
                    parts = []
                    for p in card.eles('css:p', timeout=1):
                        t = self._clean_text(p.text)
                        if t:
                            parts.append(t)
                    tags = []
                    for li in card.eles('css:.work-tag-item', timeout=1):
                        t = (li.text or '').strip()
                        if t:
                            tags.append(t)
                    if tags:
                        parts.append('福利: ' + '、'.join(tags))
                    snippet = '；'.join(parts)
                if not snippet and page_text:
                    # 兜底一：页面结构变了但标题还在，取标题后一段正文
                    m = re.search(r'工作时间及福利([\s\S]{0,300})', page_text)
                    if m:
                        snippet = self._clean_text(m.group(1))
                if not snippet and page_text:
                    # 兜底二：直接从公司页正文提取作息与休息制度
                    w, r = self._extract_work_info(page_text)
                    if w:
                        snippet = f"上班时间 {w}"
                    if r:
                        snippet = f"{snippet}；{r}" if snippet else r
                self.company_welfare_cache[company_url] = snippet
                if snippet:
                    print(f"  [福利] 公司工作时间及福利: {snippet[:60]}")
                else:
                    print("  [福利] 公司页未找到工作时间/福利信息")
                return snippet
        except (TimeoutError, InterruptedError):
            raise
        except Exception as exc:
            print(f"  [福利] 公司页获取失败: {exc}")
            return ''

    # ---------- 浏览器投递 ----------
    def deliver_one(self, job: dict, greeting: str) -> str:
        """打开详情页 -> 立即沟通 -> 输入打招呼语 -> 发送。
        返回状态: delivered / already_contacted / no_button / chat_failed / send_failed"""
        with self.browser_lock:
            self._resume_browser_if_needed()
            try:
                detail_url = job["详情链接"]
                if job.get("securityId"):
                    detail_url += f"?securityId={job['securityId']}"
                self.page.get(detail_url)
                if self._check_browser_attention(self.page):
                    self.page.get(detail_url)
                time.sleep(random.uniform(*self.cfg.get("detail_delay", (3, 6))))

                if getattr(self, "humanize_enabled", True):
                    for _ in range(random.randint(2, 4)):
                        self.page.scroll.down(random.randint(50, 120))
                        time.sleep(random.uniform(0.4, 0.9))
                    self.page.scroll.to_top()
                    time.sleep(random.uniform(0.5, 1.2))

                job_id = job.get("encryptJobId", "")
                buttons = self._job_contact_buttons(self.page)
                current_buttons = [
                    button for button in buttons
                    if self._button_targets_job(button, job_id)
                ]
                if any(self._contact_button_state(button) == "already_contacted"
                       for button in current_buttons):
                    print("  [跳过] 平台显示「继续沟通」，不重复发送招呼语")
                    return "already_contacted"
                btn = next(
                    (button for button in current_buttons
                     if self._contact_button_state(button) == "new_contact"),
                    None,
                )
                if not btn:
                    print("  [投递] 未找到可用的「立即沟通」按钮")
                    return "no_button"

                # 记录点击前的 tab，便于定位新开的聊天 tab
                tabs_before = set(self.page.tab_ids)
                btn.click()
                time.sleep(random.uniform(2.0, 3.5))
                if self._check_browser_attention(self.page):
                    return "chat_failed"

                chat_tab = None
                new_tabs = set(self.page.tab_ids) - tabs_before
                if new_tabs:
                    chat_tab = self.page.get_tab(sorted(new_tabs)[-1])
                elif '/chat' in (self.page.url or ''):
                    chat_tab = self.page  # 同页跳转到聊天
                if chat_tab is None:
                    print("  [投递] 未检测到聊天窗口")
                    return "chat_failed"

                try:
                    if self._check_browser_attention(chat_tab):
                        return "chat_failed"
                    return self._send_greeting_in_chat(chat_tab, greeting)
                finally:
                    if chat_tab is not self.page:
                        try:
                            chat_tab.close()
                        except Exception:
                            pass
                    time.sleep(random.uniform(1.0, 2.0))
            except (TimeoutError, InterruptedError):
                raise
            except Exception as exc:
                print(f"  [投递] 异常: {exc}")
                return "error"

    def _human_browse_after_delivery(self):
        """投递后恢复到当前搜索页，再同步登录态并穿插列表浏览。"""
        if not getattr(self, "humanize_enabled", True):
            return
        try:
            with self.browser_lock:
                stop_event = getattr(self, "stop_event", None)
                if stop_event is not None and stop_event.is_set():
                    return
                last_browse = getattr(self, "_last_human_browse_at", None)
                if (last_browse is not None
                        and time.monotonic() - last_browse < SpiderConfig["human_browse_cooldown"]):
                    return
                current = urlparse(self.page.url)
                if (current.netloc != urlparse(SpiderConfig["base_url"]).netloc
                        or not (current.path.startswith('/job_detail/')
                                or current.path.rstrip('/') in (
                                    '/web/geek/chat', '/web/geek/jobs'))):
                    return
                self.page.get(SpiderConfig["start_url"])
                time.sleep(random.uniform(1.5, 3.0))
                self.get_cookie_headers()
                self._human_navigate_interlude(self._human_browse_job_list)
        except Exception as exc:
            print(f"  [拟人浏览] 投递后恢复列表页失败: {exc}")

    def _after_successful_delivery(self):
        """按配置间隔恢复浏览行为或刷新登录态。"""
        every_n = int(self.cfg.get("human_every_n", 0) or 0)
        if every_n <= 0 or self.deliver_count % every_n != 0:
            return
        if self.humanize_enabled:
            self._human_browse_after_delivery()
        else:
            self.get_cookie_headers()

    def _send_greeting_in_chat(self, tab, greeting: str) -> str:
        """在聊天窗口输入并发送打招呼语。"""
        try:
            # 找输入框：常见为 #chat-input 或 .chat-input / textarea
            box = (tab.ele('#chat-input', timeout=6)
                   or tab.ele('.chat-input', timeout=3)
                   or tab.ele('tag:textarea', timeout=3))
            if not box:
                # 聊天页也可能提示已有会话，不能把它当新投递确认继续点击。
                confirm = tab.ele('text:继续沟通', timeout=3)
                if confirm:
                    print("  [投递] 聊天页要求继续沟通，未确认当前岗位状态")
                    return "chat_failed"
            if not box:
                print("  [投递] 聊天输入框未找到")
                return "chat_failed"

            box.click()
            time.sleep(random.uniform(0.5, 1.0))
            # 拟人逐字输入
            interval = random.uniform(0.03, 0.09) if getattr(self, "humanize_enabled", True) else 0
            tab.actions.type(greeting, interval=interval)
            time.sleep(random.uniform(0.8, 1.8))  # 发送前停顿

            send_btn = tab.ele('.btn-send', timeout=3) or tab.ele('text:发送', timeout=2)
            if send_btn:
                send_btn.click()
            else:
                tab.actions.key_down('Enter').key_up('Enter')
            time.sleep(random.uniform(1.5, 2.5))
            print("  [投递] 打招呼语已发送")
            return "delivered"
        except Exception as exc:
            print(f"  [投递] 发送失败: {exc}")
            return "send_failed"

    # ---------- 登录等待（自动检测登录态） ----------
    def wait_login(self, timeout: int):
        """打开登录页，自动轮询页面登录态，检测到即继续。
        注意：不能用 wt2 cookie 判断——profile 里会残留过期的 wt2，会误判已登录。
        以页面右上角用户头像（.nav-figure，仅登录后渲染）为准。
        timeout>0: 最多等 timeout 秒；timeout<=0: 一直等到检测到登录成功。"""
        self._wait_for_login(timeout)

    # ---------- 主流程 ----------
    def _run_profiled_pipeline(self):
        allocations = self.matching_context["allocations"]
        self._human_browse_job_list = []
        queued_job_ids = set()
        candidate_buffer = {}
        processed = 0
        target = max(0, int(self.cfg.get("test_limit", 0) or 0))
        configured_page_cap = self.cfg.get("deliver_max_pages")
        configured_page_cap = max(
            1,
            int(configured_page_cap)
            if configured_page_cap
            else sum(len(item.get("pages", [])) for item in allocations),
        )
        # A finite target expands a smaller configured budget; a larger
        # configured budget adds search headroom for prioritization.
        page_budget = min(50, max(configured_page_cap, target, len(allocations)))
        next_page = {item["keyword"]: 1 for item in allocations}
        initial_pages = {
            item["keyword"]: list(item.get("pages", [])) for item in allocations
        }
        requests_made = 0
        exhausted_queries = set()
        failed_queries = set()
        query_keywords = {item["keyword"] for item in allocations}

        # Share the search-request budget across queries, reusing capacity when
        # one query runs out before the others. Batch enough candidates to apply
        # job-type and scope prioritization before details reveal any rejections.
        while requests_made < page_budget:
            queued_by_id = {}
            last_job_list = None
            requests_this_round = 0
            for allocation in allocations:
                keyword = allocation["keyword"]
                if keyword in exhausted_queries or keyword in failed_queries \
                        or requests_made >= page_budget:
                    continue
                if initial_pages[keyword]:
                    page = initial_pages[keyword].pop(0)
                else:
                    page = next_page[keyword]
                next_page[keyword] = max(next_page[keyword], page + 1)
                requests_made += 1
                requests_this_round += 1
                print(f"\n[采集] 第{page}页 关键词: {keyword}"
                      f" | 画像: {', '.join(allocation['profile_ids'])}")
                try:
                    list_result = self.api_job_list(page=page, keyword=keyword)
                except (TimeoutError, InterruptedError):
                    raise
                except Exception as exc:
                    print(f"[采集] 查询失败，继续其他查询: {keyword}: {exc}")
                    failed_queries.add(keyword)
                    continue
                if not list_result:
                    print(f"[采集] 查询失败，继续其他查询: {keyword}")
                    failed_queries.add(keyword)
                    continue
                job_list = ((list_result.get("zpData") or {}).get("jobList") or [])
                if not job_list:
                    print(f"[采集] {keyword} 第{page}页没有更多岗位")
                    exhausted_queries.add(keyword)
                    continue
                last_job_list = job_list
                self._human_browse_job_list.extend(job_list)

                for job in self._filter_jobs(job_list):
                    job_id = job.get("encryptJobId")
                    if not job_id:
                        continue
                    existing = queued_by_id.get(job_id)
                    if existing is None:
                        existing = candidate_buffer.get(job_id)
                    if existing is not None:
                        if keyword not in existing["搜索来源关键词"]:
                            existing["搜索来源关键词"].append(keyword)
                        existing["来源岗位画像"] = list(dict.fromkeys(
                            [*existing["来源岗位画像"], *allocation["profile_ids"]]
                        ))
                    elif job_id not in queued_job_ids:
                        job["搜索来源关键词"] = [keyword]
                        job["来源岗位画像"] = list(allocation["profile_ids"])
                        job["工作性质"] = self._classify_job_type(job)
                        queued_by_id[job_id] = job
            queued_job_ids.update(queued_by_id)
            candidate_buffer.update(queued_by_id)
            if not requests_this_round:
                break
            should_process = bool(
                target
                and not any(initial_pages.values())
                and len(candidate_buffer) >= target - processed
            )
            if should_process:
                processed, stop = self._process_profiled_jobs(
                    list(candidate_buffer.values()), processed
                )
                candidate_buffer.clear()
                if stop:
                    break
            if requests_made < page_budget and last_job_list:
                self._human_navigate_interlude(last_job_list)

        if candidate_buffer and (not target or processed < target):
            processed, _stop = self._process_profiled_jobs(
                list(candidate_buffer.values()), processed
            )

        if target and processed < target:
            exhausted = query_keywords.issubset(exhausted_queries)
            reason = (
                f"已达每日投递上限 {self.cfg['daily_limit']}"
                if not self.tracker.can_deliver(self.cfg["daily_limit"])
                else "已无更多岗位" if exhausted
                else "搜索请求存在失败" if failed_queries
                else f"已达到搜索请求安全上限 {page_budget}"
            )
            print(f"[采集] {reason}，本轮 AI 评估 {processed}/{target} 个岗位")
        elif target:
            print(f"[本轮] 已完成 AI 评估 {processed}/{target} 个岗位")

    def _process_profiled_jobs(self, candidate_queue, processed):
        if not candidate_queue:
            return processed, False
        prioritized_jobs = self._prioritize_jobs_by_type(candidate_queue)
        # 范围排序：标题即可确认 in_scope 的岗位优先处理；
        # scope_review 靠后，预算不足时被自然截断（省下 AI 调用给确认范围内的岗位）
        def _scope_rank(job):
            status, _reason = classify_job_scope(
                job, self.matching_context["candidate"]
            )
            return {"in_scope": 0, "scope_review": 1}.get(status, 2)
        prioritized_jobs = sorted(prioritized_jobs, key=_scope_rank)
        print(f"[合并] 本批唯一岗位 {len(prioritized_jobs)}，评分画像 "
              f"{len(self.matching_context['profiles'])} 个")
        for index, job in enumerate(prioritized_jobs, 1):
            if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                print(f"[本轮] 已达到处理岗位数 {self.cfg['test_limit']}，停止")
                return processed, True
            if not self.tracker.can_deliver(self.cfg["daily_limit"]):
                print(f"[上限] 已达每日投递上限 {self.cfg['daily_limit']}，停止")
                return processed, True
            if not self._prepare_job(job):
                continue

            scope_status, scope_reason = classify_job_scope(
                job, self.matching_context["candidate"]
            )
            job["职业范围状态"] = scope_status
            if scope_status == "out_of_scope":
                self._count_stage("out_of_scope")
                self._record(self._result_row(
                    job, "", scope_reason, scope_status,
                    filter_reason=scope_reason,
                ))
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    return processed, True
                continue
            # scope_review 不再直接跳过：进 AI 评分，但阈值加罚、排序靠后
            review_penalty = (
                int(self.cfg.get("scope_review_penalty", 0) or 0)
                if scope_status == "scope_review" else 0
            )
            if scope_status == "scope_review":
                self._count_stage("scope_review")
                print(f"  [范围待复核] {job['工作名称']}：{scope_reason}"
                      f"（阈值 +{review_penalty}）")

            _, pre_detail = self._diagnose_profile_terms(job)
            job["技能匹配诊断"] = pre_detail

            # 词典预判只作诊断；非技术/新职业要求由评分模型按完整 JD 判断。
            verdict, gate_reason = local_feasibility(job, self.resume_text)
            job["本地预判"] = f"{verdict}: {gate_reason}"
            if verdict == "hard_conflict":
                self._count_stage("local_gate_conflict")
                print(f"  [本地预判] {job['工作名称']}: {job['本地预判']}（仅供参考，继续 AI 评分）")

            name = job.get("工作名称", "")
            processed += 1
            print(f"\n[岗位 {index}/{len(prioritized_jobs)} | 本轮第{processed}个] "
                  f"{job.get('工作性质', '待确认')} | {name} | {job.get('公司', '')}")

            self._count_stage("ai_called")
            if scope_status == "scope_review":
                self._count_stage("scope_review_ai_called")
            scored_profiles = self.matching_context["profiles"]
            try:
                response = self.scoring_chain.invoke(
                    resume=self.resume_text,
                    prompt_resume=self.scoring_resume_prompt,
                    candidate_profile=self.matching_context["candidate"],
                    job=job,
                    profiles=scored_profiles,
                    rules=self.matching_context["rules"],
                )
            except Exception as exc:
                response = None
                print(f"  [AI] 多画像评分失败: {exc}")
            if not response and len(scored_profiles) > 1:
                # 失败降级：只评 1 个最优画像（来源画像优先），降 token、提成功率
                self._count_stage("ai_retry_single_profile")
                fallback = next(
                    (p for p in scored_profiles
                     if p.id in (job.get("来源岗位画像") or [])),
                    scored_profiles[0],
                )
                scored_profiles = [fallback]
                print(f"  [AI] 降级为单画像重试: {fallback.name}")
                try:
                    response = self.scoring_chain.invoke(
                        resume=self.resume_text,
                        prompt_resume=self.scoring_resume_prompt,
                        candidate_profile=self.matching_context["candidate"],
                        job=job,
                        profiles=scored_profiles,
                        rules=self.matching_context["rules"],
                    )
                except Exception as exc:
                    response = None
                    print(f"  [AI] 单画像降级评分失败: {exc}")
            if not response:
                self._count_stage("match_failed")
                self._record(self._result_row(
                    job, "", "多画像评分失败或响应无效", "match_failed",
                ))
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    return processed, True
                continue

            self._count_stage("ai_scored")
            assessments = response.profile_results
            # 低置信评分向 50 收缩 20%：证据不足时避免分数虚高/虚低（阈值与记录同口径）
            if any(item.confidence < 40 for item in assessments):
                assessments = [
                    item.model_copy(update={
                        "score": int(round(item.score + (50 - item.score) * 0.2)),
                    }) if item.confidence < 40 else item
                    for item in assessments
                ]
                response = JobMatchResponse(
                    profile_results=assessments,
                    jd_requirements=response.jd_requirements,
                )
            primary = choose_primary_assessment(
                response,
                scored_profiles,
                self.cfg["match_threshold"],
                review_penalty=review_penalty,
            )
            details = json.dumps(
                [item.model_dump(mode="json") for item in assessments],
                ensure_ascii=False,
            )
            jd_requirements = "\n".join(
                f"- {item.category} / {item.importance} / {item.coverage}: "
                f"{item.content} | JD 原文: {item.source_quote}"
                for item in response.jd_requirements
            )
            top = max(assessments, key=lambda item: (item.score, item.role_fit))
            selected = primary or top
            reason = selected.reason
            match_data = {
                "hard_gaps": selected.hard_gaps,
                "unverified_requirements": selected.unverified_requirements,
                "preferred_matches": selected.preferred_matches,
                "preferred_gaps": selected.preferred_gaps,
                "evidence": [item.model_dump(mode="json") for item in selected.evidence],
                "primary_profile": (
                    next((item.name for item in self.matching_context["profiles"]
                          if primary and item.id == primary.profile_id), "")
                ),
                "profile_results": details,
                "jd_requirements": jd_requirements,
            }
            job["主岗位画像"] = match_data["primary_profile"]
            job["岗位画像评估详情"] = details
            self.match_scores[name] = selected.score
            print(f"  [AI] 最高评估 {selected.score} | "
                  f"画像: {match_data['primary_profile'] or '未达门槛'} | {reason}")
            if primary is None:
                self._count_stage("below_threshold")
                self._record(self._result_row(
                    job, selected.score, reason, "below_threshold",
                    match_data=match_data,
                ))
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    return processed, True
                continue

            greeting = self.ai.gen_greeting(
                self.resume_text, job,
                candidate_profile=self.matching_context["candidate"],
            )
            if not greeting:
                self._count_stage("greeting_failed")
                self._record(self._result_row(
                    job, primary.score, primary.reason, "greeting_failed",
                    match_data=match_data,
                ))
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    return processed, True
                continue
            self._count_stage("greeting_generated")
            if self.cfg["dry_run"]:
                self._count_stage("dry_run_ready")
                if scope_status == "scope_review":
                    self._count_stage("scope_review_delivered")
                self._record(self._result_row(
                    job, primary.score, primary.reason, "dry_run", greeting,
                    match_data=match_data,
                ))
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    return processed, True
                continue

            time.sleep(random.uniform(2.0, 4.0))
            status = self.deliver_one(job, greeting)
            if status == "already_contacted":
                self._count_stage("already_contacted")
            else:
                self._count_stage("delivery_attempted")
            self._record(self._result_row(
                job, primary.score, primary.reason, status,
                "" if status == "already_contacted" else greeting,
                filter_reason=("平台显示「继续沟通」，本轮未发送招呼语"
                               if status == "already_contacted" else ""),
                match_data=match_data,
            ))
            if status == "delivered":
                self.tracker.mark(job["encryptJobId"], name, greeting, status)
                self.deliver_count += 1
                self._count_stage("delivered")
                if scope_status == "scope_review":
                    self._count_stage("scope_review_delivered")
                self._after_successful_delivery()
            else:
                if status == "already_contacted":
                    self.tracker.mark(
                        job["encryptJobId"], name, "", status,
                        count_delivery=False,
                    )
                else:
                    self.tracker.mark(job["encryptJobId"], name, greeting, status)
            time.sleep(random.uniform(*self.cfg["job_delay"]))
            if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                return processed, True
        return processed, bool(
            self.cfg.get("test_limit")
            and processed >= self.cfg["test_limit"]
        )

    def run(self):
        exit_code = 0
        try:
            if self.cfg.get("test_limit"):
                print(f"[本轮目标] AI 评估 {self.cfg['test_limit']} 个岗位")
            if self.cfg["dry_run"]:
                print("=" * 50)
                print("【干跑测试模式】只采集+AI匹配+达标后生成招呼语，不真实投递")
                print("=" * 50)
            self.wait_login(self.cfg["login_wait"])
            self.get_cookie_headers()
            self.start_heartbeat()  # 复用心跳保活

            if getattr(self, "profile_mode", False):
                self._run_profiled_pipeline()
                return

            # Collect the configured pages first so target job types can be prioritized across pages.
            keyword = self.cfg["deliver_keyword"]
            processed = 0
            consecutive_empty = 0
            stop = False
            candidate_queue = []
            queued_job_ids = set()
            print(f"\n开始处理，今日已投 {self.tracker.data['count']}"
                  f"/上限 {self.cfg['daily_limit']}")
            for page in range(1, self.cfg["deliver_max_pages"] + 1):
                if stop:
                    break
                print(f"\n[采集] 第{page}页 关键词: {keyword}")
                list_result = self.api_job_list(page=page, keyword=keyword)
                if not list_result:
                    print("[采集] 列表获取失败，跳过")
                    break
                job_list = ((list_result.get('zpData') or {}).get('jobList') or [])
                if not job_list:
                    print("[采集] 没有更多岗位")
                    break
                self._human_browse_job_list.extend(job_list)

                candidates = self._filter_jobs(job_list)
                if not candidates:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        print("[采集] 连续3页无新相关岗位，停止")
                        break
                else:
                    consecutive_empty = 0

                for job in candidates:
                    job_id = job.get("encryptJobId")
                    if job_id in queued_job_ids:
                        continue
                    queued_job_ids.add(job_id)
                    job["工作性质"] = self._classify_job_type(job)
                    candidate_queue.append(job)

                # 翻页间隔（最后一页不歇）
                if page < self.cfg["deliver_max_pages"]:
                    self._human_navigate_interlude(job_list)

            preferred_type = effective_job_type_preference(
                self.cfg.get("platform_job_type", "不限"),
                self.cfg.get("job_type_preference", "实习"),
            )
            prioritized_jobs = self._prioritize_jobs_by_type(candidate_queue)
            priority_summary = (
                f"{preferred_type}优先" if preferred_type else "兼职筛选，不执行实习/全职优先排序"
            )
            print(f"[岗位性质优先] {priority_summary} | "
                  f"实习 {sum(job.get('工作性质') == '实习' for job in prioritized_jobs)} | "
                  f"全职 {sum(job.get('工作性质') == '全职' for job in prioritized_jobs)} | "
                  f"待确认 {sum(job.get('工作性质') == '待确认' for job in prioritized_jobs)} | "
                  f"其他 {sum(job.get('工作性质') not in ('实习', '全职', '待确认') for job in prioritized_jobs)}")

            # Sort by the applicable type preference; unknown/non-target jobs remain queued.
            for idx_in_queue, job in enumerate(prioritized_jobs, 1):
                if self.cfg["test_limit"] and processed >= self.cfg["test_limit"]:
                    print(f"\n[测试] 已达到本轮处理上限 {self.cfg['test_limit']}，停止")
                    stop = True
                    break
                if not self.tracker.can_deliver(self.cfg["daily_limit"]):
                    print(f"\n[上限] 已达每日投递上限 {self.cfg['daily_limit']}，停止")
                    stop = True
                    break

                # 懒加载：真正轮到处理时才抓详情+公司福利，被条件过滤的不占用本轮名额
                if not self._prepare_job(job):
                    continue

                _, pre_detail = self._diagnose_profile_terms(job)
                job["技能匹配诊断"] = pre_detail
                print(f"  [画像诊断] {pre_detail}")
                processed += 1

                name = job.get('工作名称', '')
                company = job.get('公司', '')
                print(f"\n[优先队列 {idx_in_queue}/{len(prioritized_jobs)} | 本轮第{processed}个]"
                      f" {job.get('工作性质', '待确认')} | {name} | {company}")

                # 1. AI 匹配（统一使用 scoring_chain，与 _run_profiled_pipeline 保持一致）
                self._count_stage("ai_called")
                scored_profiles = self.matching_context["profiles"]
                try:
                    response = self.scoring_chain.invoke(
                        resume=self.resume_text,
                        prompt_resume=self.scoring_resume_prompt,
                        candidate_profile=self.matching_context["candidate"],
                        job=job,
                        profiles=scored_profiles,
                        rules=self.matching_context["rules"],
                    )
                except Exception as exc:
                    response = None
                    print(f"  [AI] 评分失败: {exc}")
                if not response:
                    self._count_stage("match_failed")
                    self._record(self._result_row(job, "", "评分失败或响应无效", "match_failed"))
                    continue
                self._count_stage("ai_scored")
                assessments = response.profile_results
                primary = choose_primary_assessment(
                    response,
                    scored_profiles,
                    self.cfg["match_threshold"],
                    review_penalty=self.cfg.get("scope_review_penalty", 0),
                )
                details = json.dumps(
                    [item.model_dump(mode="json") for item in assessments],
                    ensure_ascii=False,
                )
                top = max(assessments, key=lambda item: (item.score, item.role_fit))
                selected = primary or top
                score, reason = selected.score, selected.reason
                match_data = {
                    "hard_gaps": selected.hard_gaps,
                    "unverified_requirements": selected.unverified_requirements,
                    "preferred_matches": selected.preferred_matches,
                    "preferred_gaps": selected.preferred_gaps,
                    "evidence": [item.model_dump(mode="json") for item in selected.evidence],
                    "primary_profile": (
                        next((p.name for p in scored_profiles
                              if primary and p.id == primary.profile_id), "")
                    ),
                    "profile_results": details,
                }
                job["主岗位画像"] = match_data["primary_profile"]
                job["岗位画像评估详情"] = details
                self.match_scores[name] = score
                print(f"  [AI] 匹配分: {score} | {reason}")
                if primary is None:
                    self._count_stage("below_threshold")
                    print("  [跳过] 分数低于阈值，不生成打招呼语")
                    self._record(self._result_row(
                        job, score, reason, "below_threshold",
                        match_data=match_data))
                    continue

                # 2. AI 生成打招呼语
                greeting = self.ai.gen_greeting(
                    self.resume_text, job,
                    candidate_profile=self.matching_context["candidate"],
                )
                if not greeting:
                    print("  [AI] 打招呼语生成失败，跳过")
                    self._count_stage("greeting_failed")
                    self._record(self._result_row(
                        job, score, reason, "greeting_failed",
                        match_data=match_data))
                    continue
                self._count_stage("greeting_generated")
                print(f"  [AI] 打招呼语: {greeting}")

                # 3. 投递（干跑模式只打印，不动浏览器）
                if self.cfg["dry_run"]:
                    print("  [干跑] 跳过真实投递")
                    self._count_stage("dry_run_ready")
                    self._record(self._result_row(job, score, reason,
                                                  "dry_run",
                                                  greeting,
                                                  match_data=match_data))
                    continue
                time.sleep(random.uniform(2.0, 4.0))
                status = self.deliver_one(job, greeting)
                if status == "already_contacted":
                    self._count_stage("already_contacted")
                else:
                    self._count_stage("delivery_attempted")
                self._record(self._result_row(
                    job, score, reason, status,
                    "" if status == "already_contacted" else greeting,
                    filter_reason=("平台显示「继续沟通」，本轮未发送招呼语"
                                   if status == "already_contacted" else ""),
                    match_data=match_data))
                if status == "delivered":
                    self.tracker.mark(job["encryptJobId"], name, greeting, status)
                    self.deliver_count += 1
                    self._count_stage("delivered")
                    print(f"  [进度] 今日投递 {self.tracker.data['count']}"
                          f"/{self.cfg['daily_limit']}")
                    self._after_successful_delivery()
                else:
                    # 失败也记录，避免本轮反复重试同一岗位
                    if status == "already_contacted":
                        self.tracker.mark(
                            job["encryptJobId"], name, "", status,
                            count_delivery=False,
                        )
                    else:
                        self.tracker.mark(job["encryptJobId"], name, greeting, status)

                # 4. 岗位间隔 + 可选拟人穿插浏览
                time.sleep(random.uniform(*self.cfg["job_delay"]))
            print(f"\n[结束] 本轮共处理 {processed} 个岗位")
        except KeyboardInterrupt:
            print("\n用户中断")
            exit_code = 130
        except Exception as exc:
            print(f"程序异常: {exc}")
            import traceback
            traceback.print_exc()
            exit_code = 1
        finally:
            self.stop_heartbeat()
            try:
                self.save_results()
                self._print_stage_summary()
            finally:
                try:
                    self.page.quit()
                except Exception:
                    pass
            print(f"程序结束，本次成功投递 {self.deliver_count} 个岗位")
        return exit_code


if __name__ == "__main__":
    try:
        matching_context = load_matching_config(DELIVER_CONFIG)
        apply_search_settings(DELIVER_CONFIG, SpiderConfig)
    except (OSError, ValueError) as exc:
        print(f"[配置错误] {exc}")
        raise SystemExit(2)
    SpiderConfig["keyword"] = matching_context["allocations"][0]["keyword"]
    SpiderConfig["start_url"] = build_job_search_url(SpiderConfig)
    deliverer = AutoDeliverer(DELIVER_CONFIG, matching_context=matching_context)
    raise SystemExit(deliverer.run())
