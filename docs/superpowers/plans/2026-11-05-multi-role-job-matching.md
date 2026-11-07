# Multi-Role Job Search and Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed AI-development search gate with user-confirmed role families, configurable job profiles, deduplicated multi-keyword search, and one AI scoring request per in-scope job.

**Architecture:** Read confirmed candidate scope from `candidate_profiles.py`, job profiles from a separate validated store, and shared screening policy from Markdown. Search unique keywords under common platform filters with a shared page budget, merge jobs by ID, apply a deterministic confirmed-scope gate, then use the shared LangChain adapter to score all enabled in-scope profiles in one request per job.

**Tech Stack:** Python 3, requests, LangChain LCEL, `langchain-openai`, Pydantic, Tkinter, CSV/JSON, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-05-multi-role-profiles-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-11-05-candidate-profile-interview.md` first; consume its `CandidateProfile`, `CandidateProfileStore`, and `build_chat_model` interfaces.
- Use confirmed career families and exclusions only. Never broaden scope from model inference, a job title, or a search keyword alone.
- A clear out-of-scope job is recorded `out_of_scope`; an ambiguous job is recorded `scope_review`. Neither reaches the job-scoring chain.
- Make at most one profile-scoring model call per unique in-scope job. This limit does not include a separately retained greeting-preview call.
- Apply the same configured platform filters to every query and enforce `DELIVER_MAX_PAGES` as one shared budget.
- If unique query count exceeds the page budget, stop before browser/search work with an actionable validation error.
- Keep resume skill-tag overlap diagnostic only; it must not reject jobs or alter AI scores.
- Do not change `.env` values, overwrite user profile files, or disturb unrelated workspace data.
- Tests and acceptance runs must set dry-run and assert zero message-send/delivery actions. Do not perform real applications.
- No Git repository exists in the workspace; do not initialize one or make commits. Use focused test checkpoints.

---

## File Structure

- Create `job_profiles.py` for Pydantic job-profile models, JSON persistence, one-time legacy keyword migration, query aggregation, and page allocation.
- Create `screening_rules.md` as the editable shared matching-policy prompt.
- Extend `ai_chains.py` from the candidate interview plan with a typed multi-profile scoring chain; keep one shared `ChatOpenAI` factory.
- Modify `auto_deliver.py` to load/validate profiles and rules before browser work; orchestrate unique keyword searches, merge listings, run the scope gate, score in-scope jobs, choose a primary passing profile, and record all profile results.
- Modify `boss_spider.py` only where needed to make configured query/filter data explicit or to remove the fixed `is_relevant` gate from this delivery path. Preserve unrelated standalone crawler behavior unless the tests show its whitelist is the same blocking path.
- Modify `desktop_panel.py` to manage job profiles and expose primary/per-profile assessment results while preserving the existing global platform-filter tab and `.env` behavior.
- Extend `tests/test_auto_deliver.py`; create `tests/test_job_profiles.py` and extend `tests/test_ai_chains.py`.

## Interfaces

`job_profiles.py` exports:

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class RequirementGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    options: list[str] = Field(min_length=1)
    mode: Literal["all", "any"] = "all"

class JobProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    enabled: bool = True
    role_family_id: str = ""
    search_keywords: list[str] = Field(default_factory=list)
    role_direction: str = ""
    hard_requirements: list[RequirementGroup] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    threshold: int | None = Field(default=None, ge=0, le=100)

class JobProfileStore:
    def load(self) -> list[JobProfile]: ...
    def save(self, profiles: list[JobProfile]) -> None: ...
    def load_or_migrate(self, legacy_keyword: str) -> list[JobProfile]: ...

def eligible_profiles(profiles: list[JobProfile], candidate: CandidateProfile) -> list[JobProfile]: ...
def build_unique_queries(profiles: list[JobProfile]) -> list[dict]: ...
def allocate_query_pages(queries: list[dict], page_budget: int) -> list[dict]: ...
```

