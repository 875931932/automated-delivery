# -*- coding: utf-8 -*-
"""投递结果页（PanelApp mixin）：排序表格、筛选条、彩色状态、详情 HTML、人工标记。"""
import csv
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from panel_result_logic import (
    build_result_detail_html,
    deduplicate_result_rows,
    filter_result_rows,
    row_score,
    status_display,
    update_result_mark,
)

SCORE_ROLE = Qt.UserRole       # 数字分数（排序用）
ROW_ROLE = Qt.UserRole + 1     # 对应 self.result_rows 下标


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
        layout.setSpacing(12)

        # 筛选条
        filter_card, filter_card_layout = self._card((16, 12, 16, 12), 0)
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(self._label("状态", "fieldLabel"))
        self.result_status_filter = QComboBox()
        self.result_status_filter.addItem("全部")
        self.result_status_filter.setMinimumWidth(120)
        self.result_status_filter.currentIndexChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_status_filter)
        filter_layout.addWidget(self._label("分数", "fieldLabel"))
        self.result_score_min = QSpinBox()
        self.result_score_min.setRange(0, 100)
        self.result_score_min.setValue(0)
        self.result_score_min.setPrefix("≥")
        self.result_score_min.setFixedWidth(78)
        self.result_score_min.valueChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_score_min)
        self.result_score_max = QSpinBox()
        self.result_score_max.setRange(0, 100)
        self.result_score_max.setValue(100)
        self.result_score_max.setPrefix("≤")
        self.result_score_max.setFixedWidth(78)
        self.result_score_max.valueChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_score_max)
        self.result_search = QLineEdit()
        self.result_search.setPlaceholderText("搜索工作名称 / 公司")
        self.result_search.setClearButtonEnabled(True)
        self.result_search.textChanged.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_search, 1)
        self.result_review_only = QCheckBox("只看待复核")
        self.result_review_only.setToolTip("只看职业范围状态为 scope_review 的记录")
        self.result_review_only.setCursor(Qt.PointingHandCursor)
        self.result_review_only.toggled.connect(self._apply_result_filter)
        filter_layout.addWidget(self.result_review_only)
        filter_layout.addStretch(1)
        self.result_total = self._label("")
        filter_layout.addWidget(self.result_total)
        refresh = QPushButton("刷新")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh_results)
        filter_layout.addWidget(refresh)
        filter_card_layout.addWidget(filter_bar)
        layout.addWidget(filter_card)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(14)

        table_card, table_layout = self._card((0, 0, 0, 0), 0)
        table_head = QWidget()
        table_head_layout = QHBoxLayout(table_head)
        table_head_layout.setContentsMargins(18, 13, 18, 13)
        table_head_layout.addWidget(self._label("投递记录", "section"))
        table_head_layout.addStretch(1)
        table_layout.addWidget(table_head)
        table_layout.addWidget(self._divider("divider"))
        self.result_table = QTableWidget(0, 10)
        self.result_table.setHorizontalHeaderLabels([
            "工作名称", "公司", "工作性质", "工资", "区域",
            "AI匹配分数", "主岗位画像", "职业范围状态", "投递状态", "投递时间",
        ])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(38)
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
        for index, width in enumerate([220, 145, 80, 95, 110, 90, 150, 100, 115, 150]):
            self.result_table.setColumnWidth(index, width)
        self.result_table.itemSelectionChanged.connect(self._show_selected_result)
        table_layout.addWidget(self.result_table, 1)
        self.result_empty_hint = self._label(
            "暂无投递记录。完成候选人画像与岗位画像后，点击右上角「启动任务」，"
            "筛选与投递结果会显示在这里。", "muted", wrap=True
        )
        self.result_empty_hint.setAlignment(Qt.AlignCenter)
        self.result_empty_hint.setVisible(False)
        table_layout.addWidget(self.result_empty_hint, 1)
        splitter.addWidget(table_card)

        detail_card, detail_layout = self._card((0, 0, 0, 0), 0)
        detail_head = QWidget()
        detail_head_layout = QHBoxLayout(detail_head)
        detail_head_layout.setContentsMargins(18, 13, 18, 13)
        detail_head_layout.setSpacing(8)
        detail_head_layout.addWidget(self._label("岗位详情", "section"))
        detail_head_layout.addStretch(1)
        detail_head_layout.addWidget(self._label("人工标记", "fieldLabel"))
        for mark in ("好", "差", "误杀"):
            button = QPushButton(f"标记：{mark}")
            button.setObjectName("soft")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, m=mark: self._mark_selected(m))
            detail_head_layout.addWidget(button)
        detail_layout.addWidget(detail_head)
        detail_layout.addWidget(self._divider("divider"))
        self.result_detail = QTextBrowser()
        self.result_detail.setObjectName("detailView")
        self.result_detail.setOpenExternalLinks(False)
        self.result_detail.setPlaceholderText("选择上方表格中的岗位，查看完整评估信息。")
        self.result_detail.anchorClicked.connect(
            lambda url: QDesktopServices.openUrl(url if url.scheme() else QUrl("https://" + url.toString()))
        )
        detail_layout.addWidget(self.result_detail, 1)
        splitter.addWidget(detail_card)
        splitter.setSizes([520, 260])
        layout.addWidget(splitter, 1)
        return page

    def _show_selected_result(self):
        row_index = self.result_table.currentRow()
        if row_index < 0:
            return
        item = self.result_table.item(row_index, 0)
        source_index = item.data(ROW_ROLE) if item is not None else None
        if source_index is None or not (0 <= int(source_index) < len(self.result_rows)):
            return
        row = self.result_rows[int(source_index)]
        self.result_detail.setHtml(build_result_detail_html(row))

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
        self.result_table.setSortingEnabled(False)
        self.result_table.setRowCount(0)
        self.result_rows = shown
        self.result_table.setRowCount(len(shown))
        for row_index, r in enumerate(shown):
            score = row_score(r)
            score_text = "" if score is None else f"{score:g}"
            values = [
                r.get("工作名称", ""), r.get("公司", ""), r.get("工作性质", ""),
                r.get("工资", ""), r.get("区域", ""), score_text,
                r.get("主岗位画像", ""), r.get("职业范围状态", ""),
                r.get("投递状态", ""), r.get("投递时间", ""),
            ]
            for column, value in enumerate(values):
                if column == 5:
                    item = ScoreTableItem(value)
                    item.setData(SCORE_ROLE, float(score) if score is not None else -1.0e9)
                    if r.get("历史有效评分") == "true":
                        item.setToolTip("上次有效评分；本次评分失败")
                else:
                    item = QTableWidgetItem(value)
                item.setData(ROW_ROLE, row_index)
                item.setToolTip(value)
                if column == 8:
                    label, color, bg = status_display(r.get("投递状态", ""))
                    item.setText(label)
                    item.setForeground(QBrush(QColor(color)))
                    item.setBackground(QBrush(QColor(bg)))
                    item.setToolTip(f"{r.get('投递状态', '')}（{label}）")
                self.result_table.setItem(row_index, column, item)
        self.result_table.setSortingEnabled(True)
        self.result_table.setVisible(bool(shown))
        self.result_empty_hint.setVisible(not shown)

    def refresh_results(self):
        self.result_detail.clear()
        path = BASE_DIR / read_env_dict().get("RESULT_FILE", "deliver_results.csv")
        rows = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
            except OSError:
                pass
        self.result_all_rows = deduplicate_result_rows(rows[::-1])  # 每个岗位展示最新有效结果

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
            f"共 {len(self.result_all_rows)} 个岗位 · 筛选命中 {filtered} 个（显示最近 200 个）"
        )


# 延迟导入：desktop_panel 在共享工具函数定义完成后才导入本模块（避免循环导入）。
from desktop_panel import BASE_DIR, read_env_dict  # noqa: E402,F401
