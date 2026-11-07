# Resume-Grounded Candidate Profile Interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LangChain-backed, resume-grounded interview that saves a candidate career boundary and evidence only after explicit user confirmation.

**Architecture:** Keep confirmed candidate data in a validated JSON profile store, AI prompting/parsing in a small LangChain adapter, and interview state transient in the desktop UI. AI may propose evidence and related role families, but only user-confirmed items enter the active profile; cancel and failure preserve the prior revision.

**Tech Stack:** Python 3, Tkinter, LangChain LCEL, `langchain-openai`, Pydantic, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-05-multi-role-profiles-design.md`

## Global Constraints

- Do not alter `.env` values or persist API keys outside `.env`.
- Do not start a job search or scoring flow until a confirmed candidate profile exists.
- Store only confirmed candidate profile revisions; interview transcript and draft remain in memory.
- AI-proposed evidence is never active until the user explicitly confirms it.
- Skipped interview questions remain unknown, not negative evidence.
- No interview operation may trigger job search, greeting generation, messaging, or delivery.
- Use mocked chat responses in automated tests; do not make paid model calls in tests.
- Do not overwrite an existing profile file or any existing unrelated workspace changes.
- The workspace has no `.git` repository; use test checkpoints instead of commits and do not initialize Git as part of this task.

---

## File Structure

- Create `requirements.txt` for the application's direct runtime dependencies, using the versions verified in the current interpreter: `DrissionPage==4.1.1.4`, `requests==2.33.1`, `python-dotenv==1.2.2`, `langchain==1.3.12`, `langchain-openai==1.3.4`, and `pydantic==2.13.4`.
- Create `candidate_profiles.py` for Pydantic models, JSON validation, atomic confirmed-profile persistence, and interview service operations.
- Create `ai_chains.py` for existing OpenAI-compatible configuration mapping, `ChatOpenAI` construction, and the interview LCEL chain. Later plan tasks add the multi-profile scoring chain here without duplicating model setup.
- Modify `desktop_panel.py` to add the candidate-profile interview and confirmation UI, with network calls kept off the Tk main thread.
- Create `tests/test_candidate_profiles.py` and `tests/test_ai_chains.py`; extend `tests/test_auto_deliver.py` only for the startup guard.

## Interfaces

`candidate_profiles.py` exports:

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    source: Literal["resume_quote", "user_confirmed"]
    evidence_text: str

class ProposedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str
    evidence_text: str
    clarification_question: str

class RoleFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    title_terms: list[str] = Field(default_factory=list)

class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    revision: int = Field(ge=0)
    primary_direction: str
    allowed_role_families: list[RoleFamily]
    excluded_role_families: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)

class InterviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_direction: str
    allowed_role_families: list[RoleFamily]
    excluded_role_families: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    proposed_evidence: list[ProposedEvidence] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    pending_question: str | None = None
    ready_for_review: bool = False

class CandidateProfileStore:
    def load(self) -> CandidateProfile | None: ...
    def save_confirmed(self, profile: CandidateProfile) -> CandidateProfile: ...

class CandidateProfileService:
    def __init__(self, store: CandidateProfileStore, chain: CandidateInterviewChain): ...
    def start_interview(self, resume: str) -> InterviewDraft: ...
    def answer(self, draft: InterviewDraft, text: str = "", skip: bool = False) -> InterviewDraft: ...
    def confirm(self, draft: InterviewDraft, user_approved: bool) -> CandidateProfile: ...
    def cancel(self) -> None: ...
```

`CandidateProfileService` holds the current resume, active profile, and `history: list[dict[str, str]]` only in instance memory for one interview. `start_interview(resume)` loads the confirmed profile, clears transient history, and asks the chain for an initial draft/question. `answer(...)` appends the user answer or skip marker, invokes the chain with the current draft/history, then appends a returned follow-up question. `cancel()` clears all transient data and does not write. `confirm()` refuses drafts not marked `ready_for_review`, refuses `user_approved=False`, and only then calls `save_confirmed()`. The chain interface is `CandidateInterviewChain.invoke(resume: str, active_profile: CandidateProfile | None, draft: InterviewDraft | None, history: list[dict[str, str]], answer: str | None, skipped: bool = False) -> InterviewDraft`; history is never persisted. `ai_chains.py` also exports `build_chat_model(config: dict) -> ChatOpenAI` and maps `ai_base_url`, `ai_api_key`, `ai_model`, `ai_timeout`, and `ai_max_retries` from `DELIVER_CONFIG` without changing `.env`.

Profile writes use a temporary file in the same directory followed by `Path.replace`, and increment the active profile revision only after an explicit confirmation. `confirm(..., user_approved=False)` raises `ValueError` and does not write.

---

### Task 1: Add the Minimal Runtime Dependency Manifest

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: Add the verified direct dependencies**

