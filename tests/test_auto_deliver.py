import csv
import json
import io
import threading
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import boss_spider
import desktop_panel
import platform_locations
from auto_deliver import (
    AIClient,
    AutoDeliverer,
    configure_platform_search,
    RESULT_FIELDS,
    classify_jd_requirements,
    classify_job_scope,
    choose_primary_assessment,
    extract_resume_evidence,
    extract_skill_tags,
    load_matching_config,
    local_feasibility,
)
from ai_chains import JobMatchResponse, ProfileAssessment
from candidate_profiles import CandidateEvidence, CandidateProfile, RoleFamily
from job_profiles import JobProfile
from job_type_logic import (
    effective_job_type_preference,
    normalize_job_type_preference,
    transition_job_type_preference,
)


def make_candidate_profile():
    return CandidateProfile(
        confirmed=True,
        revision=1,
        primary_direction="AI 应用研发",
        allowed_role_families=[
            RoleFamily(id="backend", name="后端开发", aliases=["后端开发"], title_terms=["后端工程师"]),
            RoleFamily(id="robotics", name="机器人开发", aliases=["机器人研发"], title_terms=["机器人软件工程师"]),
        ],
        excluded_role_families=["销售"],
        excluded_terms=["销售岗", "房地产经纪"],
    )


class CandidateScopeTests(unittest.TestCase):
    def test_confirmed_title_aliases_are_in_scope(self):
        state, _reason = classify_job_scope(
            {"工作名称": "Python 后端工程师", "工作介绍": "负责接口设计与开发。"},
            make_candidate_profile(),
        )

        self.assertEqual(state, "in_scope")

    def test_incidental_sales_team_mention_in_a_duty_clause_does_not_exclude_role(self):
        state, _reason = classify_job_scope(
            {
                "工作名称": "后端工程师",
                "工作介绍": "負責后端接口与数据服务开发，支持销售团队查看客户报表。",
            },
            make_candidate_profile(),
        )

        self.assertEqual(state, "in_scope")

    def test_explicitly_excluded_sales_title_is_out_of_scope(self):
        state, _reason = classify_job_scope(
            {"工作名称": "AI产品销售", "工作介绍": "负责拓展客户和签约回款。"},
            make_candidate_profile(),
        )

        self.assertEqual(state, "out_of_scope")

    def test_incidental_sales_mention_does_not_exclude_backend_role(self):
        state, _reason = classify_job_scope(
            {
                "工作名称": "后端工程师",
                "工作介绍": "负责接口和服务开发。產品需支持销售团队查看客户数据。",
            },
            make_candidate_profile(),
        )

        self.assertEqual(state, "in_scope")

    def test_excluded_role_family_is_not_inferred_from_a_duty_mention(self):
        state, _reason = classify_job_scope(
            {
                "工作名称": "后端工程师",
                "工作介绍": "负责后端接口开发，为销售团队提供客户报表服务。",
            },
            make_candidate_profile(),
        )

        self.assertEqual(state, "in_scope")

    def test_unclassifiable_role_requires_scope_review(self):
        state, _reason = classify_job_scope(
            {"工作名称": "AI产品经理", "工作介绍": "负责产品规划、需求分析和跨团队协作。"},
            make_candidate_profile(),
        )

        self.assertEqual(state, "scope_review")


class ScopeAndAssessmentTests(unittest.TestCase):
    def test_scope_synonym_group_expands_term_hits(self):
        from auto_deliver import _scope_text_hits

        self.assertTrue(_scope_text_hits("大模型应用开发工程师", "AI应用开发"))
        self.assertTrue(_scope_text_hits("LLM 推理服务研发", "大模型"))
        self.assertTrue(_scope_text_hits("Agent 工作流编排平台", "智能体"))
        self.assertTrue(_scope_text_hits("检索增强知识库项目", "RAG"))
        self.assertFalse(_scope_text_hits("行政专员", "AI应用开发"))

    def test_scope_synonym_match_makes_title_in_scope(self):
        profile = CandidateProfile(
            confirmed=True, revision=1, primary_direction="AI 应用研发",
            allowed_role_families=[
                RoleFamily(id="ai-app", name="AI应用开发", title_terms=["AI应用开发"]),
            ],
        )

        state, _reason = classify_job_scope(
            {"工作名称": "大模型应用开发工程师", "工作介绍": ""},
            profile,
        )

        self.assertEqual(state, "in_scope")

    def test_highest_passing_profile_uses_its_own_threshold(self):
        profiles = [
            JobProfile(id="backend-profile", name="后端", role_family_id="backend", search_keywords=["后端"], threshold=80),
            JobProfile(id="robotics-profile", name="机器人", role_family_id="robotics", search_keywords=["机器人"], threshold=65),
        ]
        response = JobMatchResponse(profile_results=[
            ProfileAssessment(profile_id="backend-profile", score=77, role_fit=90, reason="后端契合"),
            ProfileAssessment(profile_id="robotics-profile", score=76, role_fit=75, reason="机器人相邻经验"),
        ])

        selected = choose_primary_assessment(response, profiles, global_threshold=70)

        self.assertEqual(selected.profile_id, "robotics-profile")

    def test_malformed_or_incomplete_assessments_cannot_select_a_primary_profile(self):
        profiles = [
            JobProfile(id="backend-profile", name="后端", role_family_id="backend", search_keywords=["后端"]),
            JobProfile(id="robotics-profile", name="机器人", role_family_id="robotics", search_keywords=["机器人"]),
        ]
        response = JobMatchResponse(profile_results=[
            ProfileAssessment(profile_id="backend-profile", score=95, role_fit=95, reason="很匹配"),
        ])

        self.assertIsNone(choose_primary_assessment(response, profiles, global_threshold=70))


class JobTypePolicyTests(unittest.TestCase):
    def test_platform_internship_or_full_time_overrides_conflicting_priority(self):
        self.assertEqual(effective_job_type_preference("实习", "全职"), "实习")
        self.assertEqual(effective_job_type_preference("全职", "实习"), "全职")
        self.assertEqual(normalize_job_type_preference("实习", "全职"), "实习")

    def test_unrestricted_platform_keeps_selected_priority(self):
        self.assertEqual(effective_job_type_preference("不限", "全职"), "全职")
        self.assertEqual(normalize_job_type_preference("不限", "全职"), "全职")

    def test_part_time_disables_type_priority_without_erasing_saved_preference(self):
        self.assertIsNone(effective_job_type_preference("兼职", "全职"))
        self.assertEqual(normalize_job_type_preference("兼职", "全职"), "全职")

    def test_switching_back_to_unrestricted_restores_previous_priority(self):
        selected, remembered = transition_job_type_preference(
            "不限", "实习", "全职", "全职"
        )
        self.assertEqual((selected, remembered), ("实习", "全职"))

        selected, remembered = transition_job_type_preference(
            "实习", "不限", selected, remembered
        )
        self.assertEqual((selected, remembered), ("全职", "全职"))


class JobTypeSettingsControlTests(unittest.TestCase):
    class Combo:
        def __init__(self, value):
            self.value = value
            self.enabled = True
            self.tooltip = ""

        def currentText(self):
            return self.value

        def setCurrentText(self, value):
            self.value = value

        def setEnabled(self, enabled):
            self.enabled = bool(enabled)

        def setToolTip(self, tooltip):
            self.tooltip = tooltip

    def test_platform_change_locks_matching_type_and_restores_saved_priority(self):
        platform = self.Combo("不限")
        preference = self.Combo("全职")
        part_time = self.Combo("寒暑假")
        saved_settings = {}
        app = SimpleNamespace(
            vars={"PLATFORM_JOB_TYPE": (platform, "select", "不限"),
                  "JOB_TYPE_PREFERENCE": (preference, "select", "实习"),
                  "PLATFORM_PART_TIME": (part_time, "select", "不限")},
            _loading_env=False,
            _last_platform_job_type="不限",
            _unrestricted_job_type_preference="全职",
            _settings=SimpleNamespace(
                setValue=lambda key, value: saved_settings.__setitem__(key, value)
            ),
        )
        app._update_job_type_preference_control = lambda value: (
            desktop_panel.PanelApp._update_job_type_preference_control(app, value)
        )
        app._update_part_time_filter_control = lambda value: (
            desktop_panel.PanelApp._update_part_time_filter_control(app, value)
        )

        platform.setCurrentText("实习")
        desktop_panel.PanelApp._on_platform_job_type_changed(app, "实习")

        self.assertEqual(preference.currentText(), "实习")
        self.assertFalse(preference.enabled)
        self.assertIn("同步锁定", preference.tooltip)
        self.assertEqual(saved_settings["jobType/unrestrictedPreference"], "全职")
        # 兼职时段筛选只对「兼职」开放
        self.assertFalse(part_time.enabled)

        platform.setCurrentText("兼职")
        desktop_panel.PanelApp._on_platform_job_type_changed(app, "兼职")
        self.assertEqual(preference.currentText(), "全职")
        self.assertFalse(preference.enabled)
        self.assertTrue(part_time.enabled)

        platform.setCurrentText("不限")
        desktop_panel.PanelApp._on_platform_job_type_changed(app, "不限")

        self.assertEqual(preference.currentText(), "全职")
        self.assertTrue(preference.enabled)
        self.assertFalse(part_time.enabled)


