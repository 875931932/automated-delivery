# -*- coding: utf-8 -*-
"""打招呼语后处理：礼貌收尾、称呼补齐、简历事实约束与长度控制。"""
import unittest

from ai_client import _POLITE_TAIL, _polish_greeting


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

    def test_overlong_greeting_is_cut_at_sentence_boundary(self):
        sentence = "您好，我是计算机专业在读的学生，做过 RAG 检索与智能体项目。"
        greeting = _polish_greeting(sentence * 3)
        self.assertLessEqual(len(greeting), 120)
        self.assertTrue(greeting.endswith(("。", "！", "？")))


if __name__ == "__main__":
    unittest.main()
