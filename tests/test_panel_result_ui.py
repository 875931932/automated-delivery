import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
)

import desktop_panel
import panel_candidate_profile
import panel_result_page
from delivery_config import RESULT_FIELDS


class ResultDrawerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        with patch.object(desktop_panel.PanelApp, "_load_env"), \
                patch.object(desktop_panel.PanelApp, "refresh_results"), \
                patch.object(desktop_panel.PanelApp, "_restore_window_settings"), \
                patch.object(desktop_panel.PanelApp, "_save_window_settings"), \
                patch.object(
                    panel_candidate_profile.CandidateProfilePageMixin,
                    "_refresh_candidate_profile_view",
                ):
            return desktop_panel.PanelApp()

    def test_drawer_uses_one_scroll_area_and_renders_job_text_as_plain_text(self):
        panel = self._new_panel()
        try:
            row = {field: "" for field in RESULT_FIELDS}
            row.update({
                "encryptJobId": "job-1",
                "工作名称": "AI 应用开发实习生",
                "公司": "示例公司",
                "工资": "200-250元/天",
                "区域": "深圳 南山区",
                "AI匹配分数": "88",
                "投递状态": "dry_run",
                "人工标记": "好",
                "打招呼语": "<img src=x onerror=alert(1)>",
                "岗位画像评估详情": (
                    '[{"profile_name":"AI 应用方向","score":88,"role_fit":90,'
                    '"reason":"项目经验相关"}]'
                ),
                "简历证据": "熟悉 Python 与 RAG",
            })
            panel._fill_result_table([row])

            self.assertIsInstance(panel.result_detail, QScrollArea)
            self.assertEqual(panel.result_detail.findChildren(QTextBrowser), [])
            greeting = next(
                label for label in panel.result_detail.findChildren(QLabel)
                if label.objectName() == "resultBodyText"
                and label.text() == row["打招呼语"]
            )
            self.assertEqual(greeting.textFormat(), Qt.TextFormat.PlainText)
            self.assertTrue(greeting.wordWrap())
            self.assertTrue(panel.result_mark_buttons["好"].isChecked())

            panel.result_detail_toggle.click()
            self.assertFalse(panel.result_evidence.isHidden())
            evidence = [
                label.text() for label in panel.result_evidence.findChildren(QLabel)
            ]
            self.assertIn("熟悉 Python 与 RAG", evidence)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_manual_mark_buttons_keep_the_existing_save_action(self):
        panel = self._new_panel()
        try:
            for mark, button in panel.result_mark_buttons.items():
                with self.subTest(mark=mark), patch.object(panel, "_mark_selected") as save:
                    button.click()
                    save.assert_called_once_with(mark)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_drawer_actions_have_visible_icons(self):
        panel = self._new_panel()
        try:
            close_button = panel.result_drawer.findChild(
                QPushButton, "resultIconButton"
            )
            self.assertIsNotNone(close_button)
            buttons = [close_button, *panel.result_mark_buttons.values()]
            for button in buttons:
                with self.subTest(button=button.objectName()):
                    pixmap = button.icon().pixmap(button.iconSize())
                    self.assertFalse(pixmap.isNull())
                    image = pixmap.toImage()
                    self.assertTrue(any(
                        image.pixelColor(x, y).alpha() > 0
                        for x in range(image.width())
                        for y in range(image.height())
                    ))
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_link_column_keeps_its_job_after_sorting_and_filtering(self):
        panel = self._new_panel()
        rows = [{"工作名称": title, "详情链接": url, "AI匹配分数": score}
                for title, url, score in (
                    ("B job", "https://www.zhipin.com/job_detail/bbb.html", "70"),
                    ("A job", "https://jobs.zhaopin.com/AAA.htm", "90"),
                )]
        try:
            panel.runner.running = lambda: False
            panel._fill_result_table(rows)
            table = panel.result_table
            self.assertEqual(table.horizontalHeaderItem(panel_result_page.LINK_COLUMN).text(), "岗位链接")
            self.assertEqual(table.horizontalHeader().visualIndex(panel_result_page.LINK_COLUMN), 3)
            table.sortItems(4, Qt.DescendingOrder)
            with patch.object(panel_result_page, "open_result_job") as open_job, \
                    patch.object(panel_result_page, "read_env_dict", return_value={"KEEP_LOGIN": "true"}):
                for index in range(table.rowCount()):
                    title = table.item(index, 0).text()
                    expected = next(row for row in rows if row["工作名称"] == title)
                    button = table.cellWidget(index, panel_result_page.LINK_COLUMN).findChild(QPushButton)
                    self.assertTrue(button.isEnabled())
                    self.assertFalse(button.icon().isNull())
                    button.click()
                    open_job.assert_called_with(expected, {"KEEP_LOGIN": "true"})
                panel._fill_result_table([rows[0]])
                table.cellWidget(0, panel_result_page.LINK_COLUMN).findChild(QPushButton).click()
                open_job.assert_called_with(rows[0], {"KEEP_LOGIN": "true"})
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_missing_link_is_disabled_and_drawer_uses_project_opener(self):
        panel = self._new_panel()
        try:
            panel.runner.running = lambda: False
            panel._fill_result_table([{"工作名称": "No link"}])
            button = panel.result_table.cellWidget(0, panel_result_page.LINK_COLUMN).findChild(QPushButton)
            self.assertFalse(button.isEnabled())
            row = {"工作名称": "Job", "详情链接": "https://www.zhipin.com/job_detail/abc.html"}
            panel._fill_result_table([row])
            button = panel.result_detail.findChild(QPushButton, "resultLinkButton")
            with patch.object(panel_result_page, "open_result_job") as open_job, \
                    patch.object(panel_result_page, "read_env_dict", return_value={}):
                button.click()
                open_job.assert_called_once_with(row, {})
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_running_task_and_launch_failure_produce_actionable_messages(self):
        panel = self._new_panel()
        try:
            row = {"详情链接": "https://www.zhipin.com/job_detail/abc.html"}
            panel.runner.running = lambda: True
            with patch.object(panel_result_page, "open_result_job") as open_job, \
                    patch.object(panel_result_page.QMessageBox, "information") as message:
                panel._open_result_job(row)
                open_job.assert_not_called()
                self.assertIn("先结束任务", message.call_args.args[2])
            panel.runner.running = lambda: False
            with patch.object(panel_result_page, "open_result_job", side_effect=OSError("fixture failure")), \
                    patch.object(panel_result_page, "read_env_dict", return_value={}), \
                    patch.object(panel_result_page.QMessageBox, "warning") as message:
                panel._open_result_job(row)
                self.assertIn("fixture failure", message.call_args.args[2])
        finally:
            panel.runner.running = lambda: False
            panel.close()
            panel.deleteLater()
            self.app.processEvents()


class ResultManagementUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'results.csv'
        self.enterContext(patch.object(desktop_panel.PanelApp, '_save_window_settings'))
        self.enterContext(patch.object(
            panel_result_page, 'read_env_dict', return_value={'RESULT_FILE': str(self.path)},
        ))
        self.panel = ResultDrawerUiTests._new_panel(self)
        self.panel.runner.running = lambda: False
        self.addCleanup(self.close_panel)
        self.log = self.enterContext(patch.object(self.panel, 'append_log'))
        self.confirm = self.enterContext(patch.object(
            panel_result_page.QMessageBox, 'question', return_value=panel_result_page.QMessageBox.Yes,
        ))
        self.warning = self.enterContext(patch.object(panel_result_page.QMessageBox, 'warning'))
        self.info = self.enterContext(patch.object(panel_result_page.QMessageBox, 'information'))

    def close_panel(self):
        self.panel.runner.running = lambda: False
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def row(self, job_id, title='AI job', **values):
        row = dict.fromkeys(RESULT_FIELDS, '')
        row.update(encryptJobId=job_id, 工作名称=title, 投递状态='dry_run', AI匹配分数='80')
        row.update(values)
        return row

    def load_rows(self, rows):
        with self.path.open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        self.panel.refresh_results()

    def checkbox(self, index):
        return self.panel.result_table.cellWidget(index, panel_result_page.CHECK_COLUMN).findChild(QCheckBox)

    def test_filter_sort_and_bulk_delete_only_checked_jobs_and_their_histories(self):
        self.load_rows([
            self.row('a', 'A target', AI匹配分数='60'),
            self.row('keep', 'Hidden job'),
            self.row('a', 'A target', AI匹配分数='', 投递状态='match_failed'),
            self.row('b', 'B target', AI匹配分数='90'),
            self.row('c', 'C target', AI匹配分数='75'),
        ])
        original = self.path.read_bytes()
        self.panel.result_search.setText('target')
        self.panel.result_table.sortItems(0, Qt.AscendingOrder)
        self.checkbox(0).click()
        self.checkbox(1).click()
        self.panel.result_table.sortItems(4, Qt.AscendingOrder)
        self.assertEqual(self.panel.result_selection_count.text(), '已选 2 项')
        self.panel.result_delete_selected.click()
        self.assertIn('所选 2 项', self.confirm.call_args.args[2])
        rows, _ = panel_result_page.read_result_snapshot(self.path)
        self.assertEqual([r['encryptJobId'] for r in rows], ['keep', 'c'])
        self.assertEqual(self.panel.result_table.rowCount(), 1)
        self.assertEqual(self.panel.result_table.item(0, 0).text(), 'C target')
        self.assertEqual(self.panel.result_selection_count.text(), '已选 0 项')
        self.assertEqual(next(self.path.parent.glob('*.bak')).read_bytes(), original)
        self.panel.result_search.clear()
        self.panel.refresh_results()
        self.assertEqual(self.panel.result_table.rowCount(), 2)
        self.warning.assert_not_called()

    def test_select_page_partial_clear_and_filter_change(self):
        self.load_rows([self.row(str(i), f'Job {i}') for i in range(3)])
        self.checkbox(0).click()
        self.assertEqual(self.panel.result_select_page.checkState(), Qt.PartiallyChecked)
        self.panel.result_select_page.click()
        self.assertTrue(all(self.checkbox(i).isChecked() for i in range(3)))
        self.assertEqual(self.panel.result_select_page.checkState(), Qt.Checked)
        self.panel.result_clear_selection.click()
        self.assertFalse(any(self.checkbox(i).isChecked() for i in range(3)))
        self.assertFalse(self.panel.result_delete_selected.isEnabled())
        self.panel.result_select_page.click()
        self.panel.result_search.setText('Job 1')
        self.assertEqual(self.panel.result_checked_rows, set())
        self.assertFalse(self.checkbox(0).isChecked())
        self.assertEqual(self.panel.result_total.text(), '显示 1–1 / 1 个')

    def test_pagination_limits_selection_and_keeps_filter_counts_consistent(self):
        self.load_rows([self.row(str(i), f'Job {i}') for i in range(205)])
        self.assertEqual(self.panel.result_table.rowCount(), 200)
        self.panel.result_select_page.click()
        self.assertEqual(len(self.panel.result_checked_rows), 200)
        self.panel.result_next_page.click()
        self.assertEqual(self.panel.result_table.rowCount(), 5)
        self.assertEqual(self.panel.result_checked_rows, set())
        self.assertEqual(self.panel.result_total.text(), '显示 201–205 / 205 个')
        self.panel.result_select_page.click()
        self.panel.result_delete_selected.click()
        self.assertEqual(len(panel_result_page.read_result_snapshot(self.path)[0]), 200)
        self.assertEqual(self.panel.result_page_index, 0)
        self.assertFalse(self.panel.result_next_page.isEnabled())
        self.panel.result_search.setText('missing')
        self.assertEqual(self.panel.result_table.rowCount(), 0)
        self.assertEqual(self.panel.result_page_label.text(), '第 0 / 0 页')
        self.assertFalse(self.panel.result_select_page.isEnabled())
        self.assertIn('筛选条件', self.panel.result_empty_hint.text())

    def test_row_delete_stays_bound_after_sorting_including_missing_ids(self):
        self.load_rows([self.row('', 'Z record'), self.row('', 'A record')])
        self.panel.result_table.sortItems(0, Qt.AscendingOrder)
        button = self.panel.result_table.cellWidget(0, panel_result_page.DELETE_COLUMN).findChild(QPushButton)
        self.assertFalse(button.icon().isNull())
        button.click()
        rows, _ = panel_result_page.read_result_snapshot(self.path)
        self.assertEqual([r['工作名称'] for r in rows], ['Z record'])
        self.assertEqual(self.panel.result_table.rowCount(), 1)

    def test_cancel_and_running_task_do_not_touch_file(self):
        self.load_rows([self.row('a')])
        original = self.path.read_bytes()
        self.checkbox(0).click()
        self.confirm.return_value = panel_result_page.QMessageBox.No
        self.panel.result_delete_selected.click()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.checkbox(0).isChecked())
        self.confirm.reset_mock()
        self.panel.runner.running = lambda: True
        self.panel.result_delete_selected.click()
        self.confirm.assert_not_called()
        self.assertIn('先结束任务', self.info.call_args.args[2])
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_deleting_final_record_refreshes_summary_and_empty_state(self):
        self.load_rows([self.row('last', 投递状态='delivered')])
        self.panel.result_status_filter.setCurrentText('delivered')
        self.panel.result_select_page.click()
        self.panel.result_delete_selected.click()
        self.assertEqual(panel_result_page.read_result_snapshot(self.path)[0], [])
        self.assertEqual(self.panel.result_table.rowCount(), 0)
        self.assertEqual(self.panel.result_summary_values['total'].text(), '0')
        self.assertEqual(self.panel.result_summary_values['delivered'].text(), '0')
        self.assertEqual(self.panel.result_status_filter.currentText(), '全部')
        self.assertEqual(self.panel.result_selection_count.text(), '已选 0 项')
        self.assertFalse(self.panel.result_delete_selected.isEnabled())
        self.assertFalse(self.panel.result_select_page.isEnabled())
        self.assertFalse(self.panel.result_previous_page.isEnabled())
        self.assertFalse(self.panel.result_next_page.isEnabled())
        self.assertEqual(self.panel.result_total.text(), '显示 0–0 / 0 个')

    def test_task_starting_while_confirming_also_blocks_deletion(self):
        self.load_rows([self.row('a')])
        self.checkbox(0).click()
        def start_task(*args):
            self.panel.runner.running = lambda: True
            return panel_result_page.QMessageBox.Yes
        self.confirm.side_effect = start_task
        with patch.object(panel_result_page, 'delete_result_rows') as delete:
            self.panel.result_delete_selected.click()
            delete.assert_not_called()
        self.assertIn('先结束任务', self.info.call_args.args[2])

    def test_changed_file_or_write_failure_keeps_selection_for_review(self):
        self.load_rows([self.row('a')])
        self.checkbox(0).click()
        with patch.object(panel_result_page, 'delete_result_rows', side_effect=PermissionError('locked')):
            self.panel.result_delete_selected.click()
        self.assertIn('locked', self.warning.call_args.args[2])
        self.assertTrue(self.checkbox(0).isChecked())
        with self.path.open('a', encoding='utf-8-sig', newline='') as output:
            csv.DictWriter(output, fieldnames=RESULT_FIELDS).writerow(self.row('new'))
        changed = self.path.read_bytes()
        self.panel.result_delete_selected.click()
        self.assertIn('已变化', self.warning.call_args.args[2])
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
