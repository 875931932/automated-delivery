# Resume-Grounded Candidate Profiles, Multi-Role Search, and AI Screening

Date: 2026-11-05
Status: Draft for user review

## Problem

The current delivery flow searches one configured keyword, then applies a hard-coded AI/development title whitelist. Role-function rejection rules and most AI matching policy are also embedded in Python. This narrows the system to a small set of engineering roles. The resume is also the only candidate evidence source, even though an application resume may omit relevant experience; at the same time, the system must not broaden a user's confirmed career direction into unrelated work such as sales or real estate.

The system must support several independently configurable job directions while keeping platform search filters global, avoiding duplicate work for jobs found by multiple queries, and limiting AI cost to one evaluation request per job.

## Goals

- Let users maintain multiple job profiles and enable or disable each profile from the desktop panel.
- Guide the user through a resume-grounded natural-language interview to confirm one career-direction boundary and enrich candidate evidence.
- Keep the candidate profile distinct from job profiles: candidate profile says what the user can do and which related role families are in scope; job profiles say which roles and conditions to search within that boundary.
- Search each enabled profile using its configured platform keywords and merge results by job ID.
- Evaluate every enabled profile against each unique job in one AI request, returning separate evidence and scores.
- Let users specify role duties, hard requirements, preferred qualifications, exclusions, and a per-profile threshold.
- Load general screening policy from an editable Markdown rules file and pass it to the user-configured OpenAI-compatible model.
- Use LangChain's OpenAI-compatible chat adapter and prompt/output parsing for both the profile interview and job assessments.
- Remove fixed AI/development title and role-function assumptions from the screening path.
- Keep tests in dry-run mode; do not perform real applications or send greetings during verification.

## Non-Goals

- Replacing BOSS platform search or adding other recruitment platforms.
- Replacing the existing AI provider configuration or requiring a provider-specific Skills protocol.
- Introducing autonomous agents, LangGraph orchestration, vector memory, or per-job conversational interviews.
- Making resume skill-tag overlap a rejection condition.
- Reworking unrelated company blacklist, duplicate tracking, result display, or browser automation behavior except where needed to carry profile results.
- Changing `.env` values as part of implementation or design validation.

## Approaches Considered

1. **Per-profile search, one merged evaluation request per job (recommended).** Search each enabled profile's terms under the shared platform filters, deduplicate jobs, fetch each detail once, and ask AI to score all enabled profiles in one request. This preserves coverage while bounding duplicate work and model calls.
2. **One broad combined search query.** This reduces query requests but relies on undocumented platform interpretation of combined terms and risks missing narrower role directions.
3. **Run a complete independent pipeline per profile.** This isolates results but duplicates listing, detail fetches, and AI calls for jobs matching multiple profiles.

Approach 1 is selected.

## Configuration Model

### Job profiles

Store profiles in a separate UTF-8 JSON file, `job_profiles.json`, beside the application. The desktop panel owns editing and persistence. Each profile contains:

- Stable `id` used in results and logs.
- Human-readable `name`.
- `enabled` boolean.
- One or more `search_keywords` used as platform query terms.
- `role_direction` describing the work the user wants.
- `hard_requirements`, represented as individual conditions or explicit alternative groups. For example, "C++, Python, or Java" is one alternative group and is satisfied by any one listed option.
- `preferred_qualifications`, which can improve a fit but whose absence is not a hard gap.
- `exclusions`, describing roles or conditions the user explicitly does not want.
- Optional `threshold`; if empty, use the existing global match threshold.

Each active job profile also has a `role_family_id` that must reference a user-confirmed allowed family in the candidate profile. A legacy migration draft may have no family link, but remains disabled and ineligible until the user binds it to a confirmed family. The UI supports listing, adding, editing, enabling/disabling, and deleting profiles. Input validation rejects attempts to enable profiles without a name, search keyword, or confirmed in-scope role family, and threshold values outside 0-100. Empty descriptive criteria are allowed, but the panel should warn that a profile with only a name and keyword gives the model less role-specific guidance.

