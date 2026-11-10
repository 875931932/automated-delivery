"""Reuse the shared matching pipeline with a platform-specific browser."""

import threading

from auto_deliver import AutoDeliverer
from job_platforms import ensure_platform_available
from platform_browser import BrowserJobPlatform


class BrowserPlatformDeliverer(AutoDeliverer):
    def __init__(self, platform, deliver_cfg, matching_context=None):
        ensure_platform_available(platform)
        self.platform = platform
        super().__init__(deliver_cfg, matching_context=matching_context)

    def _init_browser_runtime(self, deliver_cfg):
        self.adapter = BrowserJobPlatform(self.platform, deliver_cfg)
        self.page = self.adapter.page
        self.browser_lock = self.adapter.lock
        self.seen_job_ids = set()
        self.stop_event = threading.Event()

    def wait_login(self, timeout):
        try:
            self.adapter.wait_login(timeout)
        finally:
            self.page = self.adapter.page

    def api_job_list(self, page=1, keyword=""):
        return self.adapter.search(page, keyword)

    def _fetch_jd_dom(self, job):
        return self.adapter.detail(job)

    def deliver_one(self, job, greeting):
        try:
            status = self.adapter.apply(job)
        except BaseException:
            # A page-level stop may follow a successful click. Preserve a record
            # before letting the shared worker terminate and close the browser.
            if getattr(self.adapter, "submission_started", False):
                self._record_unconfirmed(job, greeting)
            raise
        if status == "delivery_unconfirmed":
            self._record_unconfirmed(job, greeting)
            self.adapter.check_stopped()
        return status

    def _record_unconfirmed(self, job, greeting):
        self._count_stage("delivery_attempted")
        self._record(self._result_row(
            job, self.match_scores.get(job.get("工作名称", ""), ""), "", "delivery_unconfirmed",
            greeting, filter_reason="请在官方投递记录核对后处理",
            match_data={"primary_profile": job.get("主岗位画像", ""),
                        "profile_results": job.get("岗位画像评估详情", "")},
        ))
        self.tracker.mark(
            job.get("encryptJobId", ""), job.get("工作名称", ""), greeting, "delivery_unconfirmed",
        )

    def _raise_if_platform_stopped(self):
        self.adapter.check_stopped()

    def get_cookie_headers(self):
        self.adapter.check_page()
        return True

    def start_heartbeat(self):
        # This adapter reads the browser directly and has no HTTP cookie session.
        return None

    def stop_heartbeat(self):
        self.stop_event.set()

    def _human_navigate_interlude(self, job_list):
        self.adapter.check_page()

    def _after_successful_delivery(self):
        self.adapter.check_page()
