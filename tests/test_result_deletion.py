import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from panel_result_logic import delete_result_rows, read_result_snapshot


class ResultDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'results.csv'
        self.fields = ['encryptJobId', '工作名称', '平台', '投递状态', '自定义列']

    def write_rows(self, rows):
        with self.path.open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows(rows)
        return read_result_snapshot(self.path)

    def row(self, job_id='job-1', **values):
        row = dict.fromkeys(self.fields, '')
        row.update(encryptJobId=job_id, 工作名称='AI 实习生', 平台='BOSS 直聘')
        row.update(values)
        return row

    def test_deletes_all_selected_job_histories_and_preserves_other_platforms(self):
        rows, digest = self.write_rows([
            self.row(投递状态='dry_run'), self.row('job-2'),
            self.row('zhaopin:job-1', 平台='智联招聘'),
            self.row(投递状态='match_failed'), self.row('job-3'),
        ])
        original = self.path.read_bytes()
        removed, backup = delete_result_rows(
            self.path, [rows[3], rows[4]], expected_digest=digest,
        )
        self.assertEqual(removed, 3)
        self.assertEqual(Path(backup).read_bytes(), original)
        kept, _ = read_result_snapshot(self.path)
        self.assertEqual([r['encryptJobId'] for r in kept], ['job-2', 'zhaopin:job-1'])

    def test_preserves_unknown_columns_and_multiline_quoted_values(self):
        custom = '包含逗号, 引号' + chr(34) + '和\n多行内容'
        rows, _ = self.write_rows([self.row(), self.row('keep', 自定义列=custom)])
        delete_result_rows(self.path, [rows[0]])
        with self.path.open(encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source)
            self.assertEqual(reader.fieldnames, self.fields)
            self.assertEqual(list(reader), [rows[1]])

    def test_missing_id_deletes_only_selected_count_of_exact_matches(self):
        rows, digest = self.write_rows([
            self.row('', 工作名称='A'), self.row('', 工作名称='B'),
            self.row('', 工作名称='A'), self.row('keep', 工作名称='A'),
        ])
        removed, _ = delete_result_rows(self.path, [rows[0]], expected_digest=digest)
        self.assertEqual(removed, 1)
        kept, _ = read_result_snapshot(self.path)
        self.assertEqual(kept, rows[1:])
        removed, _ = delete_result_rows(self.path, kept[:2])
        self.assertEqual(removed, 2)
        self.assertEqual(read_result_snapshot(self.path)[0], [rows[3]])

    def test_incomplete_idless_selection_fails_without_writing(self):
        self.write_rows([self.row('')])
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '内容不完整'):
            delete_result_rows(self.path, [{'encryptJobId': ''}])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_empty_or_missing_selection_leaves_file_and_directory_untouched(self):
        self.write_rows([self.row()])
        original = self.path.read_bytes()
        for selected in ([], [self.row('missing')], [self.row('', 工作名称='missing')]):
            with self.subTest(selected=selected):
                self.assertEqual(delete_result_rows(self.path, selected), (0, None))
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_last_record_deletion_keeps_header(self):
        rows, _ = self.write_rows([self.row()])
        self.assertEqual(delete_result_rows(self.path, rows)[0], 1)
        with self.path.open(encoding='utf-8-sig', newline='') as source:
            self.assertEqual(list(csv.reader(source)), [self.fields])

    def test_changed_snapshot_is_rejected_without_backup(self):
        rows, digest = self.write_rows([self.row()])
        self.write_rows([*rows, self.row('new')])
        current = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '已变化'):
            delete_result_rows(self.path, rows, expected_digest=digest)
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_replace_failure_preserves_original_and_backup_and_cleans_temp(self):
        rows, _ = self.write_rows([self.row(), self.row('keep')])
        original = self.path.read_bytes()
        with patch('panel_result_logic.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                delete_result_rows(self.path, [rows[0]])
        self.assertEqual(self.path.read_bytes(), original)
        backups = list(self.path.parent.glob('*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_backup_failure_keeps_original(self):
        rows, _ = self.write_rows([self.row()])
        original = self.path.read_bytes()
        with patch('panel_result_logic.tempfile.NamedTemporaryFile', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                delete_result_rows(self.path, rows)
        self.assertEqual(self.path.read_bytes(), original)

    def test_change_during_write_is_preserved_and_temp_is_removed(self):
        rows, _ = self.write_rows([self.row(), self.row('keep')])
        original = self.path.read_bytes()
        flushes = 0

        def append_new_result(_descriptor):
            nonlocal flushes
            flushes += 1
            if flushes == 2:
                with self.path.open('a', encoding='utf-8-sig', newline='') as output:
                    csv.DictWriter(output, fieldnames=self.fields).writerow(self.row('new'))

        with patch('panel_result_logic.os.fsync', side_effect=append_new_result):
            with self.assertRaisesRegex(ValueError, '删除期间发生变化'):
                delete_result_rows(self.path, [rows[0]])
        self.assertEqual(
            [row['encryptJobId'] for row in read_result_snapshot(self.path)[0]],
            ['job-1', 'keep', 'new'],
        )
        self.assertEqual(next(self.path.parent.glob('*.bak')).read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_repeated_deletions_create_distinct_backups(self):
        rows, _ = self.write_rows([self.row(), self.row('other')])
        _, first = delete_result_rows(self.path, [rows[0]])
        _, second = delete_result_rows(self.path, [rows[1]])
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).is_file())
        self.assertTrue(Path(second).is_file())

    def test_malformed_rows_fail_closed(self):
        self.path.write_text('encryptJobId,title\njob-1,a,extra\n', encoding='utf-8-sig')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '列结构异常'):
            delete_result_rows(self.path, [{'encryptJobId': 'job-1'}])
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