### Candidate profile and guided interview

Store the candidate profile separately in `candidate_profile.json`. It contains:

- Confirmation state and a revision/version identifier.
- One confirmed primary career direction.
- `allowed_role_families`, such as AI application development, backend development, or robotics development, each with user-confirmed aliases and title terms.
- Explicit `excluded_role_families` and exclusion terms, such as sales or real estate, when the user says those are out of scope.
- Confirmed candidate evidence items with a concise claim, supporting resume quote or user answer, and provenance (`resume_quote` or `user_confirmed`). AI-proposed claims remain only in the unsaved interview draft and never enter active evidence until the user confirms them.
- User-confirmed preferences relevant across roles, separate from factual skills and experience.

The desktop panel provides a guided conversation based on the selected resume and any already-confirmed candidate profile. LangChain proposes a structured draft and asks one high-impact clarification at a time, focusing only on resume ambiguities that could change role scope or fit. The user can answer or skip each question. The flow ends with a review step for candidate evidence, the primary direction, allowed adjacent job families, and explicit exclusions. Only an explicit user confirmation saves a new active revision. Canceling or closing the interview discards the draft and preserves the prior confirmed revision. Later conversations create a pending revision and do not overwrite the active profile until confirmed.

The panel must not start automated searching or matching until a confirmed candidate profile exists. If there is no confirmed primary direction or allowed family, the user must finish or explicitly cancel the profile setup; the system must not infer career scope from a resume or search keyword alone.

Before AI job scoring, a local scope gate compares the job title and primary duties against all confirmed allowed family aliases and exclusions in the candidate profile. Incidental mentions elsewhere in a JD do not establish a role-family match or exclusion. Search provenance does not narrow the candidate's confirmed scope or the profiles evaluated. Explicit out-of-scope matches are recorded as `out_of_scope`; ambiguous/unclassifiable jobs are recorded as `scope_review`. Both statuses are excluded from scoring and delivery until the user expands or clarifies the confirmed scope. Users can expand aliases/families through the guided interview and confirmation flow. This gate is profile-driven, not a fixed AI/developer whitelist.

### LangChain integration

Use `langchain` and `langchain-openai` with the existing OpenAI-compatible `AI_BASE_URL`, key, model, timeout, and retry settings. Use a small LCEL pipeline built from `ChatPromptTemplate`, `ChatOpenAI`, and output parsing/validation. Keep the panel's current conversation transcript in UI/session state and send the needed messages on each turn; persist only confirmed candidate profile revisions. Reuse the same model adapter for one-per-job profile scoring. Do not add agent tools, LangGraph, or model-managed long-term memory in this iteration.

Because OpenAI-compatible providers vary in structured-output support, request JSON-compatible output through the chat model where supported and validate all interview/scoring responses locally against Pydantic or equivalent typed schemas. Invalid output must not mutate a profile or pass a job. Keep provider configuration in the existing `.env`; never persist API keys in profile or conversation files.

The project currently has no dependency manifest. Add a concise `requirements.txt` that lists the application's direct runtime dependencies and the LangChain integration at tested compatible versions; do not dump the entire development environment into it.

Global platform filters (city, region, job type) remain separate from profiles and apply to every query. Existing explicitly enabled global work-time/area filters remain available. The current hard-coded early education/experience rejections are not global user settings and must be removed from the automatic gate; evaluate these through explicit profile conditions and the matching rules. The system must not silently treat absent resume details as proof that a role condition is unmet.

### General matching rules

Store shared policy in a bundled, editable Markdown file, `screening_rules.md`. Load and validate it before search/evaluation starts, then include it in the AI request. It defines how to distinguish:

- Core duties and explicit hard requirements.
- Alternative requirement groups, where one acceptable option satisfies the group.
- Preferred/bonus qualifications.
- Ambiguous technology lists and team background that are not necessarily requirements.
- Resume evidence, transferable experience, and unverified items.

