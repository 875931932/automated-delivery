"""Validated job-profile storage and search planning."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app_paths import get_data_dir, get_resource_dir
from candidate_profiles import CandidateProfile


DEFAULT_JOB_PROFILES_PATH = get_data_dir() / "job_profiles.json"
DEFAULT_SCREENING_RULES_PATH = get_resource_dir() / "screening_rules.md"


def _clean_required(value: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError("value must not be empty")
    return cleaned


class RequirementGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    options: list[str] = Field(min_length=1)
    mode: Literal["all", "any"] = "all"

    _validate_label = field_validator("label")(_clean_required)

    @field_validator("options")
    @classmethod
    def clean_options(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not cleaned:
            raise ValueError("requirement options must not be empty")
        return cleaned


class JobProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    enabled: bool = True
    role_family_id: str = ""
    search_keywords: list[str] = Field(min_length=1)
    role_direction: str = ""
    diagnostic_terms: list[str] = Field(default_factory=list)
    hard_requirements: list[RequirementGroup] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    threshold: int | None = Field(default=None, ge=0, le=100)

    _validate_id = field_validator("id")(_clean_required)
    _validate_name = field_validator("name")(_clean_required)

    @field_validator("role_family_id")
    @classmethod
    def clean_family(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("search_keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not cleaned:
            raise ValueError("at least one search keyword is required")
        return cleaned

    @field_validator("diagnostic_terms", "preferred_qualifications", "exclusions")
    @classmethod
    def clean_text_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


class JobProfileStore:
    def __init__(self, path: Path | str = DEFAULT_JOB_PROFILES_PATH):
        self.path = Path(path)

    def load(self) -> list[JobProfile]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("job profiles must be a JSON array")
            profiles = [JobProfile.model_validate(item) for item in raw]
            ids = [item.id for item in profiles]
            if len(ids) != len(set(ids)):
                raise ValueError("job profile IDs must be unique")
            return profiles
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid job profiles at {self.path}: {exc}") from exc

    def save(self, profiles: list[JobProfile]) -> None:
        validated = [JobProfile.model_validate(item) for item in profiles]
        ids = [item.id for item in validated]
        if len(ids) != len(set(ids)):
            raise ValueError("job profile IDs must be unique")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump([item.model_dump(mode="json") for item in validated],
                          temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def load_or_migrate(self, legacy_keyword: str) -> list[JobProfile]:
        if self.path.exists():
            return self.load()
        keyword = str(legacy_keyword or "").strip()
        if not keyword:
            return []
        draft = JobProfile(
            id="legacy-keyword",
            name=keyword,
            enabled=False,
            role_family_id="",
            search_keywords=[keyword],
        )
        self.save([draft])
        return [draft]


def eligible_profiles(
    profiles: list[JobProfile], candidate: CandidateProfile
) -> list[JobProfile]:
    if not candidate.confirmed:
        return []
    allowed_ids = {family.id for family in candidate.allowed_role_families}
    return [
        item for item in profiles
        if item.enabled and item.role_family_id and item.role_family_id in allowed_ids
    ]


def build_unique_queries(profiles: list[JobProfile]) -> list[dict]:
    queries: list[dict] = []
    by_normalized: dict[str, dict] = {}
    for profile in profiles:
        for raw_keyword in profile.search_keywords:
            keyword = str(raw_keyword or "").strip()
            if not keyword:
                continue
            normalized = keyword.casefold()
            query = by_normalized.get(normalized)
            if query is None:
                query = {"keyword": keyword, "profile_ids": []}
                by_normalized[normalized] = query
                queries.append(query)
            if profile.id not in query["profile_ids"]:
                query["profile_ids"].append(profile.id)
    return queries


def allocate_query_pages(queries: list[dict], page_budget: int) -> list[dict]:
    if page_budget < len(queries):
        raise ValueError(
            f"page budget ({page_budget}) must cover at least one page for "
            f"each unique query ({len(queries)})"
        )
    allocations = [
        {"keyword": item["keyword"], "profile_ids": list(item["profile_ids"]), "pages": [1]}
        for item in queries
    ]
    remaining = page_budget - len(allocations)
    page_by_query = [2] * len(allocations)
    while remaining > 0 and allocations:
        for index, allocation in enumerate(allocations):
            if remaining == 0:
                break
            allocation["pages"].append(page_by_query[index])
            page_by_query[index] += 1
            remaining -= 1
    return allocations


def load_screening_rules(path: Path | str = DEFAULT_SCREENING_RULES_PATH) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"screening rules cannot be read: {path}: {exc}") from exc
    if not content:
        raise ValueError(f"screening rules are empty: {path}")
    return content
