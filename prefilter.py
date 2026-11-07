# -*- coding: utf-8 -*-
"""本地预筛与规则纯函数：职业范围分类、JD 要求分层、简历证据、作息/经验/职能拦截规则。
不依赖 auto_deliver（避免循环导入），类型从 candidate_profiles/job_profiles/ai_chains 导入。"""
import re
import json
import unicodedata

from ai_chains import JobMatchResponse
from candidate_profiles import CandidateProfile
from job_profiles import JobProfile


def _normalize_scope_text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


# 职能拦截规则：(拦截原因, 标题模式, 职责模式)，标题与职责同时命中才拦截
ROLE_RULES = (
    ("岗位职能偏教学培训", r"讲师|教师|培训师|教研|课程顾问|授课顾问|培训顾问|实战应用专家",
     r"授课|讲授|备课|课程教学|企业培训|企业授课|外部授课|课程体系|成熟课程|培训课程"),
    ("岗位职能偏销售商务", r"销售|商务拓展|客户经理|销售顾问|渠道拓展|BD",
     r"开发客户|拓展客户|销售产品|商务谈判|销售业绩|电话销售|签约回款|客户拜访"),
    ("岗位职能偏运营", r"运营|新媒体|内容编辑",
     r"内容策划|活动策划|社群维护|用户增长|账号运营|内容发布|活动执行"),
    ("岗位职能偏客服支持", r"客服|客户服务|售后|电话回访",
     r"客户咨询|售后处理|工单处理|投诉处理|客户回访"),
    ("岗位职能偏招聘人事", r"招聘|人力资源|人事专员|HR",
     r"简历筛选|招聘面试|员工关系|人事行政|人才招募"),
)


# 范围分类同义词组：同组内任一表述命中即视为命中该词条。
# 只扩召回（降低误杀），不新增拦截面；不定义权重或分数。
SCOPE_SYNONYMS = (
    ("llm", "大模型", "大语言模型", "llm应用", "大模型应用", "llm应用开发", "大模型应用开发"),
    ("agent", "aiagent", "ai agent", "智能体", "智能体开发"),
    ("rag", "检索增强", "检索增强生成", "知识库问答"),
    ("aigc", "生成式ai", "生成式人工智能"),
    ("多模态", "multimodal"),
    ("ai应用开发", "大模型应用开发", "ai应用研发", "大模型应用研发", "ai原生应用", "ai原生应用开发"),
)


def _scope_term_variants(term: str) -> tuple:
    normalized_term = _normalize_scope_text(term).strip()
    if not normalized_term:
        return ()
    for group in SCOPE_SYNONYMS:
        if normalized_term in {_normalize_scope_text(item) for item in group}:
            return group
    return (term,)


def _scope_text_hits(text: str, term: str) -> bool:
    normalized_text = _normalize_scope_text(text)
    for variant in _scope_term_variants(term):
        normalized_term = _normalize_scope_text(variant).strip()
        if not normalized_term:
            continue
        if re.fullmatch(r"[a-z0-9+#._-]+", normalized_term):
            if re.search(
                rf"(?<![a-z0-9+#._-]){re.escape(normalized_term)}(?![a-z0-9+#._-])",
                normalized_text,
            ):
                return True
        elif normalized_term in normalized_text:
            return True
    return False


def _primary_duty_text(job: dict) -> str:
    title = str(job.get("工作名称", job.get("jobName", "")) or "")
    description = str(job.get("工作介绍", job.get("jobDescription", "")) or "")
    selected = []
    for clause in re.split(r"[\n。；;]", description):
        clause = clause.strip()
        if clause and re.search(
            r"负责|工作内容|岗位职责|主要职责|职位描述|工作职责|任职", clause
        ):
            selected.append(clause)
    return " ".join([title, *selected])


