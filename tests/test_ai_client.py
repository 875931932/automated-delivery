# -*- coding: utf-8 -*-
"""打招呼语后处理：礼貌收尾、称呼补齐、简历事实约束与长度控制。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai_client import AIClient, _POLITE_TAIL, _polish_greeting
from greeting_prompt import DEFAULT_GREETING_PROMPT


class PolishGreetingTests(unittest.TestCase):
    def test_brusque_tail_is_replaced_with_polite_closing(self):
        greeting = _polish_greeting(
            "你好！熟悉RAG和Agent，LangChain做检索和工具调用。对贵司方向有兴趣，求聊！"
        )
        self.assertNotIn("求聊", greeting)
        self.assertIn(_POLITE_TAIL.strip("，"), greeting)
        self.assertTrue(greeting.startswith("你好！"))

    def test_brusque_tail_after_full_stop_has_no_double_punctuation(self):
        greeting = _polish_greeting(
            "您好，我做过 RAG 和 Tool Calling 项目，用 Python 实现混合检索。想聊聊。"
        )
        self.assertNotIn("想聊聊", greeting)
        self.assertNotIn("。，", greeting)
        self.assertIn(f"实现混合检索。{_POLITE_TAIL.strip('，')}", greeting)

    def test_education_lead_sentence_is_removed(self):
        greeting = _polish_greeting(
            "您好，我是广州软件学院数据科学专业在读的学生。"
            "我独立做过命题系统，把出题、批改和资料检索串成完整流程。"
        )
        self.assertNotIn("广州软件学院", greeting)
        self.assertNotIn("在读", greeting)
        self.assertTrue(greeting.startswith("您好，我独立做过命题系统"))

    def test_capability_first_sentence_mentioning_school_is_kept(self):
        greeting = _polish_greeting(
            "您好，我在学校做过一个检索问答项目，负责知识库与工具调用。想了解岗位的具体工作。"
        )
        self.assertIn("我在学校做过一个检索问答项目", greeting)

    def test_missing_opener_gets_polite_greeting(self):
        greeting = _polish_greeting("我对这个岗位很感兴趣，做过 RAG 与工具调用项目。")
        self.assertTrue(greeting.startswith("您好，"))

    def test_subjectless_verb_after_opener_gets_subject(self):
        greeting = _polish_greeting(
            "您好，独立完成过三个 AI 应用的后端开发，覆盖模型调用与失败降级。"
        )
        self.assertTrue(greeting.startswith("您好，我独立完成过三个"))
        self.assertNotIn("您好，独立", greeting)

    def test_missing_de_hua_is_fixed(self):
        greeting = _polish_greeting(
            "您好，我做过 RAG 检索问答项目，想了解岗位的具体工作，方便可以聊聊。"
        )
        self.assertIn("方便的话可以聊聊", greeting)
        self.assertNotIn("方便可以聊聊", greeting)
        self.assertTrue(greeting.endswith("。"))

    def test_quotes_prefix_and_newlines_are_cleaned(self):
        greeting = _polish_greeting('“打招呼语：您好，我是计算机专业在读的学生。\n期待沟通。”')
        self.assertTrue(greeting.startswith("您好，"))
        self.assertNotIn("\n", greeting)
        self.assertNotIn("打招呼语", greeting)
        self.assertNotIn("“", greeting)

    def test_availability_claim_is_dropped_when_resume_does_not_mention_it(self):
        greeting = _polish_greeting(
            "您好，我用 Python 和 LangChain 做过 RAG 项目，每周可到岗 5 天，希望能有机会沟通。",
            resume="Python、LangChain、RAG 项目经历",
        )
        self.assertNotIn("每周", greeting)
        self.assertNotIn("到岗", greeting)
        self.assertIn("Python", greeting)

    def test_availability_claim_is_kept_when_resume_mentions_it(self):
        greeting = _polish_greeting(
            "您好，我用 Python 做过 RAG 项目，每周可到岗 5 天，希望能有机会沟通。",
            resume="Python、RAG 项目；每周可到岗 5 天，可实习 6 个月",
        )
        self.assertIn("每周可到岗 5 天", greeting)

    def test_jd_reference_is_not_mistaken_for_an_availability_promise(self):
        for opening in (
            "您好，看到岗位需要开发文档解析接口。",
            "您好，我关注到岗位需要搭建 Agent 工作流。",
        ):
            with self.subTest(opening=opening):
                text = opening + "我做过对应的后端接口，希望有机会交流，谢谢您。"
                self.assertEqual(_polish_greeting(text, resume="后端接口项目"), text)

    def test_removing_availability_does_not_remove_the_next_project_sentence(self):
        text = "您好，我可以立即到岗。我在咨询项目中负责后端接口，做过文档解析。希望有机会交流。"
        greeting = _polish_greeting(text, resume="咨询项目：后端接口与文档解析")
        self.assertNotIn("立即到岗", greeting)
        self.assertIn("我在咨询项目中负责后端接口", greeting)

    def test_jd_evidence_and_closing_survive_a_moderate_length_greeting(self):
        text = (
            "您好，我关注到剪映 CapCut 的 AI 应用开发涉及复杂 Agent 与生成研发。"
            "我在 PaperPact 项目中基于 LangGraph 组织过题目生成与格式校验的 Agent 流程，"
            "也为助手接入过查询与生成类工具。希望能参与 AI 方向研发并交流。"
        )
        self.assertGreater(len(text), 120)
        self.assertEqual(_polish_greeting(text, resume="命题系统开发"), text)

    def test_overlong_greeting_is_cut_at_sentence_boundary(self):
        sentence = "我做过 RAG 检索与智能体项目，使用混合检索生成带来源的知识卡。"
        greeting = _polish_greeting(sentence * 8)
        self.assertLessEqual(len(greeting), 150)
        self.assertTrue(greeting.endswith(("。", "！", "？")))

    def test_overlong_sentence_never_exceeds_length_limit(self):
        greeting = _polish_greeting("我做过后端接口开发，" * 30)
        self.assertLessEqual(len(greeting), 150)


class GreetingPromptTests(unittest.TestCase):
    def make_client(self, **overrides):
        config = {
            "ai_base_url": "https://example.invalid/v1",
            "ai_api_key": "test-key",
            "ai_model": "test-model",
            "ai_timeout": 1,
            "ai_max_retries": 0,
        }
        config.update(overrides)
        return AIClient(config)

    def test_default_prompt_is_used_when_no_custom_prompt_is_configured(self):
        self.assertEqual(self.make_client().greeting_prompt, DEFAULT_GREETING_PROMPT)

    def test_custom_prompt_reaches_generation_and_result_is_still_polished(self):
        custom_prompt = "按岗位重点提炼我的项目经历，语气简洁自然。"
        client = self.make_client(greeting_prompt=custom_prompt)

        with patch.object(
            client, "chat",
            return_value="我做过 Python 接口项目，希望了解岗位，方便可以聊聊。",
        ) as chat:
            greeting = client.gen_greeting(
                "简历中有 Python 接口项目经历",
                {
                    "工作名称": "Python 后端实习生",
                    "公司": "测试公司",
                    "技术要求": "Python",
                    "工作介绍": "维护后端接口。",
                },
            )

        messages = chat.call_args.args[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("不得编造经历", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn(custom_prompt, messages[1]["content"])
        self.assertIn("简历中有 Python 接口项目经历", messages[1]["content"])
        self.assertIn("Python 后端实习生", messages[1]["content"])
        self.assertIn("方便的话可以聊聊", greeting)
        self.assertTrue(greeting.startswith("您好，"))

    def test_greeting_receives_responsibilities_beyond_the_first_600_characters(self):
        client = self.make_client()
        key_responsibility = "开发文档上传接口，解析文档并管理多轮咨询上下文。"
        description = "公司介绍与福利。" * 90 + key_responsibility
        with patch.object(client, "chat", return_value="您好，我做过文档解析接口。") as chat:
            client.gen_greeting("做过文档解析接口", {"工作介绍": description})

        self.assertIn(key_responsibility, chat.call_args.args[0][1]["content"])

    def test_profile_supplies_original_evidence_in_addition_to_summary(self):
        client = self.make_client()
        profile = SimpleNamespace(evidence=[SimpleNamespace(
            claim="有智能体开发经验",
            evidence_text="在命题项目中使用 LangGraph 组织格式校验，了解 LangGraph。",
        )])
        with patch.object(client, "chat", return_value="您好，我做过格式校验。") as chat:
            client.gen_greeting("项目经历", {}, candidate_profile=profile)

        prompt = chat.call_args.args[0][1]["content"]
        self.assertIn("有智能体开发经验", prompt)
        self.assertIn("对应原文：在命题项目中使用 LangGraph 组织格式校验，了解 LangGraph。", prompt)

    def test_missing_description_is_not_rendered_as_none(self):
        client = self.make_client()
        with patch.object(client, "chat", return_value="您好，我做过接口开发。") as chat:
            client.gen_greeting("接口开发经历", {"工作介绍": None})
        self.assertNotIn("职位描述: None", chat.call_args.args[0][1]["content"])

    def test_long_draft_is_rewritten_with_original_jd_and_evidence(self):
        client = self.make_client()
        long_draft = "您好，岗位需要文档解析。" + "我在咨询项目开发了上传接口。" * 12
        revised = "您好，看到岗位需要文档解析。我在咨询项目开发过上传与解析接口，希望有机会交流，谢谢您。"
        with patch.object(client, "chat", side_effect=[long_draft, revised]) as chat:
            greeting = client.gen_greeting("咨询项目：开发上传与解析接口", {"工作介绍": "负责文档解析"})

        self.assertEqual(greeting, revised)
        self.assertEqual(chat.call_count, 2)
        revision_messages = chat.call_args.args[0]
        self.assertIn("负责文档解析", revision_messages[1]["content"])
        self.assertIn("咨询项目：开发上传与解析接口", revision_messages[1]["content"])
        self.assertEqual(revision_messages[2]["content"], long_draft)
        self.assertIn("礼貌结尾", revision_messages[3]["content"])

    def test_failed_or_still_long_rewrite_is_not_sent_as_a_truncated_message(self):
        long_draft = "我在咨询项目开发了上传与解析接口。" * 12
        for revised in (None, long_draft):
            with self.subTest(revised=revised is None):
                client = self.make_client()
                with patch.object(client, "chat", side_effect=[long_draft, revised]) as chat:
                    self.assertEqual(client.gen_greeting("接口项目", {}), "")
                self.assertEqual(chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
