"""Small LangChain adapters for the configured OpenAI-compatible model."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from candidate_profiles import CandidateProfile, InterviewDraft, ResumeDigest
from job_profiles import JobProfile


class InterviewChainError(RuntimeError):
    """Interview model response could not be validated safely."""


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    source: str
    evidence_text: str

    @field_validator("source")
    @classmethod
    def supported_source(cls, value: str) -> str:
        if value not in {"resume_quote", "user_confirmed"}:
            raise ValueError("evidence source must be resume_quote or user_confirmed")
        return value


_EVIDENCE_SOURCE_ALIASES = {
    "resumequote": "resume_quote",
    "resume": "resume_quote",
    "简历": "resume_quote",
    "简历原文": "resume_quote",
    "候选人简历": "resume_quote",
    "来自简历": "resume_quote",
    "userconfirmed": "user_confirmed",
    "user": "user_confirmed",
    "用户": "user_confirmed",
    "用户确认": "user_confirmed",
    "候选人确认": "user_confirmed",
}


def _normalize_evidence_source(value) -> str:
    """把模型自由填写的 source（如「候选人简历」）归一化到合法枚举。"""
    raw = str(value or "").strip()
    key = re.sub(
        r"[\s_\-]+", "", unicodedata.normalize("NFKC", raw).casefold()
    )
    return _EVIDENCE_SOURCE_ALIASES.get(key, raw)


def _sanitize_scoring_payload(data):
    """容错模型输出：非法或残缺的 evidence 条目丢弃，不让整次评分失败。"""
    if not isinstance(data, dict):
        return data
    data.setdefault("jd_requirements", [])
    requirements = data.get("jd_requirements")
    if isinstance(requirements, list):
        cleaned_requirements = []
        for item in requirements:
            if not isinstance(item, dict):
                continue
            try:
                cleaned_requirements.append(
                    JDRequirement.model_validate(item).model_dump(mode="json")
                )
            except ValidationError:
                continue
        data["jd_requirements"] = cleaned_requirements
    results = data.get("profile_results")
    if not isinstance(results, list):
        return data
    for item in results:
        if not isinstance(item, dict):
            continue
        evidences = item.get("evidence")
        if not isinstance(evidences, list):
            continue
        cleaned = []
        for evidence in evidences:
            if not isinstance(evidence, dict):
                continue
            source = _normalize_evidence_source(evidence.get("source"))
            if source not in {"resume_quote", "user_confirmed"}:
                continue
            if not str(evidence.get("claim") or "").strip():
                continue
            if not str(evidence.get("evidence_text") or "").strip():
                continue
            cleaned.append({**evidence, "source": source})
        item["evidence"] = cleaned
    return data


class ProfileAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    score: int = Field(ge=0, le=100)
    role_fit: int = Field(ge=0, le=100)
    hard_gaps: list[str] = Field(default_factory=list)
    unverified_requirements: list[str] = Field(default_factory=list)
    preferred_matches: list[str] = Field(default_factory=list)
    preferred_gaps: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    reason: str
    confidence: int = Field(default=50, ge=0, le=100)
    disqualified: bool = False
    disqualification_reason: str = ""


class JDRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "responsibility",
        "skill",
        "qualification",
        "institution_tier",
        "work_condition",
        "context",
    ]
    importance: Literal["required", "preferred", "context"]
    coverage: Literal[
        "supported",
        "partial",
        "unsupported",
        "unverified",
        "not_applicable",
    ]
    content: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)


class JobMatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_results: list[ProfileAssessment] = Field(min_length=1)
    jd_requirements: list[JDRequirement] = Field(default_factory=list)


_JOB_SCORING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是岗位匹配评估员。遵循传入的通用筛选规则，对每个岗位画像分别评分。"
            "地点意向以本次任务求职城市（系统设置）为准，优先于简历、结构化摘要、已确认画像"
            "及通用筛选规则中的旧地点偏好；全国表示本轮不限求职城市。"
            "设置了本次城市时，不得因旧地点偏好扣分、降低role_fit或confidence、判定不合格，"
            "也不得据此输出不符合求职意向、hard_gaps或disqualification_reason。"
            "未提供本次城市时沿用已有地点偏好，不得自行假定用户选择了其他城市或全国。"
            "岗位实际地点与本次设置的真实地点冲突仍应如实指出；地点不明只能标为待确认。"
            "本次城市只更新地点意向，不改变简历事实或其他约束，不证明用户已在当地居住，"
            "不得推断到岗时间、搬迁安排、通勤能力或已满足其他工作条件，也不能作为能力证据。"
            "必须为每个画像恰好返回一个结果，不能依据搜索来源省略画像。"
            "先按岗位标题和核心职责识别职业职能，不预设候选人只求职软件或技术岗位；"
            "仅在岗位实际职责或明确要求涉及技术时评估技术技能，其他职业按其职责、资格和可迁移证据评估。"
            "alternative/any要求组满足任一选项即可，preferred缺失不是硬缺口。"
            "每次评分都要从当前岗位原文动态提取要求，不要套用固定职业或技能词表；"
            "按职责、技能、资格条件、工作条件分类，并用 importance 标明必需、优先或背景。"
            "把学历等级（大专/本科/硕士/博士）与院校层级（985/211/双一流/Top N）分开提取；"
            "院校层级必须单列为 institution_tier，不可并入学历等级。"
            "985/211/双一流/Top N等院校层级若写明优先、加分或择优，importance 必须为 preferred，"
            "不得作为硬缺口或淘汰理由；只有JD明确写必须、仅限等强制措辞时才可为 required。"
            "非技术职业按真实职责和资格抽取，不要强行改写成技术技能。"
            "每项 jd_requirements 都必须包含 source_quote，逐字摘录自岗位原文；无法定位原文的推断不要列为要求。"
            "jd_requirements 的 category 和 importance 使用 schema 中定义的值；不可把团队背景当作必需条件。"
            "每项都输出 coverage：supported/partial/unsupported/unverified/not_applicable。"
            "简历未提及一律是 unverified，不得仅因未写到就标为 unsupported、hard_gap 或 disqualified；"
            "只有明确否认或客观不可能时才标出硬缺口。优先项缺失不构成硬缺口。"
            "评估时逐项考虑这些要求与简历/用户确认画像的关系；简历未提及是未验证，不代表候选人不会。"
            "岗位信息中的期望福利是候选人的软偏好，只能作为轻微加分或选择参考；"
            "未提供、未命中或岗位未说明福利均不得视为硬缺口、淘汰理由或显著扣分依据。"
            "投递简历没有写某项通常是未验证，不代表候选人不会。不得发明简历证据。"
            "只有客观不可能满足或简历明确否认时才标记不合格。"
            "岗位信息中职业范围状态为scope_review时表示标题与主要职责未确认映射到目标职位族，"
            "此时role_fit证据不足，应保守评估、宁可低于投递线也不要虚高。"
            "评估时同时考虑岗位信息质量：JD是否完整、是否疑似代招/外包、薪资与经验要求是否相称；"
            "能力匹配但岗位质量存疑时，在reason中明确区分两者。"
            "为每个画像给出confidence（0-100）表示评分把握度，证据不足时应降低confidence。"
            "evidence.source 只能是 resume_quote 或 user_confirmed 两个英文值，不得写中文；"
            "resume_quote 的 evidence_text 必须逐字复制简历原文；user_confirmed 必须来自画像中已核实的用户回答原文，"
            "无法逐字对应时不要输出该条证据。画像evidence应作为能力主张与证据一起参与JD匹配，"
            "不能只依赖临时访谈记录或超出证据推断熟练程度。"
            "输出严格JSON对象，不要Markdown或额外说明。",
        ),
        (
            "human",
            "本次任务求职城市（系统设置）:\n{target_city}\n\n"
            "通用筛选规则:\n{rules}\n\n"
            "岗位画像(JSON数组，每个都必须单独评估):\n{profiles}\n\n"
            "用户确认的候选人画像(JSON，仅包含确认信息):\n{candidate_profile}\n\n"
            "候选人简历/结构化摘要（证据引用须逐字来自简历原文）:\n{resume}\n\n"
            "岗位信息与完整JD:\n{job}\n\n"
            "基于上述岗位原文提取动态JD要求，并将它们用于匹配评分；不得依据固定词表遗漏非技术职业要求。\n\n"
            "返回格式: {schema}",
        ),
    ]
)


def build_chat_model(config: dict) -> ChatOpenAI:
    effort = str(config.get("ai_reasoning_effort") or "").strip().lower()
    extra = {"reasoning_effort": effort} if effort in {"low", "medium", "high"} else {}
    return ChatOpenAI(
        model=str(config["ai_model"]),
        api_key=str(config["ai_api_key"]),
        base_url=str(config["ai_base_url"]).rstrip("/"),
        timeout=float(config["ai_timeout"]),
        max_retries=int(config["ai_max_retries"]),
        temperature=0.2,
        **extra,
    )


_INTERVIEW_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是简历画像访谈助手。只根据简历原文或用户明确回答记录事实，"
            "不清楚的信息保持未知，不把跳过当作否定。一次只提出一个最有价值的澄清问题。"
            "根据用户确认的方向提出允许的相邻职位族，但不能擅自扩大到无关职业。"
            "phase=direction时先判断简历是否已经明确职业方向；明确时直接提取方向和相关职位族，"
            "设置direction_source=resume且不得重复询问用户确认方向；只有简历确实模糊时"
            "清空primary_direction、设置direction_source=unknown并询问求职方向。"
            "在同一轮里必须给出第一个最值得澄清的问题：只要ready_for_review不为true，"
            "pending_question就不能为空，不要留到下一轮再提问。"
            "输出保持精简：aliases与title_terms可为空数组，evidence每轮最多1条，不要复述整段简历。"
            "如果当前草稿direction_source=resume或user_confirmed，方向已确定；后续阶段不得再询问或要求确认职业方向，"
            "只能围绕职位族、经历细节、能力证据和偏好补充信息。"
            "用户明确回答方向时设置direction_source=user_confirmed；未明确回答或跳过时保持unknown。"
            "phase=market_followup时可用市场资料发现值得追问的能力，但资料只代表岗位市场的一般情况，"
            "绝不能当成候选人会或不会某项能力的证据，也不能写入evidence；只能放进proposed_evidence并向用户核实。"
            "岗位市场资料为空时，禁止依据岗位标准技能要求追问简历未提及技能的掌握情况；"
            "技能补充类问题必须以岗位市场资料为依据，只能围绕简历已有经历细节与偏好提问。"
            "输出一个JSON对象，字段必须匹配给定结构；不要输出多个问题列表。"
            "source=resume_quote时，evidence_text必须逐字复制简历中的连续原文（含原有标点与连接词），"
            "不得改写、概括、补字或替换同义词；找不到逐字原文时一律放入proposed_evidence。"
            "source=user_confirmed时，evidence_text必须逐字复制用户本轮或历史回答中的连续原文，"
            "并将能力整理为简洁、可复用的claim；不得把模型推断、岗位市场要求或跳过的问题写成用户能力。"
            "候选事实如未被简历或用户原话直接支持，放入proposed_evidence并针对它追问，"
            "不要放入confirmed evidence。只有信息充分时才设置ready_for_review=true。",
        ),
        (
            "human",
            "简历原文:\n{resume}\n\n"
            "当前已确认画像:\n{active_profile}\n\n"
            "当前画像草稿:\n{draft}\n\n"
            "本次访谈历史(临时，不会持久化):\n{history}\n\n"
            "本轮用户回答: {answer}\n"
            "本轮是否跳过: {skipped}\n"
            "访谈阶段: {phase}\n"
            "岗位市场资料（只用于提出核实问题，不能视为候选人事实）:\n{market_context}\n\n"
            "重试说明: {retry_instruction}\n\n"
            "返回结构: {schema}",
        ),
    ]
)


class CandidateInterviewChain:
    def __init__(self, model=None):
        self.model = model or build_chat_model_from_default_config()
        structured_model = self.model.with_structured_output(
            InterviewDraft,
            method="json_mode",
            include_raw=True,
        )
        self.chain = _INTERVIEW_PROMPT | structured_model

    def invoke(
        self,
        resume: str,
        active_profile: CandidateProfile | None,
        draft: InterviewDraft | None,
        history: list[dict[str, str]],
        answer: str | None,
        skipped: bool = False,
        phase: str = "interview",
        market_context: str = "",
        prompt_resume: str | None = None,
    ) -> InterviewDraft:
        if not str(resume or "").strip():
            raise ValueError("resume text is required for a candidate profile interview")
        try:
            request = {
                "resume": prompt_resume if str(prompt_resume or "").strip() else resume,
                "active_profile": (
                    active_profile.model_dump_json(exclude={"resume_sha256"})
                    if active_profile is not None
                    else "无已确认画像"
                ),
                "draft": draft.model_dump_json() if draft is not None else "尚无画像草稿",
                "history": json.dumps(history, ensure_ascii=False),
                "answer": answer or "（无）",
                "skipped": "是" if skipped else "否",
                "phase": str(phase or "interview"),
                "market_context": str(market_context or "无可用岗位市场资料"),
                "retry_instruction": "无",
                "schema": json.dumps(InterviewDraft.model_json_schema(), ensure_ascii=False),
            }
            response = None
            for attempt in range(2):
                response = self.chain.invoke(request)
                if not isinstance(response, dict) or not {
                    "raw", "parsed", "parsing_error"
                }.issubset(response):
                    raise InterviewChainError("LangChain未返回预期的结构化访谈结果。")
                result = response["parsed"]
                parse_error = response["parsing_error"]
                if result is not None and parse_error is None:
                    try:
                        if isinstance(result, InterviewDraft):
                            result = result.model_dump(mode="json")
                        if not isinstance(result, dict):
                            raise TypeError("parsed interview response must be an object")
                        result = InterviewDraft.model_validate(result)
                        if result.pending_question and result.ready_for_review:
                            raise ValueError(
                                "model cannot ask a question and request confirmation in the same turn"
                            )
                        return result
                    except (TypeError, ValueError, ValidationError) as exc:
                        parse_error = exc
                if attempt == 1:
                    raw = response["raw"]
                    raw_content = getattr(raw, "content", "")
                    if not raw_content:
                        metadata = getattr(raw, "response_metadata", {}) or {}
                        additional = getattr(raw, "additional_kwargs", {}) or {}
                        finish_reason = metadata.get("finish_reason") or additional.get("finish_reason")
                        detail = f"（finish_reason={finish_reason}）" if finish_reason else ""
                        raise InterviewChainError(
                            f"AI连续2次返回空内容{detail}。请检查模型服务或输出限制，然后点击重试。"
                        ) from parse_error
                    raise InterviewChainError(
                        "AI连续2次未能按访谈结构返回有效内容，画像草稿未更新。"
                        "请检查模型服务是否支持 JSON mode / response_format，然后点击重试。"
                    ) from parse_error
                else:
                    request["retry_instruction"] = (
                        "上一次回复未通过画像字段校验。请按提示中的完整 JSON Schema 重新生成，"
                        "只返回一个 JSON 对象，不要使用 Markdown 代码块或附加说明。"
                    )
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise InterviewChainError(f"Invalid candidate interview response: {exc}") from exc
        except InterviewChainError:
            raise
        except Exception as exc:
            raise InterviewChainError(f"Candidate interview request failed: {exc}") from exc


class ResumeDigestError(RuntimeError):
    """Resume digest response could not be validated safely."""


_RESUME_DIGEST_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是简历结构化提取器。只从简历原文中摘录事实，不得补充、推测或改写措辞。"
            "skills/projects/education/preferences 中的每一条都必须逐字复制简历原文中的完整一行"
            "（含原有标点与连接词），不要合并、压缩或换一种说法；"
            "技能、项目、课程、奖项、校园经历宁可多摘，不可漏项。"
            "primary_direction 与 summary 用简短概括即可，它们不可作为证据引用。"
            "输出严格JSON对象，不要Markdown或额外说明。",
        ),
        (
            "human",
            "简历原文:\n{resume}\n\n"
            "重试说明: {retry_instruction}\n\n"
            "返回结构: {schema}",
        ),
    ]
)


class ResumeDigestChain:
    def __init__(self, model=None):
        self.model = model or build_chat_model_from_default_config()
        structured_model = self.model.with_structured_output(
            ResumeDigest,
            method="json_mode",
            include_raw=True,
        )
        self.chain = _RESUME_DIGEST_PROMPT | structured_model

    def invoke(self, resume: str) -> ResumeDigest:
        if not str(resume or "").strip():
            raise ValueError("resume text is required for a resume digest")
        request = {
            "resume": resume,
            "retry_instruction": "无",
            "schema": json.dumps(ResumeDigest.model_json_schema(), ensure_ascii=False),
        }
        parse_error = None
        for attempt in range(2):
            response = self.chain.invoke(request)
            parsed = response.get("parsed") if isinstance(response, dict) else None
            parse_error = (
                response.get("parsing_error")
                if isinstance(response, dict)
                else TypeError("unexpected digest response")
            )
            if parsed is not None and parse_error is None:
                try:
                    digest = (
                        parsed
                        if isinstance(parsed, ResumeDigest)
                        else ResumeDigest.model_validate(parsed)
                    )
                    return digest.verified(resume)
                except (TypeError, ValueError, ValidationError) as exc:
                    parse_error = exc
            if attempt == 0:
                request["retry_instruction"] = (
                    "上一次回复未通过结构校验。请严格按 JSON Schema 返回一个 JSON 对象，"
                    "不要使用 Markdown 代码块或附加说明。"
                )
        raise ResumeDigestError(f"简历摘要生成失败：{parse_error}")


class JobScoringChain:
    def __init__(self, model=None):
        self.model = model or build_chat_model_from_default_config()
        self.chain = _JOB_SCORING_PROMPT | self.model

    def invoke(
        self,
        resume: str,
        candidate_profile: CandidateProfile,
        job: dict,
        profiles: list[JobProfile],
        rules: str,
        prompt_resume: str | None = None,
        target_city: str | None = None,
    ) -> JobMatchResponse:
        if not str(rules or "").strip():
            raise ValueError("screening rules are required")
        expected_ids = [profile.id for profile in profiles]
        if not expected_ids or len(expected_ids) != len(set(expected_ids)):
            raise ValueError("job profile IDs must be non-empty and unique")
        try:
            response = self.chain.invoke({
                "target_city": str(target_city or "").strip() or "未提供（沿用已有地点偏好）",
                "rules": rules,
                # 只传评分需要的字段，去掉 search_keywords/diagnostic_terms 等无关内容省 token
                "profiles": json.dumps(
                    [
                        {
                            "id": profile.id,
                            "name": profile.name,
                            "role_direction": profile.role_direction,
                            "hard_requirements": [
                                item.model_dump(mode="json")
                                for item in profile.hard_requirements
                            ],
                            "preferred_qualifications": profile.preferred_qualifications,
                            "exclusions": profile.exclusions,
                            "threshold": profile.threshold,
                        }
                        for profile in profiles
                    ],
                    ensure_ascii=False,
                ),
                "candidate_profile": candidate_profile.model_dump_json(
                    exclude={"resume_sha256"}
                ),
                "resume": prompt_resume if str(prompt_resume or "").strip() else resume,
                "job": json.dumps(job, ensure_ascii=False, default=str),
                "schema": json.dumps(JobMatchResponse.model_json_schema(), ensure_ascii=False),
            })
            content = response.content if hasattr(response, "content") else str(response)
            if not isinstance(content, str):
                raise ValueError("model returned a non-text response")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("model response must be a JSON object")
            data = _sanitize_scoring_payload(data)
            parsed = JobMatchResponse.model_validate(data)
            actual_ids = [item.profile_id for item in parsed.profile_results]
            if len(actual_ids) != len(set(actual_ids)):
                raise ValueError("model returned duplicate profile IDs")
            if set(actual_ids) != set(expected_ids):
                raise ValueError("model response must include exactly the requested profile IDs")
            # 无法逐字溯源的证据丢弃即可，不要因一条证据让整次评分失败
            normalize = lambda value: " ".join(
                unicodedata.normalize("NFKC", value).split()
            )
            resume_normalized = normalize(resume)
            for item in parsed.profile_results:
                kept = []
                for evidence in item.evidence:
                    if (evidence.source == "resume_quote"
                            and normalize(evidence.evidence_text) not in resume_normalized):
                        print(f"[AI] 丢弃无法逐字溯源的简历证据: {evidence.claim}")
                        continue
                    kept.append(evidence)
                item.evidence = kept
            normalize_job = lambda value: " ".join(
                unicodedata.normalize("NFKC", value).split()
            )
            job_sources = [normalize_job(text) for text in _jd_source_values(job)]
            valid_requirements = []
            for requirement in parsed.jd_requirements:
                quote = normalize_job(requirement.source_quote)
                if not quote or not any(quote in source for source in job_sources):
                    print(f"[AI] 丢弃无法逐字溯源的JD要求: {requirement.content}")
                    continue
                valid_requirements.append(requirement)
            parsed.jd_requirements = valid_requirements
            return parsed
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise InterviewChainError(f"Invalid job scoring response: {exc}") from exc
        except Exception as exc:
            raise InterviewChainError(f"Job scoring request failed: {exc}") from exc


_JD_SOURCE_FIELDS = {
    "工作名称", "jobname", "title", "jobtitle",
    "工作介绍", "postdescription", "jobdescription", "description",
    "responsibilities",
    "技术要求", "jobdesc", "jobrequire", "skills", "requirements",
    "工作经验要求", "experience", "experiencerequirement",
    "学历要求", "degree", "education",
    "工作性质", "jobtype",
}


def _job_text_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _job_text_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _job_text_values(child)
    elif isinstance(value, str):
        yield value


def _jd_source_values(job):
    """Yield text only from fields that represent the job and its JD."""
    for key, value in job.items():
        if str(key).casefold() in _JD_SOURCE_FIELDS:
            yield from _job_text_values(value)


def build_chat_model_from_default_config():
    # Imported lazily to keep profile tooling independent from application startup.
    from delivery_config import DELIVER_CONFIG

    return build_chat_model(DELIVER_CONFIG)
