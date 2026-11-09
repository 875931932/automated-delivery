# -*- coding: utf-8 -*-
"""投递配置：.env 加载、DELIVER_CONFIG、平台检索配置与匹配前置校验。"""
import os

from dotenv import dotenv_values, load_dotenv

from app_paths import get_data_dir, get_resource_dir
from candidate_profiles import (
    CandidateProfileStore,
    build_base_candidate_profile,
    resume_digest_hash,
)
from job_profiles import (
    DEFAULT_SCREENING_RULES_PATH,
    JobProfile,
    JobProfileStore,
    allocate_query_pages,
    build_unique_queries,
    load_screening_rules,
)

from platform_search_filters import (
    JOB_TYPE_CODES,
    JOB_TYPE_LABELS,
    PLATFORM_FILTERS,
    resolve_platform_filter,
)
from greeting_prompt import DEFAULT_GREETING_PROMPT

# ========================= 从 .env 加载配置 =========================
_inherited_greeting_prompt = os.environ.get("GREETING_PROMPT")
_env_file = get_data_dir() / ".env"
load_dotenv(_env_file)
_raw_env = dotenv_values(_env_file, interpolate=False)


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key, "").strip()
    return value if value else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except ValueError:
        print(f"[配置] {key} 不是有效整数，使用默认值 {default}")
        return default