```text
DrissionPage==4.1.1.4
requests==2.33.1
python-dotenv==1.2.2
langchain==1.3.12
langchain-openai==1.3.4
pydantic==2.13.4
```

- [ ] **Step 2: Verify each pinned package is resolvable in the current environment**

Run: `python -m pip check`
Expected: `No broken requirements found.`

- [ ] **Step 3: Verify the manifest contains only direct runtime dependencies**

Run: `Get-Content requirements.txt`
Expected: the six pinned packages above; no transitive dependency dump and no development/test-only package.

### Task 2: Define Candidate Profile Schemas and Safe Persistence

**Files:**
- Create: `candidate_profiles.py`
- Create: `tests/test_candidate_profiles.py`

- [ ] **Step 1: Write failing schema and persistence tests**

Cover valid confirmed profile parsing; reject an unconfirmed profile, empty primary direction, and empty allowed families; round-trip provenance; validate every `resume_quote` evidence snippet against the selected resume after NFKC/whitespace normalization; load a missing profile as `None`; reject malformed JSON without rewriting it; save into a temporary directory; verify that cancellation never creates a file; verify a second confirmation increments `revision` while retaining the first confirmed profile until replacement succeeds.

```python
def test_save_confirmed_profile_increments_revision_without_losing_evidence():
    store = CandidateProfileStore(Path(self.temp_dir) / "candidate_profile.json")
    first = store.save_confirmed(make_profile(revision=0))
    second = store.save_confirmed(make_profile(revision=first.revision))
    self.assertEqual(second.revision, first.revision + 1)
    self.assertEqual(store.load().evidence[0].source, "resume_quote")
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the module is absent**

Run: `python -m unittest discover -s tests -p "test_candidate_profiles.py" -v`
Expected: import failure for `candidate_profiles`.

- [ ] **Step 3: Implement Pydantic v2 models and strict profile validation**

Use `BaseModel`, `ConfigDict(extra="forbid")`, bounded non-empty strings, and `Literal` evidence sources. Keep AI proposals in `InterviewDraft.proposed_evidence`; exclude that field entirely from `CandidateProfile`. Before accepting a `resume_quote`, verify its `evidence_text` is a real excerpt of the selected resume after NFKC/whitespace normalization; invalid citations stay as proposals for user correction and never become active evidence.

- [ ] **Step 4: Implement atomic load/save and revision handling**

`CandidateProfileStore.load()` returns `None` for a missing file and raises a typed validation error for malformed content. `save_confirmed()` validates `confirmed is True`, increments from the existing revision, writes UTF-8 JSON to a same-directory temporary file, then atomically replaces the target. Clean up the temporary file on failure and leave the existing target unchanged.

- [ ] **Step 5: Run the focused tests**

Run: `python -m unittest discover -s tests -p "test_candidate_profiles.py" -v`
Expected: all schema, provenance, cancellation, atomic-save, and revision tests pass.

### Task 3: Add the LangChain Resume Interview Chain

**Files:**
- Create: `ai_chains.py`
- Create: `tests/test_ai_chains.py`
- Modify: `candidate_profiles.py`

- [ ] **Step 1: Write failing tests around model configuration and interview output validation**

Patch the ChatOpenAI constructor and model runnable. Assert that base URL, API key, model name, timeout, and retry settings are forwarded; the prompt includes the resume, confirmed profile, transient conversation history, and current answer, not unrelated environment data; one invocation returns one next question or a `ready_for_review` draft; malformed family/evidence values raise validation errors.

```python
def test_interview_chain_asks_at_most_one_question_per_turn():
    chain = CandidateInterviewChain(model=fake_model({"pending_question": "你是否实际部署过该服务？"}))
    draft = chain.invoke(resume="Python 项目", active_profile=None, draft=None, history=[], answer=None)
    self.assertEqual(draft.pending_question, "你是否实际部署过该服务？")