`eligible_profiles()` returns enabled profiles whose non-empty `role_family_id` exists in the candidate's confirmed `allowed_role_families`. Unassigned migration profiles remain disabled/ineligible until explicit UI binding. `build_unique_queries()` takes eligible profiles and returns entries shaped as `{"keyword": str, "profile_ids": list[str]}`. Keywords are stripped, case-fold deduplicated, and preserve the first original display spelling. `allocate_query_pages()` returns `{"keyword": str, "profile_ids": list[str], "pages": list[int]}`; it raises `ValueError` if `page_budget < len(queries)`, assigns page 1 to every query, and allocates remaining pages round-robin.

`ai_chains.py` adds:

```python
class ProfileAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str
    score: int = Field(ge=0, le=100)
    role_fit: int = Field(ge=0, le=100)
    hard_gaps: list[str] = Field(default_factory=list)
    unverified_requirements: list[str] = Field(default_factory=list)
    preferred_matches: list[str] = Field(default_factory=list)
    preferred_gaps: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence]
    reason: str
    disqualified: bool = False
    disqualification_reason: str = ""

class JobMatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_results: list[ProfileAssessment]

class JobScoringChain:
    def invoke(self, resume: str, candidate_profile: CandidateProfile,
               job: dict, profiles: list[JobProfile], rules: str) -> JobMatchResponse: ...
```

`auto_deliver.py` adds pure functions:

```python
def classify_job_scope(job: dict, candidate: CandidateProfile) -> tuple[str, str]: ...
def choose_primary_assessment(response: JobMatchResponse,
                              profiles: list[JobProfile], global_threshold: int
                              ) -> ProfileAssessment | None: ...
```

`classify_job_scope` returns `("in_scope", reason)`, `("out_of_scope", reason)`, or `("scope_review", reason)`. It uses normalized confirmed family aliases/title terms and explicit confirmed exclusions against the job title and primary duties; incidental mentions in a JD do not count as a role match or exclusion. It is independent of query provenance or job-profile routing. Explicit exclusion wins; one or more confirmed in-scope matches pass; no match is `scope_review`, not an inferred pass. `choose_primary_assessment` validates assessments against all enabled eligible profile IDs and returns the highest-scoring assessment that meets its own threshold or the global fallback and is not disqualified; otherwise it returns `None`.

---

### Task 1: Define Job Profiles, Persistence, and Legacy Migration

**Files:**
- Create: `job_profiles.py`
- Create: `tests/test_job_profiles.py`

- [ ] **Step 1: Write failing model and store tests**

Cover required `id`, `name`, `role_family_id`, and non-empty `search_keywords`; enabled/default fields; threshold range; alternative hard-requirement group representation; JSON round-trip; malformed JSON; save to temporary path; and no overwrite of an existing user file during migration.

```python
def test_load_or_migrate_creates_disabled_legacy_draft_only_when_file_is_missing():
    store = JobProfileStore(Path(self.temp_dir) / "job_profiles.json")
    profiles = store.load_or_migrate("AI应用开发")
    self.assertEqual(profiles[0].search_keywords, ["AI应用开发"])
    self.assertEqual(profiles[0].role_family_id, "")
    self.assertFalse(profiles[0].enabled)
```

The migrated profile is deliberately inactive for search until the user associates it with a confirmed family and explicitly enables it.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`
Expected: import failure for `job_profiles`.

- [ ] **Step 3: Implement strict Pydantic models and atomic persistence**

Use extra-field rejection, non-empty IDs/names/keywords, and `threshold` constrained to 0-100. Persist UTF-8 JSON atomically using a same-directory temp file followed by replace.

- [ ] **Step 4: Implement one-time legacy migration without fabricated requirements**

When and only when the target profile file is missing, create one disabled profile from a non-empty `DELIVER_KEYWORD`; set `role_family_id` empty and all inferred criteria empty. Never enable it until the user links it to a confirmed family and explicitly enables it. If the file already exists, load it as-is and never append the legacy keyword implicitly.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`
Expected: all validation, persistence, migration, and no-overwrite tests pass.

### Task 2: Implement Query Deduplication and Shared Page Allocation

**Files:**
- Modify: `job_profiles.py`
- Modify: `tests/test_job_profiles.py`

- [ ] **Step 1: Write failing query and budget tests**

After `eligible_profiles()` filters disabled/unassigned profiles, verify identical keywords across eligible profiles become one query preserving every profile ID; case/space normalization deduplicates deterministically; every query gets page 1; remaining pages are round-robin; a budget smaller than query count raises before any request.

