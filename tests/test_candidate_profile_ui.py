import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from candidate_profiles import InterviewDraft, ResumeDigest, ResumeDigestStore
from desktop_panel import PanelApp


class FakeText:
    def __init__(self, value=""):
        self.value = value
        self.enabled = True

    def setText(self, value):
        self.value = value

    def text(self):
        return self.value

    def clear(self):
        self.value = ""

    def toPlainText(self):
        return self.value

    def setEnabled(self, flag):
        self.enabled = bool(flag)


class FakeLabel:
    def __init__(self, text=""):
        self.text = text
        self.tooltip = ""

    def setText(self, value):
        self.text = value

    def setToolTip(self, value):
        self.tooltip = value


class FakeButton:
    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, flag):
        self.enabled = bool(flag)

    def setText(self, value):
        self.text = value


class FakeFrame:
    def __init__(self):
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class FakeRow:
    def __init__(self):
        self.deleted = False

    def setParent(self, _parent):
        pass

    def deleteLater(self):
        self.deleted = True


class CandidateProfileTranscriptTests(unittest.TestCase):
    def _draft_app(self):
        messages = []
        app = SimpleNamespace(
            profile_rendered_history=0,
            profile_pending_user_text=None,
            profile_message_rows=[],
            _profile_log=lambda role, text, links=None: messages.append((role, text, links)),
            _render_profile_draft=lambda _draft: None,
            _set_widget_style=lambda _widget, _name: None,
            profile_summary_label=FakeLabel(),
            profile_review=FakeText(),
            profile_confirm_button=FakeButton(),
        )
        return app, messages

    def test_successful_answer_does_not_replay_existing_question_and_answer(self):
        app, messages = self._draft_app()
        service = SimpleNamespace(
            research_results=[],
            sources_displayed=False,
            research_status="未启用，使用简历访谈",
            history=[
                {"role": "assistant", "content": "你做过哪些项目？"},
                {"role": "user", "content": "我做过 RAG 项目。"},
            ],
        )
        draft = InterviewDraft(
            primary_direction="AI 应用开发",
            pending_question="你如何处理检索结果的溯源？",
        )

        PanelApp._show_profile_draft(app, service, draft)

        self.assertEqual(
            [(role, text) for role, text, _links in messages],
            [
                ("user", "我做过 RAG 项目。"),
                ("assistant", "你如何处理检索结果的溯源？"),
            ],
        )

    def test_submitted_answer_is_not_replayed_when_marked_pending(self):
        app, messages = self._draft_app()
        app.profile_pending_user_text = "我做过 RAG 项目。"
        service = SimpleNamespace(
            research_results=[],
            sources_displayed=False,
            research_status="未启用，使用简历访谈",
            history=[
                {"role": "assistant", "content": "你做过哪些项目？"},
                {"role": "user", "content": "我做过 RAG 项目。"},
            ],
        )
        draft = InterviewDraft(
            primary_direction="AI 应用开发",
            pending_question="你如何处理检索结果的溯源？",
        )

        PanelApp._show_profile_draft(app, service, draft)

        self.assertEqual(
            [(role, text) for role, text, _links in messages],
            [("assistant", "你如何处理检索结果的溯源？")],
        )
        self.assertIsNone(app.profile_pending_user_text)

    def test_successful_retry_preserves_text_entered_after_submission(self):
        service = SimpleNamespace(
            draft=InterviewDraft(pending_question="Next question"),
            history=[{"role": "user", "content": "original answer"}],
        )
        app = SimpleNamespace(
            profile_generation=4,
            profile_busy=False,
            profile_answer=FakeText("a newer note"),
            profile_error_frame=FakeFrame(),
            profile_retry_action=None,
            profile_service=service,
            profile_start_button=FakeButton(),
            profile_submit_button=FakeButton(),
            profile_skip_button=FakeButton(),
            profile_cancel_button=FakeButton(),
            profile_retry_button=FakeButton(),
            _stop_profile_wait=lambda: None,
            _set_profile_busy=lambda busy: PanelApp._set_profile_busy(app, busy),
            _show_profile_draft=lambda _service, _draft: None,
        )

        PanelApp._handle_profile_event(app, 4, "answer", (service, InterviewDraft(), False))

        self.assertEqual(app.profile_answer.value, "a newer note")
        self.assertFalse(app.profile_retry_button.enabled)

    def test_failed_interview_shows_inline_retry_and_keeps_the_action(self):
        retry = lambda: None
        app = SimpleNamespace(
            profile_generation=4,
            profile_busy=False,
            profile_retry_action=retry,
            profile_error_frame=FakeFrame(),
            profile_error_label=FakeLabel(),
            profile_retry_button=FakeButton(),
            profile_summary_label=FakeLabel(),
            _stop_profile_wait=lambda: None,
            _set_profile_busy=lambda busy: setattr(app, "profile_busy", busy),
            _set_widget_style=lambda _widget, _name: None,
            _friendly_error=lambda text: PanelApp._friendly_error(text),
            _show_profile_error=lambda text, retry_action=None:
                PanelApp._show_profile_error(app, text, retry_action),
        )

        PanelApp._handle_profile_event(app, 4, "error", "服务暂时不可用")

        self.assertTrue(app.profile_error_frame.visible)
        self.assertEqual(app.profile_error_label.text, "服务暂时不可用")
        self.assertIs(app.profile_retry_action, retry)
        self.assertTrue(app.profile_retry_button.enabled)

    def test_restarting_interview_clears_the_previous_draft_and_transcript(self):
        row = FakeRow()
        app = SimpleNamespace(
            profile_service=None,
            profile_retry_action=lambda: None,
            profile_busy=True,
            profile_rendered_history=5,
            profile_pending_user_text="上一条提交",
            profile_message_rows=[row],
            profile_answer=FakeText("old answer"),
            profile_review=FakeText("old draft"),
            profile_error_frame=FakeFrame(),
            profile_confirm_button=FakeButton(),
            _stop_profile_wait=lambda: None,
            _render_profile_draft=lambda draft: (
                app.profile_review.clear(),
                app.profile_confirm_button.setEnabled(draft is not None),
            ),
            _set_profile_busy=lambda busy: setattr(app, "busy", busy),
            _add_welcome_bubble=lambda: None,
        )

        PanelApp._reset_profile_interview_view(app)

        self.assertEqual(app.profile_answer.value, "")
        self.assertEqual(app.profile_review.value, "")
        self.assertEqual(app.profile_rendered_history, 0)
        self.assertIsNone(app.profile_pending_user_text)
        self.assertEqual(app.profile_message_rows, [])
        self.assertTrue(row.deleted)
        self.assertIsNone(app.profile_retry_action)
        self.assertFalse(app.profile_error_frame.visible)
        self.assertFalse(app.profile_confirm_button.enabled)
        self.assertFalse(app.busy)

    def test_skipped_answer_is_rendered_without_replaying_the_previous_question(self):
        app, messages = self._draft_app()
        service = SimpleNamespace(
            research_results=[], sources_displayed=False,
            research_status="未启用，使用简历访谈",
            history=[
                {"role": "assistant", "content": "做过部署吗？"},
                {"role": "user", "content": "（用户跳过本问题）"},
            ],
        )

        PanelApp._show_profile_draft(
            app, service, InterviewDraft(pending_question="有其他经历吗？")
        )

        self.assertEqual(
            [(role, text) for role, text, _links in messages],
            [("user", "跳过了这个问题"), ("assistant", "有其他经历吗？")],
        )

    def test_immediately_rendered_skip_is_not_replayed_from_service_history(self):
        app, messages = self._draft_app()
        draft = InterviewDraft(pending_question="你做过哪些项目？")
        service = SimpleNamespace(
            draft=draft,
            research_results=[],
            sources_displayed=False,
            research_status="未启用，使用简历访谈",
            history=[],
        )
        app.profile_busy = False
        app.profile_service = service
        app.profile_generation = 1
        app.profile_answer = FakeText()
        app._run_profile_answer = lambda *_args: None
        app._set_profile_busy = lambda busy: setattr(app, "profile_busy", busy)
        app._start_profile_wait = lambda _text: None

        with patch("panel_candidate_profile.threading.Thread") as worker:
            PanelApp._submit_profile_answer(app, skip=True)
            worker.return_value.start.assert_called_once()

        service.history = [
            {"role": "assistant", "content": "你做过哪些项目？"},
            {"role": "user", "content": "（用户跳过本问题）"},
        ]
        PanelApp._show_profile_draft(
            app, service, InterviewDraft(pending_question="有其他经历吗？")
        )

        self.assertEqual(
            [(role, text) for role, text, _links in messages],
            [
                ("user", "跳过了这个问题"),
                ("assistant", "有其他经历吗？"),
            ],
        )

    def test_unverifiable_interview_evidence_error_has_actionable_guidance(self):
        message = PanelApp._explain_confirm_error(
            ValueError("user-confirmed evidence must quote an answer from this interview")
        )

        self.assertIn("实际回答的原文", message)
        self.assertIn("跳过的问题不能作为能力证据", message)


