"""Browser access for experimental Zhilian and Liepin integrations."""

import random
import re
import threading
import time
from urllib.parse import urlparse

from DrissionPage import ChromiumOptions, ChromiumPage

from boss_spider import BossDP, PlatformAccessStopped
from browser_runtime import resolve_browser_path
from job_profiles import parse_search_keywords
from job_platforms import (
    PLATFORM_LABELS, build_platform_search_url, city_name, ensure_platform_available, job_identity,
    platform_city_code, platform_profile_dir,
)
from platform_job_parser import (
    normalized_job, parse_job_cards, parse_job_detail, zhilian_state_description,
)


class PlatformPageChanged(InterruptedError):
    pass


class BrowserJobPlatform:
    def __init__(self, platform, config):
        ensure_platform_available(platform)
        self.platform = platform
        self.config = config
        self.label = PLATFORM_LABELS[platform]
        platform_city_code(platform, config)
        self.lock = threading.RLock()
        self.stop_reason = ""
        self.headless = config.get("browser_background", True)
        self.profile = platform_profile_dir(platform) if config.get("keep_login", True) else None
        if self.profile:
            self.profile.mkdir(parents=True, exist_ok=True)
        self.last_search_url = ""
        self._page_signatures = {}
        self._modern_queries = {}
        self._last_navigation_at = 0
        self.page = self._open_browser()
        self._main_page = self.page
        self._detail_page = None
        self.profile = self.page.browser.user_data_path

    def _open_browser(self):
        options = ChromiumOptions()
        options.set_local_port(BossDP._pick_free_port())
        options.set_browser_path(str(resolve_browser_path()))
        if self.profile:
            options.set_user_data_path(str(self.profile))
            options.set_argument('--restore-last-session')
        options.headless(self.headless)
        options.set_argument('--no-first-run')
        options.set_argument('--no-default-browser-check')
        options.set_timeouts(base=8, page_load=30, script=15)
        return ChromiumPage(options)

    def check_stopped(self):
        if self.stop_reason:
            raise PlatformAccessStopped(
                f"{self.label}：{self.stop_reason}；本轮已停止，请在官方页面处理后手动重启。"
            )

    def _stop(self, reason):
        self.stop_reason = reason
        self.check_stopped()

    def check_page(self):
        self.check_stopped()
        page_url = urlparse(str(self.page.url or ""))
        title = str(self.page.title or "")
        if (page_url.hostname == "safe.liepin.com"
                or re.search(r"/(?:captcha|security|verify)(?:/|$)", page_url.path, re.I)
                or re.search(r"Security Verification|安全验证|访问受限|访问验证", title, re.I)):
            self._stop("页面要求安全验证或限制访问")
        for alert in self.page.eles(
            'css:[role="alert"], [role="dialog"], .ant-message-notice-content, .toast, .el-message',
            timeout=0,
        ):
            if alert.states.is_displayed and re.search(
                r"操作频繁|访问频繁|账号受限|账户受限|帐号受限|访问受限|安全验证|滑动验证|验证身份",
                alert.text,
            ):
                self._stop("页面提示验证、频率限制或账号限制")

    def _wait_navigation_interval(self):
        self.check_stopped()
        elapsed = time.monotonic() - self._last_navigation_at
        delay = random.uniform(*self.config.get("job_delay", (25, 50)))
        if self._last_navigation_at and elapsed < delay:
            time.sleep(delay - elapsed)

    def _navigate(self, url):
        self._wait_navigation_interval()
        self.page.get(url, retry=0, timeout=30)
        self._last_navigation_at = time.monotonic()
        self.check_page()

    def logged_in(self):
        self.check_page()
        # Identity/logout evidence is stronger than a public "my resume" link.
        selector = ".header-quick-menu-username" if self.platform == "liepin" else ".c-login__top__name"
        return bool(self.page.run_js(r"""
            const visible = e => !!e && e.getClientRects().length > 0
                && getComputedStyle(e).visibility !== 'hidden';
            const controls = [...document.querySelectorAll('a,button,[role="button"]')].filter(visible);
            if (controls.some(e => /^(退出登录|退出账号|安全退出|退出)$/.test(e.innerText.trim()))) return true;
            return [...document.querySelectorAll(arguments[0])].some(e => visible(e) && e.innerText.trim()
                && !/登录|注册|用户名|账号|手机号/.test(e.innerText));
        """, selector))

    def wait_login(self, timeout):
        keywords = parse_search_keywords(self.config.get("deliver_keyword", ""))
        url = build_platform_search_url(
            self.platform, self.config, keywords[0] if keywords else "",
        )
        self.page.get(url, retry=0, timeout=30)
        self.check_page()
        started = time.monotonic()
        print(f"[平台] {self.label}（试验接入），正在检查登录信息")
        while not self.logged_in():
            elapsed = time.monotonic() - started
            if timeout > 0 and elapsed >= timeout:
                raise TimeoutError(f"等待{self.label}登录超过 {timeout} 秒")
            if self.headless:
                self.page.quit(timeout=5)
                self.headless = False
                self.page = self._open_browser()
                self._main_page = self.page
                self.page.get(url, retry=0, timeout=30)
            if int(elapsed) % 30 < 2:
                print(f"[登录] 请在{self.label}浏览器完成登录，已等待 {int(elapsed)} 秒")
            time.sleep(2)
        print(f"[登录] {self.label}登录成功")

    def _wait_results(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self.check_page()
            jobs = self._read_jobs()
            if jobs:
                return jobs
            if self.page.ele(
                'css:.empty-result, .joblist-box__no-result, .ant-empty, .empty-state', timeout=0,
            ):
                return []
            time.sleep(0.5)
        raise PlatformPageChanged(f"{self.label}未识别到岗位列表，请检查登录状态和页面结构")

    def _read_jobs(self):
        jobs = parse_job_cards(self.platform, self.page.html)
        if jobs or self.platform != "zhilian":
            return jobs
        rows = self.page.run_js(r"""
            return [...document.querySelectorAll('.job-list-panel .job-card')].map(card => {
                const row = card.__vue__ && card.__vue__.$props && card.__vue__.$props.job;
                const text = selector => (card.querySelector(selector)?.textContent || '').trim();
                const titleNode = card.querySelector('.job-card__title-clamp .vue-clamp__text');
                const name = titleNode?.getAttribute('aria-label') || text('.job-card__title-clamp');
                const company = text('.job-card__company-name');
                const salary = text('.job-card__salary');
                const location = text('.job-card__location');
                if (!row || !name || !company || !salary || !location || name !== row.name
                    || !String(row.companyName || '').includes(company)
                    || salary !== row.salary60 || !row.workCity || !location.includes(row.workCity)) return null;
                return {id:row.number, url:row.positionUrl || row.positionURL,
                    name, company:row.companyName, salary, location,
                    degree:row.education || '', experience:row.workingExp || '',
                    skills:Array.isArray(row.jobSkillTags) ? row.jobSkillTags.filter(x => typeof x === 'string') : []};
            }).filter(Boolean);
        """) or []
        for row in rows:
            identity = job_identity("zhilian", row.get("url"))
            if identity and identity.native_id == str(row.get("id") or ""):
                jobs.append(normalized_job(
                    "zhilian", identity, **{key: row[key] for key in (
                        "name", "company", "salary", "location", "degree", "experience", "skills",
                    )},
                ))
        return jobs

    def search(self, page, keyword):
        with self.lock:
            state = self._modern_queries.get(keyword) if self.platform == "zhilian" else None
            if state:
                self.page = state["tab"]
                self.check_page()
                if page != state["page"] + 1 or self.page.url != state["url"]:
                    raise PlatformPageChanged("智联招聘搜索页面或加载顺序已改变，请重新启动任务")
                jobs = self._load_more_modern(state["seen"])
                state["page"] = page
            else:
                # Keep each infinite-scroll query alive while details use another tab.
                self.page = self._main_page.new_tab(background=True) \
                    if self._modern_queries else self._main_page
                url = build_platform_search_url(self.platform, self.config, keyword, page)
                self._navigate(url)
                jobs = self._wait_results()
                if self.platform == "zhilian" and self.page.ele('css:.job-list-panel .job-card', timeout=0):
                    if page != 1:
                        raise PlatformPageChanged("智联招聘滚动列表必须从第一页开始加载")
                    self._modern_queries[keyword] = {
                        "tab": self.page, "url": self.page.url, "page": page,
                        "seen": {job["encryptJobId"] for job in jobs},
                    }
            expected_city = city_name(self.config)
            title = str(self.page.title or "")
            if jobs and expected_city not in title and not any(
                expected_city == str(job.get("cityName") or "").removesuffix("市") for job in jobs
            ):
                raise PlatformPageChanged(f"{self.label}搜索结果与所选城市不一致，请核对平台城市代码")
            signature = tuple(job["encryptJobId"] for job in jobs)
            previous = self._page_signatures.get(keyword)
            if signature and previous and previous[0] != page and previous[1] == signature:
                raise PlatformPageChanged(f"{self.label}翻页后返回同一批岗位，已停止该查询")
            self._page_signatures[keyword] = (page, signature)
            self.last_search_url = self.page.url
            return {"zpData": {"jobList": jobs}}

    def _load_more_modern(self, seen):
        self.check_page()
        self._wait_navigation_interval()
        search_url = self.page.url
        result = self.page.run_js(r"""
            const panel = document.querySelector('.job-list-panel');
            const props = panel && panel.__vue__ && panel.__vue__.$props;
            if (!props || typeof props.hasMore !== 'boolean') return 'unknown';
            if (!props.hasMore) return 'end';
            const last = panel.querySelector('.job-card:last-child');
            if (!last) return 'unknown';
            last.scrollIntoView({block:'end', behavior:'instant'});
            window.scrollTo({top:document.documentElement.scrollHeight, behavior:'instant'});
            return 'loading';
        """)
        if result == "end":
            return []
        if result != "loading":
            raise PlatformPageChanged("智联招聘未识别到滚动加载状态，已停止该查询")
        self._last_navigation_at = time.monotonic()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self.check_page()
            if self.page.url != search_url:
                raise PlatformPageChanged("智联招聘滚动加载期间页面发生跳转")
            jobs = [job for job in self._read_jobs() if job["encryptJobId"] not in seen]
            if jobs:
                seen.update(job["encryptJobId"] for job in jobs)
                return jobs
            has_more = self.page.run_js(
                'return document.querySelector(".job-list-panel")?.__vue__?.$props?.hasMore;'
            )
            if has_more is False:
                return []
            time.sleep(0.5)
        raise PlatformPageChanged("智联招聘滚动后未返回新岗位，请检查页面")

    def _job_buttons(self):
        selectors = (
            '.job-apply-container, .job-apply, .job-operation, .job-detail-header, '
            '.job-detail-op, .job-summary, .job-banner, .position-head, .summary-plane, '
            '.summary-planes__action'
        )
        buttons = []
        for root in self.page.eles(f"css:{selectors}", timeout=0):
            candidates = list(root.eles('css:button, a, [role="button"], [data-selector]', timeout=0))
            if root.tag in {"button", "a"} or root.attr("role") == "button":
                candidates.insert(0, root)
            for element in candidates:
                if element.states.is_displayed:
                    buttons.append(element)
        return buttons

    @staticmethod
    def _button_text(button):
        return re.sub(r"\s+", "", button.text or "")

    def already_applied(self):
        return any(self._button_text(button) in {
            "已投递", "已投递简历", "已申请", "申请成功", "投递成功", "已应聘",
        } for button in self._job_buttons())

    def _on_job(self, job):
        expected = job_identity(self.platform, job["详情链接"])
        observed = job_identity(self.platform, self.page.url)
        return expected is not None and expected == observed

    def _activate_detail_page(self):
        if self._detail_page is None:
            self._detail_page = self._main_page.new_tab(background=True)
        self.page = self._detail_page

    def detail(self, job):
        with self.lock:
            self._activate_detail_page()
            self._navigate(job["详情链接"])
            if not self._on_job(job):
                raise PlatformPageChanged(f"{self.label}详情页发生跳转，岗位身份无法确认")
            if self.already_applied():
                return {"already_contacted": True}
            time.sleep(random.uniform(*self.config.get("detail_delay", (3, 6))))
            self.check_page()
            if not self._on_job(job):
                raise PlatformPageChanged(f"{self.label}读取详情前岗位身份发生变化")
            result = parse_job_detail(self.platform, self.page.html)
            if not result["desc"] and self.platform == "zhilian":
                identity = job_identity(self.platform, job["详情链接"])
                result["desc"] = zhilian_state_description(self.page.html, identity.native_id)
            if self.already_applied():
                return {"already_contacted": True}
            return result

    def apply(self, job):
        with self.lock:
            self.submission_started = False
            self._activate_detail_page()
            self._navigate(job["详情链接"])
            if not self._on_job(job):
                raise PlatformPageChanged(f"{self.label}投递前岗位身份无法确认")
            time.sleep(random.uniform(*self.config.get("detail_delay", (3, 6))))
            self.check_page()
            if not self._on_job(job):
                raise PlatformPageChanged(f"{self.label}等待投递按钮期间岗位身份发生变化")
            if self.already_applied():
                return "already_contacted"
            button = next((element for element in self._job_buttons() if self._button_text(element) in {
                "立即投递", "投递简历", "申请职位", "立即申请", "应聘职位",
            }), None)
            if button is None:
                return "manual_required"
            self.check_page()
            if not self._on_job(job):
                raise PlatformPageChanged(f"{self.label}点击投递前岗位身份发生变化")
            self.submission_started = True
            button.click()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.check_page()
                if self._on_job(job) and self.already_applied():
                    return "delivered"
                time.sleep(0.5)
            # Never click again or guess a resume choice when a dialog is shown.
            self.stop_reason = "投递已触发但尚未确认回执，请核对该岗位的投递记录"
            return "delivery_unconfirmed"
