import os
import subprocess
import tempfile
import threading
import unittest
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import panel_runner
import process_runtime
from auto_deliver import AutoDeliverer
from boss_spider import BossDP


@unittest.skipUnless(os.name == 'nt', 'Windows process visibility')
class QuietProcessTests(unittest.TestCase):
    def test_dependency_subprocesses_default_to_hidden_and_keep_explicit_console(self):
        calls = []

        class Popen:
            def __init__(self, *args, **kwargs):
                calls.append(kwargs)

        with patch.object(subprocess, 'Popen', Popen):
            process_runtime.configure_quiet_processes()
            wrapper = subprocess.Popen
            process_runtime.configure_quiet_processes()
            self.assertIs(wrapper, subprocess.Popen)
            subprocess.Popen('ver', shell=True)
            subprocess.Popen(['debug'], creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.assertTrue(calls[0]['creationflags'] & subprocess.CREATE_NO_WINDOW)
        self.assertEqual(calls[1]['creationflags'], subprocess.CREATE_NEW_CONSOLE)

    def test_worker_start_has_no_console_and_uses_python_with_output_pipes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            python = root / 'python.exe'
            python.touch()
            process = SimpleNamespace(poll=lambda: None, stdout=[])
            with patch.object(panel_runner, 'BASE_DIR', root), \
                    patch.object(panel_runner.sys, 'executable', str(root / 'pythonw.exe')), \
                    patch.object(panel_runner, 'is_frozen', return_value=False), \
                    patch.object(panel_runner.subprocess, 'Popen', return_value=process) as popen, \
                    patch.object(panel_runner.threading, 'Thread'):
                panel_runner.TaskRunner().start()
            self.assertEqual(popen.call_args.args[0][0], str(python))
            self.assertTrue(popen.call_args.kwargs.get('creationflags', 0)
                            & subprocess.CREATE_NO_WINDOW)
            self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.PIPE)

    def test_worker_stop_and_browser_cleanup_have_no_console(self):
        runner = panel_runner.TaskRunner()
        runner.proc = SimpleNamespace(poll=lambda: None, pid=123)
        with patch('subprocess.run') as run:
            runner.stop()
        self.assertTrue(run.call_args.kwargs.get('creationflags', 0)
                        & subprocess.CREATE_NO_WINDOW)
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='')) as run:
            BossDP._kill_stale_chrome('test-profile', 'chrome.exe')
        self.assertTrue(run.call_args.kwargs.get('creationflags', 0)
                        & subprocess.CREATE_NO_WINDOW)