DELIVER_CONFIG = {
    # --- AI 接口（OpenAI 兼容）---
    "ai_base_url": _env_str("AI_BASE_URL", "https://api.deepseek.com/v1"),
    "ai_api_key": _env_str("AI_API_KEY", ""),
    "ai_model": _env_str("AI_MODEL", "deepseek-chat"),
    # 思考强度 low/medium/high（step-5-preview 等推理模型支持；访谈/评分用 low 明显更快）
    "ai_reasoning_effort": _env_str("AI_REASONING_EFFORT", "low").lower(),
    "ai_timeout": _env_int("AI_TIMEOUT", 90),
    "ai_max_retries": _env_int("AI_MAX_RETRIES", 2),
    "greeting_prompt": (
        _inherited_greeting_prompt
        if _inherited_greeting_prompt is not None
        else _raw_env.get(
            "GREETING_PROMPT", os.getenv("GREETING_PROMPT", DEFAULT_GREETING_PROMPT)
        )
    ) or DEFAULT_GREETING_PROMPT,
    # Tavily 仅用于候选人画像访谈的 market_followup 阶段（panel_candidate_profile.py）。
    # 主投递链路（auto_deliver.py）不调用 Tavily；未配置 key 时访谈自动降级为纯简历访谈。
    "tavily_enabled": os.getenv("TAVILY_ENABLED", "true").strip().lower() == "true",
    "tavily_api_key": _env_str("TAVILY_API_KEY", ""),
    "tavily_timeout": _env_int("TAVILY_TIMEOUT", 12),

    # --- 简历与筛选 ---
    "resume_file": _env_str("RESUME_FILE", "resume.md"),
    "match_threshold": _env_int("MATCH_THRESHOLD", 70),    # AI 匹配分数 >= 该值才投递
    # 列表阶段经验门槛分级：下限 >= hard 直接拦截；soft~hard 之间放行交给 AI 评分兜底
    "experience_hard_limit": _env_int("EXPERIENCE_HARD_LIMIT", 5),
    "experience_soft_limit": _env_int("EXPERIENCE_SOFT_LIMIT", 3),
    # scope_review（职业范围未确认）岗位的有效阈值 = 阈值 + 该加罚（0 关闭加罚）
    "scope_review_penalty": _env_int("SCOPE_REVIEW_PENALTY", 5),
    # 职能规则影子模式：命中 role_rules 时只记录不拦截（观察误杀面后再收紧）
    "role_reject_shadow": os.getenv("ROLE_REJECT_SHADOW", "true").strip().lower() == "true",
    # 本地廉价 gate 影子模式：hard_conflict 只记录不拦截（误杀率 <5% 后可关闭影子）
    "local_gate_shadow": os.getenv("LOCAL_GATE_SHADOW", "true").strip().lower() == "true",
    "deliver_keyword": _env_str("DELIVER_KEYWORD", "AI应用开发"),
    "deliver_max_pages": min(50, max(1, _env_int("DELIVER_MAX_PAGES", 10))),  # 每轮搜索请求总上限
    "candidate_profile_file": _env_str("CANDIDATE_PROFILE_FILE", "candidate_profile.json"),
    "job_profiles_file": _env_str("JOB_PROFILES_FILE", "job_profiles.json"),
    "screening_rules_file": _env_str("SCREENING_RULES_FILE", "screening_rules.md"),
    "job_type_preference": _env_str("JOB_TYPE_PREFERENCE", "实习"),
    "platform_area_filter": [
        area.strip() for area in _env_str("PLATFORM_AREA_FILTER", "").split(",")
        if area.strip()
    ],
    "platform_job_type": JOB_TYPE_LABELS.get(
        _env_str("PLATFORM_JOB_TYPE", "不限"),
        _env_str("PLATFORM_JOB_TYPE", "不限"),
    ),
    # 平台筛选项按面板里保存的标签原样保留（也兼容旧版存下的平台 ID），
    # 真正的 ID 转换在 configure_platform_search 里做，浏览器与接口共用一份结果。
    **{
        config_key: _env_str(env_key, "")
        for env_key, (config_key, _param, _codes) in PLATFORM_FILTERS.items()
    },

    # --- 投递节奏与上限 ---
    "daily_limit": _env_int("DAILY_LIMIT", 50),            # 每日投递上限（可自行调整）
    "job_delay": (_env_int("JOB_DELAY_MIN", 25), _env_int("JOB_DELAY_MAX", 50)),
    "human_every_n": _env_int("HUMAN_EVERY_N", 5),         # 每投 N 个岗位穿插一次随机拟人浏览

    # --- 拟人行为 ---
    "humanize_enable": os.getenv("HUMANIZE_ENABLE", "true").strip().lower() == "true",
    "favorite_score": _env_int("FAVORITE_SCORE", 75),      # 兼容旧配置；当前流程不自动收藏

    # --- 登录与浏览节奏 ---
    "keep_login": os.getenv("KEEP_LOGIN", "true").strip().lower() == "true",
    "browser_background": os.getenv("BROWSER_BACKGROUND", "true").strip().lower() == "true",
    "detail_delay": (_env_int("DETAIL_DELAY_MIN", 3), _env_int("DETAIL_DELAY_MAX", 6)),

    # --- 输出 ---
    "result_file": _env_str("RESULT_FILE", "deliver_results.csv"),
    "log_file": _env_str("LOG_FILE", "deliver_log.json"),

    # --- 工作时间与休息制度筛选 ---
    "rest_day_require": _env_str("REST_DAY_REQUIRE", "不限"),
    # 期望福利（多选，逗号分隔）：作为 AI 评分的加分参考，不做硬过滤
    "welfare_require": [
        item.strip() for item in _env_str("WELFARE_REQUIRE", "").split(",")
        if item.strip()
    ],
    "work_time_start": _env_str("WORK_TIME_START", ""),   # 如 09:30，留空不启用
    "work_time_end": _env_str("WORK_TIME_END", ""),       # 如 19:00，留空不启用

    # --- 区域筛选（按行政区/商圈，多个用逗号分隔，留空不启用）---
    "area_filter": [a.strip() for a in _env_str("AREA_FILTER", "").split(",") if a.strip()],

    # --- 测试模式 ---
    "dry_run": os.getenv("DRY_RUN", "false").strip().lower() == "true",
    "test_limit": _env_int("TEST_LIMIT", 0),   # 本轮 AI 评估尝试数，0=不限
    "login_wait": _env_int("LOGIN_WAIT", 0),   # >0 时超时停止；0 持续等待登录
}


def apply_search_settings(config, spider_config):
    """Apply job-search settings shared by API requests and browser navigation."""
    spider_config["city_id"] = _env_str("CITY_CODE", "101280600")
    spider_config["keyword"] = config["deliver_keyword"]
    spider_config["keep_login"] = config["keep_login"]
    spider_config["browser_background"] = config.get("browser_background", True)
    spider_config["start_url"] = configure_platform_search(config, spider_config)
    return spider_config["start_url"]