def classify_job_scope(job: dict, candidate: CandidateProfile) -> tuple[str, str]:
    """Classify only from confirmed scope terms and title/primary-duty clauses."""
    text = _primary_duty_text(job)
    title = str(job.get("工作名称", job.get("jobName", "")) or "")
    excluded_hits = [
        term for term in candidate.excluded_terms
        if _scope_text_hits(text, term) or _scope_text_hits(title, term)
    ]
    excluded_family_hits = [
        family for family in candidate.excluded_role_families
        if _scope_text_hits(title, family)
    ]
    if excluded_hits or excluded_family_hits:
        terms = excluded_hits + excluded_family_hits
        return "out_of_scope", f"命中已确认排除范围：{', '.join(terms)}"

    for family in candidate.allowed_role_families:
        terms = [family.name, *family.aliases, *family.title_terms]
        matched = [term for term in dict.fromkeys(terms) if (
            _scope_text_hits(title, term)
            or (_scope_text_hits(text, term) and _scope_text_hits(text, "负责"))
        )]
        if matched:
            return "in_scope", f"命中已确认职位族「{family.name}」：{', '.join(matched)}"
    return "scope_review", "标题与主要职责无法明确映射到已确认职位族，需复核职业范围"


def choose_primary_assessment(
    response: JobMatchResponse,
    profiles: list[JobProfile],
    global_threshold: int,
    review_penalty: int = 0,
):
    expected_ids = {profile.id for profile in profiles}
    assessments = response.profile_results
    actual_ids = [item.profile_id for item in assessments]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        return None
    profile_by_id = {item.id: item for item in profiles}
    passing = []
    for assessment in assessments:
        profile = profile_by_id[assessment.profile_id]
        threshold = profile.threshold if profile.threshold is not None else global_threshold
        threshold = min(100, threshold + max(0, int(review_penalty or 0)))
        if not assessment.disqualified and assessment.score >= threshold:
            passing.append(assessment)
    return max(passing, key=lambda item: (item.score, item.role_fit), default=None)


# ========================= 技能同义词归一（JD/简历证据解析） =========================
# 仅帮助识别 JD 要求和简历证据，不定义权重、缺口或筛选分数。
SKILL_SYNONYMS = {
    "python": ("python",),
    "java": ("java",),
    "javascript": ("javascript",),
    "typescript": ("typescript",),
    "go": ("golang", "go语言", "go"),
    "c++": ("c++", "cpp"),
    "php": ("php",),
    "rust": ("rust",),
    "kotlin": ("kotlin",),
    "swift": ("swift",),
    "react": ("react",),
    "vue": ("vue",),
    "angular": ("angular",),
    "小程序": ("小程序", "uni-app", "uniapp"),
    "flutter": ("flutter",),
    "node": ("node.js", "nodejs", "nestjs", "express"),
    "django": ("django",),
    "flask": ("flask",),
    "fastapi": ("fastapi",),
    "spring": ("spring", "springboot", "spring boot", "spring cloud", "springcloud"),
    "mysql": ("mysql",),
    "postgresql": ("postgresql", "postgres", "pgsql"),
    "mongodb": ("mongodb", "mongo"),
    "redis": ("redis",),
    "elasticsearch": ("elasticsearch",),
    "kafka": ("kafka",),
    "rabbitmq": ("rabbitmq",),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "linux": ("linux",),
    "git": ("git",),
    "nginx": ("nginx",),
    "llm": ("llm", "大模型", "大语言模型"),
    "langchain": ("langchain",),
    "langgraph": ("langgraph",),
    "rag": ("rag", "检索增强"),
    "agent": ("agent", "智能体"),
    "prompt": ("prompt", "提示词"),
    "fine-tune": ("微调", "fine-tune", "finetune", "lora"),
    "pytorch": ("pytorch",),
    "tensorflow": ("tensorflow",),
    "transformers": ("transformers", "huggingface"),
    "nlp": ("nlp", "自然语言处理"),
    "cv": ("计算机视觉", "opencv"),
    "yolo": ("yolo", "目标检测"),
    "多模态": ("多模态", "multimodal"),
    "aigc": ("aigc", "stable diffusion", "comfyui", "midjourney"),
    "向量数据库": ("向量数据库", "milvus", "faiss", "chroma", "pinecone", "qdrant"),
    "embedding": ("embedding", "向量检索", "向量化"),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "spark": ("spark",),
    "hadoop": ("hadoop", "hive"),
    "flink": ("flink",),
    "爬虫": ("爬虫", "scrapy"),
    "ocr": ("ocr",),
    "restful": ("restful", "rest api", "接口开发"),
    "sse": ("sse", "流式输出", "websocket"),
    "prisma": ("prisma",),
    "数据分析": ("数据分析", "数据挖掘"),
}