```python
def test_shared_budget_allocates_one_page_per_query_then_round_robin():
    queries = build_unique_queries([profile("a", ["backend"]), profile("b", ["robotics"])])
    allocations = allocate_query_pages(queries, page_budget=5)
    self.assertEqual([item["pages"] for item in allocations], [[1, 2, 3], [1, 2]])
```

- [ ] **Step 2: Run the focused tests and verify missing functions fail**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`
Expected: errors for undefined query-builder/allocation functions.

- [ ] **Step 3: Implement deterministic query construction**

Keep profile attribution for every unique normalized keyword. Ignore blank terms defensively but have model validation prevent saving profiles with no nonblank terms.

- [ ] **Step 4: Implement page allocation**

Raise `ValueError` when the budget cannot cover one first page per unique query. Otherwise assign the first page to all queries and distribute remaining page numbers round-robin, preserving page order per keyword.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`
Expected: all query provenance and budget tests pass.

### Task 3: Add and Validate the Shared Screening Rules File

**Files:**
- Create: `screening_rules.md`
- Create/modify: `tests/test_ai_chains.py`

- [ ] **Step 1: Define a rules-file loader test**

Test that a non-empty Markdown rules file loads verbatim; missing, unreadable, and whitespace-only files raise a configuration exception before a model is invoked.

- [ ] **Step 2: Add `screening_rules.md` with explicit evidence and requirement semantics**

Include: classify core duties, hard requirements, OR alternatives, preferred items, ambiguous lists, and team background separately; resume omission means unverified, not absent; only explicit evidence supports technical hard gaps; absence of bonuses is not a hard gap; transferable experience must not invent tools; do not multiply-penalize equivalent requirements.

- [ ] **Step 3: Implement the small rules loader in `job_profiles.py` or a focused `screening_config.py`**

Expose `load_screening_rules(path: Path) -> str`; do not silently fall back to an embedded duplicate.

- [ ] **Step 4: Run the rules loader tests**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`
Expected: valid rules load, invalid states fail before any AI call.

### Task 4: Add Strict Multi-Profile Scoring to the Shared LangChain Adapter

**Files:**
- Modify: `ai_chains.py`
- Modify: `tests/test_ai_chains.py`

- [ ] **Step 1: Write mocked response contract tests**

Cover exactly one assessment for each requested profile; valid score bounds; OR-group satisfaction; preferred gaps not counted as hard gaps; omission represented as unverified; explicit disqualification; malformed JSON; duplicate, unknown, or missing profile IDs; and evidence provenance limited to `resume_quote` or `user_confirmed`.

```python
def test_scoring_chain_requires_exactly_one_result_per_profile():
    chain = JobScoringChain(model=fake_model(valid_multi_profile_json()))
    result = chain.invoke(resume, candidate, job, [backend_profile, robotics_profile], rules)
    self.assertEqual({item.profile_id for item in result.profile_results}, {"backend", "robotics"})
```

- [ ] **Step 2: Run focused tests and confirm the new scoring types are missing**

Run: `python -m unittest discover -s tests -p "test_ai_chains.py" -v`
Expected: import/assertion failures for the scoring chain/types.

- [ ] **Step 3: Implement Pydantic output models and prompt construction**

Send only the resume, confirmed candidate profile evidence and career boundary, complete available JD, in-scope enabled job profiles, and shared rules. Do not send the interview transcript or unconfirmed AI draft. Require all requested profile IDs exactly once.

- [ ] **Step 4: Implement parser validation and fail-closed behavior**

Reject malformed JSON, score values outside 0-100, missing/duplicate/unknown IDs, unsupported evidence provenance, or absent required assessment fields. Return a typed failure to the caller; never synthesize a passing score.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest discover -s tests -p "test_ai_chains.py" -v`
Expected: mock-only chain tests pass without live network calls.

### Task 5: Implement Confirmed Career Scope and Threshold Selection

**Files:**
- Modify: `auto_deliver.py`
- Modify: `tests/test_auto_deliver.py`

- [ ] **Step 1: Write failing pure-function tests**

