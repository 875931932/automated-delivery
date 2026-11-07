# -*- coding: utf-8 -*-
"""岗位画像页（PanelApp mixin）。

当前未挂载到主界面：岗位画像由系统按「目标岗位」自动派生（见 delivery_config），
用户不再手工维护硬要求/加分项/阈值。保留此文件供后续「从 JD 自动沉淀画像」功能复用。
"""
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from candidate_profiles import CandidateProfileStore
from job_profiles import JobProfile, JobProfileStore, RequirementGroup


class JobProfilesPageMixin:
    # ---------------- 岗位画像页 ----------------
    def _build_job_profiles_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left, left_layout = self._card((14, 14, 14, 14), 8)
        left.setFixedWidth(264)
        left_layout.addWidget(self._label("岗位方向", "section"))
        self.job_profile_list = QListWidget()
        self.job_profile_list.setMaximumHeight(420)
        self.job_profile_list.currentRowChanged.connect(self._load_selected_job_profile)
        left_layout.addWidget(self.job_profile_list)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        new_button = QPushButton("新增")
        new_button.clicked.connect(self._new_job_profile)
        actions.addWidget(new_button)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("danger")
        delete_button.clicked.connect(self._delete_job_profile)
        actions.addWidget(delete_button)
        actions.addStretch(1)
        left_layout.addLayout(actions)
        left_layout.addStretch(1)
        layout.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 6, 6)
        right, right_layout = self._card((20, 18, 20, 18), 10)

        hint = self._label(
            "这是从招聘 JD 抽象出的「岗位需求模板」，不是候选人画像。"
            "它决定抓哪些岗位（搜索关键词）、哪些岗位在范围内（绑定职位族），"
            "以及 AI 打分时的硬要求 / 加分项 / 排除条件 / 分数线标尺。",
            "muted", wrap=True,
        )
        right_layout.addWidget(hint)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        right_layout.addLayout(form)

        self.job_profile_id_edit = QLineEdit()
        self.job_profile_name_edit = QLineEdit()
        self.job_profile_family_combo = QComboBox()
        self.job_profile_enabled_check = QCheckBox("启用")
        self.job_profile_threshold_edit = QLineEdit()
        self.job_profile_threshold_edit.setValidator(QIntValidator(0, 100, self))
        self.job_profile_threshold_edit.setPlaceholderText("留空用全局阈值")
        self.job_profile_keywords_edit = QLineEdit()
        self.job_profile_keywords_edit.setPlaceholderText("多个关键词用逗号分隔")
        self.job_profile_direction_edit = QLineEdit()

        # ---- 常用字段（用户日常只改这几项）----
        form.addWidget(self._label("名称", "fieldLabel"), 0, 0)
        form.addWidget(self.job_profile_name_edit, 0, 1, 1, 2)
        form.addWidget(self.job_profile_enabled_check, 0, 3)

        form.addWidget(self._label("确认职位族", "fieldLabel"), 1, 0)
        form.addWidget(self.job_profile_family_combo, 1, 1, 1, 1)
        form.addWidget(self._label("匹配阈值", "fieldLabel"), 1, 2)
        form.addWidget(self.job_profile_threshold_edit, 1, 3)

        form.addWidget(self._label("搜索关键词", "fieldLabel"), 2, 0)
        form.addWidget(self.job_profile_keywords_edit, 2, 1, 1, 3)

        # ---- 高级字段（可选，默认收起）----
        self.job_profile_advanced_toggle = QPushButton(
            "高级（画像 ID / 岗位方向 / 硬要求 / 加分项 / 排除条件 / 诊断关键词）"
        )
        self.job_profile_advanced_toggle.setCheckable(True)
        self.job_profile_advanced_toggle.setToolTip(
            "不填也能用：硬要求为空时 AI 只按 JD 正文与画像方向打分"
        )
        form.addWidget(self.job_profile_advanced_toggle, 3, 0, 1, 4)

        self.job_profile_advanced_panel = QWidget()
        advanced_layout = QGridLayout(self.job_profile_advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setHorizontalSpacing(12)
        advanced_layout.setVerticalSpacing(10)
        advanced_layout.addWidget(self._label("画像 ID", "fieldLabel"), 0, 0)
        advanced_layout.addWidget(self.job_profile_id_edit, 0, 1, 1, 3)
        advanced_layout.addWidget(self._label("岗位方向", "fieldLabel"), 1, 0)
        advanced_layout.addWidget(self.job_profile_direction_edit, 1, 1, 1, 3)

        self.job_profile_hard_text = QPlainTextEdit()
        self.job_profile_hard_text.setPlaceholderText("all: A | B\nany: C | D")
        self.job_profile_hard_text.setMaximumHeight(84)
        self.job_profile_preferred_text = QPlainTextEdit()
        self.job_profile_preferred_text.setPlaceholderText("每行一项")
        self.job_profile_preferred_text.setMaximumHeight(76)
        self.job_profile_exclusions_text = QPlainTextEdit()
        self.job_profile_exclusions_text.setPlaceholderText("每行一项")
        self.job_profile_exclusions_text.setMaximumHeight(76)
        self.job_profile_diagnostic_text = QPlainTextEdit()
        self.job_profile_diagnostic_text.setPlaceholderText("每行一项")
        self.job_profile_diagnostic_text.setMaximumHeight(66)

        rows = [
            ("硬要求组（每行 all: A | B 或 any: A | B）", self.job_profile_hard_text),
            ("加分项（每行一项）", self.job_profile_preferred_text),
            ("排除条件（每行一项）", self.job_profile_exclusions_text),
            ("诊断关键词（每行一项）", self.job_profile_diagnostic_text),
        ]
        row = 2
        for label_text, widget in rows:
            advanced_layout.addWidget(self._label(label_text, "fieldLabel"), row, 0)
            advanced_layout.addWidget(widget, row, 1, 1, 3)
            row += 1

        self.job_profile_advanced_panel.setVisible(False)
        self.job_profile_advanced_toggle.toggled.connect(
            self.job_profile_advanced_panel.setVisible
        )
        form.addWidget(self.job_profile_advanced_panel, 4, 0, 1, 4)

        save = QPushButton("保存岗位画像")
        save.setObjectName("primary")
        save.clicked.connect(self._save_job_profile)
        form.addWidget(save, 5, 3, Qt.AlignRight)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        inner_layout.addWidget(right)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        self._refresh_job_profiles()
        return page

    @staticmethod
    def _text_lines(widget) -> list:
        return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]

    def _refresh_job_profiles(self):
        if not hasattr(self, "job_profile_list"):
            return
        try:
            profiles = JobProfileStore().load_or_migrate(read_env_dict().get("DELIVER_KEYWORD", ""))
        except ValueError as exc:
            QMessageBox.critical(self, "岗位画像配置无效", str(exc))
            profiles = []
        self.job_profiles = profiles
        self.job_profile_list.clear()
        for item in profiles:
            family = item.role_family_id or "未绑定"
            state = "启用" if item.enabled else "停用"
            self.job_profile_list.addItem(f"{item.name} [{state}] · {family}")
        self._refresh_job_profile_families()

    def _refresh_job_profile_families(self):
        try:
            profile = CandidateProfileStore().load()
        except ValueError:
            profile = None
        families = profile.allowed_role_families if profile else []
        self.job_profile_family_combo.clear()
        if not families:
            # 未确认候选人画像时允许不绑定：基础画像模式会用岗位画像自身定义职位族
            self.job_profile_family_combo.addItem(
                "（未确认候选人画像，可暂不绑定）", ""
            )
            return
        for item in families:
            self.job_profile_family_combo.addItem(f"{item.id} | {item.name}", item.id)

    def _new_job_profile(self):
        self.job_profile_list.setCurrentRow(-1)
        self.job_profile_id_edit.setText(uuid.uuid4().hex[:12])
        self.job_profile_name_edit.clear()
        self.job_profile_enabled_check.setChecked(False)
        self.job_profile_family_combo.setCurrentIndex(-1)
        self.job_profile_keywords_edit.clear()
        self.job_profile_threshold_edit.clear()
        self.job_profile_direction_edit.clear()
        for widget in (self.job_profile_hard_text, self.job_profile_preferred_text,
                       self.job_profile_exclusions_text, self.job_profile_diagnostic_text):
            widget.clear()

    def _load_selected_job_profile(self, row):
        if row < 0 or row >= len(self.job_profiles):
            return
        item = self.job_profiles[row]
        self.job_profile_id_edit.setText(item.id)
        self.job_profile_name_edit.setText(item.name)
        self.job_profile_enabled_check.setChecked(item.enabled)
        index = self.job_profile_family_combo.findData(item.role_family_id)
        self.job_profile_family_combo.setCurrentIndex(index if item.role_family_id else -1)
        self.job_profile_keywords_edit.setText(", ".join(item.search_keywords))
        self.job_profile_threshold_edit.setText("" if item.threshold is None else str(item.threshold))
        self.job_profile_direction_edit.setText(item.role_direction)
        hard = "\n".join(
            f"{group.mode}: {' | '.join(group.options)}" for group in item.hard_requirements
        )
        for widget, value in (
            (self.job_profile_hard_text, hard),
            (self.job_profile_preferred_text, "\n".join(item.preferred_qualifications)),
            (self.job_profile_exclusions_text, "\n".join(item.exclusions)),
            (self.job_profile_diagnostic_text, "\n".join(item.diagnostic_terms)),
        ):
            widget.setPlainText(value)

    def _save_job_profile(self):
        try:
            candidate = CandidateProfileStore().load()
            family_id = self.job_profile_family_combo.currentData() or ""
            enabled = self.job_profile_enabled_check.isChecked()
            if candidate is not None and enabled and not family_id:
                # 增强画像模式下岗位画像必须绑定已确认职位族才能参与筛选
                raise ValueError("启用岗位画像前，必须绑定一个已确认的职位族。")
            groups = []
            for line in self._text_lines(self.job_profile_hard_text):
                mode, separator, values = line.partition(":")
                if not separator or mode.strip().lower() not in ("all", "any"):
                    raise ValueError("硬要求格式应为 all: A | B 或 any: A | B")
                options = [value.strip() for value in values.split("|") if value.strip()]
                groups.append(RequirementGroup(
                    label="任选一项" if mode.strip().lower() == "any" else "全部满足",
                    options=options,
                    mode=mode.strip().lower(),
                ))
            threshold_text = self.job_profile_threshold_edit.text().strip()
            profile = JobProfile(
                id=self.job_profile_id_edit.text().strip(),
                name=self.job_profile_name_edit.text().strip(),
                enabled=enabled,
                role_family_id=family_id,
                search_keywords=[
                    item.strip() for item in self.job_profile_keywords_edit.text().split(",")
                ],
                role_direction=self.job_profile_direction_edit.text().strip(),
                hard_requirements=groups,
                diagnostic_terms=self._text_lines(self.job_profile_diagnostic_text),
                preferred_qualifications=self._text_lines(self.job_profile_preferred_text),
                exclusions=self._text_lines(self.job_profile_exclusions_text),
                threshold=int(threshold_text) if threshold_text else None,
            )
            profiles = list(self.job_profiles)
            existing = next(
                (index for index, item in enumerate(profiles) if item.id == profile.id), None
            )
            if existing is None:
                profiles.append(profile)
            else:
                profiles[existing] = profile
            JobProfileStore().save(profiles)
            self._refresh_job_profiles()
            QMessageBox.information(self, "岗位画像", "岗位画像已保存。")
        except Exception as exc:
            QMessageBox.critical(self, "岗位画像未保存", str(exc))

    def _delete_job_profile(self):
        row = self.job_profile_list.currentRow()
        if row < 0 or row >= len(self.job_profiles):
            return
        profiles = list(self.job_profiles)
        del profiles[row]
        try:
            JobProfileStore().save(profiles)
            self._refresh_job_profiles()
            self._new_job_profile()
        except Exception as exc:
            QMessageBox.critical(self, "岗位画像未删除", str(exc))


# 延迟导入：desktop_panel 在共享工具函数定义完成后才导入本模块（避免循环导入）。
from desktop_panel import read_env_dict  # noqa: E402,F401