def extract_skill_tags(text: str):
    """从简历/JD 文本抽取技能标签集合。英文词按单词边界匹配，避免 java 命中 javascript。"""
    text = str(text or "").lower()
    tags = set()
    for tag, synonyms in SKILL_SYNONYMS.items():
        for syn in synonyms:
            if syn.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(syn)}(?![a-z0-9])", text):
                    tags.add(tag)
                    break
            elif syn in text:
                tags.add(tag)
                break
    return tags


def _extract_ordered_skill_tags(text: str):
    """按 JD 原文首次出现顺序返回技能标签，便于要求组可读和审计。"""
    lowered = str(text or "").lower()
    found = []
    for tag, synonyms in SKILL_SYNONYMS.items():
        positions = []
        for synonym in synonyms:
            needle = synonym.lower()
            if synonym.isascii():
                match = re.search(
                    rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                    lowered,
                )
            else:
                match = re.search(re.escape(needle), lowered)
            if match:
                positions.append(match.start())
        if positions:
            found.append((min(positions), tag))
    return [tag for _, tag in sorted(found)]


LANGUAGE_TAGS = {
    "c++", "python", "java", "go", "javascript", "typescript", "php",
    "rust", "kotlin", "swift",
}


def _matching_resume_lines(text: str, patterns):
    lines = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" -•\t")
        if line and any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
            lines.append(line[:240])
    return list(dict.fromkeys(lines))[:3]


def _resume_evidence_level(lines):
    if not lines:
        return "not_explicit"
    if any(re.search(r"没有|未接触|不会|不熟悉|未使用|未做过", line) for line in lines):
        return "explicit_absence"
    practice_pattern = (
        r"实践|项目|开发|搭建|实现|接入|基于|编写|负责|技术栈|增删改查|"
        r"接口|检索|工具|工作流|服务"
    )
    if any(re.search(practice_pattern, line, re.IGNORECASE) for line in lines):
        return "project_practice"
    if any(re.search(r"熟悉|掌握|了解|使用过|能够|具备", line) for line in lines):
        return "explicit_skill"
    return "mentioned"


def extract_resume_evidence(text: str):
    """提取带证据来源的简历摘要；未出现表示未知，不表示候选人不会。"""
    specs = {
        "python": (r"(?<![a-z0-9])python(?![a-z0-9])",),
        "fastapi": (r"fastapi",),
        "langchain": (r"langchain",),
        "langgraph": (r"langgraph",),
        "rag": (r"(?<![a-z0-9])rag(?![a-z0-9])|检索增强",),
        "tool_use": (r"tool\s*use|工具(?:调用|接入)|\d+\s*个工具",),
        "vector_retrieval": (r"混合检索|向量检索|向量化|embedding|向量召回",),
        "vector_database": (
            r"milvus|faiss|chroma|pinecone|qdrant|elasticsearch|向量数据库组件",
        ),
        "database_crud": (r"数据库增删改查|CRUD|增删改查",),
        "mysql": (r"mysql",),
        "mongodb": (r"mongodb|mongo",),
        "prisma": (r"prisma",),
        "restful": (r"restful|rest\s*api",),
        "typescript": (r"typescript",),
        "nestjs": (r"nestjs|nest\.js",),
        "node": (r"node\.js|nodejs|node\b",),
        "express": (r"express",),
        "sse": (r"sse|流式输出",),
        "ocr": (r"ocr",),
    }
    evidence = {}
    for name, patterns in specs.items():
        lines = _matching_resume_lines(text, patterns)
        evidence[name] = {
            "level": _resume_evidence_level(lines),
            "evidence": lines,
        }
    for name, synonyms in SKILL_SYNONYMS.items():
        if name in evidence:
            continue
        patterns = []
        for synonym in synonyms:
            if synonym.isascii():
                patterns.append(
                    rf"(?<![a-z0-9]){re.escape(synonym)}(?![a-z0-9])"
                )
            else:
                patterns.append(re.escape(synonym))
        lines = _matching_resume_lines(text, patterns)
        evidence[name] = {
            "level": _resume_evidence_level(lines),
            "evidence": lines,
        }
    return evidence