def configure_platform_search(config, spider_config):
    """Apply optional platform filters and return the matching browser search URL."""
    # 延迟导入 boss_spider：它会连带加载 DrissionPage，冷启动时不需要这份开销。
    from boss_spider import build_job_search_url, resolve_platform_area_codes

    city_id = spider_config["city_id"]
    areas = config.get("platform_area_filter", [])
    spider_config["multiBusinessDistrict"] = (
        resolve_platform_area_codes(areas, city_id) if areas else ""
    )

    raw_job_type = str(config.get("platform_job_type", "不限") or "").strip()
    spider_config["jobType"] = JOB_TYPE_CODES.get(raw_job_type, "")
    # 兼职时段只在平台求职类型为「兼职」时生效：其他类型下保留会误杀全部岗位。
    # 配置值可能来自 .env 的中文标签，也可能已是平台 ID，统一解析成 ID。
    part_time = resolve_platform_filter(
        "PLATFORM_PART_TIME", config.get("platform_part_time", "")
    )
    spider_config["partTime"] = part_time if spider_config["jobType"] == "1903" else ""
    for env_key, (config_key, param_key, _codes) in PLATFORM_FILTERS.items():
        if env_key == "PLATFORM_PART_TIME" and spider_config["jobType"] != "1903":
            continue
        spider_config[param_key] = resolve_platform_filter(
            env_key, config.get(config_key, "")
        )
    return build_job_search_url(spider_config)


