# -*- coding: utf-8 -*-
"""投递结果页（PanelApp mixin）：结果筛选、原生岗位详情与人工标记。"""
import csv
import json
import time
from functools import lru_cache

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from panel_result_logic import (
    deduplicate_result_rows,
    filter_result_rows,
    row_score,
    status_display,
    summarize_result_rows,
    update_result_mark,
)
from panel_widgets import SideDrawer, pad_spinbox_text

SCORE_ROLE = Qt.UserRole       # 数字分数（排序用）
ROW_ROLE = Qt.UserRole + 1     # 对应 self.result_rows 下标


@lru_cache(maxsize=64)
def _result_icon(name, color="#65748B", size=16):
    """绘制结果抽屉使用的轻量线性图标，避免平台主题图标不一致。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 16, size / 16)
    pen = QPen(QColor(color), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "good":
        painter.drawEllipse(1.5, 1.5, 13, 13)
        painter.drawLine(4.5, 8.2, 7, 10.7)
        painter.drawLine(7, 10.7, 11.8, 5.5)
    elif name == "bad":
        painter.drawEllipse(1.5, 1.5, 13, 13)
        painter.drawLine(5.5, 5.5, 10.5, 10.5)
        painter.drawLine(10.5, 5.5, 5.5, 10.5)
    elif name == "warning":
        painter.drawLine(8, 1.5, 14.4, 13.5)
        painter.drawLine(14.4, 13.5, 1.6, 13.5)
        painter.drawLine(1.6, 13.5, 8, 1.5)
        painter.drawLine(8, 5.2, 8, 9)
        painter.drawPoint(8, 11.3)
    elif name == "close":
        painter.drawLine(4, 4, 12, 12)
        painter.drawLine(12, 4, 4, 12)
    elif name == "salary":
        painter.drawRoundedRect(1.8, 3.5, 12.4, 9, 2, 2)
        painter.drawLine(2.4, 6.2, 13.6, 6.2)
        painter.drawEllipse(9.9, 8.1, 1.8, 1.8)
    elif name == "location":
        painter.drawEllipse(3.1, 1.4, 9.8, 9.8)
        painter.drawEllipse(6.3, 4.5, 3.4, 3.4)
        painter.drawLine(4, 9.3, 8, 14.6)
        painter.drawLine(12, 9.3, 8, 14.6)
    elif name == "time":
        painter.drawRoundedRect(2, 3.3, 12, 10.7, 1.5, 1.5)
        painter.drawLine(2.5, 6.3, 13.5, 6.3)
        painter.drawLine(5.1, 1.7, 5.1, 4.5)
        painter.drawLine(10.9, 1.7, 10.9, 4.5)
        painter.drawPoint(5.4, 9)
        painter.drawPoint(8, 9)
        painter.drawPoint(10.6, 9)
    elif name == "greeting":
        painter.drawRoundedRect(1.7, 2, 12.6, 9.3, 2.2, 2.2)
        painter.drawLine(4.2, 11.1, 3, 14)
        painter.drawLine(3, 14, 6.4, 11.1)
        for x in (5, 8, 11):
            painter.drawPoint(x, 6.7)
    elif name == "profile":
        painter.drawEllipse(1.7, 1.7, 12.6, 12.6)
        painter.drawEllipse(4.4, 4.4, 7.2, 7.2)
        painter.drawEllipse(7.1, 7.1, 1.8, 1.8)
    elif name == "search":
        painter.drawEllipse(2, 2, 8.5, 8.5)
        painter.drawLine(9.5, 9.5, 14, 14)
    elif name == "link":
        painter.drawRoundedRect(2, 4.5, 9.2, 9.2, 1.2, 1.2)
        painter.drawLine(8.3, 2, 14, 2)
        painter.drawLine(14, 2, 14, 7.7)
        painter.drawLine(13.7, 2.3, 7.7, 8.3)
    elif name == "file":
        painter.drawRoundedRect(3, 1.6, 9.5, 12.8, 1.2, 1.2)
        painter.drawLine(5.2, 5.5, 10.3, 5.5)
        painter.drawLine(5.2, 8, 10.3, 8)
        painter.drawLine(5.2, 10.5, 9, 10.5)
    elif name == "list":
        for y in (3.5, 8, 12.5):
            painter.drawEllipse(2, y - 0.8, 1.6, 1.6)
            painter.drawLine(6, y, 14, y)

    painter.end()
    return QIcon(pixmap)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


class ScoreTableItem(QTableWidgetItem):
    """按数字比较的分数单元格（setData(SCORE_ROLE, float)）。"""

    def __lt__(self, other):
        left = self.data(SCORE_ROLE)
        right = other.data(SCORE_ROLE)
        if left is None or right is None:
            return super().__lt__(other)
        return float(left) < float(right)


class ResultPageMixin:
    # ---------------- 投递结果页 ----------------
    def _build_result_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        summary = QWidget()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        self.result_summary_values = {}
        for label, key in (
            ("岗位总数", "total"),
            ("已投递", "delivered"),
            ("干跑可投", "dry_run"),
            ("待复核", "review"),
            ("失败", "failed"),
        ):
            tile, value = self._stat_tile(label, "0")
            self.result_summary_values[key] = value
            summary_layout.addWidget(tile, 1)
        layout.addWidget(summary)

        filter_card, filter_card_layout = self._card((16, 12, 16, 12), 0)
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(self._label("状态", "fieldLabel"))
        self.result_status_filter = QComboBox()
        self.result_status_filter.addItem("全部")
        self.result_status_filter.setMinimumWidth(130)
        self.result_status_filter.currentIndexChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_status_filter)

        self.result_search = QLineEdit()
        self.result_search.setPlaceholderText("搜索岗位名称或公司")
        self.result_search.setClearButtonEnabled(True)
        self.result_search.textChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_search, 1)

        self.result_advanced_toggle = QPushButton("更多筛选")
        self.result_advanced_toggle.setCheckable(True)
        self.result_advanced_toggle.setObjectName("soft")
        self.result_advanced_toggle.setToolTip("按分数区间和待复核状态筛选")
        self.result_advanced_toggle.toggled.connect(
            self._toggle_result_advanced_filters
        )
        filter_layout.addWidget(self.result_advanced_toggle)

        self.result_total = self._label("")
        self.result_total.setObjectName("muted")
        filter_layout.addWidget(self.result_total)
        refresh = QPushButton("刷新")
        refresh.setObjectName("soft")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh_results)
        filter_layout.addWidget(refresh)
        filter_card_layout.addWidget(filter_bar)

        self.result_advanced_filters = QWidget()
        advanced_layout = QHBoxLayout(self.result_advanced_filters)
        advanced_layout.setContentsMargins(0, 8, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self._label("分数区间", "fieldLabel"))
        self.result_score_min = QSpinBox()
        self.result_score_min.setRange(0, 100)
        self.result_score_min.setValue(0)
        self.result_score_min.setPrefix("≥")
        self.result_score_min.setFixedWidth(84)
        pad_spinbox_text(self.result_score_min, 10)
        self.result_score_min.valueChanged.connect(self._apply_result_filter)
        advanced_layout.addWidget(self.result_score_min)
        self.result_score_max = QSpinBox()
        self.result_score_max.setRange(0, 100)
        self.result_score_max.setValue(100)
        self.result_score_max.setPrefix("≤")
        self.result_score_max.setFixedWidth(84)
        pad_spinbox_text(self.result_score_max, 10)
        self.result_score_max.valueChanged.connect(self._apply_result_filter)
        advanced_layout.addWidget(self.result_score_max)
        self.result_review_only = QCheckBox("只看待复核")
        self.result_review_only.setToolTip("只看职业范围状态为 scope_review 的记录")
        self.result_review_only.setCursor(Qt.PointingHandCursor)
        self.result_review_only.toggled.connect(self._apply_result_filter)
        advanced_layout.addWidget(self.result_review_only)
        advanced_layout.addStretch(1)
        self.result_advanced_filters.setVisible(False)
        filter_card_layout.addWidget(self.result_advanced_filters)
        layout.addWidget(filter_card)

        table_card, table_layout = self._card((0, 0, 0, 0), 0)
        table_head = QWidget()
        table_head_layout = QHBoxLayout(table_head)
        table_head_layout.setContentsMargins(20, 14, 20, 14)
        table_head_layout.setSpacing(8)
        table_head_layout.addWidget(self._label("投递记录", "section"))
        table_head_layout.addStretch(1)
        view_detail = QPushButton("查看详情")
        view_detail.setObjectName("soft")
        view_detail.setIcon(_result_icon("search", "#52627A"))
        view_detail.setIconSize(QSize(16, 16))
        view_detail.setCursor(Qt.PointingHandCursor)
        view_detail.setToolTip("在右侧抽屉中查看岗位详情（双击行也可以打开）")
        view_detail.clicked.connect(self._open_result_drawer)
        table_head_layout.addWidget(view_detail)
        table_layout.addWidget(table_head)
        table_layout.addWidget(self._divider("divider"))
        self.result_table = QTableWidget(0, 8)
        self.result_table.setHorizontalHeaderLabels([
            "工作名称", "公司", "工资", "区域", "AI匹配分数",
            "投递状态", "投递时间", "范围状态",
        ])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(40)
        self.result_table.setShowGrid(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setWordWrap(False)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.result_table.setSortingEnabled(True)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for index, width in enumerate([220, 160, 100, 110, 110, 130, 155, 100]):
            self.result_table.setColumnWidth(index, width)
        self.result_table.itemSelectionChanged.connect(self._show_selected_result)
        self.result_table.itemDoubleClicked.connect(
            lambda _item: self._open_result_drawer()
        )
        table_layout.addWidget(self.result_table, 1)
        self.result_empty_hint = self._label(
            "暂无投递记录。完成求职设置后启动任务，结果会显示在这里。",
            "muted",
            wrap=True,
        )
        self.result_empty_hint.setAlignment(Qt.AlignCenter)
        self.result_empty_hint.setVisible(False)
        table_layout.addWidget(self.result_empty_hint, 1)
        layout.addWidget(table_card, 1)

        # —— 岗位详情抽屉 ——
        self.result_drawer = SideDrawer(page, width=560)
        self.result_drawer.closed.connect(self.result_table.setFocus)
        panel_layout = self.result_drawer.panel_layout()

        drawer_head = QWidget()
        drawer_head_layout = QVBoxLayout(drawer_head)
        drawer_head_layout.setContentsMargins(20, 12, 16, 10)
        drawer_head_layout.setSpacing(10)
        drawer_title_row = QHBoxLayout()
        drawer_title_row.setContentsMargins(0, 0, 0, 0)
        drawer_title_row.addWidget(self._label("岗位详情", "section"))
        drawer_title_row.addStretch(1)
        close_button = QPushButton()
        close_button.setObjectName("resultIconButton")
        close_button.setIcon(_result_icon("close"))
        close_button.setIconSize(QSize(16, 16))
        close_button.setFixedSize(32, 32)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setToolTip("关闭详情（Esc）")
        close_button.clicked.connect(self.result_drawer.close_drawer)
        drawer_title_row.addWidget(close_button)
        drawer_head_layout.addLayout(drawer_title_row)

        marker_row = QHBoxLayout()
        marker_row.setContentsMargins(0, 0, 0, 0)
        marker_row.setSpacing(8)
        marker_row.addWidget(self._label("人工标记", "fieldLabel"))
        marker_row.addStretch(1)
        self.result_mark_group = QButtonGroup(self)
        self.result_mark_group.setExclusive(True)
        self.result_mark_buttons = {}
        for mark, icon_name, color, object_name in (
            ("好", "good", "#087A55", "resultMarkGood"),
            ("差", "bad", "#B42318", "resultMarkBad"),
            ("误杀", "warning", "#9A5B08", "resultMarkMistake"),
        ):
            button = QPushButton(mark)
            button.setObjectName(object_name)
            button.setIcon(_result_icon(icon_name, color))
            button.setIconSize(QSize(16, 16))
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"将当前岗位标记为「{mark}」")
            button.clicked.connect(
                lambda _checked=False, value=mark: self._mark_selected(value)
            )
            self.result_mark_group.addButton(button)
            self.result_mark_buttons[mark] = button
            marker_row.addWidget(button)
        drawer_head_layout.addLayout(marker_row)
        panel_layout.addWidget(drawer_head)
        panel_layout.addWidget(self._divider("softDivider"))

        selected_summary = QWidget()
        selected_summary_layout = QVBoxLayout(selected_summary)
        selected_summary_layout.setContentsMargins(20, 12, 20, 14)
        selected_summary_layout.setSpacing(8)
        self.result_selected_title = self._label(
            "选择岗位查看结果摘要", "resultTitle", wrap=True
        )
        selected_summary_layout.addWidget(self.result_selected_title)

        selected_status_row = QHBoxLayout()
        selected_status_row.setContentsMargins(0, 0, 0, 0)
        selected_status_row.setSpacing(8)
        self.result_status_chip = QFrame()
        self.result_status_chip.setObjectName("resultStatusChip")
        status_chip_layout = QHBoxLayout(self.result_status_chip)
        status_chip_layout.setContentsMargins(8, 4, 9, 4)
        status_chip_layout.setSpacing(6)
        self.result_status_icon = QLabel()
        self.result_status_icon.setFixedSize(14, 14)
        status_chip_layout.addWidget(self.result_status_icon)
        self.result_selected_status = QLabel("未选择")
        status_chip_layout.addWidget(self.result_selected_status)
        selected_status_row.addWidget(self.result_status_chip)
        self.result_selected_score = self._label("AI 匹配分 –", "scoreBadgeLow")
        selected_status_row.addWidget(self.result_selected_score)
        selected_status_row.addStretch(1)
        selected_summary_layout.addLayout(selected_status_row)

        self.result_selected_meta = QFrame()
        self.result_selected_meta.setObjectName("resultMetaPanel")
        self.result_selected_meta_layout = QGridLayout(self.result_selected_meta)
        self.result_selected_meta_layout.setContentsMargins(10, 8, 10, 8)
        self.result_selected_meta_layout.setHorizontalSpacing(14)
        self.result_selected_meta_layout.setVerticalSpacing(6)
        selected_summary_layout.addWidget(self.result_selected_meta)
        panel_layout.addWidget(selected_summary)
        panel_layout.addWidget(self._divider("softDivider"))

        self.result_detail = QScrollArea()
        self.result_detail.setObjectName("resultDetailScroll")
        self.result_detail.setWidgetResizable(True)
        self.result_detail.setFrameShape(QFrame.NoFrame)
        self.result_detail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_detail.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        detail_content = QWidget()
        detail_content.setObjectName("resultDetailContent")
        detail_content.setMinimumWidth(0)
        detail_content_layout = QVBoxLayout(detail_content)
        detail_content_layout.setContentsMargins(20, 16, 20, 22)
        detail_content_layout.setSpacing(0)
        detail_sections = QWidget()
        detail_sections.setMinimumWidth(0)
        self.result_detail_layout = QVBoxLayout(detail_sections)
        self.result_detail_layout.setContentsMargins(0, 0, 0, 0)
        self.result_detail_layout.setSpacing(0)
        detail_content_layout.addWidget(detail_sections)

        self.result_detail_toggle = QPushButton("查看评估证据与补充信息")
        self.result_detail_toggle.setObjectName("resultEvidenceToggle")
        self.result_detail_toggle.setIcon(_result_icon("file", "#52627A"))
        self.result_detail_toggle.setIconSize(QSize(16, 16))
        self.result_detail_toggle.setCheckable(True)
        self.result_detail_toggle.setEnabled(False)
        self.result_detail_toggle.setCursor(Qt.PointingHandCursor)
        self.result_detail_toggle.toggled.connect(self._toggle_result_detail)
        detail_content_layout.addWidget(self.result_detail_toggle)

        self.result_evidence = QWidget()
        self.result_evidence.setObjectName("resultEvidenceContent")
        self.result_evidence_layout = QVBoxLayout(self.result_evidence)
        self.result_evidence_layout.setContentsMargins(0, 12, 0, 0)
        self.result_evidence_layout.setSpacing(0)
        self.result_evidence.setVisible(False)
        detail_content_layout.addWidget(self.result_evidence)
        detail_content_layout.addStretch(1)
        self.result_detail.setWidget(detail_content)
        panel_layout.addWidget(self.result_detail, 1)
        return page

    def _add_result_section(self, parent_layout, title, icon_name="file"):
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 16)
        section_layout.setSpacing(8)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(_result_icon(icon_name, "#526C91").pixmap(16, 16))
        heading.addWidget(icon)
        heading.addWidget(self._label(title, "resultSectionTitle"))
        heading.addStretch(1)
        section_layout.addLayout(heading)

        body = QWidget()
        body.setMinimumWidth(0)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        section_layout.addWidget(body)
        parent_layout.addWidget(section)
        return body_layout

    def _result_text_label(self, text, name="resultBodyText"):
        label = QLabel(str(text))
        label.setObjectName(name)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _add_result_text_section(
        self, parent_layout, title, text, icon_name="file", surface=False,
    ):
        body_layout = self._add_result_section(parent_layout, title, icon_name)
        text_label = self._result_text_label(text)
        if surface:
            panel = QFrame()
            panel.setObjectName("resultQuote")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(12, 10, 12, 10)
            panel_layout.addWidget(text_label)
            body_layout.addWidget(panel)
        else:
            body_layout.addWidget(text_label)

    def _populate_result_detail(self, row):
        _clear_layout(self.result_detail_layout)
        _clear_layout(self.result_evidence_layout)
        self.result_evidence.setVisible(False)
        if str(row.get("历史有效评分", "")).lower() == "true":
            score = row_score(row)
            score_text = (
                f"沿用上次有效评分 {score:g}"
                if score is not None else "沿用上次有效评分"
            )
            warning = QFrame()
            warning.setObjectName("resultWarning")
            warning_layout = QHBoxLayout(warning)
            warning_layout.setContentsMargins(11, 9, 11, 9)
            warning_layout.setSpacing(8)
            icon = QLabel()
            icon.setFixedSize(16, 16)
            icon.setPixmap(_result_icon("warning", "#9A5B08").pixmap(16, 16))
            warning_layout.addWidget(icon)
            warning_layout.addWidget(self._result_text_label(
                f"本次评分失败，{score_text}", "resultWarningText"
            ), 1)
            self.result_detail_layout.addWidget(warning)
            self.result_detail_layout.addSpacing(14)

        greeting = str(row.get("打招呼语", "")).strip() or "暂无生成的招呼语"
        self._add_result_text_section(
            self.result_detail_layout, "打招呼语", greeting,
            "greeting", surface=True,
        )

        profile_text = str(row.get("岗位画像评估详情", "") or "").strip()
        profiles = None
        profile_fallback = ""
        if profile_text:
            try:
                parsed = json.loads(profile_text)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, list):
                profiles = [item for item in parsed if isinstance(item, dict)]
            elif parsed is None or not isinstance(parsed, list):
                profile_fallback = profile_text

        profile_layout = self._add_result_section(
            self.result_detail_layout, "岗位画像评估", "profile"
        )
        if profiles:
            for item in profiles:
                card = QFrame()
                card.setObjectName("resultProfile")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(12, 10, 12, 10)
                card_layout.setSpacing(7)
                name = str(item.get("profile_name") or item.get("profile_id") or "未命名画像")
                card_layout.addWidget(self._label(name, "resultProfileName", wrap=True))
                metrics = QHBoxLayout()
                metrics.setContentsMargins(0, 0, 0, 0)
                metrics.setSpacing(6)
                for label, key in (("岗位匹配", "score"), ("职能契合", "role_fit")):
                    value = item.get(key)
                    if value is None or not str(value).strip():
                        continue
                    metric = QLabel(f"{label}  {value}")
                    metric.setObjectName("resultMetric")
                    metrics.addWidget(metric)
                metrics.addStretch(1)
                if metrics.count() > 1:
                    card_layout.addLayout(metrics)
                reason = str(item.get("reason") or "").strip()
                if reason:
                    card_layout.addWidget(self._result_text_label(reason))
                profile_layout.addWidget(card)
        else:
            note = profile_fallback or str(
                row.get("AI匹配理由") or row.get("筛选原因") or ""
            ).strip()
            profile_layout.addWidget(self._result_text_label(
                note or "当前记录未生成岗位画像评估", "resultBodyText" if note else "muted"
            ))

        keyword = str(row.get("搜索来源关键词", "")).strip()
        if keyword:
            self._add_result_text_section(
                self.result_detail_layout, "搜索关键词", keyword, "search"
            )

        link = str(row.get("详情链接", "")).strip()
        if link.lower().startswith(("https://", "http://")):
            link_layout = self._add_result_section(
                self.result_detail_layout, "岗位链接", "link"
            )
            open_link = QPushButton("打开岗位详情")
            open_link.setObjectName("resultLinkButton")
            open_link.setIcon(_result_icon("link", "#2F5BEA"))
            open_link.setIconSize(QSize(15, 15))
            open_link.setCursor(Qt.PointingHandCursor)
            open_link.clicked.connect(
                lambda _checked=False, target=QUrl(link): QDesktopServices.openUrl(target)
            )
            link_layout.addWidget(open_link, 0, Qt.AlignLeft)

        info = []
        for key, label in (
            ("encryptJobId", "岗位 ID"), ("工作性质", "工作性质"),
            ("区域", "工作地点"), ("上班时间", "上班时间"),
            ("休息制度", "休息制度"), ("主岗位画像", "主岗位画像"),
            ("职业范围状态", "职业范围状态"), ("人工标记", "人工标记"),
            ("投递时间", "记录时间"), ("来源岗位画像", "来源岗位画像"),
        ):
            value = str(row.get(key, "")).strip()
            if value:
                info.append((label, value))
        if info:
            info_layout = self._add_result_section(
                self.result_detail_layout, "岗位信息", "list"
            )
            for label, value in info:
                info_row = QHBoxLayout()
                info_row.setContentsMargins(0, 0, 0, 0)
                info_row.setSpacing(12)
                key_label = self._label(label, "resultInfoKey")
                key_label.setFixedWidth(88)
                value_label = self._result_text_label(value, "resultInfoValue")
                info_row.addWidget(key_label, 0, Qt.AlignTop)
                info_row.addWidget(value_label, 1)
                info_layout.addLayout(info_row)

        self.result_detail_layout.addStretch(1)
        self._populate_result_evidence(row)

    def _populate_result_evidence(self, row):
        _clear_layout(self.result_evidence_layout)
        gaps = [part.strip() for part in str(row.get("硬性缺口", "") or "").replace("；", ";").split(";") if part.strip()]
        unverified = [part.strip() for part in str(row.get("未验证要求", "") or "").replace("；", ";").split(";") if part.strip()]
        if gaps or unverified:
            body_layout = self._add_result_section(
                self.result_evidence_layout, "缺口与待确认", "warning"
            )
            for title, values, object_name in (
                ("硬性缺口", gaps, "resultGapTag"),
                ("未验证要求", unverified, "resultWarnTag"),
            ):
                if not values:
                    continue
                label = self._label(title, "resultEvidenceLabel")
                body_layout.addWidget(label)
                for value in values:
                    tag = self._result_text_label(value, object_name)
                    body_layout.addWidget(tag)

        for key, label in (
            ("JD要求分层", "JD 要求分层"),
            ("加分项命中", "加分项命中"),
            ("加分项缺口", "加分项缺口"),
            ("简历证据", "简历证据"),
            ("筛选原因", "筛选结果"),
            ("技能匹配诊断", "标签诊断（仅供参考）"),
            ("本地预判", "本地预判（仅供参考）"),
        ):
            text = str(row.get(key, "")).strip()
            if text:
                self._add_result_text_section(
                    self.result_evidence_layout, label, text, "file"
                )

        if self.result_evidence_layout.count() == 0:
            empty = self._result_text_label("暂无其他评估证据", "muted")
            self.result_evidence_layout.addWidget(empty)

    def _open_result_drawer(self):
        """打开右侧岗位详情抽屉（遮罩悬浮，不挤压表格）。"""
        if self.result_table.currentRow() < 0:
            QMessageBox.information(self, "岗位详情", "请先在表格中选择一条投递记录。")
            return
        self._show_selected_result()
        self.result_drawer.open_drawer()

    def _toggle_result_advanced_filters(self, expanded):
        self.result_advanced_filters.setVisible(bool(expanded))
        self.result_advanced_toggle.setText(
            "收起筛选" if expanded else "更多筛选"
        )

    def _toggle_result_detail(self, expanded):
        self.result_evidence.setVisible(bool(expanded))
        self.result_detail_toggle.setText(
            "收起评估证据" if expanded else "查看评估证据与补充信息"
        )

    def _clear_selected_result(self):
        self.result_selected_title.setText("选择岗位查看结果摘要")
        self._set_meta_chips([])
        self.result_selected_status.setText("未选择")
        self.result_selected_status.setStyleSheet("")
        self.result_status_chip.setStyleSheet("")
        self.result_status_icon.setPixmap(
            _result_icon("file", "#7B8798", 14).pixmap(14, 14)
        )
        self.result_selected_score.setText("AI 匹配分 –")
        self._set_widget_style(self.result_selected_score, "scoreBadgeLow")
        self.result_detail_toggle.setChecked(False)
        self.result_detail_toggle.setEnabled(False)
        _clear_layout(self.result_detail_layout)
        _clear_layout(self.result_evidence_layout)
        self.result_evidence.setVisible(False)
        for button in self.result_mark_buttons.values():
            button.setChecked(False)

    def _set_meta_chips(self, chips):
        """重填岗位摘要元数据。"""
        layout = self.result_selected_meta_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not chips:
            hint = self._label(
                "暂无薪资、地区或投递时间", "muted", wrap=True
            )
            layout.addWidget(hint, 0, 0, 1, 2)
            return
        has_primary_meta = any(label != "投递" for label, _value, _icon in chips)
        next_column = 0
        for label, value, icon_name in chips:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(7)
            icon = QLabel()
            icon.setFixedSize(16, 16)
            icon.setPixmap(_result_icon(icon_name, "#68788F").pixmap(16, 16))
            item_layout.addWidget(icon, 0, Qt.AlignTop)
            text = self._result_text_label(f"{label}  {value}", "resultMetaValue")
            text.setToolTip(f"{label}：{value}")
            item_layout.addWidget(text, 1)
            if label == "投递":
                layout.addWidget(item, 1 if has_primary_meta else 0, 0, 1, 2)
            else:
                layout.addWidget(item, 0, next_column, 1, 1)
                next_column += 1

    def _show_selected_result(self):
        row_index = self.result_table.currentRow()
        if row_index < 0:
            self._clear_selected_result()
            return
        item = self.result_table.item(row_index, 0)
        source_index = item.data(ROW_ROLE) if item is not None else None
        if source_index is None or not (0 <= int(source_index) < len(self.result_rows)):
            self._clear_selected_result()
            return
        row = self.result_rows[int(source_index)]
        title = str(row.get("工作名称", "") or "未命名岗位").strip()
        company = str(row.get("公司", "")).strip()
        salary = str(row.get("工资", "")).strip()
        area = str(row.get("区域", "")).strip()
        delivery_time = str(row.get("投递时间", "")).strip()
        status, color, background = status_display(row.get("投递状态", ""))
        score = row_score(row)

        self.result_selected_title.setText(
            f"{title} · {company}" if company else title
        )
        self._set_meta_chips([
            (label, value, icon) for label, value, icon in (
                ("薪资", salary, "salary"),
                ("区域", area, "location"),
                ("投递", delivery_time, "time"),
            ) if value
        ])
        self.result_selected_status.setText(status)
        self.result_selected_status.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.result_status_chip.setStyleSheet(
            f"background-color: {background}; border: 1px solid {color}; "
            "border-radius: 6px;"
        )
        if color == "#05603A":
            status_icon = "good"
        elif color == "#93370D":
            status_icon = "warning"
        elif color == "#B42318":
            status_icon = "bad"
        else:
            status_icon = "file"
        self.result_status_icon.setPixmap(
            _result_icon(status_icon, color, 14).pixmap(14, 14)
        )
        self.result_selected_score.setText(
            f"AI 匹配分 {score:g}" if score is not None else "AI 匹配分 –"
        )
        self._set_widget_style(
            self.result_selected_score,
            "scoreBadge" if score is not None else "scoreBadgeLow",
        )
        current_mark = str(row.get("人工标记", "")).strip()
        for mark, button in self.result_mark_buttons.items():
            button.setChecked(mark == current_mark)
        self.result_detail_toggle.setChecked(False)
        self.result_detail_toggle.setEnabled(True)
        self._populate_result_detail(row)

    def _mark_selected(self, mark):
        row_index = self.result_table.currentRow()
        if row_index < 0:
            QMessageBox.information(self, "人工标记", "请先在表格中选择一行。")
            return
        item = self.result_table.item(row_index, 0)
        source_index = item.data(ROW_ROLE) if item is not None else None
        if source_index is None or not (0 <= int(source_index) < len(self.result_rows)):
            return
        row = self.result_rows[int(source_index)]
        job_id = str(row.get("encryptJobId", "")).strip()
        if not job_id:
            QMessageBox.warning(self, "人工标记", "该记录缺少岗位 ID，无法写回结果文件。")
            return
        path = BASE_DIR / read_env_dict().get("RESULT_FILE", "deliver_results.csv")
        updated = update_result_mark(path, job_id, mark)
        if not updated:
            QMessageBox.warning(self, "人工标记", "未在结果文件中找到该岗位记录。")
            return
        self.append_log(f"[面板] {time.strftime('%H:%M:%S')} 已把 {updated} 条记录（{job_id}）标记为「{mark}」")
        self.refresh_results()

    def _result_statuses(self, rows):
        statuses = []
        for row in rows:
            status = row.get("投递状态", "").strip()
            if status and status not in statuses:
                statuses.append(status)
        return sorted(statuses)

    def _apply_result_filter(self, *_args):
        rows = getattr(self, "result_all_rows", [])
        shown = filter_result_rows(
            rows,
            status=self.result_status_filter.currentText(),
            score_min=self.result_score_min.value(),
            score_max=self.result_score_max.value(),
            keyword=self.result_search.text(),
            review_only=self.result_review_only.isChecked(),
        )
        self._fill_result_table(shown)

    def _fill_result_table(self, shown):
        self._clear_selected_result()
        self.result_table.setSortingEnabled(False)
        self.result_table.setRowCount(0)
        self.result_rows = shown
        self.result_table.setRowCount(len(shown))
        for row_index, r in enumerate(shown):
            score = row_score(r)
            score_text = "" if score is None else f"{score:g}"
            values = [
                r.get("工作名称", ""), r.get("公司", ""), r.get("工资", ""),
                r.get("区域", ""), score_text, r.get("投递状态", ""),
                r.get("投递时间", ""), r.get("职业范围状态", ""),
            ]
            for column, value in enumerate(values):
                if column == 4:
                    item = ScoreTableItem(value)
                    item.setData(SCORE_ROLE, float(score) if score is not None else -1.0e9)
                    if r.get("历史有效评分") == "true":
                        item.setToolTip("上次有效评分；本次评分失败")
                else:
                    item = QTableWidgetItem(value)
                item.setData(ROW_ROLE, row_index)
                item.setToolTip(value)
                if column == 5:
                    label, color, bg = status_display(r.get("投递状态", ""))
                    item.setText(label)
                    item.setForeground(QBrush(QColor(color)))
                    item.setBackground(QBrush(QColor(bg)))
                    item.setToolTip(f"{r.get('投递状态', '')}（{label}）")
                self.result_table.setItem(row_index, column, item)
        self.result_table.setSortingEnabled(True)
        self.result_table.setVisible(bool(shown))
        self.result_empty_hint.setVisible(not shown)
        if shown:
            self.result_table.setCurrentCell(0, 0)
            self._show_selected_result()

    def refresh_results(self):
        path = BASE_DIR / read_env_dict().get("RESULT_FILE", "deliver_results.csv")
        rows = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
            except OSError:
                pass
        self.result_all_rows = deduplicate_result_rows(rows[::-1])  # 每个岗位展示最新有效结果
        for key, value in summarize_result_rows(self.result_all_rows).items():
            self.result_summary_values[key].setText(str(value))

        current = self.result_status_filter.currentText()
        self.result_status_filter.blockSignals(True)
        self.result_status_filter.clear()
        self.result_status_filter.addItem("全部")
        self.result_status_filter.addItems(self._result_statuses(self.result_all_rows))
        index = self.result_status_filter.findText(current)
        self.result_status_filter.setCurrentIndex(index if index >= 0 else 0)
        self.result_status_filter.blockSignals(False)

        self._apply_result_filter()
        filtered = len(self.result_rows)
        if filtered > 200:
            self._fill_result_table(self.result_rows[:200])
        self.result_total.setText(
            f"显示 {min(filtered, 200)} / {filtered} 个"
            + (f"（全部 {len(self.result_all_rows)} 个）"
               if filtered != len(self.result_all_rows) else "")
        )


# 延迟导入：desktop_panel 在共享工具函数定义完成后才导入本模块（避免循环导入）。
from desktop_panel import BASE_DIR, read_env_dict  # noqa: E402,F401