def _requirement_item(name, source, required=False):
    return {
        "name": name,
        "source": source.strip()[:240],
        "required": bool(required),
    }


def classify_jd_requirements(text: str):
    """保留 JD 的要求关系；模糊列表不自动解释为全部硬要求。"""
    result = {
        "required": [],
        "alternative": [],
        "preferred": [],
        "ambiguous": [],
        "context": [],
    }
    normalized_text = unicodedata.normalize("NFKC", str(text or ""))
    clauses = [part.strip() for part in re.split(r"[\n。；;！!？?]", normalized_text) if part.strip()]
    preferred_pattern = r"优先|加分|更佳|优先考虑|有.+经验者优先|会.+更好"
    hard_pattern = r"必须|必需|硬性|至少|需要|要求|需具备|必须掌握|熟练掌握"
    all_required_pattern = r"同时|均需|都要|全部|分别掌握|同时具备|必须同时|熟练掌握|并且|以及"
    alternative_pattern = r"其中一种|任一|任选一|任意一种|至少一种|二选一|三选一|或|之一|均可|/|／"
    context_pattern = r"团队使用|公司使用|技术栈包括|目前采用|有机会接触|基于.+构建"

    for clause in clauses:
        tags = _extract_ordered_skill_tags(clause)
        if not tags:
            continue
        if re.search(context_pattern, clause, re.IGNORECASE):
            result["context"].append({
                "skills": tags,
                "source": clause[:240],
            })
            continue

        is_preferred = bool(re.search(preferred_pattern, clause, re.IGNORECASE))
        is_hard = bool(re.search(hard_pattern, clause, re.IGNORECASE))
        language_tags = [tag for tag in tags if tag in LANGUAGE_TAGS]
        is_explicit_all_required = bool(
            re.search(all_required_pattern, clause, re.IGNORECASE)
        )
        slash_alternative = (
            "/" in clause or "／" in clause
        ) and len(language_tags) >= 2 and len(tags) == len(language_tags)
        is_alternative = (
            len(tags) >= 2
            and bool(re.search(alternative_pattern, clause, re.IGNORECASE))
            and (bool(re.search(r"其中一种|任一|任选一|任意一种|至少一种|二选一|三选一|或|之一|均可", clause, re.IGNORECASE))
                 or slash_alternative)
        )
        if is_alternative:
            result["alternative"].append({
                "type": "alternative",
                "options": tags,
                "required": not is_preferred,
                "source": clause[:240],
            })
        elif is_preferred:
            result["preferred"].extend(
                _requirement_item(tag, clause, required=False) for tag in tags
            )
        elif is_hard and len(tags) == 1:
            result["required"].extend(
                _requirement_item(tag, clause, required=True) for tag in tags
            )
        elif is_hard and is_explicit_all_required:
            result["required"].extend(
                _requirement_item(tag, clause, required=True) for tag in tags
            )
        elif (
            len(tags) >= 2
            and not is_explicit_all_required
        ):
            result["ambiguous"].append({
                "type": "ambiguous_list",
                "options": tags,
                "source": clause[:240],
            })
        else:
            result["ambiguous"].extend(
                _requirement_item(tag, clause, required=False) for tag in tags
            )

    for key in ("required", "preferred", "ambiguous"):
        seen = set()
        unique = []
        for item in result[key]:
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if marker not in seen:
                seen.add(marker)
                unique.append(item)
        result[key] = unique
    return result