The policy must preserve the existing evidence standard: a resume is often a concise application document; omission means unverified, not absent. Preferred-item absence does not count as a hard gap. Similar experience may be considered transferable without claiming an unmentioned tool or skill. The model may not convert an alternative group into multiple independent requirements.

The rules file is independent from role profiles. It must not contain per-user secrets or require a model-specific Skills feature. Missing, unreadable, or blank rules are configuration errors and stop screening before AI calls; the system does not silently fall back to hard-coded policy.

## Search and Screening Flow

1. Load global settings, candidate profile, job profiles, dependencies, and the shared rules file. Validate all local configuration before browser work.
2. Require a confirmed candidate profile revision. If none exists, direct the user to the guided interview and stop before searching or scoring.
3. Keep only enabled job profiles whose `role_family_id` belongs to the confirmed allowed career scope. If none remain, stop with a clear configuration message and do not search or call AI.
4. Expand eligible job profiles into unique keyword queries and retain the set of profile IDs associated with each keyword. If several profiles use the same keyword, search it once rather than issuing duplicate platform requests.
5. Apply the same city, region, job-type, and other selected platform filters to every query.
6. Treat `DELIVER_MAX_PAGES` as the shared per-run page-request budget across unique queries, rather than a full budget per profile. Guarantee at least the first page for every unique query. If the configured budget is lower than the number of unique queries, report a validation error before searching; do not silently skip queries. Allocate remaining pages round-robin until the shared budget is exhausted or searches end.
7. Continue after an individual query failure, logging the query and error. Other queries may still produce candidates.
8. Merge listings by job ID and retain all profile/query provenance. Apply duplicate/history and existing non-role company filters once per job. Remove the static `is_relevant` title whitelist from this pipeline.
9. Fetch details and apply explicit global conditions once per unique job. Run the local career-scope gate against all confirmed families and exclusions, independent of which query found the job. Record explicit mismatches as `out_of_scope` and ambiguous jobs as `scope_review`; skip both before any scoring-model call. Remove the generic `_role_function_reject` rule set from this pipeline.
10. Call AI once per unique in-scope job with the resume, confirmed candidate profile evidence (not the full interview transcript), complete available JD, all enabled job profiles linked to confirmed allowed families, and shared rules. Search provenance is retained for diagnostics but does not select which profiles are scored. Ask for one result for every included job profile.
11. Keep all profile assessments in the result. A job passes the matching gate when at least one enabled profile reaches its own threshold (or the global fallback threshold) and has no confirmed disqualifying hard conflict. If several pass, choose the highest-scoring passing profile as the primary profile for queue priority and any later job-specific action. Do not discard the other assessments.
12. Keep downstream behavior otherwise unchanged. Verification uses dry-run and must not perform a real application or send a message. A local greeting preview may be generated if the existing dry-run flow requires it, but no send action is allowed.

## AI Contract and Result Data

The AI scoring response is strict JSON with a `profile_results` array containing exactly one assessment per included enabled profile ID. Each assessment includes:

- `profile_id`, `score` (0-100), and `role_fit` (0-100).
- `hard_gaps`, `unverified_requirements`, `preferred_matches`, and `preferred_gaps`.
- Specific candidate `evidence` with provenance (`resume_quote` or `user_confirmed`) and a concise `reason`.
- A decision/reason for any profile exclusion or objective conflict.

The application validates JSON shape, profile IDs, and score bounds before using the output. Unknown, duplicate, missing, or malformed profile assessments make the evaluation invalid; the job does not pass. Invalid output must be recorded as an AI evaluation failure, not converted to a default score.

Extend result storage to include the primary profile and a serialized per-profile assessment field. The desktop results view should show the primary profile and its score/reason, with the complete assessment available in a readable detail field. Existing result files remain readable; new fields are appended without reinterpreting historical scores.

## Compatibility and Migration