def load_matching_config(config: dict):
    """启动前校验画像/规则状态，构建匹配上下文。

    运行模式说明
    ─────────────────────────────────────────────────────────────────
    基础模式（无需任何额外配置，开箱即用）
      必须：.env 中填写 AI_API_KEY、RESUME_FILE、DELIVER_KEYWORD
      可选：resume_digest.json（首次运行自动生成，加速后续评分）
      不需要：candidate_profile.json、job_profiles.json 自定义、TAVILY_API_KEY

    增强模式（候选人画像访谈完成后自动启用）
      候选人画像（candidate_profile.json）：通过桌面面板→候选人画像页 完成访谈后生成
        作用：精确职业范围过滤（in_scope/out_of_scope/scope_review）
      岗位画像（job_profiles.json）：可手动配置硬要求/加分项/逐画像阈值
        作用：AI 评分更精准，支持多画像并行评估
      Tavily 市场搜索（TAVILY_API_KEY）：仅在画像访谈的 market_followup 阶段使用
        作用：补充岗位市场资料，帮助访谈助手提出更有针对性的问题
    ─────────────────────────────────────────────────────────────────
    """
    base_dir = str(get_data_dir())

    def local_path(key: str, default: str) -> str:
        value = config.get(key) or default
        return value if os.path.isabs(value) else os.path.join(base_dir, value)

    candidate = CandidateProfileStore(
        local_path("candidate_profile_file", "candidate_profile.json")
    ).load()
    enhanced_profile_stale = False

    target = str(config.get("deliver_keyword", "") or "").strip()
    if not target:
        raise ValueError("请先在「求职设置」填写目标岗位（例如：AI 应用工程师）。")

    job_store = JobProfileStore(local_path("job_profiles_file", "job_profiles.json"))
    stored = job_store.load_or_migrate(target)
    enabled_stored = [item for item in stored if item.enabled]
    if enabled_stored:
        # 旧数据兼容：保留已有评分标尺（硬要求/加分/阈值），
        # 但搜索词完全由「目标岗位」决定，避免旧关键词污染检索范围。
        profiles = [
            item.model_copy(update={"search_keywords": [target]})
            for item in enabled_stored
        ]
    else:
        # 岗位画像不再由用户手工维护：按「目标岗位」自动派生一条，零配置即可启动。
        # 硬要求/阈值留空，AI 评分只依据 JD 正文与简历。
        profiles = [JobProfile(
            id="auto-target",
            name=target,
            role_family_id="",
            role_direction=target,
            search_keywords=[target],
        )]
        print(f"[配置] 按目标岗位自动生成岗位画像：{target}")

    base_mode = False
    resume_text = None
    resume_path = None
    if candidate is not None and candidate.resume_sha256:
        resume_path = local_path("resume_file", "resume.md")
        try:
            with open(resume_path, "r", encoding="utf-8") as f:
                resume_text = f.read()
        except OSError:
            resume_text = ""
        enhanced_profile_stale = (
            not resume_text.strip()
            or resume_digest_hash(resume_text) != candidate.resume_sha256
        )
        if enhanced_profile_stale:
            print("[配置] 增强画像对应的简历已变化或不可用，已回退基础画像")
            candidate = None

    if candidate is None:
        # 规范：用户不一定会用到增强画像，缺失或过期时按当前简历回退基础模式
        base_mode = True
        if resume_text is None:
            resume_path = local_path("resume_file", "resume.md")
            try:
                with open(resume_path, "r", encoding="utf-8") as f:
                    resume_text = f.read()
            except OSError:
                resume_text = ""
        # 基础画像需用原始多关键词派生 title_terms（搜索词压缩只服务于检索，
        # 不应传染到范围匹配：否则 title_terms 只剩 [target] 一个词，
        # 大模型应用工程师、LLM应用开发等明显相关岗位全落入 scope_review）
        candidate = build_base_candidate_profile(
            resume_text, enabled_stored or profiles, config.get("deliver_keyword", ""),
        )
        print("[配置] 未找到已确认候选人画像，已用基础画像（简历摘要+岗位画像关键词）启动")

    # 岗位画像由系统按目标岗位维护，不再要求用户绑定职位族
    active_profiles = [item for item in profiles if item.enabled]
    if not active_profiles:
        raise ValueError("没有可用的岗位方向，请检查「求职设置」里的目标岗位。")
    queries = build_unique_queries(active_profiles)
    target = max(0, int(config.get("test_limit", 0) or 0))
    allocations = allocate_query_pages(queries, len(queries))
    if len(queries) > 50:
        raise ValueError(
            f"唯一搜索关键词有 {len(queries)} 个，超过每轮 50 次搜索请求安全上限。"
        )
    page_cap = max(1, int(config.get("deliver_max_pages", 10) or 10))
    if not target and page_cap < len(queries):
        raise ValueError(
            f"搜索请求上限 {page_cap} 小于唯一关键词数 {len(queries)}，"
            "请提高高级设置中的请求预算，确保每个关键词至少搜索一页。"
        )
    rules_value = config.get("screening_rules_file") or str(DEFAULT_SCREENING_RULES_PATH)
    if os.path.isabs(rules_value):
        rules_path = rules_value
    else:
        rules_path = os.path.join(base_dir, rules_value)
        bundled_rules = get_resource_dir() / rules_value
        if not os.path.isfile(rules_path) and bundled_rules.is_file():
            rules_path = str(bundled_rules)
    rules = load_screening_rules(rules_path)
    mode_label = "基础模式（无已确认候选人画像）" if base_mode else "增强模式（已确认候选人画像）"
    print(f"[配置] 运行模式：{mode_label}")
    return {"candidate": candidate, "profiles": active_profiles,
            "allocations": allocations, "rules": rules, "base_mode": base_mode,
            "enhanced_profile_stale": enhanced_profile_stale}


if not DELIVER_CONFIG["ai_api_key"] or "你的key" in DELIVER_CONFIG["ai_api_key"]:
    print("[配置] ⚠️ 尚未在 .env 中填写 AI_API_KEY，AI 匹配将无法工作")

RESULT_FIELDS = [
    "encryptJobId", "工作名称", "公司", "工资", "区域", "上班时间", "休息制度",
    "工作性质",
    "预筛命中率", "技能匹配诊断", "本地预判", "AI匹配分数", "AI匹配理由", "JD要求分层",
    "硬性缺口", "未验证要求", "加分项命中", "加分项缺口", "简历证据", "打招呼语",
    "投递状态", "投递时间", "详情链接", "筛选原因", "人工标记",
    "主岗位画像", "岗位画像评估详情", "职业范围状态",
    "搜索来源关键词", "来源岗位画像",
]