def _format_resume_evidence(evidence):
    explicit = {
        key: value for key, value in evidence.items()
        if value.get("level") != "not_explicit"
    }
    if not explicit:
        return "（简历未提供可定位的技术证据；未列出的技术均为未验证，不代表不会）"
    return (
        json.dumps(explicit, ensure_ascii=False, indent=2)
        + "\n注：未出现在上述证据中的技术均为未验证，不等于候选人不会。"
    )


def _format_jd_requirements(requirements):
    lines = []
    if requirements["required"]:
        lines.append("明确硬要求:")
        lines.extend(f"- {item['name']} | 来源: {item['source']}" for item in requirements["required"])
    if requirements["alternative"]:
        lines.append("任选一项硬要求组:")
        lines.extend(
            f"- {'、'.join(item['options'])}（命中组内任一项即可满足）| 来源: {item['source']}"
            for item in requirements["alternative"]
        )
    if requirements["preferred"]:
        lines.append("加分/优先项:")
        lines.extend(f"- {item['name']} | 来源: {item['source']}" for item in requirements["preferred"])
    if requirements["ambiguous"]:
        lines.append("关系不明确、不得直接当作硬缺口:")
        for item in requirements["ambiguous"]:
            names = "、".join(item.get("options", [item.get("name", "")]))
            lines.append(f"- {names} | 来源: {item['source']}")
    if requirements["context"]:
        lines.append("团队/技术背景:")
        lines.extend(f"- {item['source']}" for item in requirements["context"])
    return "\n".join(lines) or "（未识别出结构化要求，结合完整JD判断）"


def _skill_key_in_text(text: str):
    lowered = unicodedata.normalize("NFKC", str(text or "")).lower()
    for key, synonyms in SKILL_SYNONYMS.items():
        for synonym in synonyms:
            if synonym.isascii():
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(synonym.lower())}(?![a-z0-9])",
                    lowered,
                ):
                    return key
            elif synonym.lower() in lowered:
                return key
    return None


def local_feasibility(job: dict, resume_text: str) -> tuple[str, str]:
    """廉价本地预判，减少无效 AI 调用（不调模型、不做标签重合率打分）。
    只依据客观条件与简历「明确否认」证据，宁可放过不确定的岗位。
    返回 (verdict, reason)：
    - hard_conflict: 硬要求被简历明确否认，或必选任选组全部明确缺失
    - likely_fit: 硬要求与任选组均有简历证据
    - uncertain: 证据不足，一律交由 AI 评分
    """
    jd_text = ' '.join(filter(None, (
        str(job.get('工作名称', '') or ''),
        str(job.get('技术要求', '') or ''),
        str(job.get('工作介绍', '') or ''),
    )))
    requirements = classify_jd_requirements(jd_text)
    resume = str(resume_text or "")

    hard_items = [item["name"] for item in requirements["required"]]
    alt_groups = [
        item for item in requirements["alternative"] if item.get("required")
    ]

    conflicts = [
        name for name in hard_items
        if _explicit_absence_for_requirement(name, resume)
    ]
    missing_groups = []
    for group in alt_groups:
        options = group.get("options") or []
        if options and all(
            _explicit_absence_for_requirement(option, resume) for option in options
        ):
            missing_groups.append("、".join(options))
    if conflicts or missing_groups:
        parts = []
        if conflicts:
            parts.append("硬要求被简历明确否认: " + "、".join(conflicts))
        if missing_groups:
            parts.append("任选组全部明确缺失: " + "；".join(missing_groups))
        return "hard_conflict", "；".join(parts)

    if not hard_items and not alt_groups:
        return "uncertain", "JD 未识别出结构化硬要求"

    evidence = extract_resume_evidence(resume)

    def has_evidence(name):
        key = _skill_key_in_text(name) or name
        return evidence.get(key, {}).get("level") not in (None, "not_explicit")

    known = [name for name in hard_items if has_evidence(name)]
    covered_groups = sum(
        1 for group in alt_groups
        if any(has_evidence(option) for option in group.get("options") or [])
    )
    if len(known) == len(hard_items) and covered_groups == len(alt_groups):
        return "likely_fit", "硬要求与任选组均有简历证据"
    return "uncertain", "部分硬要求缺少简历证据，交由 AI 判断"


