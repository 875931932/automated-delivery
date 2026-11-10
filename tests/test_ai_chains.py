import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda

from ai_chains import (
    CandidateInterviewChain,
    InterviewChainError,
    JDRequirement,
    JobMatchResponse,
    JobScoringChain,
    ProfileAssessment,
    build_chat_model,
)
from candidate_profiles import CandidateProfile, InterviewDraft, RoleFamily
from job_profiles import JobProfile


class JsonModeModel:
    def __init__(self, runnable):
        self.runnable = (
            runnable if hasattr(runnable, "invoke") else RunnableLambda(runnable)
        )
        self.structured_output_options = None

    def with_structured_output(self, schema, **options):
        self.structured_output_options = (schema, options)
        parser = PydanticOutputParser(pydantic_object=schema)

        def parse(prompt):
            raw = self.runnable.invoke(prompt)
            try:
                parsed = parser.parse(raw.content)
                error = None
            except Exception as exc:
                parsed = None
                error = exc
            return {"raw": raw, "parsed": parsed, "parsing_error": error}

        return RunnableLambda(parse)


class ChatModelFactoryTests(unittest.TestCase):
    def test_existing_openai_compatible_settings_are_forwarded(self):
        config = {
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-only-key",
            "ai_model": "test-model",
            "ai_timeout": 19,
            "ai_max_retries": 4,
        }

        with patch("ai_chains.ChatOpenAI") as chat_openai:
            build_chat_model(config)

        chat_openai.assert_called_once_with(
            model="test-model",
            api_key="test-only-key",
            base_url="https://example.invalid/v1",
            timeout=19,
            max_retries=4,
            temperature=0.2,
        )


