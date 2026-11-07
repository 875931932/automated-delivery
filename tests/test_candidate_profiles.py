import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from candidate_profiles import (
    CandidateEvidence,
    CandidateProfile,
    CandidateProfileService,
    CandidateProfileStore,
    InterviewDraft,
    ProposedEvidence,
    RoleFamily,
)


def make_profile(revision=0):
    return CandidateProfile(
        confirmed=True,
        revision=revision,
        primary_direction="AI 应用开发",
        allowed_role_families=[
            RoleFamily(
                id="backend",
                name="后端开发",
                aliases=["服务端开发"],
                title_terms=["后端工程师"],
            )
        ],
        excluded_role_families=["销售"],
        excluded_terms=["销售代表"],
        evidence=[CandidateEvidence(
            claim="有 Python 后端实践",
            source="resume_quote",
            evidence_text="Python/FastAPI 接口开发实践",
        )],
        preferences=["实习"],
    )


class CandidateProfileModelTests(unittest.TestCase):
    def test_candidate_profile_rejects_unconfirmed_or_empty_career_scope(self):
        data = make_profile().model_dump()

        with self.assertRaises(ValidationError):
            CandidateProfile.model_validate({**data, "confirmed": False})

        with self.assertRaises(ValidationError):
            CandidateProfile.model_validate({**data, "primary_direction": " "})

        with self.assertRaises(ValidationError):
            CandidateProfile.model_validate({**data, "allowed_role_families": []})

    def test_candidate_profile_rejects_ai_only_evidence_fields(self):
        data = make_profile().model_dump()
        data["evidence"][0]["source"] = "ai_proposed"

        with self.assertRaises(ValidationError):
            CandidateProfile.model_validate(data)

        draft = ProposedEvidence(
            claim="有容器部署经验",
            evidence_text="",
            clarification_question="你是否独立完成过容器部署？",
        )
        self.assertEqual(draft.claim, "有容器部署经验")


class CandidateProfileStoreTests(unittest.TestCase):
    def test_missing_profile_loads_as_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")

            self.assertIsNone(store.load())

    def test_save_confirmed_profile_increments_revision_without_losing_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            first = store.save_confirmed(make_profile(revision=0))
            second = store.save_confirmed(make_profile(revision=first.revision))

            self.assertEqual(first.revision, 1)
            self.assertEqual(second.revision, first.revision + 1)
            loaded = store.load()
            self.assertEqual(loaded.evidence[0].source, "resume_quote")
            self.assertEqual(loaded.evidence[0].evidence_text, "Python/FastAPI 接口开发实践")
            self.assertEqual(loaded.allowed_role_families[0].id, "backend")

    def test_malformed_profile_is_rejected_without_rewriting_the_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate_profile.json"
            path.write_text('{"confirmed": true,', encoding="utf-8")
            original = path.read_bytes()
            store = CandidateProfileStore(path)

            with self.assertRaises(ValueError):
                store.load()

            self.assertEqual(path.read_bytes(), original)

    def test_unconfirmed_profile_cannot_be_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")

            with self.assertRaises(ValidationError):
                store.save_confirmed({**make_profile().model_dump(), "confirmed": False})

            self.assertIsNone(store.load())

    def test_profile_save_round_trips_as_utf8_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate_profile.json"
            store = CandidateProfileStore(path)
            store.save_confirmed(make_profile())

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["primary_direction"], "AI 应用开发")
            self.assertNotIn("\\u", path.read_text(encoding="utf-8"))


class FakeInterviewChain:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeRoleResearcher:
    enabled = True
    ready = True

    def __init__(self, results=None, error=None):
        self.calls = []
        self.results = results or []
        self.error = error

    def search(self, direction, role_families):
        self.calls.append((direction, role_families))
        if self.error:
            raise self.error
        return self.results