def _explicit_absence_for_requirement(requirement: str, resume: str) -> bool:
    """Require a resume-specific negative statement before calling a technical gap explicit."""
    skill_key = _skill_key_in_text(requirement)
    absence_pattern = r"没有|未接触|不会|不熟悉|未使用|未做过"
    for line in str(resume or "").splitlines():
        normalized_line = unicodedata.normalize("NFKC", line).lower()
        clauses = re.split(r"[。！？!?；;，,]+|但是|不过|然而", normalized_line)
        for clause in clauses:
            if not re.search(absence_pattern, clause):
                continue
            if skill_key:
                for synonym in SKILL_SYNONYMS[skill_key]:
                    needle = synonym.lower()
                    if synonym.isascii():
                        found = re.search(
                            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                            clause,
                        )
                    else:
                        found = re.search(re.escape(needle), clause)
                    if found:
                        return True
            else:
                normalized_requirement = re.sub(r"[\W_]+", "", requirement.lower())
                normalized_clause = re.sub(r"[\W_]+", "", clause)
                if normalized_requirement and normalized_requirement in normalized_clause:
                    return True
    return False


# ========================= 工作时间/休息制度/经验/职能拦截规则 =========================
def to_minutes(text):
    """解析时间文本为分钟数，支持「上午09:00」「下午6点」「晚上21:30」等格式。"""
    text = (text or '').replace(' ', '')
    m = re.search(r'(\d{1,2})[:：](\d{2})', text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r'(\d{1,2})点', text)
        if not m:
            return None
        h, mi = int(m.group(1)), 0
    if re.search(r'下午|晚上', text) and h < 12:
        h += 12
    return h * 60 + mi


def extract_work_info(text):
    """从 JD/公司福利文本提取（上班时间, 休息制度），仅用于导出展示。"""
    text = str(text or '')

    def _norm(s_raw, e_raw):
        s_min, e_min = to_minutes(s_raw), to_minutes(e_raw)
        if s_min is None or e_min is None:
            return ''
        # 「9点-6点」未写下午时，按下午修正（6 点 = 18:00）
        if e_min <= s_min and e_min < 12 * 60 and '上午' not in e_raw:
            e_min += 12 * 60
        if e_min <= s_min:
            return ''
        return (f"{s_min // 60:02d}:{s_min % 60:02d}"
                f"-{e_min // 60:02d}:{e_min % 60:02d}")

    work_time = ''
    for pat in (
        r'((?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{2})'
        r'\s*(?:[-—~至]|到)\s*'
        r'((?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{2})',
        r'((?:上午|下午)?\s*\d{1,2}点)\s*(?:[-—~至]|到)\s*((?:上午|下午)?\s*\d{1,2}点)',
    ):
        times = re.findall(pat, text)
        if times:
            work_time = _norm(*times[0])
            if work_time:
                break

    compact = re.sub(r"\s+", "", text)
    schedule_patterns = (
        r"(?:大小周|单双休|隔周(?:单休|双休|休息))",
        r"(?:周末双休|双休|每周休(?:息)?两天|每周休2天|周六日休)",
        r"(?:单休|每周休(?:息)?一天|每周休1天|每周工作六天)",
    )
    negative_prefix = r"(?:并非|没有|不是|不|非|无)"
    negated_spans = []
    for pattern in schedule_patterns:
        for match in re.finditer(pattern, compact):
            prefix_start = match.start()
            prefix = re.search(
                rf"{negative_prefix}(?:固定)?(?:周末)?$",
                compact[max(0, match.start() - 8):match.start()],
            )
            if prefix:
                negated_spans.append((
                    max(0, match.start() - 8) + prefix.start(), match.end()
                ))
    schedule_text = compact
    for start, end in reversed(negated_spans):
        schedule_text = schedule_text[:start] + schedule_text[end:]

    if re.search(schedule_patterns[0], schedule_text):
        rest_day = "大小周"
    elif re.search(schedule_patterns[1], schedule_text):
        rest_day = "双休"
    elif re.search(schedule_patterns[2], schedule_text):
        rest_day = "单休"
    else:
        rest_day = ""
        month_rest = re.search(r"月休\s*(\d+)\s*天", compact)
        if month_rest:
            days = int(month_rest.group(1))
            if days >= 8:
                rest_day = "双休"
            elif days <= 6:
                rest_day = "单休"
    return work_time, rest_day


