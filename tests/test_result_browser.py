import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import result_browser
from job_platforms import PLATFORM_LABELS, platform_profile_dir


class ResultBrowserTests(unittest.TestCase):
    def test_legacy_boss_link_keeps_native_identity_and_project_profile(self):
        identity = result_browser.result_job_target({
            "详情链接": "https://www.zhipin.com/job_detail/abc123.html?lid=fixture",
        })
        self.assertEqual(identity.platform, "boss")
        self.assertEqual(identity.key, "abc123")
        self.assertEqual(platform_profile_dir("boss"),
                         Path.home() / ".boss-zhipin-scraper" / "chrome-profile")

    def test_platform_is_inferred_from_official_link_and_checked_against_saved_value(self):
        for platform, url in (
            ("zhilian", "https://jobs.zhaopin.com/ABC123.htm"),
            ("liepin", "https://www.liepin.com/job/123.shtml"),
        ):
            with self.subTest(platform=platform):
                row = {"详情链接": url, "平台": PLATFORM_LABELS[platform]}
                self.assertEqual(result_browser.result_job_target(row).platform, platform)
                self.assertEqual(result_browser.result_job_target({"详情链接": url}).platform, platform)
                row["平台"] = "BOSS 直聘"
                with self.assertRaisesRegex(ValueError, "平台不一致"):
                    result_browser.result_job_target(row)

    def test_invalid_links_never_start_a_browser(self):
        for url in ("", "file:///C:/test.html", "javascript:alert(1)",
                    "https://www.zhipin.com.evil.test/job_detail/abc.html",
                    "https://www.zhipin.com/job_detail/abc.html#bad\nargument",
                    "https://www.zhipin.com/job_detail/"):
            with self.subTest(url=url), patch.object(result_browser.subprocess, "Popen") as popen:
                with self.assertRaises(ValueError):
                    result_browser.open_result_job({"详情链接": url}, {})
                popen.assert_not_called()

    def test_opens_configured_project_browser_with_platform_profile_and_saved_ua(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "project profile"
            profile.mkdir()
            (profile / "user_agent.txt").write_text("fixture user agent", encoding="utf-8")
            executable = Path(temp) / "custom browser.exe"
            url = "https://www.zhipin.com/job_detail/abc.html?lid=fixture"
            with patch.object(result_browser, "platform_profile_dir", return_value=profile), \
                    patch.object(result_browser, "_profile_process", return_value=None), \
                    patch.object(result_browser, "resolve_browser_path", return_value=executable) as resolve, \
                    patch.object(result_browser.subprocess, "Popen") as popen:
                result_browser.open_result_job({"详情链接": url}, {"BROWSER_PATH": "configured.exe"})
            resolve.assert_called_once_with("configured.exe")
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(executable))
            self.assertIn(f"--user-data-dir={profile}", command)
            self.assertIn("--profile-directory=Default", command)
            self.assertIn("--user-agent=fixture user agent", command)
            self.assertIn("--new-window", command)
            self.assertIn("--restore-last-session", command)
            self.assertNotIn("--headless", command)
            self.assertEqual(command[-1], url)
            self.assertFalse(popen.call_args.kwargs.get("shell", False))

    def test_other_platforms_open_their_own_profile_without_boss_user_agent(self):
        for platform, url in (
            ("zhilian", "https://jobs.zhaopin.com/ABC123.htm"),
            ("liepin", "https://www.liepin.com/job/123.shtml"),
        ):
            with self.subTest(platform=platform), \
                    patch.object(result_browser, "_profile_process", return_value=None), \
                    patch.object(result_browser, "resolve_browser_path", return_value=Path("browser.exe")), \
                    patch.object(result_browser.subprocess, "Popen") as popen:
                result_browser.open_result_job({"详情链接": url}, {})
                command = popen.call_args.args[0]
                self.assertIn(f"--user-data-dir={platform_profile_dir(platform)}", command)
                self.assertFalse(any(argument.startswith("--user-agent=") for argument in command))

    def test_temporary_or_background_session_does_not_silently_open_another_account(self):
        row = {"详情链接": "https://www.zhipin.com/job_detail/abc.html"}
        with patch.object(result_browser.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "保留登录信息"):
                result_browser.open_result_job(row, {"KEEP_LOGIN": "false"})
            with patch.object(result_browser, "_profile_process", return_value=["chrome.exe", "--headless=new"]):
                with self.assertRaisesRegex(ValueError, "后台运行"):
                    result_browser.open_result_job(row, {})
            popen.assert_not_called()

    def test_visible_browser_reuses_the_same_profile(self):
        with patch.object(result_browser, "_profile_process", return_value=["chrome.exe"]), \
                patch.object(result_browser, "resolve_browser_path", return_value=Path("browser.exe")), \
                patch.object(result_browser.subprocess, "Popen") as popen:
            result_browser.open_result_job({"详情链接": "https://jobs.zhaopin.com/ABC123.htm"}, {})
        self.assertIn(f"--user-data-dir={platform_profile_dir('zhilian')}", popen.call_args.args[0])

    def test_profile_process_matches_exact_path_and_handles_both_flag_forms(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile"
            for flags in ([f"--user-data-dir={profile}"], ["--user-data-dir", str(profile)]):
                target = ["chrome.exe", *flags, "--headless=new"]
                processes = [
                    SimpleNamespace(info={"name": "chrome.exe", "cmdline": [
                        "chrome.exe", f"--user-data-dir={profile}-other",
                    ]}),
                    SimpleNamespace(info={"name": "chrome.exe", "cmdline": target}),
                ]
                with self.subTest(flags=flags), \
                        patch.object(result_browser.psutil, "process_iter", return_value=processes):
                    self.assertEqual(result_browser._profile_process(profile), target)

    def test_task_profile_check_ignores_other_platforms_and_temporary_profiles(self):
        with patch.object(result_browser, "_profile_process", return_value=["chrome.exe"]) as probe:
            with self.assertRaisesRegex(ValueError, "智联招聘.*关闭"):
                result_browser.ensure_task_profiles_available({"JOB_PLATFORMS": "zhilian"})
            probe.assert_called_once_with(platform_profile_dir("zhilian"))
            probe.reset_mock()
            result_browser.ensure_task_profiles_available({"KEEP_LOGIN": "false"})
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