class CandidateProfileServiceTests(unittest.TestCase):
    def make_ready_draft(self, evidence=None):
        return InterviewDraft(
            primary_direction="AI 应用开发",
            allowed_role_families=[RoleFamily(id="backend", name="后端开发")],
            evidence=evidence or [],
            ready_for_review=True,
        )

    def test_skip_is_transient_and_does_not_turn_into_negative_evidence(self):
        chain = FakeInterviewChain([
            InterviewDraft(
                primary_direction="AI 应用开发",
                pending_question="你是否使用过 Docker？",
            ),
            self.make_ready_draft(),
        ])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
        )

        first = service.start_interview("Python/FastAPI 项目")
        result = service.answer(first, skip=True)

        self.assertEqual(result.primary_direction, "AI 应用开发")
        self.assertNotIn("Docker", [item.claim for item in result.evidence])
        self.assertTrue(chain.calls[-1]["skipped"])
        self.assertEqual(chain.calls[-1]["answer"], "")
        self.assertEqual(chain.calls[-1]["history"][-1]["content"], "（用户跳过本问题）")

    def test_interview_capability_evidence_accumulates_across_answers(self):
        initial = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你负责过哪些模型服务工作？",
        )
        first_answer = InterviewDraft(
            evidence=[CandidateEvidence(
                claim="有模型 API 封装经验",
                source="user_confirmed",
                evidence_text="我用 FastAPI 封装了模型 API",
            )],
            pending_question="你如何验证模型输出？",
        )
        second_answer = InterviewDraft(
            pending_question=None,
            ready_for_review=True,
        )
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            FakeInterviewChain([initial, first_answer, second_answer]),
        )

        draft = service.start_interview("AI 应用开发项目")
        draft = service.answer(draft, text="我用 FastAPI 封装了模型 API")
        draft = service.answer(draft, text="我为模型输出写了回归测试")

        self.assertEqual(
            [(item.claim, item.evidence_text) for item in draft.evidence],
            [("有模型 API 封装经验", "我用 FastAPI 封装了模型 API")],
        )
        self.assertEqual(len(service.history), 4)

    def test_unquoted_model_capability_is_kept_pending_not_confirmed(self):
        initial = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你做过什么项目？",
        )
        answer = InterviewDraft(
            evidence=[CandidateEvidence(
                claim="熟悉 Kubernetes 集群运维",
                source="user_confirmed",
                evidence_text="独立管理过生产 Kubernetes 集群",
            )],
            pending_question="还有其他经历吗？",
        )
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            FakeInterviewChain([initial, answer]),
        )

        draft = service.start_interview("AI 应用开发项目")
        draft = service.answer(draft, text="我用 FastAPI 做了一个模型 API")

        self.assertEqual(draft.evidence, [])
        self.assertEqual([item.claim for item in draft.proposed_evidence], ["熟悉 Kubernetes 集群运维"])

    def test_quoted_proposal_becomes_confirmed_capability(self):
        initial = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你如何部署服务？",
        )
        answer = InterviewDraft(
            proposed_evidence=[ProposedEvidence(
                claim="有 Docker 部署经验",
                evidence_text="我用 Docker 部署了 API 服务",
                clarification_question="你是如何完成部署的？",
            )],
            pending_question="部署时遇到了什么问题？",
        )
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            FakeInterviewChain([initial, answer]),
        )

        draft = service.start_interview("AI 应用开发项目")
        draft = service.answer(draft, text="我用 Docker 部署了 API 服务")

        self.assertEqual(
            [(item.claim, item.source, item.evidence_text) for item in draft.evidence],
            [("有 Docker 部署经验", "user_confirmed", "我用 Docker 部署了 API 服务")],
        )
        self.assertEqual(draft.proposed_evidence, [])

    def test_failed_answer_can_be_retried_without_duplicating_history(self):
        first = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你是否部署过模型服务？",
        )
        completed = first.model_copy(update={
            "pending_question": None,
            "ready_for_review": True,
        })
        chain = FakeInterviewChain([
            first,
            RuntimeError("model service unavailable"),
            completed,
        ])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
        )

        draft = service.start_interview("AI 应用开发项目")
        original_history = list(service.history)
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            service.answer(draft, text="用 FastAPI 封装模型服务")

        self.assertEqual(service.history, original_history)
        self.assertIs(service.draft, draft)

        retried = service.answer(draft, text="用 FastAPI 封装模型服务")

        self.assertTrue(retried.ready_for_review)
        self.assertEqual(len(service.history), 2)
        self.assertEqual(service.history[-1]["content"], "用 FastAPI 封装模型服务")

    def test_resume_direction_is_researched_without_asking_user_to_confirm_it(self):
        first = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        follow_up = InterviewDraft(
            primary_direction="AI 应用开发",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你是否做过模型服务部署？",
        )
        chain = FakeInterviewChain([first, follow_up])
        researcher = FakeRoleResearcher(results=[{
            "title": "AI 应用开发岗位要求",
            "url": "https://example.invalid/ai-role",
            "content": "常见要求包含模型部署与服务监控。",
        }])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        result = service.start_interview("大模型应用开发项目，使用 Python/FastAPI")

        self.assertEqual(result.pending_question, "你是否做过模型服务部署？")
        self.assertEqual(researcher.calls, [("AI 应用开发", ["AI 后端开发"])])
        self.assertEqual(chain.calls[0]["phase"], "direction")
        self.assertEqual(chain.calls[1]["phase"], "market_followup")
        self.assertIn("常见要求包含模型部署", chain.calls[1]["market_context"])
        self.assertEqual(result.evidence, [])

    def test_resume_direction_continues_normal_interview_when_research_is_unavailable(self):
        direction = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        chain = FakeInterviewChain([direction])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
        )

        result = service.start_interview("大模型应用开发项目，使用 Python/FastAPI")

        self.assertEqual(result.primary_direction, "AI 应用开发")
        self.assertEqual(result.direction_source, "resume")
        # 无市场资料时只调用一次模型，用本地访谈问题继续，不再追问第二次模型
        self.assertEqual(len(chain.calls), 1)
        self.assertEqual(chain.calls[0]["phase"], "direction")
        self.assertEqual(
            result.pending_question,
            "已识别职位族：AI 后端开发。你最早什么时候能到岗实习，每周能实习几天、能持续多久？",
        )
        self.assertNotIn("求职方向", result.pending_question)

    def test_follow_up_cannot_replace_direction_extracted_from_resume(self):
        direction = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        changed_scope = InterviewDraft(
            primary_direction="销售",
            direction_source="unknown",
            allowed_role_families=[RoleFamily(id="sales", name="销售")],
            pending_question="你希望应聘哪个方向？",
        )
        chain = FakeInterviewChain([direction, changed_scope])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
        )

        initial = service.start_interview("大模型应用开发项目，使用 Python/FastAPI")
        result = service.answer(initial, text="做过本地部署和 API 封装")

        self.assertEqual(result.primary_direction, "AI 应用开发")
        self.assertEqual(result.direction_source, "resume")
        self.assertEqual([item.name for item in result.allowed_role_families], ["AI 后端开发"])
        self.assertEqual(
            result.pending_question,
            "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。",
        )
        self.assertEqual(chain.calls[-1]["phase"], "interview")

    def test_unclear_resume_direction_is_asked_before_any_search(self):
        first = InterviewDraft(pending_question="你希望主要应聘哪类岗位？")
        chain = FakeInterviewChain([first])
        researcher = FakeRoleResearcher()
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        result = service.start_interview("负责多项课程和社团活动")

        self.assertIn("求职方向", result.pending_question)
        self.assertEqual(researcher.calls, [])

    def test_user_supplied_direction_triggers_one_research_before_skill_follow_up(self):
        unclear = InterviewDraft(pending_question="你希望主要应聘哪类岗位？")
        clarified = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="user_confirmed",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        follow_up = InterviewDraft(
            primary_direction="AI 应用开发",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你是否配置过线上模型服务？",
        )
        chain = FakeInterviewChain([unclear, clarified, follow_up])
        researcher = FakeRoleResearcher(results=[{
            "title": "AI 工程师招聘要求",
            "url": "https://example.invalid/ai-engineer",
            "content": "常见工作涉及模型上线和效果评估。",
        }])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        first = service.start_interview("参与若干软件项目")
        result = service.answer(first, text="我想找 AI 应用开发，也接受相关后端开发")

        self.assertEqual(researcher.calls, [("AI 应用开发", ["AI 后端开发"])])
        self.assertEqual(result.pending_question, "你是否配置过线上模型服务？")
        self.assertEqual(chain.calls[-1]["phase"], "market_followup")
        self.assertIn("模型上线和效果评估", chain.calls[-1]["market_context"])

    def test_failed_role_research_falls_back_to_resume_interview(self):
        first = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        chain = FakeInterviewChain([first])
        researcher = FakeRoleResearcher(error=RuntimeError("search unavailable"))
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        result = service.start_interview("AI 应用开发项目")

        # 检索失败后用本地访谈问题继续，不再追加模型调用
        self.assertEqual(
            result.pending_question,
            "已识别职位族：AI 后端开发。你最早什么时候能到岗实习，每周能实习几天、能持续多久？",
        )
        self.assertEqual(chain.calls[-1]["market_context"], "")
        self.assertEqual(service.research_status, "搜索失败，已回退到简历访谈")
        self.assertEqual(result.proposed_evidence, [])

    def test_skipping_unclear_direction_does_not_trigger_research(self):
        first = InterviewDraft(pending_question="你希望重点应聘哪类岗位？")
        chain = FakeInterviewChain([
            first,
            InterviewDraft(pending_question="还需要确认方向。"),
        ])
        researcher = FakeRoleResearcher()
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        initial = service.start_interview("参加过一些软件项目")
        result = service.answer(initial, skip=True)

        self.assertEqual(researcher.calls, [])
        self.assertEqual(result.direction_source, "unknown")
        self.assertIn("没有明确求职方向", result.pending_question)

    def test_market_search_cannot_replace_candidate_direction_scope_or_evidence(self):
        first = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            evidence=[CandidateEvidence(
                claim="Python 服务开发", source="resume_quote", evidence_text="Python 项目"
            )],
        )
        follow_up = InterviewDraft(
            primary_direction="错误改写方向",
            direction_source="unknown",
            allowed_role_families=[RoleFamily(id="sales", name="销售")],
            excluded_role_families=["开发"],
            evidence=[],
            proposed_evidence=[{
                "claim": "线上部署",
                "clarification_question": "你是否部署过线上模型？",
            }],
        )
        chain = FakeInterviewChain([first, follow_up])
        researcher = FakeRoleResearcher(results=[{
            "title": "AI 岗位指南", "url": "https://example.invalid/guide",
            "content": "部分岗位要求线上部署。",
        }])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        result = service.start_interview("Python 项目")

        self.assertEqual(result.primary_direction, "AI 应用开发")
        self.assertEqual(result.direction_source, "resume")
        self.assertEqual([item.name for item in result.allowed_role_families], ["AI 后端开发"])
        self.assertEqual([item.claim for item in result.evidence], ["Python 服务开发"])
        self.assertEqual(result.excluded_role_families, [])

    def test_cancel_discards_draft_and_never_saves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate_profile.json"
            service = CandidateProfileService(
                CandidateProfileStore(path),
                FakeInterviewChain([self.make_ready_draft()]),
            )

            service.start_interview("Python 项目")
            service.cancel()

            self.assertFalse(path.exists())
            self.assertIsNone(service.draft)
            self.assertEqual(service.history, [])

    def test_user_must_approve_ready_draft_before_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            service = CandidateProfileService(store, FakeInterviewChain([]))
            service.resume = "Python 项目"
            draft = self.make_ready_draft()

            with self.assertRaises(ValueError):
                service.confirm(draft, user_approved=False)
            with self.assertRaises(ValueError):
                service.confirm(draft.model_copy(update={"ready_for_review": False}), user_approved=True)

            self.assertIsNone(store.load())

    def test_resume_quote_must_exist_in_selected_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            previous = store.save_confirmed(make_profile())
            service = CandidateProfileService(store, FakeInterviewChain([]))
            service.resume = "Python/FastAPI 项目"
            draft = self.make_ready_draft([
                CandidateEvidence(
                    claim="会使用 Docker",
                    source="resume_quote",
                    evidence_text="独立负责 Kubernetes 集群",
                )
            ])

            with self.assertRaises(ValueError):
                service.confirm(draft, user_approved=True)

            self.assertEqual(store.load().revision, previous.revision)

    def test_confirmed_user_answer_is_saved_only_after_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            service = CandidateProfileService(store, FakeInterviewChain([]))
            resume = "Python/FastAPI 项目"
            service.resume = resume
            service.history = [
                {"role": "assistant", "content": "你做过哪些容器化工作？"},
                {"role": "user", "content": "我做过项目容器化部署"},
            ]
            draft = self.make_ready_draft([
                CandidateEvidence(
                    claim="会使用 Docker",
                    source="user_confirmed",
                    evidence_text="我做过项目容器化部署",
                )
            ])

            saved = service.confirm(draft, user_approved=True)

            self.assertEqual(saved.revision, 1)
            from candidate_profiles import resume_digest_hash

            self.assertEqual(saved.resume_sha256, resume_digest_hash(resume))
            self.assertEqual(store.load().evidence[0].source, "user_confirmed")
            self.assertFalse((Path(temp_dir) / "conversation.json").exists())

    def test_proposed_evidence_is_not_promoted_when_saving_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            service = CandidateProfileService(store, FakeInterviewChain([]))
            service.resume = "Python 项目"
            draft = self.make_ready_draft()
            draft = draft.model_copy(update={
                "proposed_evidence": [ProposedEvidence(
                    claim="熟悉 Docker 部署",
                    evidence_text="用 Docker 部署了服务",
                    clarification_question="你是否独立完成过部署？",
                )],
            })

            saved = service.confirm(draft, user_approved=True)

            self.assertEqual(saved.evidence, [])

    def test_user_confirmed_evidence_must_be_grounded_in_interview_answer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            service = CandidateProfileService(store, FakeInterviewChain([]))
            service.resume = "Python 项目"
            draft = self.make_ready_draft([CandidateEvidence(
                claim="熟悉 Docker 部署",
                source="user_confirmed",
                evidence_text="我独立完成了 Docker 部署",
            )])

            with self.assertRaisesRegex(ValueError, "user-confirmed evidence"):
                service.confirm(draft, user_approved=True)

            self.assertIsNone(store.load())

    def test_skipped_interview_turn_cannot_ground_confirmed_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateProfileStore(Path(temp_dir) / "candidate_profile.json")
            service = CandidateProfileService(store, FakeInterviewChain([]))
            service.resume = "Python 项目"
            service.history = [
                {"role": "assistant", "content": "你是否使用过 Docker？"},
                {"role": "user", "content": "（用户跳过本问题）"},
            ]
            draft = self.make_ready_draft([CandidateEvidence(
                claim="熟悉 Docker 部署",
                source="user_confirmed",
                evidence_text="我独立完成了 Docker 部署",
            )])

            with self.assertRaisesRegex(ValueError, "user-confirmed evidence"):
                service.confirm(draft, user_approved=True)

            self.assertIsNone(store.load())