- If `job_profiles.json` does not exist and legacy `DELIVER_KEYWORD` is non-empty, initialize and persist one disabled migration draft whose name and first search keyword use that legacy value. Leave its role-family link empty until the user binds it to a confirmed family. Do not infer hard requirements or preferred qualifications from the keyword, and never overwrite an existing profile file.
- Once profiles are present, profile search terms become authoritative. The legacy environment variable remains readable during migration but is not an additional hidden search query.
- Preserve the global match threshold as the default for profiles without an override.
- If `candidate_profile.json` is absent, derive only an interview draft from the resume; do not treat inferred direction or abilities as confirmed and do not search until the user confirms a profile.
- A legacy keyword-derived job profile stays disabled/unassigned until the user associates it with a confirmed candidate role family in the panel.
- Do not rewrite `.env` merely by opening the panel. Existing values are not changed by this design step.
- Keep existing result columns and legacy CSV records readable; missing profile fields display as empty/legacy.

## Failure Handling and Safety

- Invalid candidate/job profile JSON, no confirmed candidate profile, no eligible enabled profiles, insufficient page budget, unavailable LangChain dependencies, or invalid rules stop before search with an actionable message.
- One query failure is logged and does not abort other queries.
- No results after query failures is a completed search with failure diagnostics, not a successful zero-match claim.
- AI request failure, invalid JSON, or incomplete profile results never passes the matching gate.
- Interview extraction failures leave the confirmed candidate profile untouched. Skipped answers remain unknown rather than becoming negative evidence; canceling an interview never saves its draft.
- Confirmed exclusions and out-of-scope families are enforced before scoring. Uncertain scope matching is logged as `scope_review` and skipped for user review rather than silently broadening the confirmed career boundary.
- Tests and acceptance runs explicitly set dry-run and a small test limit. They must not call delivery/send actions. Existing `.env` and any running desktop panel are left untouched during validation.

## Testing and Acceptance

- Unit tests for candidate/job profile JSON load/save/validation, atomic confirmation and cancellation, provenance, legacy keyword migration, enabled profile selection, unique query construction, shared platform filter propagation, and page-budget allocation.
- Interview tests for resume-grounded draft extraction, one-question turns, skipped answers, unknown versus negative evidence, explicit career-boundary confirmation, and pending revision behavior.
- Search-flow tests proving duplicate jobs retain all query/profile provenance and are detailed/evaluated only once.
- Scope-gate tests proving confirmed in-scope backend/robotics roles can proceed, confirmed out-of-scope sales/real-estate roles are recorded as `out_of_scope`, and ambiguous roles are recorded as `scope_review`, all without an out-of-scope scoring-model call.
- LangChain adapter tests using a mocked OpenAI-compatible chat endpoint for interview and scoring chains, JSON parsing/validation, timeout/error handling, and preservation of existing provider configuration.
- AI contract tests for multiple profile outputs, alternative groups, optional items, omitted resume evidence, hard conflicts, malformed JSON, duplicate/unknown/missing profile IDs, and per-profile thresholds.
- Regression tests that general roles are no longer rejected by the old AI title whitelist or development-only function rules.
- UI tests or focused component tests for add/edit/enable/disable/delete and persistence without changing `.env` unexpectedly.
- End-to-end acceptance only in dry-run: inspect search counts, unique job counts, profile-scoring call count (at most one per unique detailed candidate), each profile assessment, and primary-profile selection. Greeting-generation calls, if retained in dry-run, are counted separately. Assert zero message-send or delivery attempts.

## Implementation Scope

Expected files are `auto_deliver.py`, `boss_spider.py`, `desktop_panel.py`, `tests/test_auto_deliver.py`, a `requirements.txt`, candidate/job profile loaders and schemas, and `screening_rules.md`. User-specific `candidate_profile.json` and `job_profiles.json` files should be initialized from drafts/migration only when appropriate; never overwrite an existing user profile file. Result output fields may need a focused compatibility update.

This design document is not implementation approval by itself. After the user reviews and approves this written spec, the next step is an implementation plan, followed by implementation under a separate approval/workflow gate.