Verify title/primary-duty aliases for confirmed backend and robotics families pass; confirmed sales/real-estate exclusions return `out_of_scope`; a sales term appearing only in a peripheral JD clause does not cause exclusion; no family match returns `scope_review`; exclusion wins if both allowed and excluded terms appear; search provenance does not restrict evaluated profiles; thresholds fall back to global when unset; highest passing score is selected; no passing score returns `None`.

- [ ] **Step 2: Run tests and confirm the new helpers are missing**

Run: `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`
Expected: import failure for `classify_job_scope` and `choose_primary_assessment`.

- [ ] **Step 3: Implement normalized, deterministic scope classification**

Normalize NFKC text and case-fold Latin terms. Use only user-confirmed aliases, title terms, and exclusions; do not include the former global AI/development whitelist. Keep ambiguous scope at `scope_review` to avoid expanding the career boundary silently.

- [ ] **Step 4: Implement profile-specific threshold selection**

For each valid assessment, resolve `profile.threshold` or `MATCH_THRESHOLD`; remove disqualified and below-threshold assessments from passing candidates; return the highest score, preserving all original assessments for result storage.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`
Expected: all scope and threshold-selection tests pass.

### Task 6: Add Multi-Profile Configuration and Results to the Desktop Panel

**Files:**
- Modify: `desktop_panel.py`
- Create/modify: `tests/test_job_profiles.py`

- [ ] **Step 1: Write store/controller tests for CRUD and family binding**

Cover add/edit/enable/disable/delete, keyword parsing, threshold validation, role-family selection restricted to confirmed allowed families, legacy-profile family binding, and no `.env` writes as a side effect of opening/saving a profile.

- [ ] **Step 2: Implement a Job Profiles tab with a profile list and editor**

Provide explicit controls for profile selection, add, update, delete, and enabled state. Use multiline text fields for direction, hard requirements, preferred qualifications, and exclusions; represent alternative requirement groups with a clear group label so an OR group is not split into separate hard requirements. Edit and save `job_profiles.json` independently from `.env`.

- [ ] **Step 3: Bind migrated profile to a confirmed family**

After the candidate profile is confirmed, require the user to choose which confirmed allowed role family the legacy profile represents. Keep it ineligible until that binding is saved.

- [ ] **Step 4: Add result columns without breaking historical CSV rows**

Append `主岗位画像`, `岗位画像分数`, and `岗位画像评估详情` to `RESULT_FIELDS`. Read old rows with empty defaults. Show the primary profile and compact reason in the table; put serialized assessment detail in the existing readable detail/result surface without overwriting historical score columns.

- [ ] **Step 5: Run tests and inspect the panel without starting a task**

Run: `python -m unittest discover -s tests -p "test_job_profiles.py" -v`; `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`
Expected: CRUD/persistence/result compatibility tests pass. If a panel process is already running, do not restart or close it; launch a separate instance only if safe and only for configuration UI inspection, never press Start.

### Task 7: Refactor the Delivery Pipeline to Search, Merge, Scope, and Score

**Files:**
- Modify: `auto_deliver.py`
- Modify: `boss_spider.py`
- Modify: `tests/test_auto_deliver.py`

- [ ] **Step 1: Write flow tests with fake API/detail/scoring collaborators**

Test shared platform filters on every query; page allocation; partial query failure continuing other queries; duplicate job ID merged once with all profile/query provenance; detail fetch exactly once; explicit out-of-scope and `scope_review` jobs cause zero scoring calls; one scoring call per unique in-scope job; all enabled eligible profile assessments persisted regardless of the query that found the job; primary profile picked from passing scores; and zero delivery calls in dry-run. Include jobs with a master's degree or years-of-experience value that do not match the resume and assert they are not dropped by the old hard-coded `_hard_reject` before profile-aware evaluation.

- [ ] **Step 2: Run the focused tests and confirm old flow violates them**

Run: `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`
Expected: failures show the fixed keyword/whitelist and single-profile match flow do not meet the new tests.

- [ ] **Step 3: Add a preflight stage before browser initialization**

Load confirmed candidate profile, job profiles, and rules. Select only enabled profiles linked to confirmed allowed families. If profile/rules validation fails, no browser, search, or model client is started. Build unique query/page allocations and fail before requests when the shared page budget is insufficient. For legacy migration, create only a disabled/unassigned draft; require explicit family binding and explicit enablement before search.

- [ ] **Step 4: Search every allocated query under the shared platform filters**

Before each `api_job_list` request, set the query keyword and apply city, region, and job type consistently. Call only allocated pages. Catch per-query failure, log query/profile provenance, and continue other query entries.

- [ ] **Step 5: Merge results and remove the fixed title/function gate from this delivery path**

Merge by `encryptJobId`, retaining originating keyword and profile IDs. Keep duplicate/history, company blacklist, and explicit global platform/user filters. Do not invoke `is_relevant` or generic `_role_function_reject` to decide candidate role family.

- [ ] **Step 6: Fetch detail once and run the local scope gate before AI scoring**

Record `out_of_scope` or `scope_review` with a reason and continue without invoking the scoring chain. For `in_scope`, proceed to explicitly configured global work-time/rest-day conditions. Remove the hard-coded education/experience checks in `_hard_reject`; send these requirements to per-profile AI assessment unless an equivalent global filter is explicitly configured by the user.

- [ ] **Step 7: Score each in-scope job exactly once and record all assessments**

Call `JobScoringChain.invoke` once. Validate all enabled eligible profiles are represented, calculate the primary passing profile, preserve every profile assessment in result JSON/CSV, and only continue to any local greeting preview when a primary profile passes. Keep resume tag overlap diagnostic-only.

- [ ] **Step 8: Ensure dry-run never sends or applies**

Exercise the dry-run branch with the delivery action mocked and assert zero `deliver_one`/send calls. If greeting preview is retained, count that separately from the one scoring call.

- [ ] **Step 9: Remove only obsolete config wiring after regression tests pass**

Remove `DELIVER_KEYWORD` from the active panel search path only after the legacy migration tests pass. Keep migration support for existing `.env`; do not rewrite `.env` from tests. Remove or bypass the fixed `is_relevant` whitelist in the auto-delivery path; leave unrelated standalone crawler behavior unchanged unless its own user-facing flow is explicitly migrated.

- [ ] **Step 10: Run focused tests**

Run: `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`; `python -m unittest discover -s tests -p "test_job_profiles.py" -v`; `python -m unittest discover -s tests -p "test_ai_chains.py" -v`
Expected: all new search, scope, AI contract, migration, and existing regression tests pass.

### Task 8: End-to-End Dry-Run Acceptance and Compatibility Audit

**Files:**
- Modify: `docs/superpowers/specs/2026-11-05-multi-role-profiles-design.md` only to correct verified implementation drift.

- [ ] **Step 1: Hash `.env` and existing profile/result files before validation**

Use `Get-FileHash -Algorithm SHA256` for `.env`, any pre-existing `candidate_profile.json` or `job_profiles.json`, and current results. Do not back up or rewrite files unless the test needs isolated temporary paths.

- [ ] **Step 2: Run compile and complete unit tests**

Run: `python -m compileall -q auto_deliver.py boss_spider.py desktop_panel.py candidate_profiles.py job_profiles.py ai_chains.py`
Run: `python -m unittest discover -s tests -v`
Expected: compile succeeds; all tests pass.

- [ ] **Step 3: Run a bounded dry-run with mocked or explicitly approved model calls**

Set test configuration in memory or a temporary test environment, not the user's `.env`; use at least two confirmed role families and overlapping keywords; cap to a small number of pages/jobs; assert one query per unique keyword, one detail per job ID, at most one scoring call per unique in-scope job, per-profile output completeness, and zero send/delivery calls.

- [ ] **Step 4: Audit result compatibility and status accounting**

Verify legacy CSV rows render; new rows include primary profile and all profile assessments; `out_of_scope`, `scope_review`, AI failure, below-threshold, and dry-run-ready states remain distinguishable. Profile-family, alternative-requirement, and result data survive one read/write cycle without loss.

- [ ] **Step 5: Verify persistent files and `.env` hashes**

Compare hashes captured in Step 1. Automated tests must leave user `.env` and pre-existing profile files unchanged unless an explicit isolated acceptance step intentionally confirmed a new profile; report any expected artifact hash change.

- [ ] **Step 6: Run full suite once more after any compatibility fixes**

Run: `python -m unittest discover -s tests -v`
Expected: all tests pass and delivery/send count remains zero.