```

- [ ] **Step 2: Run the tests and verify they fail before implementation**

Run: `python -m unittest discover -s tests -p "test_ai_chains.py" -v`
Expected: import failure for `ai_chains`.

- [ ] **Step 3: Implement the shared chat model factory and LCEL interview chain**

Build `ChatPromptTemplate | ChatOpenAI | PydanticOutputParser` (or equivalent typed parsing). Ask only one high-impact clarification at a time. Distinguish confirmed resume evidence, user answers, AI proposals, and unknowns. Pass the current transient `history` explicitly so the model sees earlier interview turns without persisting the transcript. A skipped answer is passed as `skipped=True` and must not become negative evidence.

- [ ] **Step 4: Add retry-safe error translation without persistence side effects**

Return a clear chain error on provider, timeout, JSON, or schema failures. The chain may return only a draft; it must never write profile files.

- [ ] **Step 5: Run the focused tests**

Run: `python -m unittest discover -s tests -p "test_ai_chains.py" -v`
Expected: all mock-only chain and configuration tests pass; no network request occurs.

### Task 4: Build the Guided Interview and Review UI

**Files:**
- Modify: `desktop_panel.py`
- Create: `tests/test_candidate_profile_ui.py` if UI helpers can be tested headlessly; otherwise test extracted non-Tk controller methods in `candidate_profiles.py`.

- [ ] **Step 1: Add a controller test for answer, skip, confirm, and cancel transitions**

Use a fake `CandidateInterviewChain` and temporary `CandidateProfileStore`. Assert that `answer(..., skip=True)` preserves unknown evidence, `confirm(..., user_approved=False)` does not save, and `confirm(..., user_approved=True)` saves exactly the reviewed draft.

- [ ] **Step 2: Run the controller test and confirm the transition API is missing**

Run: `python -m unittest discover -s tests -p "test_candidate_profiles.py" -v`
Expected: the newly added service-method assertions fail.

- [ ] **Step 3: Implement `CandidateProfileService` transitions**

Keep draft mutations isolated from the stored active profile. The service holds resume, active profile, and turn history in memory only; `cancel()` clears them. Refuse confirmation if direction or allowed families are empty. Convert only user-approved AI proposals into `user_confirmed` evidence; preserve resume quotations as `resume_quote` evidence only after verifying each quote against the selected resume. A false confirmation never calls `save_confirmed()`.

- [ ] **Step 4: Add a Candidate Profile tab to Tkinter**

Show the current confirmation status and summary. Add controls to start/restart interview, submit an answer, skip a question, cancel, review the proposed direction/families/evidence/exclusions/preferences, and explicitly confirm. Keep one pending question visible at a time.

- [ ] **Step 5: Keep model calls off the Tk main thread**

Run interview calls in a worker thread, deliver typed success/error events through a `queue.Queue`, and consume them from the existing `_poll` callback. Disable answer/start controls during a request and restore them on success/failure. Give each interview a generation token; after cancel/close, ignore queued responses from older generations so an in-flight model call cannot restore a discarded draft. Never update Tk widgets from the worker thread.

- [ ] **Step 6: Test the UI controller transitions and launch the panel for a local visual smoke check**

Run: `python -m unittest discover -s tests -p "test_candidate_profiles.py" -v`
Expected: all service transitions pass. Launch only the panel for inspection if no panel is already running; do not start the task runner. Confirm the review step is visible and cancellation leaves the active JSON unchanged.

### Task 5: Gate Task Startup on Confirmed Candidate Scope

**Files:**
- Modify: `desktop_panel.py`
- Modify: `auto_deliver.py`
- Modify: `tests/test_auto_deliver.py`

- [ ] **Step 1: Write failing startup-guard tests**

Assert that a missing or invalid confirmed candidate profile is checked before `PanelApp.start_task()` calls `write_env_file()` or `TaskRunner.start()`, prevents launching `auto_deliver.py`, displays an actionable message directing the user to the profile tab, and leaves `.env` unchanged. Assert that a confirmed profile allows normal dry-run startup.

- [ ] **Step 2: Run the focused tests and confirm the guard is absent**

Run: `python -m unittest discover -s tests -p "test_auto_deliver.py" -v`
Expected: the new guard test fails because startup does not check candidate profile state.

- [ ] **Step 3: Add a preflight validator shared by panel and process entry point**

Load the candidate profile before creating a browser session. On invalid/missing profile, log a configuration error and exit before login, search, AI scoring, greeting generation, or delivery.

- [ ] **Step 4: Verify `.env` is untouched and run the full suite**

Capture the `.env` SHA-256 before and after the test command.

Run: `python -m unittest discover -s tests -v`
Expected: all tests pass and `.env` hashes match.

### Task 6: Verify Candidate Interview Acceptance

**Files:**
- Modify: `docs/superpowers/specs/2026-11-05-multi-role-profiles-design.md` only if the implementation reveals a genuine design mismatch.

- [ ] **Step 1: Run static checks and the complete test suite**

Run: `python -m compileall -q candidate_profiles.py ai_chains.py desktop_panel.py auto_deliver.py`
Run: `python -m unittest discover -s tests -v`
Expected: compile succeeds and all tests pass.

- [ ] **Step 2: Exercise the interview with a mocked model in dry-run UI mode**

Use a deterministic fake response to create a draft, skip one question, answer one question, review the final direction/families, and confirm. Verify `candidate_profile.json` contains only confirmed evidence and no raw transcript/API key.

- [ ] **Step 3: Verify no search or delivery was triggered by interview actions**

Assert the fake browser/search and delivery methods have zero calls throughout interview creation, answer, skip, cancel, and confirmation.

- [ ] **Step 4: Record the verified behavior in the design/spec notes**

Record exact test commands and outcomes; do not claim a live model was tested unless the user explicitly authorizes a separate dry-run using their configured endpoint.