class BaseCandidateProfileTests(unittest.TestCase):
    def test_base_candidate_profile_synthesizes_from_resume_and_job_profiles(self):
        from types import SimpleNamespace

        from candidate_profiles import build_base_candidate_profile

        profile = SimpleNamespace(
            role_family_id="backend", role_direction="AI 后端开发",
            name="后端岗", search_keywords=["后端", "Python API"],
        )

        candidate = build_base_candidate_profile("简历文本", [profile], "AI应用开发")

        self.assertTrue(candidate.confirmed)
        self.assertEqual(candidate.primary_direction, "AI应用开发")
        self.assertEqual(
            [f.id for f in candidate.allowed_role_families], ["backend"]
        )
        self.assertEqual(candidate.allowed_role_families[0].name, "AI 后端开发")
        self.assertEqual(
            candidate.allowed_role_families[0].title_terms, ["后端", "Python API"]
        )

    def test_base_candidate_profile_requires_a_direction(self):
        from types import SimpleNamespace

        from candidate_profiles import build_base_candidate_profile

        with self.assertRaisesRegex(ValueError, "求职方向"):
            build_base_candidate_profile("", [], "")

        self.assertRaisesRegex(
            ValueError, "岗位方向",
            build_base_candidate_profile, "", [], "AI应用开发",
        )

    def test_unbound_job_profile_defines_its_own_family_in_base_mode(self):
        """基础模式不要求岗位画像已绑定职位族，避免首次使用时的死锁。"""
        from types import SimpleNamespace

        from candidate_profiles import build_base_candidate_profile

        unbound = SimpleNamespace(
            id="draft-1", role_family_id="", role_direction="AI 应用开发",
            name="草稿", search_keywords=["AI应用开发", "大模型"],
        )

        candidate = build_base_candidate_profile("", [unbound], "AI应用开发")

        self.assertEqual(
            [f.id for f in candidate.allowed_role_families], ["draft-1"]
        )
        self.assertEqual(candidate.allowed_role_families[0].name, "AI 应用开发")
        self.assertEqual(
            candidate.allowed_role_families[0].title_terms, ["AI应用开发", "大模型"]
        )


