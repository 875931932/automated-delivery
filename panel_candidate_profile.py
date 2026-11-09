# -*- coding: utf-8 -*-
"""候选人画像页（PanelApp mixin）：访谈聊天、草稿渲染与访谈状态机。"""
import difflib
import threading
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from candidate_profiles import (
    CandidateProfileService,
    CandidateProfileStore,
    InterviewDraft,
    InterviewDraftCacheStore,
    ResumeDigestStore,
    resume_digest_hash,
)
from panel_widgets import FlowLayout


class CandidateProfilePageMixin:
    def _build_profile_view_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)
        self.profile_view_status = self._label("正在读取画像…", "statusChipIdle")
        toolbar_layout.addWidget(self.profile_view_status)
        toolbar_layout.addStretch(1)
        refresh = QPushButton("刷新")
        refresh.setObjectName("soft")
        refresh.setToolTip("重新读取当前简历解析结果和已确认画像")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self._refresh_candidate_profile_view)
        toolbar_layout.addWidget(refresh)
        layout.addWidget(toolbar)

        panels = QSplitter(Qt.Horizontal)
        panels.setChildrenCollapsible(False)
        panels.setHandleWidth(14)
        self.profile_resume_view, self.profile_resume_view_layout = self._profile_view_panel(
            "基础画像 · 简历解析", "由当前简历逐字提取，无需人工确认。"
        )
        self.profile_enhanced_view, self.profile_enhanced_view_layout = self._profile_view_panel(
            "增强画像 · 访谈确认", "完成访谈并确认后才生效，可随时重新访谈。"
        )
        panels.addWidget(self.profile_resume_view)
        panels.addWidget(self.profile_enhanced_view)
        panels.setSizes([560, 560])
        layout.addWidget(panels, 1)
        self._refresh_candidate_profile_view()
        return page

    def _profile_view_panel(self, title, subtitle=""):
        """左右两栏各包一张卡片：标题栏 + 可滚动内容区。"""
        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(20, 15, 20, 15)
        head_layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("section")
        titles.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("sectionHint")
            subtitle_label.setWordWrap(True)
            titles.addWidget(subtitle_label)
        head_layout.addLayout(titles, 1)
        outer.addWidget(head)
        outer.addWidget(self._divider("divider"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 14, 16)
        body_layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return card, body_layout

    def _load_candidate_profile_view_data(self):
        from desktop_panel import BASE_DIR, read_env_dict

        widget, _field_type, _default = self.vars.get("RESUME_FILE", (None, "", ""))
        resume_path_value = widget.text().strip() if widget is not None else ""
        if not resume_path_value:
            resume_path_value = read_env_dict().get("RESUME_FILE", "resume.md")
        resume_path = Path(resume_path_value or "resume.md")
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            resume = resume_path.read_text(encoding="utf-8")
            resume_error = ""
        except OSError as exc:
            resume = ""
            resume_error = f"简历读取失败：{exc}"

        digest = ResumeDigestStore().load_for(resume) if resume.strip() else None
        profile_error = ""
        try:
            profile = CandidateProfileStore().load()
        except ValueError as exc:
            profile = None
            profile_error = str(exc)
        profile_stale = bool(
            profile is not None
            and profile.resume_sha256
            and (
                not resume.strip()
                or profile.resume_sha256 != resume_digest_hash(resume)
            )
        )
        return {
            "resume": resume,
            "resume_error": resume_error,
            "digest": digest,
            "profile": profile,
            "profile_error": profile_error,
            "profile_stale": profile_stale,
        }

    def _clear_profile_view_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def _profile_view_section(self, layout, title, values, source=""):
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)
        section_layout.addWidget(self._label(title, "fieldLabel"))
        if not values:
            section_layout.addWidget(self._label("暂无内容", "muted"))
        else:
            for value in values:
                row = QFrame()
                row.setObjectName("evidenceCard")
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(4)
                text = self._label(str(value), "evidenceQuote", wrap=True)
                row_layout.addWidget(text)
                if source:
                    row_layout.addWidget(self._label(f"来源：{source}", "muted"))
                section_layout.addWidget(row)
        layout.addWidget(section)

    def _refresh_candidate_profile_view(self):
        if not hasattr(self, "profile_resume_view_layout"):
            return
        self._clear_profile_view_layout(self.profile_resume_view_layout)
        self._clear_profile_view_layout(self.profile_enhanced_view_layout)
        data = self._load_candidate_profile_view_data()
        digest = data["digest"]
        profile = data["profile"]

        if data["resume_error"]:
            self.profile_view_status.setText(data["resume_error"])
            self._set_widget_style(self.profile_view_status, "statusChipWarn")
        elif not data["resume"].strip():
            self.profile_view_status.setText("未找到当前简历")
            self._set_widget_style(self.profile_view_status, "statusChipWarn")
        elif digest is None:
            self.profile_view_status.setText("当前简历尚未结构化")
            self._set_widget_style(self.profile_view_status, "statusChipWait")
        else:
            self.profile_view_status.setText("已加载当前简历对应的结构化画像")
            self._set_widget_style(self.profile_view_status, "statusChipOk")

        if digest is None:
            message = data["resume_error"] or (
                "请先在「求职设置」完成简历结构化。简历修改后，旧解析结果不会继续展示。"
                if data["resume"].strip()
                else "请先在「求职设置」选择并结构化一份简历。"
            )
            self.profile_resume_view_layout.addWidget(self._label(message, "muted", wrap=True))
            settings_button = QPushButton("前往求职设置")
            settings_button.setCursor(Qt.PointingHandCursor)
            settings_button.clicked.connect(lambda: self._show_page("求职设置"))
            self.profile_resume_view_layout.addWidget(settings_button, 0, Qt.AlignLeft)
        else:
            self._profile_view_section(
                self.profile_resume_view_layout,
                "求职方向概括",
                [digest.primary_direction] if digest.primary_direction.strip() else [],
                "模型归纳，供方向参考",
            )
            for title, values in (
                ("技能", digest.skills),
                ("项目经历", digest.projects),
                ("教育与校园经历", digest.education),
                ("求职偏好", digest.preferences),
            ):
                self._profile_view_section(
                    self.profile_resume_view_layout, title, values, "简历原文逐字摘录"
                )
            if digest.summary.strip():
                self._profile_view_section(
                    self.profile_resume_view_layout,
                    "补充概述",
                    [digest.summary],
                    "模型归纳，不作为经历证据",
                )

        if data["profile_error"]:
            self.profile_enhanced_view_layout.addWidget(
                self._label(f"增强画像读取失败：{data['profile_error']}", "errorText", wrap=True)
            )
        else:
            if data["profile_stale"]:
                self.profile_enhanced_view_layout.addWidget(
                    self._label(
                        "当前简历不可用或已变化。此增强画像无法确认仍然适用，运行匹配时会暂时回退到基础画像；"
                        "重新完成访谈并确认后可恢复使用。",
                        "statusChipWarn",
                        wrap=True,
                    )
                )
            if profile is None:
                self.profile_enhanced_view_layout.addWidget(
                    self._label("尚无已确认的增强画像。完成访谈并确认草稿后，画像会显示在这里。", "muted", wrap=True)
                )
                enhance = QPushButton("前往增强画像")
                enhance.setCursor(Qt.PointingHandCursor)
                enhance.clicked.connect(lambda: self._show_page("增强画像"))
                self.profile_enhanced_view_layout.addWidget(enhance, 0, Qt.AlignLeft)
            else:
                self.profile_enhanced_view_layout.addWidget(
                    self._label(
                        f"{'当前不可用' if data['profile_stale'] else '已确认'} · v{profile.revision}",
                        "statusChipWarn" if data["profile_stale"] else "statusChipOk",
                    )
                )
                self._profile_view_section(
                    self.profile_enhanced_view_layout, "主要方向", [profile.primary_direction]
                )
                self._profile_view_section(
                    self.profile_enhanced_view_layout,
                    "允许职位族",
                    [
                        f"{family.name}（{family.id}）"
                        + (f"\n别名：{'、'.join(family.aliases)}" if family.aliases else "")
                        + (f"\n职位关键词：{'、'.join(family.title_terms)}" if family.title_terms else "")
                        for family in profile.allowed_role_families
                    ],
                )
                if profile.evidence:
                    self.profile_enhanced_view_layout.addWidget(self._label("已确认能力与依据", "fieldLabel"))
                    for evidence in profile.evidence:
                        self.profile_enhanced_view_layout.addWidget(self._evidence_card(evidence))
                for title, values in (
                    ("求职偏好", profile.preferences),
                    ("排除职位族", profile.excluded_role_families),
                    ("排除关键词", profile.excluded_terms),
                ):
                    if values:
                        self._profile_view_section(self.profile_enhanced_view_layout, title, values)
                self.profile_enhanced_view_layout.addWidget(
                    self._label(
                        "联网职位信息仅用于辅助追问，不会作为个人技能或经历证据。",
                        "muted",
                        wrap=True,
                    )
                )

        self.profile_resume_view_layout.addStretch(1)
        self.profile_enhanced_view_layout.addStretch(1)

    # ---------------- 候选人画像页 ----------------
    def _build_candidate_profile_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)
        self.profile_start_button = QPushButton("从简历开始访谈")
        self.profile_start_button.setObjectName("primary")
        self.profile_start_button.setCursor(Qt.PointingHandCursor)
        self.profile_start_button.clicked.connect(self._start_profile_interview)
        toolbar_layout.addWidget(self.profile_start_button)

        self.profile_cancel_button = QPushButton("取消访谈")
        self.profile_cancel_button.setObjectName("danger")
        self.profile_cancel_button.setEnabled(False)
        self.profile_cancel_button.setCursor(Qt.PointingHandCursor)
        self.profile_cancel_button.clicked.connect(self._cancel_profile_interview)
        toolbar_layout.addWidget(self.profile_cancel_button)
        toolbar_layout.addStretch(1)

        self.profile_summary_label = QLabel("正在读取候选人画像…")
        self.profile_summary_label.setObjectName("statusChipIdle")
        toolbar_layout.addWidget(self.profile_summary_label)
        layout.addWidget(toolbar)

        workspace = QSplitter(Qt.Horizontal)
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(14)
        workspace.addWidget(self._build_chat_card())
        workspace.addWidget(self._build_review_card())
        workspace.setSizes([640, 520])
        layout.addWidget(workspace, 1)
        self._refresh_candidate_profile_summary()
        self._refresh_candidate_profile_view()
        self._add_welcome_bubble()
        return page

    def _build_chat_card(self) -> QFrame:
        card, card_layout = self._card((20, 16, 20, 18), 12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(3)
        title_label = QLabel("画像访谈")
        title_label.setObjectName("section")
        titles.addWidget(title_label)
        hint = QLabel("问答仅用于形成待确认草稿")
        hint.setObjectName("sectionHint")
        titles.addWidget(hint)
        head_layout.addLayout(titles, 1)
        card_layout.addWidget(head)

        self.profile_transcript = QScrollArea()
        self.profile_transcript.setObjectName("chatScroll")
        self.profile_transcript.setWidgetResizable(True)
        self.profile_transcript.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("chatInner")
        self.profile_messages_layout = QVBoxLayout(inner)
        self.profile_messages_layout.setContentsMargins(14, 12, 14, 12)
        self.profile_messages_layout.setSpacing(0)
        self.profile_messages_layout.addStretch(1)
        self.profile_transcript.setWidget(inner)
        card_layout.addWidget(self.profile_transcript, 1)

        self.profile_error_frame = QFrame()
        self.profile_error_frame.setObjectName("errorBanner")
        error_layout = QHBoxLayout(self.profile_error_frame)
        error_layout.setContentsMargins(14, 10, 14, 10)
        error_layout.setSpacing(10)
        self.profile_error_label = QLabel("")
        self.profile_error_label.setObjectName("errorText")
        self.profile_error_label.setWordWrap(True)
        error_layout.addWidget(self.profile_error_label, 1)
        self.profile_retry_button = QPushButton("重试")
        self.profile_retry_button.setEnabled(False)
        self.profile_retry_button.clicked.connect(self._retry_profile_action)
        error_layout.addWidget(self.profile_retry_button)
        self.profile_error_frame.hide()
        card_layout.addWidget(self.profile_error_frame)

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(10)

        self.profile_answer = QPlainTextEdit()
        self.profile_answer.setPlaceholderText("在这里回答画像助手的问题…（Ctrl+Enter 发送）")
        self.profile_answer.setMinimumHeight(78)
        self.profile_answer.setMaximumHeight(130)
        self.profile_answer.setEnabled(False)
        composer_layout.addWidget(self.profile_answer, 1)
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.profile_answer)
        shortcut.activated.connect(lambda: self._submit_profile_answer(False))

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        self.profile_skip_button = QPushButton("跳过")
        self.profile_skip_button.setEnabled(False)
        self.profile_skip_button.clicked.connect(lambda: self._submit_profile_answer(True))
        buttons.addWidget(self.profile_skip_button)
        self.profile_submit_button = QPushButton("发送")
        self.profile_submit_button.setObjectName("primary")
        self.profile_submit_button.setEnabled(False)
        self.profile_submit_button.clicked.connect(lambda: self._submit_profile_answer(False))
        buttons.addWidget(self.profile_submit_button)
        composer_layout.addLayout(buttons)

        card_layout.addWidget(composer)
        return card

    def _build_review_card(self) -> QFrame:
        card, card_layout = self._card((20, 16, 20, 18), 12)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(3)
        title_label = QLabel("画像草稿")
        title_label.setObjectName("section")
        titles.addWidget(title_label)
        self.profile_draft_status = QLabel("尚未开始")
        self.profile_draft_status.setObjectName("statusChipIdle")
        titles.addWidget(self.profile_draft_status)
        head_layout.addLayout(titles, 1)
        self.profile_confirm_button = QPushButton("确认并保存")
        self.profile_confirm_button.setObjectName("primary")
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.clicked.connect(self._confirm_profile_draft)
        head_layout.addWidget(self.profile_confirm_button)
        card_layout.addWidget(head)
        card_layout.addWidget(self._label(
            "确认后作为筛选任务的职业边界；内容已转为可读表单，无需理解 JSON。",
            "muted", wrap=True,
        ))

        self.profile_draft_empty = QLabel(
            "还没有画像草稿\n\n点击「从简历开始访谈」，助手会逐条确认方向与经历，\n"
            "结果会以可读卡片展示在这里。"
        )
        self.profile_draft_empty.setObjectName("draftEmpty")
        self.profile_draft_empty.setAlignment(Qt.AlignCenter)
        self.profile_draft_empty.setWordWrap(True)
        card_layout.addWidget(self.profile_draft_empty, 1)

        self.profile_draft_body = QWidget()
        body_layout = QVBoxLayout(self.profile_draft_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self.profile_draft_scroll = QScrollArea()
        self.profile_draft_scroll.setWidgetResizable(True)
        self.profile_draft_scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 8, 4)
        content_layout.setSpacing(16)

        content_layout.addWidget(self._label("职业方向", "fieldTitle"))
        self.profile_direction_edit = QLineEdit()
        self.profile_direction_edit.setPlaceholderText("访谈确认后填入，可在此微调")
        content_layout.addWidget(self.profile_direction_edit)
        content_layout.addWidget(self._label("职位族", "fieldTitle"))
        content_layout.addWidget(self._chip_host("profile_families_layout"))
        content_layout.addWidget(self._label("排除范围", "fieldTitle"))
        content_layout.addWidget(self._chip_host("profile_excluded_layout"))

        content_layout.addWidget(self._label("已确认能力与依据", "fieldTitle"))
        evidence_host = QWidget()
        self.profile_evidence_layout = QVBoxLayout(evidence_host)
        self.profile_evidence_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_evidence_layout.setSpacing(8)
        content_layout.addWidget(evidence_host)

        content_layout.addWidget(self._label("待核实能力与信息", "fieldTitle"))
        pending_host = QWidget()
        self.profile_pending_layout = QVBoxLayout(pending_host)
        self.profile_pending_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_pending_layout.setSpacing(8)
        content_layout.addWidget(pending_host)

        content_layout.addWidget(self._label("偏好", "fieldTitle"))
        content_layout.addWidget(self._chip_host("profile_preferences_layout"))
        content_layout.addStretch(1)

        self.profile_draft_scroll.setWidget(content)
        body_layout.addWidget(self.profile_draft_scroll, 1)

        self.profile_json_toggle = QPushButton("查看原始 JSON")
        self.profile_json_toggle.setObjectName("link")
        self.profile_json_toggle.setCheckable(True)
        self.profile_json_toggle.clicked.connect(self._toggle_profile_json)
        body_layout.addWidget(self.profile_json_toggle, 0, Qt.AlignLeft)

        self.profile_review = QPlainTextEdit()
        self.profile_review.setFont(QFont("Cascadia Mono", 9))
        self.profile_review.setPlaceholderText("访谈完成后，这里会生成待确认的画像 JSON。")
        self.profile_review.setFixedHeight(200)
        self.profile_review.hide()
        body_layout.addWidget(self.profile_review)

        card_layout.addWidget(self.profile_draft_body, 1)
        self.profile_draft_body.hide()
        return card

    def _chip_host(self, attr_name):
        host = QWidget()
        layout = FlowLayout(host, spacing=6)
        setattr(self, attr_name, layout)
        return host

    def _toggle_profile_json(self, checked):
        # 展开前把表单里的方向同步进 JSON，避免两处内容不一致
        if checked and self.profile_draft is not None:
            if self.profile_review.toPlainText() == self.profile_json_generated:
                direction = self.profile_direction_edit.text().strip()
                if direction and direction != self.profile_draft.primary_direction:
                    self.profile_draft = self.profile_draft.model_copy(
                        update={"primary_direction": direction}
                    )
                    self.profile_json_generated = self.profile_draft.model_dump_json(indent=2)
                    self.profile_review.setPlainText(self.profile_json_generated)
        self.profile_review.setVisible(checked)
        self.profile_json_toggle.setText("隐藏原始 JSON" if checked else "查看原始 JSON")

    def _render_profile_draft(self, draft):
        self.profile_draft = draft
        self.profile_draft_empty.setVisible(draft is None)
        self.profile_draft_body.setVisible(draft is not None)
        self.profile_confirm_button.setEnabled(bool(draft and draft.ready_for_review))
        if draft is None:
            self.profile_direction_edit.clear()
            self.profile_json_generated = ""
            self.profile_review.clear()
            for name in (
                "profile_families_layout", "profile_excluded_layout",
                "profile_preferences_layout", "profile_evidence_layout",
                "profile_pending_layout",
            ):
                self._clear_layout(getattr(self, name))
            self.profile_draft_status.setText("尚未开始")
            self._set_widget_style(self.profile_draft_status, "statusChipIdle")
            return

        self.profile_direction_edit.setText(draft.primary_direction)

        self._clear_layout(self.profile_families_layout)
        for family in draft.allowed_role_families:
            self._add_chip(self.profile_families_layout, family.name, "chip")
        if not draft.allowed_role_families:
            self._add_chip(self.profile_families_layout, "尚未识别出职位族", "chipMuted")

        self._clear_layout(self.profile_excluded_layout)
        for name in draft.excluded_role_families:
            self._add_chip(self.profile_excluded_layout, name, "chipDanger")
        for term in draft.excluded_terms:
            self._add_chip(self.profile_excluded_layout, term, "chipMuted")
        if not draft.excluded_role_families and not draft.excluded_terms:
            self._add_chip(self.profile_excluded_layout, "未设置排除范围", "chipMuted")

        self._clear_layout(self.profile_evidence_layout)
        for evidence in draft.evidence:
            self.profile_evidence_layout.addWidget(self._evidence_card(evidence))
        if not draft.evidence:
            self.profile_evidence_layout.addWidget(
                self._label("还没有可确认的能力证据。", "muted")
            )

        self._clear_layout(self.profile_pending_layout)
        for item in draft.proposed_evidence:
            self.profile_pending_layout.addWidget(self._pending_card(item))
        if not draft.proposed_evidence:
            self.profile_pending_layout.addWidget(
                self._label("暂无待确认信息。", "muted")
            )

        self._clear_layout(self.profile_preferences_layout)
        for preference in draft.preferences:
            self._add_chip(self.profile_preferences_layout, preference, "chipMuted")
        if not draft.preferences:
            self._add_chip(self.profile_preferences_layout, "暂无偏好", "chipMuted")

        self.profile_json_generated = draft.model_dump_json(indent=2)
        self.profile_review.setPlainText(self.profile_json_generated)
        if draft.ready_for_review:
            self.profile_draft_status.setText("待确认")
            self._set_widget_style(self.profile_draft_status, "statusChipOk")
            self.profile_summary_label.setText("访谈完成 · 待确认")
            self._set_widget_style(self.profile_summary_label, "statusChipOk")
        else:
            self.profile_draft_status.setText("访谈中")
            self._set_widget_style(self.profile_draft_status, "statusChipWait")
            self.profile_summary_label.setText("访谈进行中")
            self._set_widget_style(self.profile_summary_label, "statusChipWait")

    def _evidence_card(self, evidence) -> QFrame:
        frame = QFrame()
        frame.setObjectName("evidenceCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(4)
        claim = QLabel(evidence.claim)
        claim.setObjectName("evidenceClaim")
        claim.setWordWrap(True)
        layout.addWidget(claim)
        quote = QLabel(f"「{evidence.evidence_text}」")
        quote.setObjectName("evidenceQuote")
        quote.setWordWrap(True)
        layout.addWidget(quote)
        source = "简历原文" if evidence.source == "resume_quote" else "你的确认"
        layout.addWidget(self._label(f"来源：{source}", "muted"))
        return frame

    def _pending_card(self, item) -> QFrame:
        frame = QFrame()
        frame.setObjectName("pendingCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(4)
        claim = QLabel(item.claim)
        claim.setObjectName("pendingClaim")
        claim.setWordWrap(True)
        layout.addWidget(claim)
        question = QLabel(item.clarification_question or "等待进一步确认")
        question.setObjectName("pendingQuestion")
        question.setWordWrap(True)
        layout.addWidget(question)
        return frame

    def _refresh_candidate_profile_summary(self):
        error = candidate_profile_startup_error()
        if error:
            self.profile_summary_label.setText("画像未确认")
            self.profile_summary_label.setToolTip(error)
            self._set_widget_style(self.profile_summary_label, "statusChipWarn")
            return
        profile = CandidateProfileStore().load()
        if profile is None:
            self.profile_summary_label.setText("基础画像模式")
            self.profile_summary_label.setToolTip(
                "未确认候选人画像，将按基础画像（简历+岗位画像）运行；完成访谈后可升级为增强画像"
            )
            self._set_widget_style(self.profile_summary_label, "statusChipWait")
            return
        families = "、".join(item.name for item in profile.allowed_role_families)
        self.profile_summary_label.setText(f"已确认 · v{profile.revision}")
        self.profile_summary_label.setToolTip(
            f"当前方向：{profile.primary_direction}\n允许职位族：{families or '未设置'}"
        )
        self._set_widget_style(self.profile_summary_label, "statusChipOk")

    def _profile_log(self, role, text, links=None):
        if role == "user":
            bubble_name, bubble_id, name_id, text_id = "你", "bubbleUser", "bubbleNameUser", "bubbleText"
        elif role == "error":
            bubble_name, bubble_id, name_id, text_id = "连接提示", "bubbleError", "bubbleNameError", "bubbleTextError"
        else:
            bubble_name, bubble_id, name_id, text_id = "画像助手", "bubbleAI", "bubbleNameAI", "bubbleText"

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 6, 0, 6)
        row_layout.setSpacing(10)

        avatar = QFrame()
        avatar.setObjectName("avatarUser" if role == "user" else "avatar")
        avatar.setFixedSize(26, 26)
        avatar_layout = QVBoxLayout(avatar)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_layout.setSpacing(0)
        avatar_text = QLabel("我" if role == "user" else "助")
        avatar_text.setAlignment(Qt.AlignCenter)
        avatar_layout.addWidget(avatar_text)

        bubble = QFrame()
        bubble.setObjectName(bubble_id)
        bubble.setMaximumWidth(560)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(16, 12, 16, 12)
        bubble_layout.setSpacing(5)

        name = QLabel(bubble_name)
        name.setObjectName(name_id)
        bubble_layout.addWidget(name)

        message = QLabel(text)
        message.setObjectName(text_id)
        message.setWordWrap(True)
        message.setMinimumWidth(340)
        message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble_layout.addWidget(message)

        for title, url in links or []:
            link = QLabel(f'<a href="{url}">{title}</a>')
            link.setObjectName("sourceLink")
            link.setWordWrap(True)
            link.setTextFormat(Qt.RichText)
            link.setOpenExternalLinks(True)
            link.setToolTip(url)
            bubble_layout.addWidget(link)

        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
            row_layout.addWidget(avatar)
        else:
            row_layout.addWidget(avatar)
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        self.profile_messages_layout.insertWidget(
            self.profile_messages_layout.count() - 1, row
        )
        self.profile_message_rows.append(row)
        QTimer.singleShot(0, self._scroll_chat_to_bottom)
        return row, message

    def _scroll_chat_to_bottom(self):
        bar = self.profile_transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _start_profile_wait(self, text: str):
        """在聊天区插入等待气泡，并持续显示已等待秒数。"""
        self._stop_profile_wait()
        self.profile_wait_started = time.time()
        self.profile_wait_base = text
        row, label = self._profile_log("assistant", text)
        self.profile_wait_row = row
        self.profile_wait_label = label
        self.profile_wait_timer.start(700)

    def _tick_profile_wait(self):
        if self.profile_wait_label is None:
            self.profile_wait_timer.stop()
            return
        seconds = int(time.time() - self.profile_wait_started)
        suffix = "已等待 {}s".format(seconds)
        if seconds >= 20:
            suffix += " · 仍在调用模型，可点「取消访谈」"
        self.profile_wait_label.setText(f"{self.profile_wait_base}  {suffix}")

    def _stop_profile_wait(self):
        self.profile_wait_timer.stop()
        row = self.profile_wait_row
        self.profile_wait_row = None
        self.profile_wait_label = None
        if row is not None:
            if row in self.profile_message_rows:
                self.profile_message_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def _add_welcome_bubble(self):
        self._profile_log(
            "assistant",
            "点击「从简历开始访谈」后，我会读取简历文件，逐条确认职业方向、职位族与经历证据。"
            "过程中可以跳过问题；右侧草稿只有点击「确认并保存」才会生效。",
        )

    def _retry_profile_action(self):
        action = self.profile_retry_action
        self.profile_error_frame.hide()
        if action is not None:
            action()

    def _show_profile_error(self, text, retry_action=None):
        self.profile_error_label.setText(self._friendly_error(text))
        self.profile_retry_action = retry_action
        self.profile_retry_button.setEnabled(retry_action is not None and not self.profile_busy)
        self.profile_error_frame.show()
        self.profile_summary_label.setText("访谈失败")
        self.profile_summary_label.setToolTip(str(text))
        self._set_widget_style(self.profile_summary_label, "statusChipWarn")

    def _set_profile_busy(self, busy):
        self.profile_busy = busy
        draft = self.profile_service.draft if self.profile_service else None
        can_answer = draft is not None and not draft.ready_for_review
        answer_state = can_answer and not busy
        self.profile_start_button.setEnabled(not busy)
        self.profile_submit_button.setText("生成中…" if busy else "发送")
        self.profile_skip_button.setText("生成中…" if busy else "跳过")
        for widget in (
            self.profile_submit_button, self.profile_skip_button, self.profile_answer,
        ):
            widget.setEnabled(answer_state)
        self.profile_cancel_button.setEnabled(self.profile_service is not None)
        self.profile_retry_button.setEnabled(bool(self.profile_retry_action) and not busy)

    def _reset_profile_interview_view(self):
        self._stop_profile_wait()
        self.profile_service = None
        self.profile_retry_action = None
        self.profile_rendered_history = 0
        self.profile_pending_user_text = None
        self.profile_answer.clear()
        self._render_profile_draft(None)
        self.profile_error_frame.hide()
        for row in self.profile_message_rows:
            row.setParent(None)
            row.deleteLater()
        self.profile_message_rows.clear()
        self._set_profile_busy(False)
        self._add_welcome_bubble()

    def _start_profile_interview(self):
        self.profile_generation += 1
        generation = self.profile_generation
        if self.profile_service is not None:
            self.profile_service.cancel()
        self._reset_profile_interview_view()
        values = read_env_dict()
        resume_path = Path(values.get("RESUME_FILE", "resume.md"))
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            resume = resume_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._show_profile_error(f"简历文件读取失败：{exc}", self._start_profile_interview)
            return
        if not resume.strip():
            self._show_profile_error("简历文件为空。", self._start_profile_interview)
            return

        self.profile_resume = resume
        self.profile_retry_action = self._start_profile_interview

        cache = self._profile_cache
        if cache and cache.get("hash") == resume_digest_hash(resume):
            # 启动时已预生成首个草稿，直接展示，无需等待模型
            self._profile_cache = None
            self.profile_service = cache["service"]
            self._set_profile_busy(False)
            self._show_profile_draft(cache["service"], cache["draft"])
            return

        self.profile_summary_label.setText("访谈准备中")
        self.profile_summary_label.setToolTip("正在初始化访谈服务并读取简历")
        self._set_widget_style(self.profile_summary_label, "statusChipWait")
        self._set_profile_busy(True)
        self._start_profile_wait("正在初始化访谈服务并读取简历…")
        threading.Thread(
            target=self._run_profile_bootstrap,
            args=(generation, resume),
            daemon=True,
        ).start()

    def _maybe_prewarm_draft(self):
        """首次进入候选人画像页时预生成首个草稿；不使用访谈则不调用模型。"""
        if self._draft_prewarm_started or self.profile_service is not None:
            return
        self._draft_prewarm_started = True
        self._draft_prewarm_thread = threading.Thread(
            target=self._prewarm_first_draft, daemon=True
        )
        self._draft_prewarm_thread.start()

    def _prewarm_first_draft(self):
        """准备首个访谈草稿：优先用磁盘缓存（零成本），缺失才调用模型，生成后落盘复用。"""
        try:
            deps = self._interview_deps or self._load_interview_deps()
            self._interview_deps = deps
            model = self._resolve_model(deps)
            resume = self._read_resume_for_interview()
            if not resume.strip():
                return
            if self.profile_service is not None or self._profile_cache is not None:
                return
            store = InterviewDraftCacheStore()
            revision = self._profile_revision()
            draft = store.load_for(resume, revision)
            if draft is not None:
                # 缓存有效：直接包装复用，不调用模型
                self._profile_cache = {
                    "hash": resume_digest_hash(resume),
                    "service": self._wrap_service_with_draft(deps, model, resume, draft),
                    "draft": draft,
                }
                return
            service = self._build_profile_service(deps, model, resume)
            draft = service.start_interview(resume)
            if self.profile_service is None:
                store.save(resume, revision, draft)
                self._profile_cache = {
                    "hash": resume_digest_hash(resume),
                    "service": service,
                    "draft": draft,
                }
        except Exception:
            self._draft_prewarm_started = False  # 失败后再次进入页面时可重试

    @staticmethod
    def _profile_revision():
        profile = CandidateProfileStore().load()
        return profile.revision if profile else 0

    def _wrap_service_with_draft(self, deps, model, resume, draft):
        service = self._build_profile_service(deps, model, resume)
        service.resume = resume
        service.active_profile = CandidateProfileStore().load()
        service.draft = draft
        return service

    @staticmethod
    def _read_resume_for_interview() -> str:
        values = read_env_dict()
        resume_path = Path(values.get("RESUME_FILE", "resume.md"))
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            return resume_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _build_profile_service(self, deps, model, resume=""):
        # 运行时现读 .env：面板保存 Tavily/AI 配置后立即生效，不受 import 快照限制
        config = current_deliver_config()
        service = CandidateProfileService(
            CandidateProfileStore(),
            deps["CandidateInterviewChain"](model=model),
            researcher=deps["TavilyRoleResearcher"](
                enabled=config["tavily_enabled"],
                api_key=config["tavily_api_key"],
                timeout=config["tavily_timeout"],
            ),
        )
        # 访谈模型直接使用结构化摘要（各行均为简历原文）；无缓存时回退简历原文
        digest = ResumeDigestStore().load_for(resume)
        if digest is not None:
            service.resume_prompt = digest.prompt_text()
        return service

    @staticmethod
    def _friendly_error(text):
        raw = str(text)
        low = raw.lower()
        if any(token in low for token in ("connection", "connect", "nameresolution", "temporary failure")):
            return "无法连接 AI 接口。请检查网络，或到「AI 接口」页核对接口地址 / API Key，然后点重试。"
        if "timed out" in low or "timeout" in low:
            return "AI 接口请求超时。可到「AI 接口」页调大请求超时秒数，或稍后点重试。"
        if "401" in raw or "unauthorized" in low:
            return "AI 接口认证失败，请到「AI 接口」页核对 API Key 后点重试。"
        if "429" in raw or ("rate" in low and "limit" in low):
            return "AI 接口限流，请稍后点重试。"
        return raw

    def _load_interview_deps(self):
        from ai_chains import CandidateInterviewChain, build_chat_model
        from auto_deliver import DELIVER_CONFIG
        from tavily_search import TavilyRoleResearcher

        return {
            "CandidateInterviewChain": CandidateInterviewChain,
            "build_chat_model": build_chat_model,
            "DELIVER_CONFIG": DELIVER_CONFIG,
            "TavilyRoleResearcher": TavilyRoleResearcher,
            "model": None,
            "signature": None,
        }

    def _run_profile_bootstrap(self, generation, resume):
        """后台完成服务构建与首个问题生成，避免界面卡死。"""
        try:
            deps = self._interview_deps or self._load_interview_deps()
            self._interview_deps = deps
            model = self._resolve_model(deps)

            # 页面预热若正在生成同一份草稿，等它完成并复用结果，避免重复调用模型
            thread = self._draft_prewarm_thread
            while (
                thread is not None and thread.is_alive()
                and self._profile_cache is None
                and self.profile_service is None
            ):
                thread.join(0.5)
            if generation != self.profile_generation:
                return

            cache = self._profile_cache
            if cache and cache.get("hash") == resume_digest_hash(resume):
                # 预热刚好完成：直接消费缓存草稿，不再重复调用模型
                self._profile_cache = None
                self.profile_events.put((generation, "service", cache["service"]))
                self.profile_events.put((generation, "draft", (cache["service"], cache["draft"])))
                return

            service = self._build_profile_service(deps, model, resume)
            self.profile_events.put((generation, "service", service))
            draft = service.start_interview(resume)
            self.profile_events.put((generation, "draft", (service, draft)))
            InterviewDraftCacheStore().save(resume, self._profile_revision(), draft)
        except Exception as exc:
            self.profile_events.put((generation, "error", str(exc)))

    def _submit_profile_answer(self, skip):
        if self.profile_busy or self.profile_service is None or self.profile_service.draft is None:
            return
        service = self.profile_service
        draft = service.draft
        answer = "" if skip else self.profile_answer.toPlainText().strip()
        if not skip and not answer:
            return
        generation = self.profile_generation
        # 先把自己这轮的话显示出来，避免点发送后界面毫无反应
        if skip:
            self.profile_pending_user_text = "跳过了这个问题"
            self._profile_log("user", self.profile_pending_user_text)
            wait_text = "已跳过，正在整理下一个问题…"
        else:
            self._profile_log("user", answer)
            self.profile_pending_user_text = answer
            self.profile_answer.clear()
            wait_text = "正在思考下一个问题…"
        self._set_profile_busy(True)
        self._start_profile_wait(wait_text)
        self.profile_retry_action = lambda: self._retry_profile_answer(
            generation, service, draft, answer, skip
        )
        threading.Thread(
            target=self._run_profile_answer,
            args=(generation, service, draft, answer, skip),
            daemon=True,
        ).start()

    def _retry_profile_answer(self, generation, service, draft, answer, skip):
        if self.profile_busy:
            return
        self._set_profile_busy(True)
        self._start_profile_wait("正在重试…")
        self.profile_retry_action = lambda: self._retry_profile_answer(
            generation, service, draft, answer, skip
        )
        threading.Thread(
            target=self._run_profile_answer,
            args=(generation, service, draft, answer, skip),
            daemon=True,
        ).start()

    def _run_profile_answer(self, generation, service, draft, answer, skip):
        try:
            updated = service.answer(draft, text=answer, skip=skip)
            self.profile_events.put((generation, "answer", (service, updated, skip)))
        except Exception as exc:
            self.profile_events.put((generation, "error", str(exc)))

    def _show_profile_draft(self, service, draft):
        if service.research_results and not service.sources_displayed:
            links = [
                (item.get("title") or "未命名来源", item.get("url") or "")
                for item in service.research_results
            ]
            self._profile_log("assistant", f"岗位市场搜索：{service.research_status}，仅作为追问参考。", links)
            service.sources_displayed = True
        while self.profile_rendered_history < len(service.history):
            item = service.history[self.profile_rendered_history]
            if item["role"] == "user":
                content = item["content"]
                if content == "（用户跳过本问题）":
                    content = "跳过了这个问题"
                if self.profile_pending_user_text is not None and content == self.profile_pending_user_text:
                    # 这轮回答已经在提交时先渲染过了，跳过避免重复
                    self.profile_pending_user_text = None
                else:
                    self._profile_log("user", content)
            self.profile_rendered_history += 1
        self.profile_pending_user_text = None
        if draft.pending_question:
            self._profile_log("assistant", draft.pending_question)
        elif draft.ready_for_review:
            self._profile_log("assistant", "画像草稿已整理完成，请复核职业边界与经历。")
        self._render_profile_draft(draft)
        self.profile_summary_label.setText("待确认" if draft.ready_for_review else "访谈进行中")
        self.profile_summary_label.setToolTip(f"岗位市场搜索：{service.research_status}")
        self._set_widget_style(self.profile_summary_label, "statusChipWait")

    def _handle_profile_event(self, generation, kind, payload):
        if generation != self.profile_generation:
            return
        if kind == "service":
            self.profile_service = payload
            self.profile_cancel_button.setEnabled(True)
            return
        self._stop_profile_wait()
        if kind not in {"draft", "answer"}:
            self._set_profile_busy(False)
            self._show_profile_error(payload, self.profile_retry_action)
            return

        self.profile_retry_action = None
        self._set_profile_busy(False)
        self.profile_error_frame.hide()
        if kind == "draft":
            service, draft = payload
            self.profile_service = service
            self._show_profile_draft(service, draft)
        elif kind == "answer":
            service, draft, skipped = payload
            self._show_profile_draft(service, draft)

    def _cancel_profile_interview(self):
        self.profile_generation += 1
        self._stop_profile_wait()
        if self.profile_service is not None:
            self.profile_service.cancel()
        self.profile_service = None
        self.profile_retry_action = None
        self.profile_error_frame.hide()
        self._render_profile_draft(None)
        self._set_profile_busy(False)
        self.profile_answer.clear()
        for row in self.profile_message_rows:
            row.setParent(None)
            row.deleteLater()
        self.profile_message_rows.clear()
        self.profile_rendered_history = 0
        self._refresh_candidate_profile_summary()
        self._add_welcome_bubble()

    def _confirm_profile_draft(self):
        service = self.profile_service
        if service is None or service.draft is None or self.profile_draft is None:
            return
        if self.profile_json_toggle.isChecked():
            try:
                edited = InterviewDraft.model_validate_json(self.profile_review.toPlainText())
            except Exception as exc:
                QMessageBox.critical(self, "画像未保存", f"原始 JSON 无法解析：{exc}")
                return
        else:
            direction = self.profile_direction_edit.text().strip()
            if not direction:
                QMessageBox.warning(self, "画像未保存", "职业方向不能为空。")
                return
            edited = self.profile_draft.model_copy(update={"primary_direction": direction})

        aligned, changes = self._align_resume_quotes(edited, service.resume)
        if changes:
            detail = "\n".join(f"「{old}」\n→「{new}」" for old, new in changes[:5])
            reply = QMessageBox.question(
                self, "修正简历引用",
                "以下证据没有逐字出现在简历中：\n\n" + detail
                + "\n\n是否用最接近的简历原文替换后再保存？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return
            edited = aligned
            self.profile_json_generated = edited.model_dump_json(indent=2)
            self.profile_review.setPlainText(self.profile_json_generated)

        service.draft = edited
        try:
            profile = service.confirm(edited, user_approved=True)
        except Exception as exc:
            QMessageBox.critical(self, "画像未保存", self._explain_confirm_error(exc))
            return
        self.profile_draft = edited
        self.profile_service = None
        self.profile_retry_action = None
        self.profile_confirm_button.setEnabled(False)
        self._set_profile_busy(False)
        self.profile_draft_status.setText(f"已保存 · v{profile.revision}")
        self._set_widget_style(self.profile_draft_status, "statusChipOk")
        self._profile_log("assistant", f"已确认并保存画像版本 {profile.revision}。")
        self._refresh_candidate_profile_summary()
        self._refresh_candidate_profile_view()

    @staticmethod
    def _normalize_quote(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())

    @classmethod
    def _align_resume_quotes(cls, draft: InterviewDraft, resume: str):
        """把无法逐字匹配的简历引用对齐到最接近的简历原文行。"""
        normalized_resume = cls._normalize_quote(resume)
        segments = []
        for line in str(resume or "").splitlines():
            text = line.strip().lstrip("-*># ").strip()
            if len(text) >= 8:
                segments.append(text)
        evidences = []
        changes = []
        for evidence in draft.evidence:
            quote = evidence.evidence_text
            if evidence.source == "resume_quote" and cls._normalize_quote(quote) not in normalized_resume:
                best, best_ratio = None, 0.0
                for segment in segments:
                    ratio = difflib.SequenceMatcher(
                        None, cls._normalize_quote(quote), cls._normalize_quote(segment)
                    ).ratio()
                    if ratio > best_ratio:
                        best, best_ratio = segment, ratio
                if best is not None and best_ratio >= 0.55:
                    changes.append((quote, best))
                    evidences.append(evidence.model_copy(update={"evidence_text": best}))
                    continue
            evidences.append(evidence)
        if not changes:
            return draft, []
        return draft.model_copy(update={"evidence": evidences}), changes

    @staticmethod
    def _explain_confirm_error(exc: Exception) -> str:
        text = str(exc)
        if "resume evidence is not present" in text:
            return (
                "草稿里有证据没有逐字对应简历原文，自动修正后仍未通过。\n\n"
                "请在右侧草稿的 evidence 中把 evidence_text 改成简历里的原句，"
                "或删除该条证据后重新点击「确认并保存」。"
            )
        if "user-confirmed evidence must quote an answer" in text:
            return (
                "草稿里的用户确认能力没有对应到本轮访谈回答。\n\n"
                "请把 evidence_text 改成你实际回答的原文，或删除该条证据。"
                "跳过的问题不能作为能力证据。"
            )
        if "interview draft is not ready for review" in text:
            return "访谈还没有完成，草稿暂不能确认。请继续回答问题，或重新开始访谈。"
        if "confirm a primary direction" in text:
            return "草稿缺少职业方向或至少一个职位族，请先补充后再保存。"
        return f"画像未保存：{text}"


# 延迟导入：desktop_panel 在共享工具函数定义完成后才导入本模块，
# 因此这里放到文件末尾导入，保证两种导入顺序都不会循环。
from desktop_panel import (  # noqa: E402,F401
    BASE_DIR,
    candidate_profile_startup_error,
    current_deliver_config,
    read_env_dict,
)