class CandidateInterviewChainTests(unittest.TestCase):
    def test_interview_uses_json_object_response_format(self):
        expected = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            pending_question="你是否做过线上部署？",
        )

        model = JsonModeModel(RunnableLambda(
            lambda _prompt: AIMessage(content=expected.model_dump_json())
        ))
        chain = CandidateInterviewChain(model=model)

        result = chain.invoke(
            resume="Python 项目",
            active_profile=None,
            draft=None,
            history=[],
            answer=None,
        )

        self.assertEqual(model.structured_output_options, (
            InterviewDraft,
            {"method": "json_mode", "include_raw": True},
        ))
        self.assertEqual(result, expected)

    def test_interview_chain_asks_at_most_one_question_per_turn(self):
        response = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            pending_question="你是否实际部署过该服务？",
            ready_for_review=False,
        )
        model = JsonModeModel(RunnableLambda(
            lambda _prompt: AIMessage(content=response.model_dump_json())
        ))
        chain = CandidateInterviewChain(model=model)

        draft = chain.invoke(
            resume="Python 项目",
            active_profile=None,
            draft=None,
            history=[],
            answer=None,
        )

        self.assertEqual(draft.pending_question, "你是否实际部署过该服务？")
        self.assertFalse(draft.ready_for_review)
        self.assertEqual(draft.direction_source, "resume")

    def test_prompt_includes_resume_transient_history_and_skip_marker(self):
        captured = {}

        def answer(prompt_value):
            captured["messages"] = prompt_value.to_messages()
            draft = InterviewDraft(
                primary_direction="AI 应用开发",
                ready_for_review=True,
            )
            return AIMessage(content=draft.model_dump_json())

        chain = CandidateInterviewChain(model=JsonModeModel(RunnableLambda(answer)))
        result = chain.invoke(
            resume="LangChain 项目经历",
            active_profile=None,
            draft=InterviewDraft(primary_direction="AI 应用开发"),
            history=[{"role": "assistant", "content": "是否部署过？"}],
            answer=None,
            skipped=True,
        )
        prompt_text = "\n".join(message.content for message in captured["messages"])

        self.assertIn("LangChain 项目经历", prompt_text)
        self.assertIn("是否部署过？", prompt_text)
        self.assertIn("跳过", prompt_text)
        self.assertTrue(result.ready_for_review)

    def test_market_context_is_question_research_not_candidate_evidence(self):
        captured = {}
        response = InterviewDraft(
            primary_direction="AI 应用开发",
            proposed_evidence=[{
                "claim": "模型服务部署",
                "clarification_question": "你是否配置过线上模型服务？",
            }],
            pending_question="你是否配置过线上模型服务？",
        )

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=response.model_dump_json())

        chain = CandidateInterviewChain(model=JsonModeModel(RunnableLambda(answer)))
        result = chain.invoke(
            resume="AI 应用项目",
            active_profile=None,
            draft=InterviewDraft(primary_direction="AI 应用开发"),
            history=[],
            answer=None,
            phase="market_followup",
            market_context="常见职责包括模型部署。来源：https://example.invalid/role",
        )

        self.assertIn("常见职责包括模型部署", captured["prompt"])
        self.assertIn("不能视为候选人事实", captured["prompt"])
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.proposed_evidence[0].claim, "模型服务部署")

    def test_invalid_json_fails_closed_with_chain_error(self):
        chain = CandidateInterviewChain(
            model=JsonModeModel(RunnableLambda(lambda _prompt: AIMessage(content="not-json")))
        )

        with self.assertRaises(InterviewChainError):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )

    def test_fenced_json_interview_response_is_accepted(self):
        expected = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            pending_question="你是否做过线上部署？",
        )
        chain = CandidateInterviewChain(
            model=JsonModeModel(RunnableLambda(
                lambda _prompt: AIMessage(
                    content=f"```json\n{expected.model_dump_json()}\n```"
                )
            ))
        )

        result = chain.invoke(
            resume="Python 项目",
            active_profile=None,
            draft=None,
            history=[],
            answer=None,
        )

        self.assertEqual(result.pending_question, expected.pending_question)

    def test_invalid_json_interview_response_is_retried_once(self):
        expected = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            pending_question="你是否做过线上部署？",
        )
        responses = iter((
            AIMessage(content="暂时无法整理"),
            AIMessage(content=expected.model_dump_json()),
        ))
        calls = []
        chain = CandidateInterviewChain(
            model=JsonModeModel(
                RunnableLambda(lambda prompt: calls.append(prompt) or next(responses))
            )
        )

        result = chain.invoke(
            resume="Python 项目",
            active_profile=None,
            draft=None,
            history=[],
            answer=None,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result.pending_question, expected.pending_question)

    def test_repeated_invalid_interview_json_has_actionable_error(self):
        chain = CandidateInterviewChain(
            model=JsonModeModel(
                RunnableLambda(lambda _prompt: AIMessage(content="暂时无法整理"))
            )
        )

        with self.assertRaisesRegex(InterviewChainError, "response_format"):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )

    def test_extra_question_fields_are_rejected_after_structured_parsing(self):
        payload = {
            "primary_direction": "AI 应用开发",
            "follow_up_questions": ["第二个问题？"],
        }
        calls = []
        chain = CandidateInterviewChain(
            model=JsonModeModel(lambda prompt: calls.append(prompt) or AIMessage(
                content=json.dumps(payload, ensure_ascii=False)
            ))
        )

        with self.assertRaisesRegex(InterviewChainError, "连续2次"):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )

        self.assertEqual(len(calls), 2)

    def test_pending_question_and_review_ready_cannot_be_returned_together(self):
        payload = InterviewDraft(
            primary_direction="AI 应用开发",
            pending_question="是否做过线上部署？",
            ready_for_review=True,
        )
        calls = []
        chain = CandidateInterviewChain(
            model=JsonModeModel(lambda prompt: calls.append(prompt) or AIMessage(
                content=payload.model_dump_json()
            ))
        )

        with self.assertRaisesRegex(InterviewChainError, "连续2次"):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )

        self.assertEqual(len(calls), 2)

    def test_empty_interview_response_is_retried_once(self):
        valid = InterviewDraft(
            primary_direction="AI 应用开发",
            direction_source="resume",
            pending_question="你是否实际部署过该服务？",
        )
        responses = iter((AIMessage(content=""), AIMessage(content=valid.model_dump_json())))
        calls = []
        chain = CandidateInterviewChain(
            model=JsonModeModel(
                RunnableLambda(lambda prompt: calls.append(prompt) or next(responses))
            )
        )

        result = chain.invoke(
            resume="Python 项目",
            active_profile=None,
            draft=None,
            history=[],
            answer=None,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result.pending_question, "你是否实际部署过该服务？")

    def test_repeated_empty_interview_response_reports_finish_reason(self):
        calls = []
        chain = CandidateInterviewChain(
            model=JsonModeModel(RunnableLambda(
                lambda prompt: calls.append(prompt) or AIMessage(
                    content="", response_metadata={"finish_reason": "length"}
                )
            ))
        )

        with self.assertRaisesRegex(InterviewChainError, "finish_reason=length"):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )

        self.assertEqual(len(calls), 2)

    def test_only_one_pending_question_is_allowed(self):
        payload = {
            "primary_direction": "AI 应用开发",
            "pending_question": "第一个问题？",
            "follow_up_questions": ["第二个问题？"],
        }
        chain = CandidateInterviewChain(
            model=JsonModeModel(RunnableLambda(
                lambda _prompt: AIMessage(content=json.dumps(payload, ensure_ascii=False))
            ))
        )

        with self.assertRaises(InterviewChainError):
            chain.invoke(
                resume="Python 项目",
                active_profile=None,
                draft=None,
                history=[],
                answer=None,
            )