class CrossProfessionMatchingTests(unittest.TestCase):
    SCENARIOS = (
        {
            "name": "产品经理",
            "id": "product",
            "title_terms": ["B端产品经理", "产品运营"],
            "resume": (
                "校园服务产品项目 | 产品负责人\n"
                "访谈12名学生和6家校园商户，整理高频问题并绘制核心用户流程。\n"
                "编写预约服务PRD与验收用例，和3名开发同学协作上线微信小程序原型。\n"
                "根据两轮可用性测试记录调整预约步骤，形成需求变更与版本复盘文档。"
            ),
            "evidence": "编写预约服务PRD与验收用例",
            "target": {
                "title": "B端产品经理（商户服务）",
                "duties": "岗位职责：负责商户需求访谈、产品方案设计、PRD编写和研发验收。",
                "score": 91,
            },
            "adjacent": {
                "title": "产品运营专员",
                "duties": "岗位职责：负责产品上线运营、收集用户反馈、分析活动数据并推动体验优化。",
                "score": 73,
            },
            "unrelated": {
                "title": "仓储物流专员",
                "duties": "岗位职责：负责仓库出入库登记、库存盘点和物流单据核对。",
                "score": 73,
            },
        },
        {
            "name": "数据分析师",
            "id": "data-analyst",
            "title_terms": ["数据分析师", "商业分析师"],
            "resume": (
                "电商经营分析项目 | 数据分析\n"
                "使用SQL清洗并关联订单、商品和渠道表，核对关键指标口径。\n"
                "用Python分析复购与退款分布，发现两个渠道的退款率存在明显差异。\n"
                "搭建Power BI周报看板，并向运营同学说明指标变化及数据限制。"
            ),
            "evidence": "使用SQL清洗并关联订单、商品和渠道表",
            "target": {
                "title": "数据分析师（电商）",
                "duties": "岗位职责：负责SQL取数、经营指标分析、异常归因和BI看板维护。",
                "score": 89,
            },
            "adjacent": {
                "title": "商业分析师",
                "duties": "岗位职责：负责市场与经营数据分析，支持业务规划并输出专题分析报告。",
                "score": 72,
            },
            "unrelated": {
                "title": "招聘专员",
                "duties": "岗位职责：负责候选人寻访、简历筛选、面试安排和招聘进度跟踪。",
                "score": 73,
            },
        },
        {
            "name": "招聘专员",
            "id": "recruiter",
            "title_terms": ["招聘专员", "人才招聘"],
            "resume": (
                "校园招聘协作项目 | 招聘助理\n"
                "按岗位画像整理候选人筛选表，初筛80余份简历并记录匹配依据。\n"
                "协调业务面试官完成20余场面试，及时同步候选人进度与反馈。\n"
                "复盘招聘渠道到面情况，整理周报和常见候选人问题供团队参考。"
            ),
            "evidence": "初筛80余份简历并记录匹配依据",
            "target": {
                "title": "招聘专员（校招）",
                "duties": "岗位职责：负责岗位发布、简历筛选、面试协调及候选人沟通。",
                "score": 90,
            },
            "adjacent": {
                "title": "人才招聘顾问",
                "duties": "岗位职责：理解客户招聘需求，寻访候选人并推进面试和录用流程。",
                "score": 74,
            },
            "unrelated": {
                "title": "产品运营专员",
                "duties": "岗位职责：负责产品上线运营、用户活动策划和体验问题跟进。",
                "score": 73,
            },
        },
        {
            "name": "会计",
            "id": "accountant",
            "title_terms": ["会计", "财务会计", "成本会计"],
            "resume": (
                "制造企业财务实习 | 会计助理\n"
                "整理费用报销单和原始凭证，按科目归档并协助检查附件完整性。\n"
                "使用Excel汇总月度费用，协助核对银行流水与往来明细。\n"
                "参与存货抽盘和月结资料准备，按复核意见更正台账差异。"
            ),
            "evidence": "协助核对银行流水与往来明细",
            "target": {
                "title": "财务会计",
                "duties": "岗位职责：负责日常账务处理、凭证审核、银行对账及月结支持。",
                "score": 88,
            },
            "adjacent": {
                "title": "成本会计",
                "duties": "岗位职责：负责成本数据归集、存货核算、差异分析和成本报表。",
                "score": 71,
            },
            "unrelated": {
                "title": "视觉设计师",
                "duties": "岗位职责：负责品牌视觉设计、宣传物料制作和电商页面改版。",
                "score": 73,
            },
        },
        {
            "name": "护士",
            "id": "nurse",
            "title_terms": ["护士", "临床护理", "门诊护士"],
            "resume": (
                "综合病区护理实习 | 护理专业\n"
                "在带教老师指导下测量并记录生命体征，按流程完成护理文书。\n"
                "参与病区交接与患者宣教，发现异常情况后及时向带教老师报告。\n"
                "遵循院感要求完成基础护理操作练习，熟悉医嘱核对和隐私保护流程。"
            ),
            "evidence": "测量并记录生命体征，按流程完成护理文书",
            "target": {
                "title": "临床护士（综合病区）",
                "duties": "岗位职责：负责病区基础护理、生命体征观察、护理记录和患者宣教。",
                "score": 90,
            },
            "adjacent": {
                "title": "门诊护士",
                "duties": "岗位职责：负责门诊患者分诊、就诊引导、基础护理和诊疗秩序维护。",
                "score": 70,
            },
            "unrelated": {
                "title": "数据分析师",
                "duties": "岗位职责：负责业务数据提取、指标体系维护和经营分析报告。",
                "score": 73,
            },
        },
        {
            "name": "视觉设计师",
            "id": "visual-designer",
            "title_terms": ["视觉设计师", "平面设计师", "电商设计师"],
            "resume": (
                "校园品牌视觉项目 | 视觉设计\n"
                "使用Figma和Photoshop制作活动主视觉、社交媒体海报及延展物料。\n"
                "为校园文创小店改版商品详情页，整理字体、色彩和组件使用规范。\n"
                "根据同学试用反馈调整信息层级，并交付可复用的源文件和导出规范。"
            ),
            "evidence": "使用Figma和Photoshop制作活动主视觉",
            "target": {
                "title": "视觉设计师（品牌方向）",
                "duties": "岗位职责：负责品牌视觉、活动主视觉、线上线下宣传物料设计。",
                "score": 92,
            },
            "adjacent": {
                "title": "电商设计师",
                "duties": "岗位职责：负责商品详情页、营销活动页面和店铺视觉规范维护。",
                "score": 72,
            },
            "unrelated": {
                "title": "招聘专员",
                "duties": "岗位职责：负责简历初筛、候选人联系、面试组织和录用跟进。",
                "score": 73,
            },
        },
    )

    def test_user_confirmed_professions_are_not_limited_to_software_roles(self):
        for scenario in self.SCENARIOS:
            family_name = scenario["name"]
            with self.subTest(family=family_name):
                candidate = CandidateProfile(
                    confirmed=True,
                    revision=1,
                    primary_direction=family_name,
                    allowed_role_families=[RoleFamily(
                        id=scenario["id"],
                        name=family_name,
                        title_terms=scenario["title_terms"],
                    )],
                )

                state, _reason = classify_job_scope({
                    "工作名称": scenario["target"]["title"],
                    "工作介绍": scenario["target"]["duties"],
                }, candidate)

                self.assertEqual(state, "in_scope")

    def test_target_adjacent_and_unrelated_jobs_are_scored_against_realistic_resumes(self):
        from ai_chains import JobScoringChain
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda

        for scenario in self.SCENARIOS:
            with self.subTest(family=scenario["name"]):
                candidate = CandidateProfile(
                    confirmed=True,
                    revision=1,
                    primary_direction=scenario["name"],
                    allowed_role_families=[RoleFamily(
                        id=scenario["id"],
                        name=scenario["name"],
                        title_terms=scenario["title_terms"],
                    )],
                    evidence=[{
                        "claim": f"{scenario['name']}相关实践",
                        "source": "resume_quote",
                        "evidence_text": scenario["evidence"],
                    }],
                )
                profile = JobProfile(
                    id=f"{scenario['id']}-profile",
                    name=f"{scenario['name']}岗位",
                    role_family_id=scenario["id"],
                    role_direction=scenario["name"],
                    search_keywords=[scenario["name"]],
                )

                for relation in ("target", "adjacent", "unrelated"):
                    job_case = scenario[relation]
                    with self.subTest(job=job_case["title"]):
                        scope, _reason = classify_job_scope({
                            "工作名称": job_case["title"],
                            "工作介绍": job_case["duties"],
                        }, candidate)
                        if relation == "unrelated":
                            self.assertEqual(scope, "scope_review")
                        else:
                            self.assertEqual(scope, "in_scope")

                        captured_prompts = []
                        payload = {"profile_results": [{
                            "profile_id": profile.id,
                            "score": job_case["score"],
                            "role_fit": job_case["score"],
                            "reason": f"{job_case['title']}与该简历的相关性测试评分。",
                            "confidence": 90,
                            "evidence": ([{
                                "claim": f"{scenario['name']}相关实践",
                                "source": "resume_quote",
                                "evidence_text": scenario["evidence"],
                            }] if relation != "unrelated" else []),
                        }]}

                        def answer(prompt, response=payload):
                            captured_prompts.append("\n".join(
                                message.content for message in prompt.to_messages()
                            ))
                            return AIMessage(
                                content=json.dumps(response, ensure_ascii=False)
                            )

                        chain = JobScoringChain(model=RunnableLambda(answer))
                        response = chain.invoke(
                            resume=scenario["resume"],
                            candidate_profile=candidate,
                            job={
                                "工作名称": job_case["title"],
                                "工作介绍": job_case["duties"],
                                "职业范围状态": scope,
                            },
                            profiles=[profile],
                            rules="只引用简历中存在的证据；按每个岗位职责分别评估。",
                        )
                        unpenalized = choose_primary_assessment(
                            response,
                            [profile],
                            global_threshold=70,
                        )
                        selected = choose_primary_assessment(
                            response,
                            [profile],
                            global_threshold=70,
                            review_penalty=5 if scope == "scope_review" else 0,
                        )

                        self.assertEqual(
                            selected is not None,
                            relation != "unrelated",
                        )
                        self.assertIsNotNone(unpenalized)
                        self.assertEqual(
                            response.profile_results[0].score,
                            job_case["score"],
                        )
                        self.assertIn(scenario["resume"], captured_prompts[0])
                        self.assertIn(job_case["duties"], captured_prompts[0])
                        if relation != "unrelated":
                            self.assertEqual(
                                response.profile_results[0].evidence[0].evidence_text,
                                scenario["evidence"],
                            )
                        else:
                            self.assertEqual(response.profile_results[0].evidence, [])

    def test_confirmed_profession_controls_scope_not_the_search_keyword(self):
        candidate = CandidateProfile(
            confirmed=True,
            revision=1,
            primary_direction="会计",
            allowed_role_families=[RoleFamily(
                id="accounting",
                name="会计",
                title_terms=["会计", "财务会计"],
            )],
        )

        state, _reason = classify_job_scope({
            "工作名称": "招聘专员",
            "工作介绍": "负责简历筛选和候选人面试。",
            "搜索来源关键词": ["会计"],
        }, candidate)

        self.assertEqual(state, "scope_review")

    def test_profile_mode_does_not_apply_global_education_or_experience_rejections(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.profile_mode = True
        deliverer.cfg = {"area_filter": []}
        deliverer.tracker = SimpleNamespace(already_done=lambda _job_id: False)
        deliverer.seen_job_ids = set()
        deliverer.stage_counts = {}

        candidates = deliverer._filter_jobs([{
            "encryptJobId": "senior-accountant",
            "jobName": "高级会计师",
            "jobExperience": "5-10年",
            "jobDegree": "博士",
            "brandName": "示例事务所",
        }])

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["工作名称"], "高级会计师")

    def test_profile_mode_does_not_apply_fixed_hr_function_rejection(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.profile_mode = True
        deliverer.cfg = {
            "welfare_require": [],
            "rest_day_require": "不限",
            "work_time_start": "",
            "work_time_end": "",
            "role_reject_shadow": False,
        }
        deliverer.seen_job_ids = set()
        deliverer.stage_counts = {}
        recorded = []
        deliverer._record = recorded.append
        deliverer._fetch_jd_dom = lambda _job: {
            "desc": "岗位职责：负责简历筛选、招聘面试及候选人沟通。",
            "skills": [],
            "welfare_tags": [],
            "company_url": "",
        }

        with patch("auto_deliver.time.sleep"):
            prepared = deliverer._prepare_job({
                "encryptJobId": "recruiter-1",
                "工作名称": "招聘专员",
                "技术要求": "",
                "公司": "示例公司",
            })

        self.assertTrue(prepared)
        self.assertEqual(deliverer.stage_counts["eligible_for_ai"], 1)
        self.assertEqual(recorded, [])

    def test_synthetic_resumes_and_jobs_reach_the_shared_scoring_chain(self):
        from ai_chains import JobScoringChain
        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda

        for scenario in self.SCENARIOS:
            family_name = scenario["name"]
            with self.subTest(family=family_name):
                resume = scenario["resume"]
                family_id = scenario["id"]
                candidate = CandidateProfile(
                    confirmed=True,
                    revision=1,
                    primary_direction=family_name,
                    allowed_role_families=[RoleFamily(
                        id=family_id,
                        name=family_name,
                        title_terms=scenario["title_terms"],
                    )],
                    evidence=[{
                        "claim": f"{family_name}相关实践",
                        "source": "resume_quote",
                        "evidence_text": scenario["evidence"],
                    }],
                )
                profile = JobProfile(
                    id=f"{family_id}-profile",
                    name=f"{family_name}岗位",
                    role_family_id=family_id,
                    role_direction=family_name,
                    search_keywords=[family_name],
                )
                payload = {"profile_results": [{
                    "profile_id": profile.id,
                    "score": scenario["target"]["score"],
                    "role_fit": scenario["target"]["score"],
                    "reason": f"{family_name}职责与简历中的相关实践相符。",
                    "confidence": 90,
                    "evidence": [{
                        "claim": f"{family_name}相关实践",
                        "source": "resume_quote",
                        "evidence_text": scenario["evidence"],
                    }],
                }]}
                captured_prompts = []
                deliverer = AutoDeliverer.__new__(AutoDeliverer)
                deliverer.cfg = {
                    "dry_run": True,
                    "test_limit": 1,
                    "daily_limit": 10,
                    "match_threshold": 70,
                    "scope_review_penalty": 5,
                    "local_gate_shadow": True,
                    "job_type_preference": "实习",
                    "job_delay": (0, 0),
                    "login_wait": 0,
                    "area_filter": [],
                }
                deliverer.profile_mode = True
                deliverer.matching_context = {
                    "candidate": candidate,
                    "profiles": [profile],
                    "rules": "简历未提及表示未验证；不同行业按岗位职责分别评估。",
                    "allocations": [{
                    "keyword": family_name,
                        "profile_ids": [profile.id],
                        "pages": [1],
                    }],
                }
                deliverer.tracker = SimpleNamespace(
                    data={"count": 0},
                    can_deliver=lambda _limit: True,
                    already_done=lambda _job_id: False,
                )
                deliverer.seen_job_ids = set()
                deliverer.stage_counts = {}
                deliverer.resume_text = resume
                deliverer.scoring_resume_prompt = resume
                deliverer.scoring_chain = JobScoringChain(model=RunnableLambda(
                    lambda prompt, response=payload: captured_prompts.append(
                        "\n".join(
                            message.content for message in prompt.to_messages()
                        )
                    ) or AIMessage(
                        content=json.dumps(response, ensure_ascii=False)
                    )
                ))
                deliverer.ai = SimpleNamespace(
                    gen_greeting=lambda *_args, **_kwargs: "您好，我有相关项目实践。"
                )
                deliverer.match_scores = {}
                deliverer.deliver_count = 0
                deliverer.stop_event = threading.Event()
                deliverer.page = SimpleNamespace(quit=lambda: None)
                deliverer.wait_login = lambda _timeout: None
                deliverer.get_cookie_headers = lambda: True
                deliverer.start_heartbeat = lambda: None
                deliverer.api_job_list = lambda page, keyword: {
                    "zpData": {"jobList": [{
                        "encryptJobId": f"{family_id}-job",
                        "jobName": scenario["target"]["title"],
                        "brandName": "合成测试公司",
                        "jobTypeName": "实习",
                    }]},
                }
                duties = scenario["target"]["duties"]
                deliverer._prepare_job = lambda job, description=duties: (
                    job.update({"工作介绍": description}) or True
                )
                deliverer._diagnose_profile_terms = lambda _job: (None, "仅展示")
                deliverer.save_results = lambda: None
                deliverer._print_stage_summary = lambda: None
                recorded = []
                deliverer._record = recorded.append
                deliverer.deliver_one = lambda *_args, **_kwargs: self.fail(
                    "synthetic dry-run must not call delivery"
                )

                with patch("auto_deliver.time.sleep"):
                    deliverer.run()

                self.assertEqual(deliverer.stage_counts["ai_called"], 1)
                self.assertEqual(deliverer.stage_counts["dry_run_ready"], 1)
                self.assertEqual(recorded[0]["投递状态"], "dry_run")
                self.assertEqual(
                    recorded[0]["AI匹配分数"],
                    scenario["target"]["score"],
                )
                self.assertEqual(deliverer.deliver_count, 0)
                self.assertIn(resume, captured_prompts[0])
                self.assertIn(duties, captured_prompts[0])
                self.assertIn(f"{family_name}岗位", captured_prompts[0])


class PlatformSearchFilterTests(unittest.TestCase):
    def test_job_list_request_includes_selected_platform_filters(self):
        spider = boss_spider.BossDP.__new__(boss_spider.BossDP)
        with patch.dict(boss_spider.Config, {
            "city_id": "101280600",
            "page_size": 30,
            "multiBusinessDistrict": "440305,440304",
            "jobType": "1902",
            "payType": "2501",
            "partTime": "2702",
            "experience": "108",
            "degree": "202",
            "industry": "100020",
            "scale": "302",
        }), patch.object(spider, "_request_json", return_value={}) as request:
            spider.api_job_list(page=2, keyword="AI应用开发")

        self.assertEqual(request.call_args.kwargs["data"], {
            "page": 2,
            "pageSize": 30,
            "city": "101280600",
            "query": "AI应用开发",
            "scene": 1,
            "multiBusinessDistrict": "440305,440304",
            "jobType": "1902",
            "payType": "2501",
            "partTime": "2702",
            "experience": "108",
            "degree": "202",
            "industry": "100020",
            "scale": "302",
        })
        self.assertNotIn("params", request.call_args.kwargs)

    def test_job_list_request_omits_unselected_platform_filters(self):
        spider = boss_spider.BossDP.__new__(boss_spider.BossDP)
        with patch.dict(boss_spider.Config, {
            "city_id": "101280600",
            "page_size": 30,
            "multiBusinessDistrict": "",
            "jobType": "",
            "payType": "",
            "partTime": "",
            "experience": "",
            "degree": "",
            "industry": "",
            "scale": "",
        }), patch.object(spider, "_request_json", return_value={}) as request:
            spider.api_job_list(page=1, keyword="AI应用开发")

        self.assertEqual(request.call_args.kwargs["data"], {
            "page": 1,
            "pageSize": 30,
            "city": "101280600",
            "query": "AI应用开发",
            "scene": 1,
        })
        self.assertNotIn("params", request.call_args.kwargs)

    def test_browser_search_url_carries_the_same_selected_filters(self):
        builder = getattr(boss_spider, "build_job_search_url", None)
        self.assertTrue(callable(builder), "search URL builder is missing")

        url = builder({
            "base_url": "https://www.zhipin.com",
            "city_id": "101280600",
            "position": "",
            "keyword": "AI应用开发",
            "multiBusinessDistrict": "440305",
            "jobType": "1902",
        })

        self.assertEqual(parse_qs(urlparse(url).query), {
            "city": ["101280600"],
            "multiBusinessDistrict": ["440305"],
            "jobType": ["1902"],
            "query": ["AI应用开发"],
        })

    def test_browser_search_url_carries_every_selected_filter(self):
        url = boss_spider.build_job_search_url({
            "base_url": "https://www.zhipin.com",
            "city_id": "101280600",
            "position": "",
            "keyword": "兼职测试岗位",
            "multiBusinessDistrict": "440305",
            "jobType": "1903",
            "payType": "2501",
            "partTime": "2702",
            "experience": "108",
            "degree": "202",
            "industry": "100020",
            "scale": "302",
        })

        self.assertEqual(parse_qs(urlparse(url).query), {
            "city": ["101280600"],
            "multiBusinessDistrict": ["440305"],
            "jobType": ["1903"],
            "payType": ["2501"],
            "partTime": ["2702"],
            "experience": ["108"],
            "degree": ["202"],
            "industry": ["100020"],
            "scale": ["302"],
            "query": ["兼职测试岗位"],
        })

    def test_desktop_settings_persist_platform_filter_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            with patch.object(desktop_panel, "ENV_FILE", env_path):
                desktop_panel.write_env_file({
                    "PLATFORM_AREA_FILTER": "南山区,福田区",
                    "PLATFORM_JOB_TYPE": "实习",
                })
                saved = desktop_panel.read_env_dict()

        self.assertEqual(saved["PLATFORM_AREA_FILTER"], "南山区,福田区")
        self.assertEqual(saved["PLATFORM_JOB_TYPE"], "实习")

    def test_tavily_settings_persist_without_dropping_existing_env_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("AI_API_KEY=existing-model-key\n", encoding="utf-8")
            with patch.object(desktop_panel, "ENV_FILE", env_path):
                desktop_panel.write_env_file({
                    "TAVILY_ENABLED": "true",
                    "TAVILY_API_KEY": "test-tavily-key",
                    "TAVILY_TIMEOUT": "9",
                })
                saved = desktop_panel.read_env_dict()

        self.assertEqual(saved["AI_API_KEY"], "existing-model-key")
        self.assertEqual(saved["TAVILY_ENABLED"], "true")
        self.assertEqual(saved["TAVILY_API_KEY"], "test-tavily-key")
        self.assertEqual(saved["TAVILY_TIMEOUT"], "9")


class CandidateProfileStartupGuardTests(unittest.TestCase):
    def test_panel_starts_in_base_mode_without_confirmed_profile(self):
        logs = []
        runner = SimpleNamespace(start=lambda: "任务已启动", running=lambda: True)
        app = SimpleNamespace(
            _collect_values=lambda: {"DRY_RUN": "true"},
            runner=runner,
            append_log=logs.append,
        )
        missing_store = SimpleNamespace(load=lambda: None)

        with patch.object(desktop_panel, "CandidateProfileStore", return_value=missing_store, create=True), \
                patch.object(desktop_panel, "target_job_startup_error", return_value=None), \
                patch.object(desktop_panel, "write_env_file") as write_env, \
                patch.object(desktop_panel.QMessageBox, "warning") as showwarning:
            desktop_panel.PanelApp.start_task(app)

        # 规范：允许不使用增强画像，缺失画像按基础画像启动，不再阻塞
        write_env.assert_called_once()
        showwarning.assert_not_called()
        self.assertTrue(any("基础画像" in line for line in logs))

    def test_panel_blocks_task_without_a_target_job(self):
        runner = SimpleNamespace(start=lambda: self.fail("task runner must not start"), running=lambda: False)
        app = SimpleNamespace(
            _collect_values=lambda: {"DRY_RUN": "true"},
            runner=runner,
            append_log=lambda _message: None,
            _show_page=lambda name: None,
        )
        missing_store = SimpleNamespace(load=lambda: None)

        # 不依赖工作区真实配置：显式模拟「没有填写目标岗位」
        with patch.object(desktop_panel, "CandidateProfileStore", return_value=missing_store, create=True), \
                patch.object(desktop_panel, "target_job_startup_error",
                             return_value="请先在「求职设置」填写目标岗位。"), \
                patch.object(desktop_panel, "write_env_file") as write_env, \
                patch.object(desktop_panel.QMessageBox, "warning") as showwarning:
            desktop_panel.PanelApp.start_task(app)

        write_env.assert_not_called()
        showwarning.assert_called_once()
        self.assertIn("目标岗位", showwarning.call_args[0][1])

    def test_panel_still_blocks_invalid_candidate_profile_file(self):
        def raise_invalid():
            raise ValueError("坏文件")

        bad_store = SimpleNamespace(load=raise_invalid)
        runner = SimpleNamespace(start=lambda: self.fail("task runner must not start"), running=lambda: False)
        app = SimpleNamespace(
            _collect_values=lambda: {"DRY_RUN": "true"},
            runner=runner,
            append_log=lambda _message: None,
        )

        with patch.object(desktop_panel, "CandidateProfileStore", return_value=bad_store, create=True), \
                patch.object(desktop_panel, "write_env_file") as write_env, \
                patch.object(desktop_panel.QMessageBox, "warning") as showwarning:
            desktop_panel.PanelApp.start_task(app)

        write_env.assert_not_called()
        showwarning.assert_called_once()

    def test_panel_runtime_config_reads_env_fresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            with patch.object(desktop_panel, "ENV_FILE", env_path):
                desktop_panel.write_env_file({
                    "TAVILY_ENABLED": "true",
                    "TAVILY_API_KEY": "fresh-key",
                    "AI_API_KEY": "fresh-ai-key",
                    "AI_TIMEOUT": "45",
                })
                config = desktop_panel.current_deliver_config()
                self.assertEqual(config["tavily_api_key"], "fresh-key")
                self.assertTrue(config["tavily_enabled"])
                self.assertEqual(config["ai_api_key"], "fresh-ai-key")
                self.assertEqual(config["ai_timeout"], 45)

                # 清空 key 后现读结果立即反映（保存即生效；ready 需要 key 非空）
                desktop_panel.write_env_file({"TAVILY_API_KEY": ""})
                config = desktop_panel.current_deliver_config()
                self.assertEqual(config["tavily_api_key"], "")

    def test_profile_service_researcher_uses_fresh_env_key(self):
        recorded = {}

        class FakeResearcher:
            def __init__(self, **kwargs):
                recorded.update(kwargs)

        deps = {
            "CandidateInterviewChain": lambda model: None,
            "build_chat_model": lambda cfg: None,
            "TavilyRoleResearcher": FakeResearcher,
            # 模拟 import 快照过期：key 为空
            "DELIVER_CONFIG": {
                "tavily_enabled": False, "tavily_api_key": "", "tavily_timeout": 12,
            },
            "model": None,
            "signature": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            with patch.object(desktop_panel, "ENV_FILE", env_path):
                desktop_panel.write_env_file({
                    "TAVILY_ENABLED": "true",
                    "TAVILY_API_KEY": "fresh-key",
                })
                desktop_panel.PanelApp._build_profile_service(
                    SimpleNamespace(), deps, None, resume="",
                )

        # 面板保存后立即生效，不再依赖过期的 DELIVER_CONFIG 快照
        self.assertEqual(recorded.get("api_key"), "fresh-key")
        self.assertTrue(recorded.get("enabled"))

    def test_city_setting_shows_names_but_password_stores_codes(self):
        self.assertIn("深圳", desktop_panel.SELECT_OPTIONS["CITY_CODE"])
        self.assertEqual(desktop_panel.CITY_CHOICES["深圳"], "101280600")
        self.assertEqual(
            desktop_panel.CITY_NAME_BY_CODE["101280600"], "深圳"
        )

    def test_city_widget_round_trips_code_to_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("CITY_CODE=101020100\n", encoding="utf-8")
            with patch.object(desktop_panel, "ENV_FILE", env_path):
                env = desktop_panel.read_env_dict()
        self.assertEqual(env["CITY_CODE"], "101020100")
        # 界面显示城市名，.env 写回代码
        self.assertEqual(desktop_panel.CITY_NAME_BY_CODE["101020100"], "上海")
        self.assertEqual(desktop_panel.CITY_CHOICES["上海"], "101020100")

    def test_city_choices_are_loaded_from_attached_city_code_file(self):
        self.assertEqual(len(desktop_panel.CITY_CHOICES), 374)
        self.assertEqual(desktop_panel.CITY_CHOICES["深圳"], "101280600")
        self.assertEqual(desktop_panel.CITY_CHOICES["上海"], "101020100")

    def test_boss_district_response_is_parsed_and_scoped_to_requested_city(self):
        payload = {
            "code": 0,
            "zpData": {"businessDistrict": {
                "code": 101280600,
                "subLevelModelList": [
                    {"code": 440305, "name": "南山区", "subLevelModelList": []},
                    {"code": 34583731, "name": "科技园", "subLevelModelList": []},
                ],
            }},
        }
        self.assertEqual(
            platform_locations.parse_platform_districts(payload, "101280600"),
            [{"name": "南山区", "code": "440305"},
             {"name": "科技园", "code": "34583731"}],
        )
        with self.assertRaises(ValueError):
            platform_locations.parse_platform_districts(payload, "101280100")

    def test_district_lookup_uses_selected_city_code(self):
        response = unittest.mock.Mock()
        response.json.return_value = {
            "code": 0,
            "zpData": {"businessDistrict": {
                "code": 101280600,
                "subLevelModelList": [{"code": 440305, "name": "南山区"}],
            }},
        }
        with patch("platform_locations.requests.get", return_value=response) as get:
            districts = platform_locations.fetch_platform_districts("101280600")

        get.assert_called_once_with(
            platform_locations.BUSINESS_DISTRICT_URL,
            params={"cityCode": "101280600"},
            timeout=8,
        )
        self.assertEqual(districts, [{"name": "南山区", "code": "440305"}])

    def test_area_names_resolve_to_verified_platform_codes_and_deduplicate(self):
        districts = [
            {"name": "南山区", "code": "440305"},
            {"name": "福田区", "code": "440304"},
        ]
        with patch.object(platform_locations, "fetch_platform_districts", return_value=districts):
            self.assertEqual(
                boss_spider.resolve_platform_area_codes(
                    ["南山区", "440305", "福田区"], "101280600"
                ),
                "440305,440304",
            )

    def test_area_from_another_city_is_rejected(self):
        districts = [{"name": "天河区", "code": "440106"}]
        with patch.object(platform_locations, "fetch_platform_districts", return_value=districts):
            with self.assertRaises(ValueError):
                boss_spider.resolve_platform_area_codes(["南山区"], "101280100")

    def test_platform_settings_configure_area_and_job_type_for_selected_city(self):
        spider_config = {
            "base_url": "https://www.zhipin.com",
            "city_id": "101280600",
            "position": "",
            "keyword": "AI应用开发",
        }

        url = configure_platform_search({
            "platform_area_filter": ["南山区"],
            "platform_job_type": "实习",
        }, spider_config)

        self.assertEqual(spider_config["multiBusinessDistrict"], "440305")
        self.assertEqual(spider_config["jobType"], "1902")
        self.assertIn("multiBusinessDistrict=440305", url)
        self.assertIn("jobType=1902", url)

    def test_other_city_area_filter_is_verified_and_passed_with_job_type(self):
        spider_config = {
            "base_url": "https://www.zhipin.com",
            "city_id": "101280100",
            "position": "",
            "keyword": "AI应用开发",
        }

        with patch.object(platform_locations, "fetch_platform_districts", return_value=[
            {"name": "天河区", "code": "440106"},
        ]):
            url = configure_platform_search({
                "platform_area_filter": ["天河区"],
                "platform_job_type": "全职",
            }, spider_config)

        self.assertEqual(spider_config["multiBusinessDistrict"], "440106")
        self.assertEqual(spider_config["jobType"], "1901")
        self.assertIn("multiBusinessDistrict=440106", url)
        self.assertIn("jobType=1901", url)


class PrefilterTests(unittest.TestCase):
    def test_resume_evidence_distinguishes_vector_retrieval_from_vector_database(self):
        evidence = extract_resume_evidence(
            "- 大模型应用：有关键词+向量混合检索与溯源实践\n"
            "- 项目技术栈：Python、LangChain、RAG"
        )

        self.assertEqual(evidence["vector_retrieval"]["level"], "project_practice")
        self.assertTrue(evidence["vector_retrieval"]["evidence"])
        self.assertEqual(evidence["vector_database"]["level"], "not_explicit")
        self.assertNotIn("vector_database", extract_skill_tags("向量检索实践"))

    def test_resume_evidence_recognizes_explicit_vector_database_component(self):
        evidence = extract_resume_evidence("使用 Milvus 向量数据库完成知识库检索。")

        self.assertEqual(evidence["vector_database"]["level"], "project_practice")

    def test_resume_evidence_keeps_python_backend_and_database_proof(self):
        evidence = extract_resume_evidence(
            "- 后端服务：具备 Python/FastAPI 接口开发实践，熟悉 RESTful API 和数据库增删改查（MySQL/MongoDB/Prisma）\n"
            "- 为 AI 助手接入 16 个工具，支持查询信息和资料问答"
        )

        self.assertEqual(evidence["python"]["level"], "project_practice")
        self.assertEqual(evidence["fastapi"]["level"], "project_practice")
        self.assertEqual(evidence["database_crud"]["level"], "project_practice")
        self.assertIn("16 个工具", evidence["tool_use"]["evidence"][0])

    def test_jd_parser_treats_or_language_list_as_one_required_alternative(self):
        requirements = classify_jd_requirements(
            "C++/Python/Java其中一种；熟悉RAG项目经验"
        )

        self.assertEqual(len(requirements["alternative"]), 1)
        self.assertEqual(
            requirements["alternative"][0]["options"],
            ["c++", "python", "java"],
        )
        self.assertTrue(requirements["alternative"][0]["required"])
        self.assertNotIn("c++", [item["name"] for item in requirements["required"]])

    def test_jd_parser_normalizes_compatibility_ideograph_in_alternative_phrase(self):
        requirements = classify_jd_requirements(
            "要求掌握Python、Java、C++其中之\u2f00语言"
        )

        self.assertEqual(len(requirements["alternative"]), 1)
        self.assertEqual(
            requirements["alternative"][0]["options"],
            ["python", "java", "c++"],
        )
        self.assertIn("其中之一", requirements["alternative"][0]["source"])

    def test_jd_parser_separates_preferred_and_ambiguous_skill_lists(self):
        preferred = classify_jd_requirements("Java经验优先；有医疗行业经验者加分")
        ambiguous = classify_jd_requirements("熟悉C++、Python、Java")

        self.assertEqual(
            [item["name"] for item in preferred["preferred"]],
            ["java"],
        )
        self.assertEqual(len(preferred["required"]), 0)
        self.assertEqual(len(ambiguous["ambiguous"]), 1)
        self.assertEqual(
            ambiguous["ambiguous"][0]["options"],
            ["c++", "python", "java"],
        )
        self.assertEqual(len(ambiguous["required"]), 0)

    def test_plain_language_list_with_requirement_word_is_still_unverified(self):
        requirements = classify_jd_requirements("岗位要求熟悉C++、Python、Java")

        self.assertEqual(len(requirements["required"]), 0)
        self.assertEqual(requirements["ambiguous"][0]["options"], ["c++", "python", "java"])

    def test_explicit_all_language_requirement_is_kept_as_three_hard_requirements(self):
        requirements = classify_jd_requirements("必须同时掌握C++、Python、Java")

        self.assertEqual(
            [item["name"] for item in requirements["required"]],
            ["c++", "python", "java"],
        )

    def test_multi_technology_list_with_requirement_word_is_not_all_hard_by_default(self):
        requirements = classify_jd_requirements("需要Go、Java、SpringCloud经验")

        self.assertEqual(len(requirements["required"]), 0)
        self.assertEqual(
            requirements["ambiguous"][0]["options"],
            ["go", "java", "spring"],
        )

    def test_non_technical_job_requirements_do_not_depend_on_skill_vocabulary(self):
        examples = [
            ("产品经理", "负责用户调研、需求分析与产品规划；有SaaS经验优先"),
            ("会计", "要求会计专业资格，负责月度结账和税务申报；熟悉金蝶优先"),
            ("护士", "需持护士执业证；负责患者护理与生命体征记录"),
            ("视觉设计师", "负责品牌视觉与活动物料设计；有作品集优先"),
        ]
        self.assertEqual(len(examples), 4)
        for title, jd in examples:
            with self.subTest(title=title):
                verdict, reason = local_feasibility(
                    {"工作名称": title, "工作介绍": jd},
                    "候选人简历未描述该岗位技能，也没有明确否认。",
                )
                self.assertNotEqual(verdict, "hard_conflict")
                self.assertTrue(reason)

    def test_profile_diagnostic_terms_are_unweighted_and_do_not_create_a_score(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        from job_profiles import JobProfile

        deliverer.resume_text = "有 Python 和 REST API 项目经历。"
        deliverer.matching_context = {"profiles": [JobProfile(
            id="backend", name="后端", role_family_id="backend",
            search_keywords=["后端"], diagnostic_terms=["Python", "Go", "REST API"],
        )]}

        overlap, detail = deliverer._diagnose_profile_terms({
            "工作名称": "后端工程师",
            "技术要求": "需要 Go 和 REST API 经验",
            "工作介绍": "负责服务端开发。",
        })

        self.assertIsNone(overlap)
        self.assertIn("JD出现: Go, REST API", detail)
        self.assertIn("简历出现: Python, REST API", detail)
        self.assertIn("不代表硬性缺口", detail)

    def test_explicit_single_rest_is_still_rejected_when_double_rest_is_required(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {
            "rest_day_require": "双休",
            "work_time_start": "",
            "work_time_end": "",
        }

        reason = deliverer._work_condition_reject("岗位说明：大小周工作制")

        self.assertEqual(reason, "休息制度不符合（要求双休，岗位标注大小周）")

    def test_experience_requirements_are_rejected_by_tier(self):
        # 3~5 年软区间放行交给 AI；>=5 年硬拦；标题含实习/届字样全放行
        self.assertIsNone(AutoDeliverer._hard_reject({
            "jobExperience": "3-5年",
            "jobName": "Java开发工程师",
            "jobDegree": "本科",
        }, hard_limit=5, soft_limit=3))
        self.assertEqual(
            AutoDeliverer._hard_reject({
                "jobExperience": "5-10年",
                "jobName": "Java开发工程师",
                "jobDegree": "本科",
            }, hard_limit=5, soft_limit=3),
            "经验要求 5-10年（下限超过 5 年，在校生不匹配）",
        )
        self.assertIsNone(AutoDeliverer._hard_reject({
            "jobExperience": "3-5年",
            "jobName": "AI应用开发工程师（2027届）",
            "jobDegree": "本科",
        }, hard_limit=5, soft_limit=3))

    def test_experience_soft_band_is_observed_but_not_rejected(self):
        self.assertEqual(
            AutoDeliverer._exp_soft_banded({
                "jobExperience": "3-5年",
                "jobName": "Java开发工程师",
            }, hard_limit=5, soft_limit=3),
            "经验要求 3-5年（3~5 年软区间，交由 AI 判断）",
        )
        self.assertIsNone(AutoDeliverer._exp_soft_banded({
            "jobExperience": "1-3年",
            "jobName": "Java开发工程师",
        }, hard_limit=5, soft_limit=3))
        self.assertIsNone(AutoDeliverer._exp_soft_banded({
            "jobExperience": "3-5年",
            "jobName": "Java开发实习生",
        }, hard_limit=5, soft_limit=3))

    def test_local_gate_flags_explicitly_denied_hard_requirement(self):
        from auto_deliver import local_feasibility

        verdict, reason = local_feasibility(
            {"工作名称": "后端开发工程师", "技术要求": "需要Java",
             "工作介绍": "必须掌握Java。"},
            "熟悉 Python 开发。没有使用过 Java。",
        )

        self.assertEqual(verdict, "hard_conflict")
        self.assertIn("java", reason)

    def test_local_gate_flags_fully_missing_alternative_group(self):
        from auto_deliver import local_feasibility

        verdict, reason = local_feasibility(
            {"工作名称": "开发工程师", "技术要求": "C++/Python/Java其中一种",
             "工作介绍": "C++/Python/Java其中一种。"},
            "不会 C++。不会 Python。没有 Java 经验。",
        )

        self.assertEqual(verdict, "hard_conflict")
        self.assertIn("任选组全部明确缺失", reason)

    def test_local_gate_passes_jobs_without_explicit_negations(self):
        from auto_deliver import local_feasibility

        verdict, _reason = local_feasibility(
            {"工作名称": "Java开发工程师", "技术要求": "需要Java",
             "工作介绍": "必须掌握Java。"},
            "熟悉 Python 开发，做过 FastAPI 项目。",
        )

        self.assertEqual(verdict, "uncertain")

    def test_local_gate_reports_likely_fit_when_evidence_covers_requirements(self):
        from auto_deliver import local_feasibility

        verdict, _reason = local_feasibility(
            {"工作名称": "后端工程师", "技术要求": "需要Python",
             "工作介绍": "必须掌握Python。"},
            "熟悉 Python 开发，做过 FastAPI 项目。",
        )

        self.assertEqual(verdict, "likely_fit")

    def test_unmarked_job_type_remains_pending_confirmation(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发工程师",
            "jobExperience": "经验不限",
        }), "待确认")

    def test_monthly_salary_defaults_to_full_time_without_internship_signal(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发工程师",
            "salaryDesc": "13-20K",
            "jobDesc": "负责AI应用研发。",
        }), "全职")

    def test_explicit_internship_in_jd_overrides_monthly_salary_fallback(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发助理",
            "salaryDesc": "3-5K",
            "jobDesc": "本岗位为实习岗位，负责AI应用研发。",
        }), "实习")

    def test_intern_role_phrases_are_detected_without_requiring招聘_wording(self):
        for description in (
            "岗位为实习生，负责AI应用研发。",
            "该岗位面向实习生开放，负责AI应用研发。",
        ):
            with self.subTest(description=description):
                self.assertEqual(AutoDeliverer._classify_job_type({
                    "jobName": "AI应用开发工程师",
                    "salaryDesc": "15-20K/月",
                    "jobDesc": description,
                }), "实习")

    def test_intern_experience_or_management_mentions_do_not_override_monthly_full_time(self):
        for description in (
            "招聘全职工程师，有实习生管理经验。",
            "有实习经验优先，岗位为全职。",
        ):
            with self.subTest(description=description):
                self.assertEqual(AutoDeliverer._classify_job_type({
                    "jobName": "AI应用开发工程师",
                    "salaryDesc": "15-20K/月",
                    "jobDesc": description,
                }), "全职")

    def test_monthly_salary_does_not_override_explicit_part_time_job(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "周末兼职运营",
            "salaryDesc": "5-8K/月",
            "jobDesc": "招聘长期兼职，周末排班。",
        }), "兼职")

    def test_explicit_full_time_and_internship_types_are_classified(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobTypeName": "实习",
            "jobName": "AI应用开发",
        }), "实习")
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobTypeName": "全职",
            "jobName": "AI应用开发",
        }), "全职")

    def test_conflicting_structured_job_types_are_not_arbitrarily_prioritized(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobType": "1901",
            "jobTypeName": "实习",
            "jobName": "AI应用开发",
            "salaryDesc": "15-20K/月",
        }), "待确认")

    def test_conflicting_title_and_jd_job_types_remain_unconfirmed(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发实习生",
            "salaryDesc": "15-20K/月",
            "jobDesc": "本岗位招聘全职工程师。",
        }), "待确认")

    def test_structured_job_type_overrides_incidental_opposite_jd_mentions(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobTypeName": "实习",
            "jobName": "AI应用开发",
            "jobDesc": "有实习生管理经验优先。",
        }), "实习")

    def test_daily_salary_does_not_trigger_monthly_full_time_fallback(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发工程师",
            "salaryDesc": "200-250元/天",
        }), "待确认")

    def test_monthly_salary_overrides_internship_title_without_jd_signal(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发实习生",
            "salaryDesc": "15-20K/月",
        }), "全职")

    def test_monthly_salary_does_not_override_part_time_title(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "周末兼职运营",
            "salaryDesc": "5-8K/月",
        }), "兼职")

    def test_mentions_of_internship_experience_do_not_classify_a_role_as_internship(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发工程师",
            "工作介绍": "有实习经验优先，负责AI产品研发。",
        }), "待确认")

    def test_explicitly_negated_internship_text_does_not_override_full_time_type(self):
        self.assertEqual(AutoDeliverer._classify_job_type({
            "jobName": "AI应用开发工程师",
            "工作介绍": "不招实习生，招聘正式员工。",
        }), "全职")

    def test_job_type_priority_reorders_without_dropping_or_reordering_ties(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {"platform_job_type": "不限", "job_type_preference": "实习"}
        jobs = [
            {"encryptJobId": "full-1", "工作性质": "全职"},
            {"encryptJobId": "unknown-1", "工作性质": "待确认"},
            {"encryptJobId": "intern-1", "工作性质": "实习"},
            {"encryptJobId": "full-2", "工作性质": "全职"},
            {"encryptJobId": "intern-2", "工作性质": "实习"},
        ]

        prioritized = deliverer._prioritize_jobs_by_type(jobs)

        self.assertEqual(
            [job["encryptJobId"] for job in prioritized],
            ["intern-1", "intern-2", "full-1", "full-2", "unknown-1"],
        )
        self.assertEqual({job["encryptJobId"] for job in prioritized}, {
            "full-1", "unknown-1", "intern-1", "full-2", "intern-2",
        })

        deliverer.cfg["job_type_preference"] = "全职"
        prioritized = deliverer._prioritize_jobs_by_type(jobs)
        self.assertEqual(
            [job["encryptJobId"] for job in prioritized],
            ["full-1", "full-2", "intern-1", "intern-2", "unknown-1"],
        )

        deliverer.cfg.update({"platform_job_type": "实习", "job_type_preference": "全职"})
        prioritized = deliverer._prioritize_jobs_by_type(jobs)
        self.assertEqual(
            [job["encryptJobId"] for job in prioritized],
            ["intern-1", "intern-2", "full-1", "full-2", "unknown-1"],
        )

        deliverer.cfg["platform_job_type"] = "兼职"
        self.assertEqual(deliverer._prioritize_jobs_by_type(jobs), jobs)

    def test_irrelevant_title_passes_when_list_skills_hit_whitelist(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)

        self.assertFalse(deliverer.is_relevant("软件测试工程师"))
        self.assertTrue(deliverer.is_relevant("软件测试工程师", ["Python", "Django"]))
        self.assertFalse(deliverer.is_relevant("软件测试工程师", ["手工测试"]))

    def test_job_list_filters_report_stage_counts(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.seen_job_ids = {"duplicate"}
        deliverer.stage_counts = {}
        deliverer.cfg = {"area_filter": ["南山"]}
        deliverer.is_relevant = lambda title, skills=None: "AI" in title
        deliverer._is_blacklisted_company = lambda company: False
        deliverer._is_truncated_name = lambda company: False
        deliverer.tracker = SimpleNamespace(
            already_done=lambda job_id: job_id == "done"
        )
        deliverer._format_list = lambda items: "; ".join(items or [])

        jobs = [
            {"encryptJobId": "duplicate", "jobName": "AI开发"},
            {"encryptJobId": "irrelevant", "jobName": "行政"},
            {
                "encryptJobId": "experience", "jobName": "AI开发",
                "jobExperience": "5-10年", "areaDistrict": "南山",
            },
            {
                "encryptJobId": "area", "jobName": "AI开发",
                "areaDistrict": "福田",
            },
            {
                "encryptJobId": "done", "jobName": "AI开发",
                "areaDistrict": "南山",
            },
            {
                "encryptJobId": "candidate", "jobName": "AI开发",
                "areaDistrict": "南山",
            },
        ]

        candidates = deliverer._filter_jobs(jobs)

        self.assertEqual([job["encryptJobId"] for job in candidates], ["candidate"])
        self.assertEqual(deliverer.stage_counts["jobs_listed"], 6)
        self.assertEqual(deliverer.stage_counts["duplicate_rejected"], 1)
        self.assertEqual(deliverer.stage_counts["irrelevant_rejected"], 1)
        self.assertEqual(deliverer.stage_counts["hard_rejected"], 1)
        self.assertEqual(deliverer.stage_counts["area_rejected"], 1)
        self.assertEqual(deliverer.stage_counts["already_done"], 1)
        self.assertEqual(deliverer.stage_counts["candidate_ready"], 1)

    def test_role_filter_rejects_clear_teaching_role_with_teaching_duties(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI编程培训讲师",
            "工作介绍": "负责Python课程授课、备课和学员答疑，不承担软件产品开发。",
        })

        self.assertEqual(reason, "岗位职能偏教学培训")

    def test_role_filter_allows_mixed_development_duties(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI编程培训讲师",
            "工作介绍": "负责Python课程授课，同时参与教学平台后端接口开发和代码维护。",
        })

        self.assertIsNone(reason)

    def test_role_filter_does_not_treat_teaching_development_process_as_development_duty(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI软件培训讲师",
            "工作介绍": "负责讲解AI软件开发流程、备课和企业授课。",
        })

        self.assertEqual(reason, "岗位职能偏教学培训")

    def test_role_filter_allows_operations_title_with_ai_system_maintenance_duties(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI产品运营",
            "工作介绍": "负责账号运营和活动策划，同时维护AI应用后台系统与RAG知识库服务。",
        })

        self.assertIsNone(reason)

    def test_role_filter_keeps_product_manager_and_ambiguous_expert_roles(self):
        jobs = [
            {
                "工作名称": "AI产品经理",
                "工作介绍": "负责产品规划、需求分析、原型设计和跨团队协作。",
            },
            {
                "工作名称": "AI办公软件实战应用专家",
                "工作介绍": "负责AI办公应用方案设计和企业客户需求调研，具体工作内容面议。",
            },
        ]

        self.assertEqual(
            [AutoDeliverer._role_function_reject(job) for job in jobs],
            [None, None],
        )

    def test_role_filter_rejects_expert_title_when_duties_are_clearly_teaching(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI办公软件实战应用专家",
            "工作介绍": "负责企业授课、备课，建设4-8门成熟培训课程体系，不承担软件产品开发。",
        })

        self.assertEqual(reason, "岗位职能偏教学培训")

    def test_role_filter_rejects_clear_non_development_functions(self):
        jobs = [
            {
                "工作名称": "AI产品销售",
                "工作介绍": "负责拓展客户、销售产品、商务谈判和签约回款。",
            },
            {
                "工作名称": "AI软件销售顾问",
                "工作介绍": "公司自研的软件产品开发平台广受欢迎；负责开发客户、讲解产品方案和推进签约回款。",
            },
            {
                "工作名称": "AI内容运营",
                "工作介绍": "负责AI应用市场推广、账号运营、活动策划、社群维护和内容发布。",
            },
            {
                "工作名称": "AI售后客服",
                "工作介绍": "负责客户咨询、工单处理和投诉处理。",
            },
            {
                "工作名称": "AI招聘专员",
                "工作介绍": "负责简历筛选、招聘面试和人才招募。",
            },
        ]

        self.assertEqual(
            [AutoDeliverer._role_function_reject(job) for job in jobs],
            [
                "岗位职能偏销售商务",
                "岗位职能偏销售商务",
                "岗位职能偏运营",
                "岗位职能偏客服支持",
                "岗位职能偏招聘人事",
            ],
        )

    def test_role_rejection_is_recorded_separately_from_ai_match(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.seen_job_ids = set()
        deliverer.stage_counts = {"role_rejected": 0}
        deliverer.cfg = {
            "rest_day_require": "",
            "work_time_start": "",
            "work_time_end": "",
        }
        deliverer._fetch_jd_dom = lambda job: {
            "desc": "负责Python课程授课、备课和学员答疑。",
            "skills": [],
            "welfare_tags": [],
            "company_url": "",
        }
        rows = []
        deliverer._record = rows.append

        with patch("auto_deliver.time.sleep"):
            prepared = deliverer._prepare_job({
                "encryptJobId": "teaching-1",
                "工作名称": "AI编程培训讲师",
                "工作介绍": "",
                "技术要求": "Python",
            })

        self.assertFalse(prepared)
        self.assertEqual(deliverer.stage_counts["role_rejected"], 1)
        self.assertEqual(rows[0]["投递状态"], "role_reject")
        self.assertEqual(rows[0]["筛选原因"], "岗位职能偏教学培训")
        self.assertEqual(rows[0]["AI匹配分数"], "")

    def test_role_rejection_shadow_records_without_blocking(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.seen_job_ids = set()
        deliverer.stage_counts = {}
        deliverer.cfg = {
            "rest_day_require": "",
            "work_time_start": "",
            "work_time_end": "",
            "role_reject_shadow": True,
        }
        deliverer._fetch_jd_dom = lambda job: {
            "desc": "负责Python课程授课、备课和学员答疑。",
            "skills": [],
            "welfare_tags": [],
            "company_url": "",
        }
        job = {
            "encryptJobId": "teaching-2",
            "工作名称": "AI编程培训讲师",
            "工作介绍": "",
            "技术要求": "Python",
        }

        with patch("auto_deliver.time.sleep"):
            prepared = deliverer._prepare_job(job)

        self.assertTrue(prepared)
        self.assertEqual(deliverer.stage_counts.get("role_shadowed"), 1)
        self.assertEqual(deliverer.stage_counts.get("role_rejected", 0), 0)
        self.assertEqual(job["筛选观察"], "role_rule_shadow: 岗位职能偏教学培训")
        row = AutoDeliverer._result_row(job, 72, "匹配理由", "below_threshold")
        self.assertIn("role_rule_shadow: 岗位职能偏教学培训", row["筛选原因"])

    def test_role_filter_allows_when_title_is_development_role(self):
        reason = AutoDeliverer._role_function_reject({
            "工作名称": "AI课程研发工程师",
            "工作介绍": "负责企业授课、备课，建设培训课程体系。",
        })

        self.assertIsNone(reason)


class MatchingPromptTests(unittest.TestCase):
    def test_match_prompt_distinguishes_required_and_preferred_skills(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        captured = {}

        def fake_chat(messages, json_mode=False, temperature=0.7):
            captured["messages"] = messages
            captured["json_mode"] = json_mode
            return '{"score": 72, "reason": "项目经历匹配，缺少岗位要求的部署经验。"}'

        job = {
            "工作名称": "AI应用开发实习生",
            "工资": "面议",
            "工作经验要求": "在校生",
            "学历要求": "本科",
            "技术要求": "Python; RAG",
            "技能匹配诊断": "测试诊断不应进入AI提示词",
            "工作介绍": "负责RAG应用开发，熟悉Java为加分项。",
        }
        with patch.object(client, "chat", side_effect=fake_chat):
            result = client.match_job("简历中有Python与RAG项目", job)

        prompt = captured["messages"][0]["content"]
        self.assertEqual(result["score"], 72)
        self.assertTrue(captured["json_mode"])
        self.assertIn("必需", prompt)
        self.assertIn("加分", prompt)
        self.assertNotIn("测试诊断不应进入AI提示词", prompt)
        self.assertNotIn("本地技能标签诊断", prompt)
        self.assertIn("70-84", prompt)
        self.assertIn("85-100", prompt)
        self.assertIn("简历中有Python与RAG项目", prompt)
        self.assertIn("熟悉Java为加分项", prompt)
        self.assertIn("Python; RAG", prompt)

    def test_match_prompt_score_bands_follow_configured_delivery_threshold(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 60,
        })
        captured = {}

        def fake_chat(messages, json_mode=False, temperature=0.7):
            captured["prompt"] = messages[0]["content"]
            return '{"score": 68, "reason": "核心职责基本吻合。"}'

        with patch.object(client, "chat", side_effect=fake_chat):
            client.match_job("Python项目", {
                "工作名称": "AI应用开发",
                "技术要求": "Python",
                "工作介绍": "开发AI应用。",
            })

        self.assertIn("60-84", captured["prompt"])
        self.assertIn("85-100", captured["prompt"])

    def test_match_prompt_includes_requirements_after_first_1500_characters(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
        })
        captured = {}

        def fake_chat(messages, json_mode=False, temperature=0.7):
            captured["prompt"] = messages[0]["content"]
            return '{"score": 71, "reason": "岗位要求与经历匹配。"}'

        long_jd = "普通职责描述。" * 300 + "必须满足尾部要求：可接受在校实习。"
        with patch.object(client, "chat", side_effect=fake_chat):
            client.match_job("Python项目经历", {
                "工作名称": "AI应用开发实习生",
                "工作介绍": long_jd,
            })

        self.assertIn("必须满足尾部要求：可接受在校实习。", captured["prompt"])

    def test_match_prompt_includes_requirement_groups_and_resume_evidence(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
        })
        captured = {}

        def fake_chat(messages, json_mode=False, temperature=0.7):
            captured["prompt"] = messages[0]["content"]
            return '{"score": 78, "role_fit": 86, "hard_gaps": [], "preferred_gaps": ["java"], "reason": "核心职责匹配。"}'

        resume = (
            "- 大模型应用：有关键词+向量混合检索与溯源实践\n"
            "- 后端服务：具备 Python/FastAPI 接口开发实践"
        )
        with patch.object(client, "chat", side_effect=fake_chat):
            result = client.match_job(resume, {
                "工作名称": "AI应用开发",
                "技术要求": "C++/Python/Java其中一种；Java经验优先",
                "工作介绍": "负责RAG应用开发。",
            })

        self.assertEqual(result["score"], 78)
        self.assertEqual(result["preferred_gaps"], ["java"])
        self.assertIn("任选一项", captured["prompt"])
        self.assertIn("c++、python、java", captured["prompt"])
        self.assertIn("vector_retrieval", captured["prompt"])
        self.assertIn("Python/FastAPI", captured["prompt"])
        self.assertIn("Java经验优先", captured["prompt"])

    def test_match_job_does_not_truncate_structured_reason_at_half_a_word(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
        })
        reason = "候选人的Python、FastAPI、RAG与LangGraph项目经历和岗位核心职责匹配；Java、SpringCloud属于未明确关系的技术列表，向量数据库也没有直接组件证据。" * 2

        with patch.object(
            client,
            "chat",
            return_value='{"score": 72, "hard_gaps": ["java"], "preferred_gaps": [], "reason": ' + json.dumps(reason, ensure_ascii=False) + '}',
        ):
            result = client.match_job("Python/FastAPI/RAG项目", {
                "工作名称": "AI应用开发",
                "技术要求": "Python; Java; SpringCloud",
                "工作介绍": "开发AI应用。",
            })

        self.assertLessEqual(len(result["reason"]), 240)
        self.assertNotRegex(result["reason"], r"[A-Za-z0-9+#._-]…$")

    def test_unwritten_technical_skill_is_unverified_not_a_hard_gap(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
        })
        content = (
            '{"score": 61, "hard_gaps": ["Java", "向量数据库"], '
            '"unverified_requirements": [], "preferred_gaps": [], '
            '"evidence": ["Python/FastAPI项目"], "reason": "技术栈存在未验证项。"}'
        )

        with patch.object(client, "chat", return_value=content):
            result = client.match_job("Python/FastAPI项目经历", {
                "工作名称": "AI应用开发",
                "技术要求": "Java；向量数据库",
                "工作介绍": "负责AI应用开发。",
            })

        self.assertEqual(result["hard_gaps"], [])
        self.assertIn("Java", result["unverified_requirements"])
        self.assertIn("向量数据库", result["unverified_requirements"])
        self.assertEqual(result["resume_evidence"]["python"]["level"], "project_practice")

    def test_unmapped_hard_gap_without_resume_evidence_is_unverified_and_softened(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        content = (
            '{"score": 55, "role_fit": 82, '
            '"hard_gaps": ["终端程序开发与dump文件分析"], '
            '"unverified_requirements": [], "preferred_gaps": [], '
            '"reason": "岗位方向匹配，部分技能未验证。"}'
        )

        with patch.object(client, "chat", return_value=content):
            result = client.match_job("Python/FastAPI/RAG项目经历", {
                "工作名称": "AI应用开发",
                "技术要求": "终端程序开发与dump文件分析",
                "工作介绍": "负责AI应用开发。",
            })

        self.assertEqual(result["hard_gaps"], [])
        self.assertEqual(
            result["unverified_requirements"], ["终端程序开发与dump文件分析"]
        )
        self.assertEqual(result["score"], 65)

    def test_explicit_resume_absence_remains_a_hard_gap_without_softening(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        content = (
            '{"score": 55, "role_fit": 82, "hard_gaps": ["C++"], '
            '"unverified_requirements": [], "preferred_gaps": [], '
            '"reason": "简历明确未接触C++。"}'
        )

        with patch.object(client, "chat", return_value=content):
            result = client.match_job("未接触C++，有Python/FastAPI项目", {
                "工作名称": "AI应用开发",
                "技术要求": "C++",
                "工作介绍": "负责AI应用开发。",
            })

        self.assertEqual(result["hard_gaps"], ["C++"])
        self.assertEqual(result["score"], 55)

    def test_java_absence_does_not_mark_javascript_as_explicitly_absent(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        content = (
            '{"score": 72, "role_fit": 82, "hard_gaps": ["JavaScript"], '
            '"unverified_requirements": [], "preferred_gaps": [], '
            '"reason": "JavaScript经验证据不足。"}'
        )

        with patch.object(client, "chat", return_value=content):
            result = client.match_job("不会Java。JavaScript项目实践。", {
                "工作名称": "AI应用开发",
                "技术要求": "JavaScript",
                "工作介绍": "负责AI应用开发。",
            })

        self.assertEqual(result["hard_gaps"], [])
        self.assertEqual(result["unverified_requirements"], ["JavaScript"])

    def test_unknown_technical_gaps_do_not_push_good_role_fit_below_soft_floor(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        content = (
            '{"score": 55, "role_fit": 82, "hard_gaps": [], '
            '"unverified_requirements": ["Java", "向量数据库"], '
            '"preferred_gaps": [], "reason": "核心方向匹配，但有未验证项。"}'
        )
        with patch.object(client, "chat", return_value=content):
            result = client.match_job("Python/FastAPI/RAG项目", {
                "工作名称": "AI应用开发",
                "技术要求": "Java；向量数据库",
                "工作介绍": "负责AI应用开发。",
            })

        self.assertEqual(result["score"], 65)

    def test_many_unverified_requirements_keep_high_role_fit_at_soft_floor(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        content = (
            '{"score": 42, "role_fit": 82, "hard_gaps": [], '
            '"unverified_requirements": ["Java", "Linux", "Docker"], '
            '"preferred_gaps": [], "reason": "核心方向匹配，但多项技能未验证。"}'
        )

        with patch.object(client, "chat", return_value=content):
            result = client.match_job("Python/FastAPI/RAG项目", {
                "工作名称": "AI应用开发",
                "技术要求": "Java、Linux、Docker",
                "工作介绍": "負責AI应用开发。",
            })

        self.assertEqual(result["score"], 65)

    def test_greeting_prompt_includes_confirmed_candidate_profile(self):
        client = AIClient({
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 1,
            "match_threshold": 70,
        })
        captured = {}

        def fake_chat(messages, json_mode=False, temperature=0.7):
            captured["messages"] = messages
            return "你好，看到贵司在招 AI 应用开发实习生，我做过 RAG 项目。"

        profile = CandidateProfile(
            confirmed=True, revision=1, primary_direction="AI 应用研发",
            allowed_role_families=[RoleFamily(
                id="backend", name="后端开发", title_terms=["后端工程师"],
            )],
            evidence=[CandidateEvidence(
                claim="有 RAG 项目实践",
                source="resume_quote",
                evidence_text="RAG 项目实践",
            )],
            preferences=["实习"],
        )

        with patch.object(client, "chat", side_effect=fake_chat):
            greeting = client.gen_greeting(
                "简历原文",
                {"工作名称": "AI应用开发实习生", "公司": "某公司",
                 "技术要求": "Python", "工作介绍": "负责RAG应用开发。"},
                candidate_profile=profile,
            )

        prompt = captured["messages"][0]["content"]
        self.assertIn("我的画像", prompt)
        self.assertIn("AI 应用研发", prompt)
        self.assertIn("有 RAG 项目实践", prompt)
        self.assertIn("目标职位族：后端开发", prompt)
        self.assertIn("偏好：实习", prompt)
        self.assertTrue(greeting.strip())


class ResultSchemaTests(unittest.TestCase):
    def test_result_row_does_not_emit_legacy_prefilter_score(self):
        row = AutoDeliverer._result_row(
            {
                "encryptJobId": "job-1",
                "工作性质": "实习",
                "预筛命中率": 26,
                "技能匹配诊断": "标签覆盖较低",
            },
            88,
            "项目经历与岗位核心职责匹配。",
            "dry_run",
        )

        self.assertEqual(row["预筛命中率"], "")
        self.assertEqual(row["工作性质"], "实习")
        self.assertEqual(row["技能匹配诊断"], "标签覆盖较低")
        self.assertEqual(row["AI匹配分数"], 88)
        self.assertEqual(row["筛选原因"], "")
        self.assertEqual(row["JD要求分层"], "")
        self.assertEqual(row["硬性缺口"], "")
        self.assertEqual(row["加分项缺口"], "")
        self.assertEqual(row["简历证据"], "")
        self.assertNotIn("匹配分数", row)

    def test_save_results_migrates_legacy_rows_and_keeps_a_backup(self):
        legacy_fields = [
            "encryptJobId", "工作名称", "公司", "工资", "区域", "上班时间",
            "休息制度", "匹配分数", "AI匹配理由", "打招呼语", "投递状态",
            "投递时间", "详情链接",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "results.csv"
            with result_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=legacy_fields)
                writer.writeheader()
                writer.writerow({
                    "encryptJobId": "job-prefilter",
                    "匹配分数": 26,
                    "AI匹配理由": "预筛未通过: 标签命中率26%",
                    "投递状态": "prefilter_reject",
                })
                writer.writerow({
                    "encryptJobId": "job-scored",
                    "匹配分数": 88,
                    "投递状态": "dry_run",
                })

            deliverer = AutoDeliverer.__new__(AutoDeliverer)
            deliverer.cfg = {"result_file": str(result_path)}
            deliverer.results = [{
                "encryptJobId": "job-new",
                "预筛命中率": 45,
                "AI匹配分数": 80,
                "投递状态": "dry_run",
            }]
            deliverer._saved_count = 0

            deliverer.save_results()

            with result_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                migrated = list(reader)
                self.assertEqual(reader.fieldnames, RESULT_FIELDS)
            self.assertEqual(len(migrated), 3)
            self.assertEqual(migrated[0]["预筛命中率"], "26")
            self.assertEqual(migrated[0]["AI匹配分数"], "")
            self.assertEqual(migrated[0]["技能匹配诊断"], "标签命中率26%")
            self.assertEqual(migrated[0]["AI匹配理由"], "")
            self.assertEqual(migrated[1]["预筛命中率"], "")
            self.assertEqual(migrated[1]["AI匹配分数"], "88")
            self.assertEqual(migrated[2]["预筛命中率"], "45")
            self.assertEqual(migrated[2]["AI匹配分数"], "80")
            self.assertIn("筛选原因", reader.fieldnames)
            self.assertEqual(migrated[0]["筛选原因"], "")
            self.assertEqual(len(list(Path(temp_dir).glob("results.csv.*.bak"))), 1)

            deliverer.results.append({
                "encryptJobId": "job-after-migration",
                "AI匹配分数": 75,
                "投递状态": "below_threshold",
            })
            deliverer.save_results()

            with result_path.open("r", encoding="utf-8-sig", newline="") as f:
                appended = list(csv.DictReader(f))
            self.assertEqual(len(appended), 4)
            self.assertEqual(appended[-1]["AI匹配分数"], "75")
            self.assertEqual(len(list(Path(temp_dir).glob("results.csv.*.bak"))), 1)

    def test_migration_preserves_rows_from_intermediate_split_score_schema(self):
        intermediate_fields = [
            "encryptJobId", "预筛命中率", "AI匹配分数", "AI匹配理由", "投递状态",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "results.csv"
            with result_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=intermediate_fields)
                writer.writeheader()
                writer.writerow({
                    "encryptJobId": "job-intermediate",
                    "预筛命中率": 45,
                    "AI匹配分数": 80,
                    "AI匹配理由": "核心职责匹配。",
                    "投递状态": "dry_run",
                })

            AutoDeliverer._migrate_result_file(str(result_path))

            with result_path.open("r", encoding="utf-8-sig", newline="") as f:
                migrated = list(csv.DictReader(f))
            self.assertEqual(len(migrated), 1)
            self.assertEqual(migrated[0]["encryptJobId"], "job-intermediate")
            self.assertEqual(migrated[0]["预筛命中率"], "45")
            self.assertEqual(migrated[0]["AI匹配分数"], "80")
            self.assertEqual(migrated[0]["AI匹配理由"], "核心职责匹配。")
            self.assertEqual(migrated[0]["技能匹配诊断"], "")


class PipelineTests(unittest.TestCase):
    def _make_deliverer(self, score, dry_run=True):
        from ai_chains import JobMatchResponse, ProfileAssessment
        from job_profiles import JobProfile

        class Tracker:
            data = {"count": 0}

            def can_deliver(self, limit):
                return True

            def mark(self, *args):
                raise AssertionError("dry-run must not update daily delivery state")

        job = {
            "encryptJobId": "job-low-overlap",
            "工作名称": "Java后端工程师",
            "公司": "示例公司",
            "工资": "面议",
            "区域": "深圳",
            "学历要求": "本科",
            "工作经验要求": "在校生",
            "技术要求": "Java; Spring Cloud; PyTorch",
            "工作介绍": "负责Java、Spring Cloud与PyTorch服务开发。",
            "工作性质": "实习",
            "详情链接": "https://example.invalid/job",
        }
        profile = JobProfile(
            id="backend", name="后端开发", role_family_id="backend",
            search_keywords=["AI应用开发"], threshold=70,
        )
        assessment = ProfileAssessment(
            profile_id=profile.id,
            score=score,
            role_fit=90,
            reason="项目经验与核心职责相关。",
        )
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {
            "dry_run": dry_run,
            "test_limit": 1,
            "daily_limit": 10,
            "deliver_keyword": "AI应用开发",
            "deliver_max_pages": 1,
            "match_threshold": 70,
            "job_delay": (0, 0),
            "human_every_n": 5,
            "humanize_enable": False,
            "login_wait": 1,
            "scope_review_penalty": 5,
            "local_gate_shadow": True,
            "area_filter": [],
        }
        deliverer.profile_mode = True
        deliverer.matching_context = {
            "candidate": make_candidate_profile(),
            "profiles": [profile],
            "rules": "评分规则",
            "allocations": [
                {"keyword": "AI应用开发", "profile_ids": [profile.id], "pages": [1]},
            ],
        }
        deliverer.tracker = Tracker()
        deliverer.resume_text = "Python、LangChain、RAG 项目经历"
        deliverer.scoring_resume_prompt = deliverer.resume_text
        deliverer.ai = SimpleNamespace(
            gen_greeting=unittest.mock.Mock(return_value="您好，我有相关项目经验。"),
        )
        deliverer.scoring_chain = SimpleNamespace(
            invoke=unittest.mock.Mock(return_value=JobMatchResponse(
                profile_results=[assessment],
            )),
        )
        deliverer.match_scores = {}
        deliverer.stage_counts = {}
        deliverer.seen_job_ids = set()
        deliverer.deliver_count = 0
        deliverer.stop_event = threading.Event()
        deliverer.page = SimpleNamespace(quit=lambda: None)
        deliverer.wait_login = lambda timeout: None
        deliverer.get_cookie_headers = lambda: True
        deliverer.start_heartbeat = lambda: None
        deliverer.api_job_list = lambda page, keyword: {
            "zpData": {"jobList": [job]},
        }
        deliverer._filter_jobs = lambda job_list: [dict(item) for item in job_list]
        deliverer._prepare_job = lambda candidate: True
        deliverer._diagnose_profile_terms = lambda candidate: (None, "诊断仅供参考")
        deliverer._human_navigate_interlude = lambda jobs: None
        deliverer.deliver_one = lambda *args: (_ for _ in ()).throw(
            AssertionError("dry-run must never call the delivery method")
        )
        recorded = []
        deliverer._record = recorded.append
        deliverer.save_results = lambda: None

        return deliverer, recorded

    def test_low_overlap_reaches_ai_and_dry_run_never_delivers(self):
        deliverer, recorded = self._make_deliverer(score=88)
        output = io.StringIO()

        with redirect_stdout(output), patch("auto_deliver.time.sleep"):
            deliverer.run()

        deliverer.scoring_chain.invoke.assert_called_once()
        self.assertNotIn(
            "预筛命中率", deliverer.scoring_chain.invoke.call_args.kwargs["job"]
        )
        self.assertEqual(recorded[0]["预筛命中率"], "")
        self.assertNotIn("[预筛] 简历技能标签", output.getvalue())
        self.assertEqual(recorded[0]["AI匹配分数"], 88)
        self.assertEqual(recorded[0]["投递状态"], "dry_run")
        deliverer.ai.gen_greeting.assert_called_once()
        self.assertEqual(deliverer.stage_counts["ai_called"], 1)
        self.assertEqual(deliverer.stage_counts["ai_scored"], 1)
        self.assertEqual(deliverer.stage_counts["dry_run_ready"], 1)
        self.assertEqual(deliverer.tracker.data["count"], 0)

    def test_below_threshold_skips_greeting_in_dry_run_and_delivery_modes(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                deliverer, recorded = self._make_deliverer(score=65, dry_run=dry_run)

                with patch("auto_deliver.time.sleep"):
                    deliverer.run()

                deliverer.scoring_chain.invoke.assert_called_once()
                deliverer.ai.gen_greeting.assert_not_called()
                self.assertEqual(recorded[0]["AI匹配分数"], 65)
                self.assertEqual(recorded[0]["投递状态"], "below_threshold")
                self.assertEqual(recorded[0]["打招呼语"], "")
                self.assertEqual(deliverer.stage_counts["below_threshold"], 1)
                self.assertEqual(deliverer.stage_counts.get("delivery_attempted", 0), 0)

    def test_preferred_internship_from_later_page_is_processed_before_full_time(self):
        deliverer, recorded = self._make_deliverer(score=65)
        full_time_job = {
            "encryptJobId": "full-time-1",
            "工作名称": "Java后端工程师全职",
            "工作性质": "全职",
            "公司": "公司A",
            "工资": "面议",
            "区域": "深圳 南山",
            "技术要求": "Python",
            "工作介绍": "负责后端服务开发。",
            "详情链接": "https://example.invalid/full-time",
        }
        internship_job = {
            "encryptJobId": "intern-1",
            "工作名称": "Java后端工程师实习生",
            "工作性质": "实习",
            "公司": "公司B",
            "工资": "面议",
            "区域": "深圳 南山",
            "技术要求": "Python",
            "工作介绍": "负责后端服务开发。",
            "详情链接": "https://example.invalid/intern",
        }
        deliverer.cfg.update({"platform_job_type": "实习", "job_type_preference": "全职"})
        deliverer.matching_context["allocations"] = [
            {"keyword": "AI应用开发", "profile_ids": ["backend"], "pages": [1, 2]},
        ]
        deliverer.api_job_list = lambda page, keyword: {
            "zpData": {"jobList": [full_time_job if page == 1 else internship_job]},
        }

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        self.assertEqual(recorded[0]["encryptJobId"], "intern-1")
        self.assertEqual(recorded[0]["工作性质"], "实习")
        self.assertEqual(deliverer.stage_counts["ai_called"], 1)

    def _make_profiled_deliverer(self, jobs_by_keyword):
        from ai_chains import JobMatchResponse, ProfileAssessment
        from candidate_profiles import CandidateProfile, RoleFamily
        from job_profiles import JobProfile

        profile = JobProfile(
            id="backend-profile", name="后端开发", role_family_id="backend",
            search_keywords=["后端", "Python API"], threshold=70,
        )
        candidate = CandidateProfile(
            confirmed=True, revision=1, primary_direction="AI 应用研发",
            allowed_role_families=[RoleFamily(
                id="backend", name="后端开发", title_terms=["后端工程师"]
            )],
            excluded_role_families=["销售"],
        )
        assessment = ProfileAssessment(
            profile_id=profile.id, score=88, role_fit=90,
            reason="后端职责与候选人项目经验匹配。",
        )
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.cfg = {
            "test_limit": 0, "daily_limit": 10, "job_type_preference": "实习",
            "match_threshold": 70, "dry_run": True, "job_delay": (0, 0),
            "login_wait": 1, "scope_review_penalty": 5,
        }
        deliverer.matching_context = {
            "candidate": candidate,
            "profiles": [profile],
            "rules": "规则",
            "allocations": [
                {"keyword": "后端", "profile_ids": [profile.id], "pages": [1]},
                {"keyword": "Python API", "profile_ids": [profile.id], "pages": [1]},
            ],
        }
        deliverer.profile_mode = True
        deliverer.tracker = SimpleNamespace(
            data={"count": 0}, can_deliver=lambda _limit: True,
            already_done=lambda _job_id: False,
        )
        deliverer.seen_job_ids = set()
        deliverer.stage_counts = {}
        deliverer.resume_text = "使用 Python 开发后端接口"
        deliverer.scoring_resume_prompt = "简历摘要：使用 Python 开发后端接口"
        deliverer.match_scores = {}
        deliverer.deliver_count = 0
        deliverer.stop_event = threading.Event()
        deliverer.page = SimpleNamespace(quit=lambda: None)
        deliverer._filter_jobs = lambda _listing: [dict(item) for item in jobs_by_keyword[current_keyword[0]]]
        current_keyword = [""]

        def list_jobs(page, keyword):
            current_keyword[0] = keyword
            return {"zpData": {"jobList": [dict(item) for item in jobs_by_keyword[keyword]]}}

        deliverer.api_job_list = list_jobs
        deliverer._prepare_job = lambda _job: True
        deliverer._diagnose_profile_terms = lambda _job: (None, "诊断仅供参考")
        deliverer._human_navigate_interlude = lambda _jobs: None
        deliverer.start_heartbeat = lambda: None
        deliverer.wait_login = lambda _timeout: None
        deliverer.get_cookie_headers = lambda: True
        deliverer.save_results = lambda: None
        deliverer._print_stage_summary = lambda: None
        deliverer._recorded = []
        deliverer._record = deliverer._recorded.append
        deliverer.scoring_chain = SimpleNamespace(
            invoke=unittest.mock.Mock(return_value=JobMatchResponse(
                profile_results=[assessment]
            ))
        )
        deliverer.ai = SimpleNamespace(
            gen_greeting=unittest.mock.Mock(return_value="您好，我有相关项目经验。")
        )
        deliverer.deliver_one = unittest.mock.Mock(
            side_effect=AssertionError("dry-run must not call delivery")
        )
        return deliverer

    def test_duplicate_job_from_multiple_queries_is_scored_once_in_dry_run(self):
        shared_job = {
            "encryptJobId": "shared-job",
            "工作名称": "Python 后端工程师",
            "公司": "示例公司",
            "工作性质": "实习",
            "工作介绍": "负责后端接口开发。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [shared_job], "Python API": [shared_job],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        deliverer.scoring_chain.invoke.assert_called_once()
        deliverer.deliver_one.assert_not_called()
        self.assertEqual(deliverer._recorded[0]["投递状态"], "dry_run")
        self.assertEqual(deliverer._recorded[0]["搜索来源关键词"], "后端；Python API")
        # 招呼语必须基于用户画像 + JD 生成（规范要求）
        self.assertIs(
            deliverer.ai.gen_greeting.call_args[1]["candidate_profile"],
            deliverer.matching_context["candidate"],
        )

    def test_out_of_scope_job_is_recorded_without_scoring_call(self):
        sales_job = {
            "encryptJobId": "sales-job",
            "工作名称": "AI产品销售",
            "公司": "示例公司",
            "工作性质": "全职",
            "工作介绍": "负责拓展客户、商务谈判和签约回款。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [sales_job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        deliverer.scoring_chain.invoke.assert_not_called()
        self.assertEqual(deliverer._recorded[0]["投递状态"], "out_of_scope")
        self.assertEqual(deliverer._recorded[0]["职业范围状态"], "out_of_scope")

    def test_scope_review_job_is_scored_with_threshold_penalty(self):
        review_job = {
            "encryptJobId": "review-job",
            "工作名称": "AI产品经理",
            "公司": "示例公司",
            "工作性质": "全职",
            "工作介绍": "负责产品规划、需求分析和跨团队协作。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [review_job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        # scope_review 不再跳过：进 AI 评分（88 >= 70+5），阈值加罚后仍可投
        deliverer.scoring_chain.invoke.assert_called_once()
        self.assertEqual(deliverer._recorded[0]["投递状态"], "dry_run")
        self.assertEqual(deliverer._recorded[0]["职业范围状态"], "scope_review")
        self.assertEqual(deliverer.stage_counts.get("scope_review_delivered"), 1)

    def test_scope_review_penalty_blocks_a_marginally_passing_score(self):
        review_job = {
            "encryptJobId": "review-job",
            "工作名称": "AI产品经理",
            "公司": "示例公司",
            "工作性质": "全职",
            "工作介绍": "负责产品规划、需求分析和跨团队协作。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [review_job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]
        deliverer.scoring_chain.invoke.return_value = JobMatchResponse(
            profile_results=[ProfileAssessment(
                profile_id="backend-profile", score=72, role_fit=80,
                reason="职责接近但职业范围未确认。",
            )]
        )

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        # 72 过全局阈值 70，但 scope_review 加罚后有效阈值 75，不允许投递
        deliverer.scoring_chain.invoke.assert_called_once()
        self.assertEqual(deliverer._recorded[0]["投递状态"], "below_threshold")
        self.assertEqual(deliverer._recorded[0]["AI匹配分数"], 72)
        self.assertEqual(deliverer.stage_counts.get("scope_review_ai_called"), 1)

    def _conflict_deliverer(self):
        job = {
            "encryptJobId": "conflict-job",
            "工作名称": "Java后端工程师",
            "公司": "示例公司",
            "工作性质": "实习",
            "工作介绍": "必须掌握Java。",
            "技术要求": "需要Java",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]
        deliverer.resume_text = "熟悉 Python 开发。没有使用过 Java。"
        return deliverer

    def test_local_gate_shadow_records_verdict_but_still_scores(self):
        deliverer = self._conflict_deliverer()
        deliverer.cfg["local_gate_shadow"] = True

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        deliverer.scoring_chain.invoke.assert_called_once()
        self.assertEqual(deliverer.stage_counts.get("local_gate_conflict"), 1)
        self.assertEqual(deliverer._recorded[0]["投递状态"], "dry_run")
        self.assertIn("hard_conflict", deliverer._recorded[0]["本地预判"])

    def test_legacy_gate_setting_no_longer_blocks_unknown_occupation_requirements(self):
        deliverer = self._conflict_deliverer()
        deliverer.cfg["local_gate_shadow"] = False

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        deliverer.scoring_chain.invoke.assert_called_once()
        self.assertEqual(deliverer._recorded[0]["投递状态"], "dry_run")
        self.assertEqual(deliverer.stage_counts.get("local_gate_rejected", 0), 0)
        self.assertIn("hard_conflict", deliverer._recorded[0]["本地预判"])

    def test_low_confidence_score_is_shrunk_toward_fifty(self):
        shared_job = {
            "encryptJobId": "low-conf-job",
            "工作名称": "Python 后端工程师",
            "公司": "示例公司",
            "工作性质": "实习",
            "工作介绍": "负责后端接口开发。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [shared_job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]
        deliverer.scoring_chain.invoke.return_value = JobMatchResponse(
            profile_results=[ProfileAssessment(
                profile_id="backend-profile", score=90, role_fit=90,
                reason="证据较少但方向接近。", confidence=30,
            )]
        )

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        # 90 -> 90 + (50-90)*0.2 = 82，低置信分数向 50 收缩 20%
        self.assertEqual(deliverer._recorded[0]["AI匹配分数"], 82)

    def test_multi_profile_failure_falls_back_to_single_profile_scoring(self):
        from job_profiles import JobProfile as _JobProfile

        shared_job = {
            "encryptJobId": "retry-job",
            "工作名称": "Python 后端工程师",
            "公司": "示例公司",
            "工作性质": "实习",
            "工作介绍": "负责后端接口开发。",
            "详情链接": "https://example.invalid/job",
        }
        deliverer = self._make_profiled_deliverer({
            "后端": [shared_job], "Python API": [],
        })
        deliverer._filter_jobs = lambda listing: [dict(item) for item in listing]
        extra = _JobProfile(
            id="robotics-profile", name="机器人", role_family_id="robotics",
            search_keywords=["机器人"], threshold=70,
        )
        deliverer.matching_context["profiles"] = (
            deliverer.matching_context["profiles"] + [extra]
        )
        single = JobMatchResponse(profile_results=[ProfileAssessment(
            profile_id="backend-profile", score=88, role_fit=90,
            reason="后端职责匹配。",
        )])
        deliverer.scoring_chain.invoke.side_effect = [
            RuntimeError("boom"), single,
        ]

        with patch("auto_deliver.time.sleep"):
            deliverer.run()

        self.assertEqual(deliverer.scoring_chain.invoke.call_count, 2)
        retry_profiles = deliverer.scoring_chain.invoke.call_args_list[1][1]["profiles"]
        self.assertEqual([p.id for p in retry_profiles], ["backend-profile"])
        self.assertEqual(deliverer._recorded[0]["投递状态"], "dry_run")
        self.assertEqual(deliverer.stage_counts.get("ai_retry_single_profile"), 1)


class DeliveryStartupPreflightTests(unittest.TestCase):
    def test_missing_candidate_profile_falls_back_to_base_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            job_path = base / "jobs.json"
            job_path.write_text(json.dumps([
                JobProfile(
                    id="one", name="后端", role_family_id="backend",
                    role_direction="AI 后端开发",
                    search_keywords=["后端", "Python API"],
                ).model_dump(),
            ], ensure_ascii=False), encoding="utf-8")
            config = {
                "candidate_profile_file": str(base / "missing-candidate.json"),
                "job_profiles_file": str(job_path),
                "screening_rules_file": str(Path(__file__).parents[1] / "screening_rules.md"),
                "deliver_keyword": "AI应用开发",
                "deliver_max_pages": 3,
                "resume_file": str(base / "missing-resume.md"),
            }

            context = load_matching_config(config)

        # 规范：用户不一定会用到增强画像，缺失时按基础画像（简历+岗位画像）启动
        self.assertTrue(context["base_mode"])
        candidate = context["candidate"]
        self.assertTrue(candidate.confirmed)
        self.assertEqual(candidate.primary_direction, "AI应用开发")
        self.assertEqual([f.id for f in candidate.allowed_role_families], ["backend"])
        # 基础画像保留岗位画像关键词作为职位族词条，检索词仍统一由目标岗位决定。
        self.assertEqual(
            candidate.allowed_role_families[0].title_terms, ["后端", "Python API"]
        )
        self.assertEqual([p.id for p in context["profiles"]], ["one"])
        self.assertEqual(context["profiles"][0].search_keywords, ["AI应用开发"])

    def test_candidate_profile_for_changed_resume_falls_back_to_base_profile(self):
        from candidate_profiles import resume_digest_hash

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            resume_path = base / "resume.md"
            resume_path.write_text("新的简历内容", encoding="utf-8")
            candidate_path = base / "candidate.json"
            candidate = make_candidate_profile().model_copy(
                update={"resume_sha256": resume_digest_hash("旧的简历内容")}
            )
            candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
            config = {
                "candidate_profile_file": str(candidate_path),
                "job_profiles_file": str(base / "missing-jobs.json"),
                "screening_rules_file": str(Path(__file__).parents[1] / "screening_rules.md"),
                "deliver_keyword": "AI 应用工程师",
                "deliver_max_pages": 3,
                "resume_file": str(resume_path),
            }

            context = load_matching_config(config)

        self.assertTrue(context["base_mode"])
        self.assertTrue(context["enhanced_profile_stale"])
        self.assertEqual(context["candidate"].primary_direction, "AI 应用工程师")
        self.assertEqual(
            [family.id for family in context["candidate"].allowed_role_families],
            ["auto-target"],
        )

    def test_missing_target_job_stops_before_browser_initialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config = {
                "candidate_profile_file": str(base / "missing-candidate.json"),
                "job_profiles_file": str(base / "missing-jobs.json"),
                "screening_rules_file": str(Path(__file__).parents[1] / "screening_rules.md"),
                "deliver_keyword": "",
                "deliver_max_pages": 3,
                "log_file": "unused.json",
                "resume_file": str(base / "missing-resume.md"),
            }

            with patch("auto_deliver.BossDP.__init__") as browser_init:
                with self.assertRaisesRegex(ValueError, "目标岗位"):
                    AutoDeliverer(config)

        browser_init.assert_not_called()

    def test_empty_job_profiles_are_derived_from_the_target_job(self):
        """岗位画像不再由用户填写：只给目标岗位即可启动，画像自动派生。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            config = {
                "candidate_profile_file": str(base / "missing-candidate.json"),
                "job_profiles_file": str(base / "missing-jobs.json"),
                "screening_rules_file": str(Path(__file__).parents[1] / "screening_rules.md"),
                "deliver_keyword": "AI 应用工程师",
                "deliver_max_pages": 3,
                "resume_file": str(base / "missing-resume.md"),
            }

            context = load_matching_config(config)

        self.assertTrue(context["base_mode"])
        self.assertEqual(len(context["profiles"]), 1)
        profile = context["profiles"][0]
        self.assertEqual(profile.id, "auto-target")
        self.assertEqual(profile.search_keywords, ["AI 应用工程师"])
        self.assertTrue(profile.enabled)
        self.assertEqual(profile.hard_requirements, [])

    def test_multiple_enabled_profiles_search_only_the_target_job(self):
        """岗位画像只保留评分标尺；搜索词一律由目标岗位决定，不会产生多查询预算问题。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            candidate_path = base / "candidate.json"
            candidate_path.write_text(make_candidate_profile().model_dump_json(), encoding="utf-8")
            job_path = base / "jobs.json"
            from job_profiles import JobProfile
            job_path.write_text(json.dumps([
                JobProfile(id="one", name="后端", role_family_id="backend", search_keywords=["后端"]).model_dump(),
                JobProfile(id="two", name="机器人", role_family_id="robotics", search_keywords=["机器人"]).model_dump(),
            ], ensure_ascii=False), encoding="utf-8")
            config = {
                "candidate_profile_file": str(candidate_path),
                "job_profiles_file": str(job_path),
                "screening_rules_file": str(Path(__file__).parents[1] / "screening_rules.md"),
                "deliver_keyword": "AI 应用工程师",
                "deliver_max_pages": 1,
            }

            context = load_matching_config(config)

        self.assertEqual(
            [p.search_keywords for p in context["profiles"]],
            [["AI 应用工程师"], ["AI 应用工程师"]],
        )
        self.assertEqual(len(context["allocations"]), 1)
        self.assertEqual(context["allocations"][0]["keyword"], "AI 应用工程师")


if __name__ == "__main__":
    unittest.main()