def need_company_welfare(jd_text: str, cfg: dict) -> bool:
    """只在作息或用户配置的福利偏好尚无法从 JD 判断时打开公司页。"""
    work_time, rest_day = extract_work_info(jd_text)
    if cfg["rest_day_require"] != "不限" and not rest_day:
        return True
    if (cfg["work_time_start"] or cfg["work_time_end"]) and not work_time:
        return True
    welfare_require = [
        str(item).strip() for item in cfg.get("welfare_require", [])
        if str(item).strip()
    ]
    if any(item not in str(jd_text or "") for item in welfare_require):
        return True
    return False


def work_condition_reject(jd_text: str, cfg: dict):
    """检查 JD 中的休息制度与工作时间，返回拒绝理由或 None（通过/未知均放行）。"""
    text = str(jd_text or '')
    if not text:
        return None  # 没有详情文本，无法判断，放行

    # Explicitly stated but incompatible schedules are filtered; unknown schedules pass.
    need = cfg["rest_day_require"]
    _work_time, actual_rest = extract_work_info(text)
    if need != "不限" and actual_rest and actual_rest != need:
        return f"休息制度不符合（要求{need}，岗位标注{actual_rest}）"

    # 工作时间：解析 09:00-18:00 / 上午09:00 - 下午06:00 / 9点-6点 形式
    times = re.findall(
        r'((?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{2}|(?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}点)'
        r'\s*(?:[-—~至]|到)\s*'
        r'((?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{2}|(?:上午|中午|下午|晚上|凌晨)?\s*\d{1,2}点)',
        text)
    # 弹性工作制不作下班时间限制
    flexible = bool(re.search(r'弹性', text))
    start_limit = to_minutes(cfg["work_time_start"]) \
        if cfg["work_time_start"] else None
    end_limit = to_minutes(cfg["work_time_end"]) \
        if cfg["work_time_end"] else None
    for s_raw, e_raw in times:
        s_min, e_min = to_minutes(s_raw), to_minutes(e_raw)
        if s_min is None or e_min is None:
            continue
        if e_min <= s_min and e_min < 12 * 60 and "上午" not in e_raw:
            e_min += 12 * 60
        if e_min < s_min:  # 跨天的情况（如 熬夜班），保守放行
            continue
        if start_limit is not None and s_min > start_limit:
            return f"上班时间过晚（{s_raw} 上班）"
        if end_limit is not None and not flexible and e_min > end_limit:
            return f"下班时间过晚（{e_raw} 下班，疑似加班）"
    return None


def hard_reject(job, hard_limit=5, soft_limit=3):
    """只用列表字段判断硬性门槛（经验/学历），命中就提前跳过，连详情都不用抓。
    经验分级：下限 >= hard_limit 拦截；soft_limit~hard_limit 之间放行，
    交给 AI 评分按"经验要求 vs 在校生"扣分兜底，降低误杀。"""
    exp = str(job.get('jobExperience', '') or '')
    m = re.search(r'(\d+)\s*(?:[-~至]\s*(\d+))?', exp)
    job_name = str(job.get('jobName', '') or '')
    intern_title = re.search(r'实习|应届|在校|校招|\d{4}\s*届', job_name)
    if m and not intern_title and int(m.group(1)) >= int(hard_limit):
        return f"经验要求 {exp}（下限超过 {hard_limit} 年，在校生不匹配）"
    edu = str(job.get('jobDegree', '') or '')
    if '博士' in edu or ('硕士' in edu and '本科' not in edu):
        return f"学历要求 {edu}"
    return None