def _candidate():
    return CandidateProfile(
        confirmed=True,
        revision=1,
        primary_direction="AI 应用研发",
        allowed_role_families=[RoleFamily(id="backend", name="后端开发")],
        evidence=[{
            "claim": "Python 后端接口开发",
            "source": "resume_quote",
            "evidence_text": "使用 Python 开发后端接口",
        }],
    )


def _profiles():
    return [
        JobProfile(
            id="backend", name="后端开发", role_family_id="backend",
            search_keywords=["Python后端"],
            hard_requirements=[{
                "label": "编程语言至少一种", "options": ["C++", "Python", "Java"],
                "mode": "any",
            }],
            preferred_qualifications=["有向量数据库实践"],
        ),
    ]


def _assessment(profile_id="backend"):
    return {
        "profile_id": profile_id,
        "score": 85,
        "role_fit": 90,
        "hard_gaps": [],
        "unverified_requirements": ["未明确提及 Go"],
        "preferred_matches": [],
        "preferred_gaps": ["向量数据库实践"],
        "evidence": [{
            "claim": "Python 后端接口开发",
            "source": "resume_quote",
            "evidence_text": "使用 Python 开发后端接口",
        }],
        "reason": "岗位职责与已证实的 Python 后端实践相符。",
        "disqualified": False,
        "disqualification_reason": "",
    }


