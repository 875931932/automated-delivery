"""Validated candidate profile storage and interview state transitions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_PROFILE_PATH = Path(__file__).with_name("candidate_profile.json")
DEFAULT_DIGEST_PATH = Path(__file__).with_name("resume_digest.json")
DEFAULT_DRAFT_CACHE_PATH = Path(__file__).with_name("interview_draft_cache.json")


def resume_digest_hash(resume: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(resume or "")).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _non_empty(value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError("value must not be empty")
    return value


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    source: Literal["resume_quote", "user_confirmed"]
    evidence_text: str

    _validate_claim = field_validator("claim")(_non_empty)
    _validate_evidence = field_validator("evidence_text")(_non_empty)


class ProposedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    evidence_text: str = ""
    clarification_question: str

    _validate_claim = field_validator("claim")(_non_empty)
    _validate_question = field_validator("clarification_question")(_non_empty)


class RoleFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    title_terms: list[str] = Field(default_factory=list)

    _validate_id = field_validator("id")(_non_empty)
    _validate_name = field_validator("name")(_non_empty)

    @field_validator("aliases", "title_terms")
    @classmethod
    def clean_terms(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(term.strip() for term in values if term.strip()))


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    revision: int = Field(ge=0)
    resume_sha256: str = ""
    primary_direction: str
    allowed_role_families: list[RoleFamily] = Field(min_length=1)
    excluded_role_families: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)

    _validate_direction = field_validator("primary_direction")(_non_empty)

    @model_validator(mode="after")
    def unique_family_ids(self) -> CandidateProfile:
        ids = [family.id for family in self.allowed_role_families]
        if len(ids) != len(set(ids)):
            raise ValueError("allowed role family IDs must be unique")
        return self

    @field_validator("excluded_role_families", "excluded_terms", "preferences")
    @classmethod
    def clean_text_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class InterviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_direction: str = ""
    direction_source: Literal["resume", "user_confirmed", "unknown"] = "unknown"
    allowed_role_families: list[RoleFamily] = Field(default_factory=list)
    excluded_role_families: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    proposed_evidence: list[ProposedEvidence] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    pending_question: str | None = None
    ready_for_review: bool = False


class CandidateProfileStore:
    def __init__(self, path: Path | str = DEFAULT_PROFILE_PATH):
        self.path = Path(path)

    def load(self) -> CandidateProfile | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return CandidateProfile.model_validate(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid candidate profile at {self.path}: {exc}") from exc

    def save_confirmed(self, profile: CandidateProfile | dict) -> CandidateProfile:
        candidate = CandidateProfile.model_validate(profile)
        current = self.load()
        candidate = candidate.model_copy(
            update={"revision": (current.revision if current else 0) + 1}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(candidate.model_dump(mode="json"), temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return candidate


class ResumeDigest(BaseModel):
    """简历结构化摘要：列表条目为简历原文逐字行，可安全用作证据引用。"""

    model_config = ConfigDict(extra="forbid")

    primary_direction: str = ""
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("skills", "projects", "education", "preferences")
    @classmethod
    def clean_text_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    def has_content(self) -> bool:
        return bool(self.skills or self.projects or self.education or self.preferences)

    def verified(self, resume: str) -> ResumeDigest:
        """丢弃无法逐字对上简历原文的条目，保证摘要各行都可安全引用。"""
        normalize = lambda value: " ".join(unicodedata.normalize("NFKC", value).split())
        haystack = normalize(resume)
        keep = lambda values: [value for value in values if normalize(value) in haystack]
        return self.model_copy(update={
            "skills": keep(self.skills),
            "projects": keep(self.projects),
            "education": keep(self.education),
            "preferences": keep(self.preferences),
        })

    def prompt_text(self) -> str:
        if not self.has_content():
            return ""
        lines = ["=== 候选人简历结构化摘要（以下每行均为简历原文，可逐字引用） ==="]
        if self.primary_direction.strip():
            lines.append(f"求职方向概括：{self.primary_direction.strip()}")
        for title, items in (
            ("技能", self.skills),
            ("项目经历要点", self.projects),
            ("教育与校园经历", self.education),
            ("求职意向与偏好", self.preferences),
        ):
            if items:
                lines.append(f"{title}：")
                lines.extend(f"- {item}" for item in items)
        if self.summary.strip():
            lines.append(f"补充概述（仅供理解，不可作为简历证据引用）：{self.summary.strip()}")
        return "\n".join(lines)


class ResumeDigestStore:
    """按简历内容哈希缓存结构化摘要；简历变化后缓存自动失效。"""

    def __init__(self, path: Path | str = DEFAULT_DIGEST_PATH):
        self.path = Path(path)

    def load_for(self, resume: str) -> ResumeDigest | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("resume_sha256") != resume_digest_hash(resume):
                return None
            return ResumeDigest.model_validate(raw.get("digest"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, resume: str, digest: ResumeDigest) -> ResumeDigest:
        candidate = ResumeDigest.model_validate(digest)
        payload = {
            "resume_sha256": resume_digest_hash(resume),
            "digest": candidate.model_dump(mode="json"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return candidate


def build_base_candidate_profile(
    resume_text: str,
    job_profiles: list,
    fallback_direction: str = "",
) -> CandidateProfile:
    """基础画像：仅从简历摘要与岗位画像关键词合成，无需访谈增强。

    规范允许用户不使用增强画像，此时用简历结构化摘要的方向概括 + 岗位画像
    已绑定职位族及其搜索关键词合成初始画像，供范围过滤与 AI 评分使用。
    """
    digest = None
    try:
        digest = ResumeDigestStore().load_for(str(resume_text or ""))
    except Exception:
        digest = None

    direction = str(getattr(digest, "primary_direction", "") or "").strip()
    if not direction:
        direction = str(fallback_direction or "").strip()
    if not direction:
        raise ValueError("无法从简历构建基础画像：缺少求职方向概括。")

    families_by_id = {}
    for profile in job_profiles:
        # 基础模式不要求岗位画像已绑定职位族：未绑定时用岗位画像自身定义职位族，
        # 避免「无候选人画像 → 不能绑定职位族 → 无岗位画像 → 基础画像建不出来」的死锁。
        family_id = str(
            getattr(profile, "role_family_id", "") or getattr(profile, "id", "") or ""
        ).strip()
        if not family_id:
            continue
        entry = families_by_id.setdefault(family_id, {
            "name": str(
                getattr(profile, "role_direction", "")
                or getattr(profile, "name", "") or family_id
            ),
            "terms": [],
        })
        entry["terms"].extend(getattr(profile, "search_keywords", []) or [])
    if not families_by_id:
        raise ValueError("还没有可用的岗位方向，无法构建基础画像。")

    return CandidateProfile(
        confirmed=True,
        revision=0,
        primary_direction=direction,
        allowed_role_families=[
            RoleFamily(
                id=family_id,
                name=entry["name"],
                title_terms=list(dict.fromkeys(entry["terms"])),
            )
            for family_id, entry in families_by_id.items()
        ],
        preferences=list(digest.preferences) if digest is not None else [],
    )


class InterviewDraftCacheStore:
    """缓存预生成的首个访谈草稿：简历内容与画像版本不变时免重复生成。"""

    def __init__(self, path: Path | str = DEFAULT_DRAFT_CACHE_PATH):
        self.path = Path(path)

    def load_for(self, resume: str, profile_revision: int) -> InterviewDraft | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("resume_sha256") != resume_digest_hash(resume):
                return None
            if raw.get("profile_revision") != profile_revision:
                return None
            return InterviewDraft.model_validate(raw.get("draft"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, resume: str, profile_revision: int, draft: InterviewDraft) -> None:
        payload = {
            "resume_sha256": resume_digest_hash(resume),
            "profile_revision": profile_revision,
            "draft": InterviewDraft.model_validate(draft).model_dump(mode="json"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def resume_quote_exists(evidence: CandidateEvidence, resume: str) -> bool:
    """Check a claimed resume excerpt after normalizing Unicode and whitespace."""
    return _quote_exists(evidence.evidence_text, resume)


def _normalized_evidence_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _quote_exists(quote: str, text: str) -> bool:
    normalized_quote = _normalized_evidence_text(quote)
    return bool(normalized_quote and normalized_quote in _normalized_evidence_text(text))


class CandidateProfileService:
    def __init__(self, store: CandidateProfileStore, chain, researcher=None):
        self.store = store
        self.chain = chain
        self.researcher = researcher
        self.resume = ""
        self.resume_prompt = ""  # 模型看到的简历内容（结构化摘要或原文），校验始终用 resume 原文
        self.active_profile: CandidateProfile | None = None
        self.draft: InterviewDraft | None = None
        self.history: list[dict[str, str]] = []
        self.market_context = ""
        self.research_attempted = False
        self.researched_families: set = set()
        self.research_results: list[dict[str, str]] = []
        self.research_status = "未启用"
        self.sources_displayed = False

    def start_interview(self, resume: str) -> InterviewDraft:
        if not str(resume or "").strip():
            raise ValueError("resume text is required")
        self.resume = resume
        self.active_profile = self.store.load()
        self.draft = None
        self.history = []
        self.market_context = ""
        self.research_attempted = False
        self.researched_families = set()
        self.research_results = []
        self.research_status = "未启用"
        self.sources_displayed = False
        draft = self._invoke_chain(
            phase="direction",
            resume=self.resume,
            active_profile=self.active_profile,
            draft=None,
            history=[],
            answer=None,
        )
        if self.active_profile is not None and str(draft.primary_direction or "").strip():
            draft = draft.model_copy(update={"direction_source": "user_confirmed"})
        elif str(draft.primary_direction or "").strip() and draft.direction_source == "unknown":
            draft = draft.model_copy(update={"direction_source": "resume"})
        if self._direction_is_known(draft):
            draft = self._replace_direction_question(draft)
            draft = self._research_then_continue(draft)
        else:
            draft = self._ask_for_direction(draft)
        draft = self._merge_interview_evidence(None, draft, self.history)
        self.draft = self._guard_skill_question(draft)
        return self.draft

    @staticmethod
    def _direction_is_known(draft: InterviewDraft) -> bool:
        return bool(
            str(draft.primary_direction or "").strip()
            and draft.direction_source in {"resume", "user_confirmed"}
        )

    @staticmethod
    def _replace_direction_question(draft: InterviewDraft) -> InterviewDraft:
        question = str(draft.pending_question or "")
        direction_clarification_markers = (
            "求职方向",
            "职业方向",
            "应聘方向",
            "求职目标",
            "职业目标",
            "希望应聘哪个方向",
            "希望应聘什么方向",
            "希望主要应聘哪类岗位",
            "希望重点应聘哪些岗位",
            "想找什么工作",
            "想从事什么工作",
        )
        if any(marker in question for marker in direction_clarification_markers):
            return draft.model_copy(update={
                "pending_question": "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。",
            })
        return draft

    @staticmethod
    def _ask_for_direction(draft: InterviewDraft) -> InterviewDraft:
        return draft.model_copy(update={
            "primary_direction": "",
            "direction_source": "unknown",
            "allowed_role_families": [],
            "pending_question": "简历没有明确求职方向。你希望重点应聘哪些岗位方向？可以说一个主方向和愿意考虑的相邻岗位。",
            "ready_for_review": False,
        })

    def _guard_skill_question(self, draft: InterviewDraft) -> InterviewDraft:
        """无岗位市场资料时禁止无依据的技能追问（规范：提问前必须先搜索岗位技能体系）。

        问题提到的技能既不在简历、也没有用户对话确认过，且当前没有模型搜索到的
        岗位市场资料佐证时，降级为经历类澄清问题，不问无依据的技能问题。
        """
        question = str(draft.pending_question or "")
        if not question or self.market_context:
            return draft
        from prefilter import SKILL_SYNONYMS  # 延迟导入，避免与预筛模块循环依赖

        def normalized(value: str) -> str:
            return unicodedata.normalize("NFKC", str(value or "")).casefold()

        def appears(text: str, term: str) -> bool:
            needle = normalized(term)
            if not needle:
                return False
            if needle.isascii():
                return bool(re.search(
                    rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text
                ))
            return needle in text

        grounded = normalized(self.resume) + " " + normalized(" ".join(
            str(turn.get("content") or "")
            for turn in self.history
            if turn.get("role") == "user"
        ))
        question_lower = normalized(question)
        for key, synonyms in SKILL_SYNONYMS.items():
            if not (appears(question_lower, key)
                    or any(appears(question_lower, s) for s in synonyms)):
                continue
            if appears(grounded, key) or any(appears(grounded, s) for s in synonyms):
                continue
            return draft.model_copy(update={
                "pending_question": "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。",
            })
        return draft

    def _invoke_chain(self, phase: str, **kwargs) -> InterviewDraft:
        return self.chain.invoke(
            **kwargs,
            phase=phase,
            market_context=self.market_context,
            prompt_resume=self.resume_prompt or None,
        )

    def _merge_interview_evidence(
        self,
        previous: InterviewDraft | None,
        updated: InterviewDraft,
        history: list[dict[str, str]],
    ) -> InterviewDraft:
        """Accumulate grounded capability claims and keep unsupported claims pending."""
        user_text = "\n".join(
            str(turn.get("content") or "")
            for turn in history
            if turn.get("role") == "user"
            and turn.get("content") != "（用户跳过本问题）"
        )
        trusted_existing = {
            (
                _normalized_evidence_text(item.claim),
                _normalized_evidence_text(item.evidence_text),
            )
            for item in (self.active_profile.evidence if self.active_profile else [])
            if item.source == "user_confirmed"
        }
        evidence_by_key = {}
        proposals_by_claim = {}
        if self.active_profile is not None:
            for item in self.active_profile.evidence:
                if item.source == "user_confirmed":
                    evidence_by_key.setdefault(
                        (item.source, _normalized_evidence_text(item.claim),
                         _normalized_evidence_text(item.evidence_text)),
                        item,
                    )
                elif (
                    self.active_profile.resume_sha256 == resume_digest_hash(self.resume)
                    and resume_quote_exists(item, self.resume)
                ):
                    evidence_by_key.setdefault(
                        (item.source, _normalized_evidence_text(item.claim),
                         _normalized_evidence_text(item.evidence_text)),
                        item,
                    )
        drafts = [draft for draft in (previous, updated) if draft is not None]
        for draft in drafts:
            for item in draft.evidence:
                claim_key = _normalized_evidence_text(item.claim)
                quote_key = _normalized_evidence_text(item.evidence_text)
                grounded = (
                    resume_quote_exists(item, self.resume)
                    if item.source == "resume_quote"
                    else _quote_exists(item.evidence_text, user_text)
                    or (claim_key, quote_key) in trusted_existing
                )
                if not grounded:
                    proposals_by_claim.setdefault(
                        claim_key,
                        ProposedEvidence(
                            claim=item.claim,
                            clarification_question="请补充能说明这项能力的具体经历或结果。",
                        ),
                    )
                    continue
                key = (item.source, claim_key, quote_key)
                evidence_by_key.setdefault(key, item)

            for item in draft.proposed_evidence:
                claim_key = _normalized_evidence_text(item.claim)
                if item.evidence_text.strip() and _quote_exists(item.evidence_text, user_text):
                    evidence = CandidateEvidence(
                        claim=item.claim,
                        source="user_confirmed",
                        evidence_text=item.evidence_text,
                    )
                    key = (
                        evidence.source,
                        claim_key,
                        _normalized_evidence_text(evidence.evidence_text),
                    )
                    evidence_by_key.setdefault(key, evidence)
                else:
                    proposals_by_claim.setdefault(claim_key, item)

        confirmed_claims = {key[1] for key in evidence_by_key}
        proposals = [
            item for key, item in proposals_by_claim.items()
            if key not in confirmed_claims
        ]
        return updated.model_copy(update={
            "evidence": list(evidence_by_key.values()),
            "proposed_evidence": proposals,
        })

    @staticmethod
    def _format_market_context(results: list[dict[str, str]]) -> str:
        from datetime import date

        lines = [f"检索日期：{date.today().isoformat()}"]
        for item in results:
            title = item.get("title") or "未命名来源"
            url = item.get("url") or "无链接"
            content = item.get("content") or ""
            lines.append(f"- {title} | {url}\n  {content}")
        return "\n".join(lines) if results else ""

    def _search_role_families(self, direction: str, families: list[str]) -> None:
        """按职位族增量补搜岗位技能体系：每个职位族独立检索，来源按 URL 去重合并。"""
        self.research_attempted = True
        self.researched_families.update(families)
        for name in families:
            self.research_status = "搜索中"
            try:
                results = self.researcher.search(direction, [name])
            except Exception:
                self.research_status = "搜索失败，已回退到简历访谈"
                continue
            known_urls = {str(item.get("url") or "") for item in self.research_results}
            merged = [
                item for item in (results or [])
                if str(item.get("url") or "") not in known_urls
            ]
            if merged:
                self.research_results.extend(merged)
                self.sources_displayed = False
            self.market_context = self._format_market_context(self.research_results)
            self.research_status = (
                f"已获取 {len(self.research_results)} 条来源"
                if self.research_results else "没有找到可用来源"
            )

    def _research_then_continue(self, draft: InterviewDraft) -> InterviewDraft:
        families = [item.name for item in draft.allowed_role_families if item.name]
        pending = [name for name in families if name not in self.researched_families]
        first_pass = not self.research_attempted
        if getattr(self.researcher, "ready", False) and pending:
            # 规范：技能补充提问前必须先搜索岗位技能体系；按职位族增量补搜
            self._search_role_families(draft.primary_direction, pending)
        if not first_pass:
            # 之后的调用只做职位族增量补搜，不再追加模型调用
            return draft

        if not self.market_context:
            if draft.pending_question or draft.ready_for_review:
                return draft
            # 没有市场资料时，若模型本轮没给问题，用本地兜底问题，避免再发起一次模型调用
            families = "、".join(item.name for item in draft.allowed_role_families if item.name)
            question = (
                f"已识别职位族：{families}。你最早什么时候能到岗实习，每周能实习几天、能持续多久？"
                if families
                else "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。"
            )
            if not self.research_attempted:
                self.research_status = "未启用，使用简历访谈"
            return draft.model_copy(update={"pending_question": question})

        phase = "market_followup" if self.market_context else "interview"
        continued = self._invoke_chain(
            phase=phase,
            resume=self.resume,
            active_profile=self.active_profile,
            draft=draft,
            history=list(self.history),
            answer=None,
        )
        if not self.market_context:
            self.research_status = "未启用，使用简历访谈" if not self.research_attempted else self.research_status
        continued = continued.model_copy(update={
            "primary_direction": draft.primary_direction,
            "direction_source": draft.direction_source,
            "allowed_role_families": draft.allowed_role_families,
            "excluded_role_families": draft.excluded_role_families,
            "excluded_terms": draft.excluded_terms,
            "evidence": draft.evidence,
            "preferences": draft.preferences,
        })
        return self._replace_direction_question(continued)

    def answer(
        self,
        draft: InterviewDraft,
        text: str = "",
        skip: bool = False,
    ) -> InterviewDraft:
        if not self.resume:
            raise ValueError("start an interview before answering")
        if self.draft is not None and draft is not self.draft:
            raise ValueError("draft is stale or does not belong to this interview")
        if skip and str(text or "").strip():
            raise ValueError("a skipped answer cannot also contain answer text")

        previous_history = list(self.history)
        turn = {"role": "assistant", "content": draft.pending_question or "（画像补充）"}
        pending_history = [
            *previous_history,
            turn,
            {
                "role": "user",
                "content": "（用户跳过本问题）" if skip else str(text or "").strip(),
            },
        ]
        direction_was_known = self._direction_is_known(draft)
        try:
            updated = self._invoke_chain(
                phase="direction" if not direction_was_known else "interview",
                resume=self.resume,
                active_profile=self.active_profile,
                draft=draft,
                history=pending_history,
                answer="" if skip else str(text or "").strip(),
                skipped=skip,
            )
        except Exception:
            self.history = previous_history
            raise
        self.history = pending_history
        answer_text = str(text or "").strip()
        direction_denials = ("不确定", "没想好", "还没想好", "不知道", "没有方向")
        try:
            if (
                not direction_was_known
                and not skip
                and answer_text
                and not any(term in answer_text for term in direction_denials)
                and str(updated.primary_direction or "").strip()
                and updated.direction_source == "unknown"
            ):
                updated = updated.model_copy(update={"direction_source": "user_confirmed"})
            if not direction_was_known and not skip and self._direction_is_known(updated):
                updated = self._research_then_continue(updated)
            elif not direction_was_known:
                updated = self._ask_for_direction(updated)
            else:
                updated = updated.model_copy(update={
                    "primary_direction": draft.primary_direction,
                    "direction_source": draft.direction_source,
                    "allowed_role_families": draft.allowed_role_families,
                    "excluded_role_families": draft.excluded_role_families,
                    "excluded_terms": draft.excluded_terms,
                })
                updated = self._replace_direction_question(updated)
            if not updated.ready_for_review and not updated.pending_question:
                updated = updated.model_copy(update={
                    "pending_question": "请继续补充与求职方向相关的项目经历、能力证据或岗位偏好。",
                })
        except Exception:
            self.history = previous_history
            raise
        updated = self._merge_interview_evidence(draft, updated, pending_history)
        self.draft = self._guard_skill_question(updated)
        return self.draft

    def confirm(self, draft: InterviewDraft, user_approved: bool) -> CandidateProfile:
        if not user_approved:
            raise ValueError("candidate profile was not confirmed by the user")
        if not self.resume:
            raise ValueError("start an interview before confirming a profile")
        if self.draft is not None and draft is not self.draft:
            raise ValueError("draft is stale or does not belong to this interview")
        if not draft.ready_for_review:
            raise ValueError("interview draft is not ready for review")
        if not str(draft.primary_direction or "").strip() or not draft.allowed_role_families:
            raise ValueError("confirm a primary direction and at least one role family")

        invalid_quotes = [
            evidence.evidence_text
            for evidence in draft.evidence
            if evidence.source == "resume_quote" and not resume_quote_exists(evidence, self.resume)
        ]
        if invalid_quotes:
            raise ValueError("resume evidence is not present in the selected resume")

        user_text = "\n".join(
            str(turn.get("content") or "")
            for turn in self.history
            if turn.get("role") == "user"
            and turn.get("content") != "（用户跳过本问题）"
        )
        trusted_existing = {
            (
                _normalized_evidence_text(item.claim),
                _normalized_evidence_text(item.evidence_text),
            )
            for item in (self.active_profile.evidence if self.active_profile else [])
            if item.source == "user_confirmed"
        }
        invalid_user_quotes = [
            item.evidence_text
            for item in draft.evidence
            if item.source == "user_confirmed"
            and not _quote_exists(item.evidence_text, user_text)
            and (
                _normalized_evidence_text(item.claim),
                _normalized_evidence_text(item.evidence_text),
            ) not in trusted_existing
        ]
        if invalid_user_quotes:
            raise ValueError("user-confirmed evidence must quote an answer from this interview")

        profile = CandidateProfile(
            confirmed=True,
            revision=0,
            resume_sha256=resume_digest_hash(self.resume),
            primary_direction=draft.primary_direction,
            allowed_role_families=draft.allowed_role_families,
            excluded_role_families=draft.excluded_role_families,
            excluded_terms=draft.excluded_terms,
            evidence=draft.evidence,
            preferences=draft.preferences,
        )
        saved = self.store.save_confirmed(profile)
        self.active_profile = saved
        self.draft = None
        self.history = []
        self.resume = ""
        return saved

    def cancel(self) -> None:
        self.resume = ""
        self.active_profile = None
        self.draft = None
        self.history = []
        self.market_context = ""
        self.research_results = []
        self.research_attempted = False