def exp_soft_banded(job, hard_limit=5, soft_limit=3):
    """经验下限落在 soft~hard 区间时返回说明文本（不拦截，仅提示）。"""
    exp = str(job.get('jobExperience', '') or '')
    m = re.search(r'(\d+)\s*(?:[-~至]\s*(\d+))?', exp)
    job_name = str(job.get('jobName', '') or '')
    if not m or re.search(r'实习|应届|在校|校招|\d{4}\s*届', job_name):
        return None
    years = int(m.group(1))
    if int(soft_limit) <= years < int(hard_limit):
        return f"经验要求 {exp}（{soft_limit}~{hard_limit} 年软区间，交由 AI 判断）"
    return None


def role_function_reject(job_data):
    """只在标题和职责均明确指向非开发工作时拦截；混合或模糊岗位放行。"""
    title = str(job_data.get("工作名称", "") or "")
    duties = str(job_data.get("工作介绍", "") or "")
    if not title or not duties:
        return None
    # 标题即为开发类岗位时直接放行（标题型岗位职责写得含蓄，避免误杀）
    if re.search(r"开发|研发|工程师|Agent|智能体|算法", title, re.IGNORECASE):
        return None

    duties_for_check = re.sub(
        r"(?:不承担|无需|不涉及|不负责|不需要|非)\s*"
        r"[\u4e00-\u9fff\w/+#.]{0,12}(?:开发|研发|编码)",
        "",
        duties,
    )
    duties_for_check = re.sub(
        r"(?:讲解|介绍|讲授|培训|教授|教学)[^。；;！？\n]{0,24}"
        r"(?:开发流程|研发流程|开发方法|开发知识|开发理念|软件工程概念)",
        "",
        duties_for_check,
    )
    duties_for_check = re.sub(
        r"(?:开发|拓展|挖掘)(?:潜在)?(?:客户|市场|渠道|商机)",
        "",
        duties_for_check,
    )
    engineering_action = (
        r"负责|参与|主导|承担|持续|从事|进行|维护|搭建|构建|实现|编写|完成"
    )
    engineering_artifact = (
        r"软件|系统|平台|应用|后端|前端|接口|API|算法|模型|代码|功能|"
        r"服务|模块|网站|小程序|客户端|数据库|脚本|程序|智能体|Agent|"
        r"工作流|RAG|知识库|大模型"
    )
    development_action = (
        r"开发|研发|搭建|构建|实现|迭代|编码|联调|部署|上线|维护|修复|优化"
    )
    development_duties = any(
        re.search(
            rf"(?:{engineering_action}).{{0,10}}(?:{development_action})"
            rf".{{0,10}}(?:{engineering_artifact})",
            clause,
            re.IGNORECASE,
        )
        or re.search(
            rf"(?:{engineering_action}).{{0,10}}(?:{engineering_artifact})"
            rf".{{0,10}}(?:{development_action})",
            clause,
            re.IGNORECASE,
        )
        or re.search(
            rf"(?:维护|修复|优化).{{0,10}}(?:{engineering_artifact})",
            clause,
            re.IGNORECASE,
        )
        for clause in re.split(r"[。；;！？\n]", duties_for_check)
    ) or bool(re.search(
        r"编写代码|代码开发|测试开发|运维开发",
        duties_for_check,
        re.IGNORECASE,
    ))
    if development_duties:
        return None

    for reason, title_pattern, duties_pattern in ROLE_RULES:
        if re.search(title_pattern, title, re.IGNORECASE) and re.search(
            duties_pattern, duties_for_check, re.IGNORECASE
        ):
            return reason
    return None