class JobScoringChainTests(unittest.TestCase):
    def test_current_city_is_separate_from_resume_and_profile_preferences(self):
        resume = "求职城市：深圳。使用 Python 开发后端接口"
        candidate = _candidate().model_copy(update={"preferences": ["只考虑深圳"]})
        for target_city in ("上海", "杭州", "全国", "深圳"):
            for use_digest in (False, True):
                with self.subTest(city=target_city, digest=use_digest):
                    captured = []
                    chain = JobScoringChain(model=RunnableLambda(
                        lambda prompt: captured.extend(prompt.to_messages()) or AIMessage(
                            content=json.dumps({"profile_results": [_assessment()]}, ensure_ascii=False)
                        )
                    ))
                    prompt_resume = "结构化摘要：求职城市：深圳。使用 Python 开发后端接口"
                    result = chain.invoke(
                        resume=resume,
                        prompt_resume=prompt_resume if use_digest else None,
                        candidate_profile=candidate,
                        job={"工作名称": "Python 后端工程师", "区域": "上海"},
                        profiles=_profiles(),
                        rules="优先考虑深圳岗位。",
                        target_city=target_city,
                    )

                    system, human = captured
                    self.assertIn("优先于", system.content)
                    self.assertIn("全国表示本轮不限求职城市", system.content)
                    self.assertIn("不得因旧地点偏好扣分", system.content)
                    self.assertIn("真实地点冲突", system.content)
                    self.assertIn("不得推断到岗时间", system.content)
                    self.assertIn(f"本次任务求职城市（系统设置）:\n{target_city}\n\n", human.content)
                    self.assertIn("只考虑深圳", human.content)
                    self.assertIn(prompt_resume if use_digest else resume, human.content)
                    self.assertEqual(candidate.preferences, ["只考虑深圳"])
                    self.assertEqual(
                        result.profile_results[0].evidence[0].evidence_text,
                        "使用 Python 开发后端接口",
                    )

    def test_missing_city_does_not_invent_a_current_preference(self):
        for target_city in (None, "", "   "):
            with self.subTest(city=target_city):
                captured = []
                chain = JobScoringChain(model=RunnableLambda(
                    lambda prompt: captured.extend(prompt.to_messages()) or AIMessage(
                        content=json.dumps({"profile_results": [_assessment()]}, ensure_ascii=False)
                    )
                ))
                chain.invoke(
                    resume="求职城市：深圳。使用 Python 开发后端接口",
                    candidate_profile=_candidate(),
                    job={"工作名称": "Python 后端工程师"},
                    profiles=_profiles(),
                    rules="规则",
                    target_city=target_city,
                )

                self.assertIn(
                    "本次任务求职城市（系统设置）:\n未提供（沿用已有地点偏好）\n\n",
                    captured[1].content,
                )

    def test_scoring_extracts_institution_tier_as_a_distinct_requirement(self):
        response = {
            "profile_results": [_assessment()],
            "jd_requirements": [{
                "category": "institution_tier",
                "importance": "preferred",
                "coverage": "unverified",
                "content": "985/211院校优先",
                "source_quote": "985/211院校优先",
            }],
        }
        captured = {}

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

        chain = JobScoringChain(model=RunnableLambda(answer))
        result = chain.invoke(
            resume="本科在读。",
            candidate_profile=_candidate(),
            job={
                "工作名称": "AI应用开发实习生",
                "工作介绍": "本科及以上学历，985/211院校优先。",
            },
            profiles=_profiles(),
            rules="学历和院校层级分开判断。",
        )

        self.assertIn("institution_tier", captured["prompt"])
        self.assertEqual(len(result.jd_requirements), 1)
        self.assertEqual(result.jd_requirements[0].category, "institution_tier")
        self.assertEqual(result.jd_requirements[0].importance, "preferred")
        self.assertEqual(result.jd_requirements[0].source_quote, "985/211院校优先")

    def test_scoring_extracts_non_technical_jd_requirements_and_validates_quotes(self):
        response = {
            "profile_results": [_assessment()],
            "jd_requirements": [
                {
                    "category": "qualification",
                    "importance": "required",
                    "coverage": "unverified",
                    "content": "持护士执业证",
                    "source_quote": "需持护士执业证",
                },
                {
                    "category": "responsibility",
                    "importance": "required",
                    "coverage": "supported",
                    "content": "处理虚构要求",
                    "source_quote": "JD 中不存在的原文",
                },
                {
                    "category": "work_condition",
                    "importance": "preferred",
                    "coverage": "supported",
                    "content": "候选人偏好的福利",
                    "source_quote": "弹性工作、带薪年假",
                },
                {
                    "category": "context",
                    "importance": "context",
                    "coverage": "unverified",
                    "content": "空白引用不能构成来源",
                    "source_quote": "   ",
                },
                {"category": "unknown", "content": "invalid"},
            ],
        }
        captured = {}

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

        chain = JobScoringChain(model=RunnableLambda(answer))
        result = chain.invoke(
            resume="有三年病房护理经验。",
            candidate_profile=_candidate(),
            job={
                "工作名称": "护士",
                "工作介绍": "需持护士执业证，负责患者护理与生命体征记录。",
                "期望福利": "弹性工作、带薪年假",
            },
            profiles=_profiles(),
            rules="简历未写代表未验证。",
        )

        self.assertIn("不要套用固定职业或技能词表", captured["prompt"])
        self.assertEqual(len(result.jd_requirements), 1)
        requirement = result.jd_requirements[0]
        self.assertIsInstance(requirement, JDRequirement)
        self.assertEqual(requirement.category, "qualification")
        self.assertEqual(requirement.coverage, "unverified")
        self.assertEqual(requirement.source_quote, "需持护士执业证")

    def test_scoring_chain_validates_exactly_one_assessment_per_profile(self):
        response = {"profile_results": [_assessment()]}
        captured = {}

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

        chain = JobScoringChain(model=RunnableLambda(answer))
        result = chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=_candidate(),
            job={"工作名称": "Python 后端工程师", "工作介绍": "负责接口开发。"},
            profiles=_profiles(),
            rules="简历未写代表未验证。",
        )

        self.assertIsInstance(result, JobMatchResponse)
        self.assertEqual([item.profile_id for item in result.profile_results], ["backend"])
        self.assertIn("简历未写代表未验证", captured["prompt"])
        self.assertIn('"mode": "any"', captured["prompt"])

    def test_scoring_prompt_serializes_only_assessment_relevant_profile_fields(self):
        response = {"profile_results": [_assessment()]}
        captured = {}

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

        chain = JobScoringChain(model=RunnableLambda(answer))
        chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=_candidate(),
            job={
                "工作名称": "Python 后端工程师",
                "工作介绍": "负责接口开发。",
                "期望福利": "弹性工作、带薪年假",
            },
            profiles=[JobProfile(
                id="backend", name="后端开发", role_family_id="backend",
                role_direction="AI 后端开发",
                search_keywords=["内部搜索词不应进提示词"],
                diagnostic_terms=["内部诊断词不应进提示词"],
                preferred_qualifications=["熟悉分布式系统"],
            )],
            rules="规则",
        )

        self.assertNotIn("内部搜索词不应进提示词", captured["prompt"])
        self.assertNotIn("内部诊断词不应进提示词", captured["prompt"])
        self.assertNotIn("search_keywords", captured["prompt"])
        self.assertNotIn("diagnostic_terms", captured["prompt"])
        self.assertIn("熟悉分布式系统", captured["prompt"])
        self.assertIn("AI 后端开发", captured["prompt"])
        self.assertIn("不预设候选人只求职软件或技术岗位", captured["prompt"])
        self.assertIn("其他职业按其职责、资格和可迁移证据评估", captured["prompt"])
        self.assertIn("弹性工作、带薪年假", captured["prompt"])
        self.assertIn("软偏好", captured["prompt"])
        self.assertIn("不得视为硬缺口", captured["prompt"])

    def test_scoring_prompt_does_not_include_resume_hash_metadata(self):
        response = {"profile_results": [_assessment()]}
        captured = {}

        def answer(prompt_value):
            captured["prompt"] = "\n".join(
                message.content for message in prompt_value.to_messages()
            )
            return AIMessage(content=json.dumps(response, ensure_ascii=False))

        candidate = _candidate().model_copy(
            update={"resume_sha256": "private-resume-hash"}
        )
        chain = JobScoringChain(model=RunnableLambda(answer))
        chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=candidate,
            job={"工作名称": "Python 后端工程师"},
            profiles=_profiles(),
            rules="规则",
        )

        self.assertNotIn("private-resume-hash", captured["prompt"])

    def test_scoring_chain_rejects_missing_duplicate_and_unknown_profile_ids(self):
        profiles = [*_profiles(), JobProfile(
            id="robotics", name="机器人研发", role_family_id="backend",
            search_keywords=["机器人"],
        )]
        for values in ([_assessment()], [_assessment(), _assessment()], [_assessment("unknown")]):
            with self.subTest(values=values):
                chain = JobScoringChain(model=RunnableLambda(
                    lambda _prompt, payload=values: AIMessage(
                        content=json.dumps({"profile_results": payload}, ensure_ascii=False)
                    )
                ))
                with self.assertRaises(InterviewChainError):
                    chain.invoke(
                        resume="使用 Python 开发后端接口",
                        candidate_profile=_candidate(),
                        job={"工作名称": "Python 后端工程师"},
                        profiles=profiles,
                        rules="规则",
                    )

    def test_scoring_chain_rejects_out_of_range_score(self):
        payload = _assessment()
        payload.update({"score": 101})
        chain = JobScoringChain(model=RunnableLambda(
            lambda _prompt, result=payload: AIMessage(
                content=json.dumps({"profile_results": [result]}, ensure_ascii=False)
            )
        ))
        with self.assertRaises(InterviewChainError):
            chain.invoke(
                resume="使用 Python 开发后端接口",
                candidate_profile=_candidate(),
                job={"工作名称": "Python 后端工程师"},
                profiles=_profiles(),
                rules="规则",
            )

    def test_unverifiable_resume_evidence_is_dropped_without_failing_the_score(self):
        payload = _assessment()
        payload.update({"evidence": [{
            "claim": "Go 开发", "source": "resume_quote", "evidence_text": "熟练使用 Go",
        }]})
        chain = JobScoringChain(model=RunnableLambda(
            lambda _prompt, result=payload: AIMessage(
                content=json.dumps({"profile_results": [result]}, ensure_ascii=False)
            )
        ))

        result = chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=_candidate(),
            job={"工作名称": "Python 后端工程师"},
            profiles=_profiles(),
            rules="规则",
        )

        self.assertEqual(result.profile_results[0].score, 85)
        self.assertEqual(result.profile_results[0].evidence, [])

    def test_chinese_evidence_source_is_normalized_instead_of_rejected(self):
        """线上模型常把 source 写成「候选人简历」，应归一化为合法枚举。"""
        payload = _assessment()
        payload.update({"evidence": [
            {"claim": "Python 后端接口开发", "source": "候选人简历",
             "evidence_text": "使用 Python 开发后端接口"},
            {"claim": "用户确认实习", "source": "用户确认",
             "evidence_text": "用户确认"},
        ]})
        chain = JobScoringChain(model=RunnableLambda(
            lambda _prompt, result=payload: AIMessage(
                content=json.dumps({"profile_results": [result]}, ensure_ascii=False)
            )
        ))

        result = chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=_candidate(),
            job={"工作名称": "Python 后端工程师"},
            profiles=_profiles(),
            rules="规则",
        )

        sources = [item.source for item in result.profile_results[0].evidence]
        self.assertEqual(sources, ["resume_quote", "user_confirmed"])

    def test_unknown_or_incomplete_evidence_source_is_dropped_not_fatal(self):
        payload = _assessment()
        payload.update({"evidence": [
            {"claim": "神秘证据", "source": "unknown_source", "evidence_text": "x"},
            {"claim": "", "source": "resume_quote", "evidence_text": "使用 Python 开发后端接口"},
        ]})
        chain = JobScoringChain(model=RunnableLambda(
            lambda _prompt, result=payload: AIMessage(
                content=json.dumps({"profile_results": [result]}, ensure_ascii=False)
            )
        ))

        result = chain.invoke(
            resume="使用 Python 开发后端接口",
            candidate_profile=_candidate(),
            job={"工作名称": "Python 后端工程师"},
            profiles=_profiles(),
            rules="规则",
        )

        self.assertEqual(result.profile_results[0].evidence, [])


if __name__ == "__main__":
    unittest.main()