class SkillQuestionGuardTests(unittest.TestCase):
    """规范：技能补充类提问必须有搜索到的岗位技能依据，禁止无依据随意提问。"""

    def _service(self, resume, history=None, market_context=""):
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            FakeInterviewChain([]),
        )
        service.resume = resume
        service.history = list(history or [])
        service.market_context = market_context
        return service

    def test_unfounded_skill_question_is_replaced_without_market_context(self):
        service = self._service("熟悉 Python 开发。")
        draft = InterviewDraft(pending_question="你是否使用过 Java？")

        result = service._guard_skill_question(draft)

        self.assertEqual(
            result.pending_question,
            "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。",
        )

    def test_skill_question_confirmed_in_dialogue_is_kept(self):
        service = self._service(
            "熟悉 Python 开发。",
            history=[{"role": "user", "content": "我自学过 Java。"}],
        )
        draft = InterviewDraft(pending_question="你 Java 项目经历是怎样的？")

        self.assertEqual(
            service._guard_skill_question(draft).pending_question,
            "你 Java 项目经历是怎样的？",
        )

    def test_skill_question_with_market_context_is_kept(self):
        service = self._service(
            "熟悉 Python 开发。",
            market_context="该职位常见要求包含 Java 与分布式经验",
        )
        draft = InterviewDraft(pending_question="你是否使用过 Java？")

        self.assertEqual(
            service._guard_skill_question(draft).pending_question,
            "你是否使用过 Java？",
        )

    def test_resume_grounded_skill_question_is_kept(self):
        service = self._service("熟悉 Python 开发，做过 FastAPI 项目。")
        draft = InterviewDraft(pending_question="你 Python 项目里的难点是怎么解决的？")

        self.assertEqual(
            service._guard_skill_question(draft).pending_question,
            "你 Python 项目里的难点是怎么解决的？",
        )

    def test_non_skill_question_is_kept(self):
        service = self._service("熟悉 Python 开发。")
        draft = InterviewDraft(
            pending_question="你最早什么时候能到岗实习，每周能实习几天？"
        )

        self.assertEqual(
            service._guard_skill_question(draft).pending_question,
            "你最早什么时候能到岗实习，每周能实习几天？",
        )

    def test_answer_flow_replaces_unfounded_skill_question(self):
        direction = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        skill_question = InterviewDraft(
            primary_direction="AI 应用开发",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你是否使用过 Java？",
        )
        chain = FakeInterviewChain([direction, skill_question])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
        )

        initial = service.start_interview("熟悉 Python 开发。")
        result = service.answer(initial, text="做过接口开发")

        self.assertEqual(
            result.pending_question,
            "请补充与当前求职方向相关的项目经历、能力细节或岗位偏好。",
        )