class CandidateProfileViewDataTests(unittest.TestCase):
    def test_profile_view_uses_only_digest_for_the_current_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resume_path = root / "resume.md"
            resume_path.write_text("当前简历内容", encoding="utf-8")
            digest_store = ResumeDigestStore(root / "resume_digest.json")
            digest_store.save("旧简历内容", ResumeDigest(primary_direction="旧方向"))

            app = SimpleNamespace(vars={"RESUME_FILE": (FakeText(str(resume_path)), "text", "")})
            with (
                patch("panel_candidate_profile.ResumeDigestStore", return_value=digest_store),
                patch(
                    "panel_candidate_profile.CandidateProfileStore",
                    return_value=SimpleNamespace(load=lambda: None),
                ),
            ):
                data = PanelApp._load_candidate_profile_view_data(app)

            self.assertEqual(data["resume"], "当前简历内容")
            self.assertIsNone(data["digest"])
            self.assertIsNone(data["profile"])

    def test_profile_with_unavailable_resume_is_marked_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resume_path = Path(temp_dir) / "missing-resume.md"
            app = SimpleNamespace(
                vars={"RESUME_FILE": (FakeText(str(resume_path)), "text", "")}
            )
            digest_store = SimpleNamespace(load_for=lambda _resume: None)
            profile = SimpleNamespace(resume_sha256="previous-resume-hash")
            with (
                patch("panel_candidate_profile.ResumeDigestStore", return_value=digest_store),
                patch(
                    "panel_candidate_profile.CandidateProfileStore",
                    return_value=SimpleNamespace(load=lambda: profile),
                ),
            ):
                data = PanelApp._load_candidate_profile_view_data(app)

        self.assertTrue(data["resume_error"])
        self.assertTrue(data["profile_stale"])


if __name__ == "__main__":
    unittest.main()