class BackgroundBrowserTests(unittest.TestCase):
    def make_deliverer(self):
        deliverer = AutoDeliverer.__new__(AutoDeliverer)
        deliverer.page = Mock()
        deliverer.browser_lock = threading.RLock()
        deliverer.stop_event = threading.Event()
        deliverer.browser_background = True
        deliverer._browser_headless = True
        deliverer._browser_attention_url = None

        def switch(headless, url=None):
            deliverer._browser_headless = headless
            return True

        deliverer._switch_browser_mode = Mock(side_effect=switch)
        return deliverer

    def test_valid_session_remains_headless_without_showing_login(self):
        deliverer = self.make_deliverer()
        deliverer.page.ele.return_value = object()
        with patch('boss_spider.time.sleep'):
            deliverer.wait_login(20)
        deliverer._switch_browser_mode.assert_not_called()

    def test_expired_session_switches_once_each_way_and_rechecks_login(self):
        deliverer = self.make_deliverer()
        deliverer.page.ele.side_effect = [None] * 7 + [object(), object()]
        with patch('boss_spider.time.sleep'), \
                patch('boss_spider.time.monotonic', side_effect=count(0, 3)):
            deliverer.wait_login(60)
        self.assertEqual([c.args[0] for c in deliverer._switch_browser_mode.call_args_list],
                         [False, True])
        self.assertEqual(deliverer.page.ele.call_count, 9)
        deliverer.page.get.assert_called_once()

    def test_login_timeout_stops_instead_of_proceeding_without_authentication(self):
        deliverer = self.make_deliverer()
        deliverer.page.ele.return_value = None
        with patch('boss_spider.time.sleep'), \
                patch('boss_spider.time.monotonic', side_effect=count(0, 3)):
            with self.assertRaises(TimeoutError):
                deliverer.wait_login(3)

    def test_visible_browser_option_leaves_window_alone(self):
        deliverer = self.make_deliverer()
        deliverer.browser_background = False
        deliverer._browser_headless = False
        deliverer.page.ele.side_effect = [None, None, object()]
        with patch('boss_spider.time.sleep'), \
                patch('boss_spider.time.monotonic', side_effect=count(0, 3)):
            deliverer.wait_login(20)
        deliverer._switch_browser_mode.assert_not_called()

    def test_incompatible_headless_session_falls_back_without_repeated_switching(self):
        deliverer = self.make_deliverer()
        deliverer.page.ele.side_effect = [None, None, object(), None, None, object()]
        with patch('boss_spider.time.sleep'), \
                patch('boss_spider.time.monotonic', side_effect=count(0, 3)):
            deliverer.wait_login(60)
        self.assertEqual([c.args[0] for c in deliverer._switch_browser_mode.call_args_list],
                         [False, True, False])
        self.assertFalse(deliverer._browser_headless)
        self.assertTrue(deliverer._background_unavailable)
        deliverer._switch_browser_mode.reset_mock()
        deliverer.page.ele.side_effect = [object()]
        with patch('boss_spider.time.sleep'):
            deliverer.wait_login(20)
        deliverer._switch_browser_mode.assert_not_called()

    def test_switch_preserves_profile_and_cookies_and_discards_old_detail_tab(self):
        deliverer = self.make_deliverer()
        del deliverer._switch_browser_mode
        old_page = deliverer.page
        cookies = [{'name': 'session', 'value': 'local-test', 'domain': '127.0.0.1'}]
        old_page.run_cdp.return_value = {'cookies': cookies}
        deliverer._browser_profile_dir = 'isolated-test-profile'
        deliverer._detail_tab = Mock()
        new_page = Mock()
        deliverer._open_browser = Mock(return_value=new_page)
        deliverer._switch_browser_mode(False, url='about:blank')
        old_page.quit.assert_called_once_with(timeout=5)
        deliverer._open_browser.assert_called_once_with(False)
        self.assertEqual(deliverer._browser_profile_dir, 'isolated-test-profile')
        new_page.browser.set.cookies.assert_called_once_with(cookies)
        new_page.get.assert_called_once_with('about:blank')
        self.assertIs(deliverer.page, new_page)
        self.assertIsNone(deliverer._detail_tab)

    def test_cookie_snapshot_failure_does_not_close_active_browser(self):
        deliverer = self.make_deliverer()
        del deliverer._switch_browser_mode
        deliverer.page.run_cdp.side_effect = RuntimeError('disconnected')
        with self.assertRaises(RuntimeError):
            deliverer._switch_browser_mode(False)
        deliverer.page.quit.assert_not_called()

    def test_heartbeat_only_signals_verification_without_switching_browser(self):
        deliverer = self.make_deliverer()
        deliverer._session_lock = threading.RLock()
        url = 'https://www.zhipin.com/web/common/security-check.html'
        deliverer.page.run_cdp.return_value = {'targetInfo': {'url': url}}
        deliverer._heartbeat_once()
        self.assertEqual(deliverer._browser_attention_url, url)
        deliverer._switch_browser_mode.assert_not_called()
        deliverer.page.get.assert_not_called()

    def test_heartbeat_does_not_touch_interactive_login(self):
        deliverer = self.make_deliverer()
        deliverer._login_waiting = True
        deliverer._heartbeat_once()
        deliverer.page.run_cdp.assert_not_called()

    def test_query_pipeline_does_not_swallow_login_timeout(self):
        deliverer = self.make_deliverer()
        deliverer.cfg = {'test_limit': 1, 'deliver_max_pages': 1}
        deliverer.matching_context = {
            'allocations': [{'keyword': 'test', 'pages': [1], 'profile_ids': []}],
        }
        deliverer.api_job_list = Mock(side_effect=TimeoutError('login timed out'))
        with self.assertRaises(TimeoutError):
            deliverer._run_profiled_pipeline()
        deliverer.api_job_list.assert_called_once()


if __name__ == '__main__':
    unittest.main()