class IncrementalResearchTests(unittest.TestCase):
    """规范：提问前先搜索岗位技能体系；按职位族增量补搜，不重复检索。"""

    def test_research_runs_per_family_and_merges_incrementally(self):
        first = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
        )
        follow_up = InterviewDraft(
            primary_direction="AI 应用开发",
            allowed_role_families=[RoleFamily(id="backend", name="AI 后端开发")],
            pending_question="你是否做过模型服务部署？",
        )
        chain = FakeInterviewChain([first, follow_up])
        researcher = FakeRoleResearcher(results=[{
            "title": "AI 工程师招聘要求",
            "url": "https://example.invalid/ai-engineer",
            "content": "常见要求包含模型部署。",
        }])
        service = CandidateProfileService(
            CandidateProfileStore(Path(tempfile.gettempdir()) / "unused-profile.json"),
            chain,
            researcher=researcher,
        )

        service.start_interview("参与若干软件项目")

        # 每个职位族独立检索标准技能要求
        self.assertEqual(researcher.calls, [("AI 应用开发", ["AI 后端开发"])])
        self.assertIn("常见要求包含模型部署", service.market_context)

        # 新增职位族时只补搜增量，来源按 URL 去重合并
        researcher.results = [{
            "title": "智能体开发要求",
            "url": "https://example.invalid/agent",
            "content": "常见工作涉及工具调用与工作流编排。",
        }]
        extended = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            allowed_role_families=[
                RoleFamily(id="backend", name="AI 后端开发"),
                RoleFamily(id="agent", name="智能体开发"),
            ],
        )
        service._research_then_continue(extended)

        self.assertEqual(researcher.calls, [
            ("AI 应用开发", ["AI 后端开发"]),
            ("AI 应用开发", ["智能体开发"]),
        ])
        self.assertEqual(len(service.research_results), 2)
        self.assertIn("模型部署", service.market_context)
        self.assertIn("工具调用与工作流编排", service.market_context)

        # 已检索过的职位族不重复搜索
        service._research_then_continue(extended)
        self.assertEqual(len(researcher.calls), 2)


if __name__ == "__main__":
    unittest.main()
