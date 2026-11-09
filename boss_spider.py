from process_runtime import configure_quiet_processes, quiet_process_options

configure_quiet_processes()

from DrissionPage import ChromiumPage,ChromiumOptions
from browser_runtime import resolve_browser_path
from get_user_agent import get_user_agent_of_pc
import time
import random
import requests
import threading
import re
import html
# page.listen.start('joblist.json')
from typing import Optional, Dict# 移除前（误匹配）
import os
import csv
from urllib.parse import quote, urlencode, urlparse
from platform_locations import resolve_platform_area_codes
from platform_search_filters import JOB_TYPE_CODES, PLATFORM_FILTER_PARAMS

Config = {
    "base_url": "https://www.zhipin.com",
    "city_id": "101280100",
    "position": "",
    "keyword": "AI应用开发",
    "multiBusinessDistrict": "",
    "jobType": "",
    "payType": "",
    "partTime": "",
    "experience": "",
    "degree": "",
    "industry": "",
    "scale": "",
    "page_size": 30,
    "max_pages": 10,  # 单次最多 10 页（300 条），上限保护，降低被封风险
    "request_timeout": 15,
    "max_retries": 2,
    "heart_time": 60,
    "human_browse_cooldown": 60,
    "job_delay": (1.5, 3),
    "page_delay": (12, 22),  # 翻页间隔 12-22 秒随机延迟，模拟真人浏览节奏
    "retry_delay": 4,
    "detail_page_fallback": False,  # 默认禁用 DOM fallback，避免字体反爬导致的薪资乱码
    "output_file": "boss_jobs.csv",
    "max_api_requests": 500,  # 单次最大 API 请求数，上限保护
    # BOSS 专用 Chrome profile（独立于主 Chrome，避免污染主浏览器登录态）
    "chrome_profile_dir": os.path.join(os.path.expanduser("~"), ".boss-zhipin-scraper", "chrome-profile"),
    # 登录态保持：true=固定UA+持久profile(重启免登录)；false=随机UA+临时profile(每次需登录)
    "keep_login": True,
    "browser_background": True,
}

# 干净的 Chrome UA 候选（登录态要求 UA 稳定，首次随机后持久化复用）
STABLE_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]
def build_job_search_url(config):
    params = {"city": config["city_id"]}
    if config.get("multiBusinessDistrict"):
        params["multiBusinessDistrict"] = config["multiBusinessDistrict"]
    for key in PLATFORM_FILTER_PARAMS:
        if config.get(key):
            params[key] = config[key]
    if config.get("position"):
        params["position"] = config["position"]
    params["query"] = config["keyword"]
    return f"{config['base_url']}/web/geek/jobs?{urlencode(params)}"


Config["start_url"] = build_job_search_url(Config)

CSV_FIELDS = [
    "encryptJobId", "工作名称", "工资", "学历要求", "技术要求",
    "薪资下限", "薪资上限", "薪资单位", "薪资月数", "工作经验要求",
    "经验下限年", "学历等级", "工作性质", "工作介绍", "工作区域",
    "城市", "行政区", "商圈", "工作详细地址", "详情链接",
    "公司", "公司阶段", "公司行业", "公司规模", "公司介绍", "公司福利",
]


class BossDP:
    @staticmethod
    def _pick_free_port():
        """自行挑选空闲端口。不能用 DrissionPage 的 auto_port(True)：
        它会强制把 user_data_path 替换成临时目录（与持久登录态冲突），
        且 set_user_data_path 会关闭 auto_port 导致启动地址为空而报错。"""
        import socket
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
        finally:
            s.close()

    @classmethod
    def _stable_user_agent(cls, profile_dir):
        """登录态要求 UA 稳定：首次随机选定后写入 profile 目录，之后固定复用。"""
        ua_file = os.path.join(profile_dir, "user_agent.txt")
        try:
            if os.path.exists(ua_file):
                with open(ua_file, "r", encoding="utf-8") as f:
                    ua = f.read().strip()
                if ua:
                    print(f"[登录保持] 使用固定 UA: {ua[:70]}...")
                    return ua
        except OSError:
            pass
        ua = random.choice(STABLE_UAS)
        try:
            with open(ua_file, "w", encoding="utf-8") as f:
                f.write(ua)
        except OSError:
            pass
        print(f"[登录保持] 首次选定固定 UA（已持久化）: {ua[:70]}...")
        return ua

    @staticmethod
    def _kill_stale_chrome(profile_dir, browser_path=None):
        """清理仍占用本程序专用 profile 的残留 Chromium 进程。
        同一个 --user-data-dir 只允许一个实例：残留进程会让新启动的 Chrome 直接转发 URL 后退出，
        结果 DrissionPage 连不上新端口、页面始终不跳转。"""
        import subprocess
        try:
            env = os.environ.copy()
            env['BOSS_PROFILE'] = profile_dir
            env['BOSS_BROWSER_PROCESS'] = (
                os.path.basename(browser_path) if browser_path else "chrome.exe"
            )
            ps = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -ieq $env:BOSS_BROWSER_PROCESS } | "
                "Where-Object { $_.CommandLine -like \"*$env:BOSS_PROFILE*\" "
                "-and $_.CommandLine -like '*--remote-debugging-port*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
                "$_.ProcessId }"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                env=env, capture_output=True, text=True, timeout=20,
                **quiet_process_options(),
            )
            killed = [x.strip() for x in (result.stdout or '').splitlines() if x.strip()]
            if killed:
                print(f"[浏览器] 清理残留浏览器进程: {', '.join(killed)}")
                time.sleep(1.5)
        except Exception as exc:
            print(f"[浏览器] 清理残留进程失败（可忽略）: {exc}")

    def __init__(self):
        self.urgent_event=threading.Event()#设置紧急心跳信号
        self.stop_event = threading.Event()
        self.browser_lock=threading.RLock()#心跳线程和主线程共用浏览器
        self._session_lock = threading.RLock()  # requests.Session 与 cookie 同步锁
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_thread = None
        self._last_human_browse_at = None
        self.click_job_count = 0  # 点击职位计数
        self.enter_detail_count = 0  # 进入详细页面计数
        # 登录态保持开关：开启时 UA 固定 + 持久 profile；关闭时随机 UA（更隐蔽但需重新登录）
        self.keep_login = Config.get("keep_login", True)
        if self.keep_login:
            os.makedirs(Config["chrome_profile_dir"], exist_ok=True)
            self.user_agent = self._stable_user_agent(Config["chrome_profile_dir"])
        else:
            self.user_agent = get_user_agent_of_pc()
        self.api_request_count = 0  # API 请求计数器
        self.max_api_requests = Config.get("max_api_requests", 500)  # 单次最大 API 请求数

        # 准备 BOSS 专用 Chrome profile（独立于主 Chrome）
        profile_dir = Config.get("chrome_profile_dir") if self.keep_login else None
        if self.keep_login:
            os.makedirs(profile_dir, exist_ok=True)
            print(f"使用 BOSS 专用 Chrome profile: {profile_dir}")

        self.browser_path = resolve_browser_path()
        print(f"[浏览器] 使用 Chromium: {self.browser_path}")
        self.browser_background = Config.get("browser_background", True)
        self._background_unavailable = False
        self._browser_profile_dir = profile_dir
        self._browser_attention_url = None
        self._login_waiting = False
        if profile_dir:
            self._kill_stale_chrome(profile_dir, self.browser_path)
        self.page = self._open_browser(self.browser_background)
        # Keep even a temporary profile across interactive login mode switches.
        self._browser_profile_dir = self.page.browser.user_data_path
        self._browser_headless = self.browser_background
        #初始化requests
        self.session=requests.Session()
        self.current_cookies={}
        self.current_headers={}
        #存储数据
        self.all_jobs=[]
        self.seen_job_ids=set()
        self.detail_company_cache = {}
        self.stats={
            'page':0,
            "jobs_fetched":0,
            "details_success":0
        }

    def _open_browser(self, headless):
        co=ChromiumOptions()
        co.set_browser_path(str(self.browser_path))
        co.set_local_port(self._pick_free_port())  # 随机空闲端口，替代 auto_port（见 _pick_free_port 注释）
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')#初始化了浏览器模拟浏览器指纹
        co.set_user_agent(self.user_agent)
        co.set_argument('--window-size','1920,1080')
        co.headless(headless)
        co.set_argument('--no-first-run')
        co.set_argument('--no-default-browser-check')
        # 窗口被用户最小化后，后台标签仍要正常加载，不被 Chrome 节流冻结
        co.set_argument('--disable-background-timer-throttling')
        co.set_argument('--disable-backgrounding-occluded-windows')
        co.set_argument('--disable-renderer-backgrounding')

        # 使用独立 profile，避免污染主 Chrome（必须用官方 API，set_argument 会与内部默认值冲突）
        if self._browser_profile_dir:
            co.set_user_data_path(self._browser_profile_dir)
            # 使用 Default profile，确保登录态持久化
            co.set_argument('--profile-directory=Default')
        
        page = ChromiumPage(co)
        page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source='''
                // 1. 伪造内存大小 (解决 CHR_MEMORY FAIL)
                Object.defineProperty(navigator, 'deviceMemory', {
                    value: 8, 
                    writable: false, 
                    configurable: true, 
                    enumerable: false
                });

                // 2. CPU 核心数
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    value: 8, 
                    writable: false, 
                    configurable: true, 
                    enumerable: false
                });
            '''
        )
        return page

    def _switch_browser_mode(self, headless, url=None):
        """Called only by the main flow, between page operations."""
        with self.browser_lock:
            if self._browser_headless == headless:
                return False
            # Session cookies need an in-memory transfer in addition to the profile.
            cookies = self.page.run_cdp('Storage.getCookies', _timeout=3)['cookies']
            target_url = url or self.page.url
            self.page.quit(timeout=5)
            self._detail_tab = None
            self.page = self._open_browser(headless)
            self._browser_headless = headless
            self.page.browser.set.cookies(cookies)
            self.page.get(target_url)
            print("[浏览器] 已切换为后台运行" if headless else
                  "[浏览器] 请在打开的窗口中完成登录或验证")
            return True

    @staticmethod
    def _is_browser_attention_url(url):
        if not isinstance(url, str):
            return False
        parsed = urlparse(url)
        return (parsed.netloc == urlparse(Config['base_url']).netloc
                and parsed.path.startswith(('/web/user/', '/web/common/security')))

    def _wait_for_login(self, timeout, start_url=None):
        """Check the rendered avatar, and show an interactive browser only if needed."""
        start_url = start_url or Config['start_url']
        started = time.monotonic()
        background_retry = self.browser_background and not getattr(self, '_background_unavailable', False)
        mode_started = started
        self._login_waiting = True
        try:
            with self.browser_lock:
                self.page.get(start_url)
            print("正在检查登录信息；需要扫码时会显示浏览器...")
            last_report = 0
            while not self.stop_event.is_set():
                time.sleep(3)
                with self.browser_lock:
                    logged_in = bool(self.page.ele('.nav-figure', timeout=2))
                    elapsed = time.monotonic() - started
                    if logged_in:
                        if background_retry and not self._browser_headless:
                            self._switch_browser_mode(True, url=Config['start_url'])
                            # Revalidate the session after restarting; never assume cookies suffice.
                            background_retry = False
                            mode_started = time.monotonic()
                            continue
                        self._browser_attention_url = None
                        print(f"检测到登录成功（用时 {int(elapsed)} 秒）")
                        return
                    if timeout > 0 and elapsed >= timeout:
                        raise TimeoutError(f"等待登录超过 {timeout} 秒，请完成登录后重新启动任务")
                    if self._browser_headless and time.monotonic() - mode_started >= 6:
                        if not background_retry:
                            self._background_unavailable = True
                            print("[浏览器] 后台登录检查未通过，本轮保留可见窗口")
                        self._switch_browser_mode(False)
                    # Do not reload while the user is scanning the QR code.
                if elapsed - last_report >= 30:
                    print(f"  仍在等待登录... 已等待 {int(elapsed)} 秒")
                    last_report = elapsed
            raise InterruptedError("任务已停止，取消登录等待")
        finally:
            self._login_waiting = False

    def _resume_browser_if_needed(self):
        """Consume heartbeat's signal on the main thread, never inside an HTTP request."""
        url = getattr(self, '_browser_attention_url', None)
        if url:
            timeout = getattr(self, 'cfg', {}).get('login_wait', 300)
            self._wait_for_login(timeout, start_url=url)
            self.get_cookie_headers()

    def _check_browser_attention(self, page):
        if self._is_browser_attention_url(page.url):
            self._browser_attention_url = page.url
            self._resume_browser_if_needed()
            return True
        return False

    def login(self):
        self._wait_for_login(0)
        #同步初始cookies和headers
        self.get_cookie_headers()
        
    def get_cookie_headers(self):
        try:
            # Keep one lock order: browser, then session. Direct CDP avoids the
            # unbounded document-load wait used by page.cookies().
            with self.browser_lock, self._session_lock:
                cookies_list = self.page.run_cdp(
                    'Network.getCookies', _timeout=2,
                )['cookies']
                cookies_dict = {
                    cookie['name']: cookie['value']
                    for cookie in cookies_list
                    if 'name' in cookie and 'value' in cookie
                }
                self.session.cookies.clear()
                self.session.cookies.update(cookies_dict)
                self.current_cookies = cookies_dict
                self.current_headers={
                    "User-Agent": self.user_agent,
                    'Accept': 'application/json, text/plain, */*',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'origin': 'https://www.zhipin.com',
                    'referer': Config["start_url"],
                    'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,en-GB;q=0.6',
                    'priority': 'u=1, i',
                }
                self.session.headers.update(self.current_headers)
            return True
        except Exception as e:
            print("同步cookies失败",e)
            return False
    def click_job(self):
        """已迁移到 _human_click_job_action，此方法保留为空兼容旧调用"""
        pass

    @staticmethod
    def _is_platform_homepage(url):
        """只识别平台根首页，避免把详情页或聊天页误判成首页。"""
        try:
            parsed = urlparse(str(url or ''))
            return (
                parsed.scheme in {'http', 'https'}
                and parsed.netloc == urlparse(Config['base_url']).netloc
                and parsed.path.rstrip('/') == ''
            )
        except ValueError:
            return False

    @staticmethod
    def _is_search_page(url):
        try:
            parsed = urlparse(str(url or ''))
            return (
                parsed.scheme in {'http', 'https'}
                and parsed.netloc == urlparse(Config['base_url']).netloc
                and parsed.path.rstrip('/') == '/web/geek/jobs'
            )
        except ValueError:
            return False

    # ================= 心跳线程（只做被动保活与页面恢复） =================
    def _heartbeat_once(self):
        if (self.stop_event.is_set() or getattr(self, '_login_waiting', False)
                or not self.browser_lock.acquire(blocking=False)):
            return
        try:
            # Never hold the browser hostage to an in-flight HTTP request.
            if not self._session_lock.acquire(blocking=False):
                return
            try:
                if self.stop_event.is_set():
                    return
                info = self.page.run_cdp('Target.getTargetInfo', _timeout=2)
                current_url = info['targetInfo']['url']
                parsed = urlparse(current_url)
                if parsed.netloc != urlparse(Config['base_url']).netloc:
                    return
                if self._is_browser_attention_url(current_url):
                    print(" [心跳] 当前为登录或验证页面，等待人工处理")
                    self._browser_attention_url = current_url
                    return
                if self.stop_event.is_set():
                    return
                if self._is_platform_homepage(current_url):
                    print(" [心跳] 检测到首页，恢复搜索列表")
                    self.page.get(Config['start_url'], retry=0, timeout=5)
                if not self.stop_event.is_set():
                    self.get_cookie_headers()
            finally:
                self._session_lock.release()
        except Exception as exc:
            print(f" [心跳] 页面检查失败: {exc}")
        finally:
            self.browser_lock.release()

    def _heartbeat_loop(self):
        interval = max(1, Config['heart_time'])
        print(f"[心跳线程] 启动，每 {interval} 秒检查页面并同步登录信息\n")
        while not self.stop_event.is_set():
            self.urgent_event.wait(timeout=interval)
            if self.stop_event.is_set():
                break
            self.urgent_event.clear()
            self._heartbeat_once()

    def start_heartbeat(self):
        """启动唯一的后台心跳线程，不在后台线程执行随机拟人操作。"""
        with self._heartbeat_lock:
            if self.stop_event.is_set():
                return None
            existing = self._heartbeat_thread
            if existing is not None and existing.is_alive():
                return existing
            thread = threading.Thread(
                target=self._heartbeat_loop, name="boss-heartbeat", daemon=True,
            )
            self._heartbeat_thread = thread
            thread.start()
            return thread

    def stop_heartbeat(self):
        """停止心跳并等待其退出，确保页面关闭前没有后台浏览器调用。"""
        stop_event = getattr(self, 'stop_event', None)
        if stop_event is not None:
            stop_event.set()
        urgent_event = getattr(self, 'urgent_event', None)
        if urgent_event is not None:
            urgent_event.set()
        lifecycle_lock = getattr(self, '_heartbeat_lock', None)
        if lifecycle_lock is not None:
            with lifecycle_lock:
                thread = self._heartbeat_thread
        else:
            thread = getattr(self, '_heartbeat_thread', None)
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        if thread is not None and not thread.is_alive():
            self._heartbeat_thread = None

    #通过api获取信息
    def api_job_list(self,page:int =1,keyword:str=Config['keyword'])->Optional[Dict]:
        url=f"{Config['base_url']}/wapi/zpgeek/search/joblist.json"
        data = {
            "page": page,
            "pageSize": Config["page_size"],
            "city": Config["city_id"],
            "query": keyword,
            "scene": 1,
        }
        if Config.get("multiBusinessDistrict"):
            data["multiBusinessDistrict"] = Config["multiBusinessDistrict"]
        for key in PLATFORM_FILTER_PARAMS:
            if Config.get(key):
                data[key] = Config[key]
        return self._request_json("post", url, data=data, label="列表")

    def _request_json(
        self, method: str, url: str, label: str,
        request_headers=None, **kwargs,
    ):
        """请求 JSON 接口，统一处理网络、HTTP、JSON 和业务错误。"""
        self._resume_browser_if_needed()
        # 请求间随机延迟，模拟真人操作节奏
        delay = random.uniform(1.5, 4.0)
        time.sleep(delay)
        
        for attempt in range(Config["max_retries"]):
            try:
                # Read browser cookies before taking the session lock.
                if not self.current_cookies and not self.get_cookie_headers():
                    raise requests.RequestException("登录态同步失败")
                with self._session_lock:
                    if self.api_request_count >= self.max_api_requests:
                        print(f"⚠️ 已达到单次最大 API 请求数上限 ({self.max_api_requests})，停止请求")
                        return None
                    # 增加请求计数
                    self.api_request_count += 1
                    current_count = self.api_request_count

                    # 每 20 次请求打印一次计数，方便监控
                    if current_count % 20 == 0:
                        print(f"  [API] 累计请求 {current_count} 次")

                    headers = {**self.current_headers, **(request_headers or {})}
                    response = self.session.request(
                        method, url, headers=headers,
                        timeout=Config["request_timeout"], **kwargs
                    )
                if response.status_code != 200:
                    raise requests.RequestException(
                        f"HTTP {response.status_code}"
                    )
                result = response.json()
                if result.get("code") != 0:
                    print(f"{label}接口业务错误: {result.get('message', result.get('msg', '未知错误'))}")
                    return None
                return result
            except (requests.RequestException, ValueError) as exc:
                if attempt + 1 == Config["max_retries"]:
                    print(f"请求{label}失败: {exc}")
                    return None
                wait_seconds = 2 ** attempt
                print(f"请求{label}失败，将在{wait_seconds}秒后重试: {exc}")
                time.sleep(wait_seconds)
        return None
    def api_job_detail(self, security_id: str, request_headers=None):
        url=f"{Config['base_url']}/wapi/zpgeek/job/detail.json"
        return self._request_json(
            "get", url, label="详情", params={"securityId": security_id},
            request_headers=request_headers,
        )
#详情只需要需要工作介绍，详细地址，公司介绍
    @staticmethod
    def _clean_text(text):
        """清理 HTML 标签和实体，返回纯文本"""
        if not text:
            return ""
        # 解码 HTML 实体（如 &nbsp; &lt; &gt; &#13; 等）
        text = html.unescape(text)
        # 去除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 清理常见空白字符：换行、制表符、多余空格
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = re.sub(r'\n\s*\n+', '\n', text)  # 多个空行合并为一个
        text = re.sub(r'[ \t]+', ' ', text)     # 多个空格/制表符合并为一个
        text = text.replace('来自BOSS直聘', '')  # 去掉 BOSS 混入正文的防爬水印
        return text.strip()

    @staticmethod
    def _format_list(items):
        """将列表格式化为分号分隔的字符串"""
        if not items:
            return ""
        if isinstance(items, list):
            return "; ".join(str(item) for item in items if item)
        return str(items)

    @staticmethod
    def _parse_salary(salary):
        """把 15-25K、200-300元/天 等薪资文本拆成数值字段。"""
        text = str(salary or '').strip().replace('－', '-').replace('～', '-')
        result = {"薪资下限": "", "薪资上限": "", "薪资单位": "", "薪资月数": ""}
        match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:-|~|至)\s*'
            r'(\d+(?:\.\d+)?)\s*(万|K|k|元/月|元/天|元)', text
        )
        if match:
            result["薪资下限"] = match.group(1)
            result["薪资上限"] = match.group(2)
            unit = match.group(3)
            result["薪资单位"] = "K/月" if unit.lower() == "k" else unit
        else:
            single = re.search(r'(\d+(?:\.\d+)?)\s*(万|K|k|元/月|元/天|元)', text)
            if single:
                result["薪资下限"] = single.group(1)
                result["薪资上限"] = single.group(1)
                unit = single.group(2)
                result["薪资单位"] = "K/月" if unit.lower() == "k" else unit
        months = re.search(r'(\d+)\s*薪', text)
        if months:
            result["薪资月数"] = months.group(1)
        return result

    @staticmethod
    def _parse_experience(experience):
        """提取最低工作年限；应届生和在校生按 0 年处理。"""
        text = str(experience or '').strip()
        match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:-|~|至)\s*\d+(?:\.\d+)?\s*年', text
        )
        if match:
            return match.group(1)
        match = re.search(r'(\d+(?:\.\d+)?)\s*(?:年|年以上)', text)
        if match:
            return match.group(1)
        if re.search(r'应届|在校|经验不限|不限', text):
            return "0"
        return ""

    @staticmethod
    def _degree_level(degree):
        """把学历文本转换为便于排序的等级，未知学历返回空值。"""
        text = str(degree or '')
        for keyword, level in (
            ('博士', 6), ('硕士', 5), ('研究生', 5), ('本科', 4),
            ('大专', 3), ('专科', 3), ('高中', 2), ('中专', 2),
            ('初中', 1), ('学历不限', 0), ('不限', 0),
        ):
            if keyword in text:
                return str(level)
        return ""

    @staticmethod
    def _split_location(job):
        """保留页面中的城市、行政区和商圈层级，便于按区域推荐。"""
        return {
            "城市": job.get('cityName', ''),
            "行政区": job.get('areaDistrict', ''),
            "商圈": job.get('businessDistrict', ''),
        }

    @staticmethod
    def _is_truncated_name(name):
        """判断页面展示名称是否是省略文本。"""
        return bool(re.search(r'(?:\.\.\.|…|等)$', str(name or '').strip()))

    @classmethod
    def _best_company_name(cls, *names):
        """优先选择非空且未被页面省略的公司名称。"""
        values = [str(name).strip() for name in names if name]
        for name in values:
            if not cls._is_truncated_name(name):
                return name
        return values[0] if values else ""

    def _company_name_from_detail_page(self, job):
        """仅在公司名被省略时，从职位详情页读取完整公司名（始终执行）。"""
        job_id = job.get("encryptJobId")
        if not job_id:
            return ""
        if job_id in self.detail_company_cache and self.detail_company_cache[job_id]:
            return self.detail_company_cache[job_id]

        security_id = job.get("securityId")
        detail_url = f"{Config['base_url']}/job_detail/{job_id}.html"
        if security_id:
            detail_url += f"?securityId={quote(str(security_id))}"
        company_name = ""
        try:
            with self.browser_lock:
                print(f"详情页补全公司名: {job.get('jobName', '')}")
                self.page.get(detail_url)
                company_ele = self.page.ele(".company-name", timeout=5)
                if company_ele:
                    company_name = self._clean_text(company_ele.text)
                else:
                    print("详情页未找到 .company-name，保留原公司名")
                self.page.get(Config["start_url"])
                time.sleep(2)
            company_name = "" if self._is_truncated_name(company_name) else company_name
            if not company_name:
                print("详情页公司名仍为空或被省略，保留原公司名")
            else:
                print(f"详情页完整公司名: {company_name}")
        except Exception as exc:
            print(f"详情页读取公司名失败: {exc}")
        self.detail_company_cache[job_id] = company_name
        return company_name

    @staticmethod
    def _classify_job_type(job_data):
        """Prefer role-specific employment signals; monthly salary is only a fallback."""
        type_fields = (
            "jobType", "jobTypeName", "jobNature", "employmentType",
            "jobLabels", "工作性质",
        )
        values = []
        for field in type_fields:
            value = job_data.get(field, "")
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item).strip().lower() for item in value if item)
            elif isinstance(value, dict):
                values.extend(str(item).strip().lower() for item in value.values() if item)
            elif value:
                values.append(str(value).strip().lower())

        explicit_intern = any(re.fullmatch(
            r"(?:实习|实习生|实习岗位|实习职位|实习岗|intern|internship)", value
        ) for value in values)
        explicit_full_time = any(re.fullmatch(
            r"(?:全职|正式员工|full[ -]?time)", value
        ) for value in values)
        explicit_part_time = any(re.fullmatch(
            r"(?:兼职|非全日制|part[ -]?time)", value
        ) for value in values)
        structured_types = set()
        if explicit_intern or "1902" in values:
            structured_types.add("实习")
        if explicit_full_time or "1901" in values:
            structured_types.add("全职")
        if explicit_part_time or "1903" in values:
            structured_types.add("兼职")
        if len(structured_types) == 1:
            return next(iter(structured_types))

        title = str(job_data.get("jobName", job_data.get("工作名称", "")) or "")
        title_types = set()
        if re.search(r"全职|正式员工|full[ -]?time", title, re.IGNORECASE):
            title_types.add("全职")
        if re.search(r"兼职|非全日制|part[ -]?time", title, re.IGNORECASE):
            title_types.add("兼职")
        if re.search(r"实习(?:生|岗位|岗|职位)?(?:[（(].*)?$|intern(?:ship)?\b", title, re.IGNORECASE) \
                and not re.search(r"实习(?:生)?(?:管理|经验|经历|培训|培养)|管理实习生", title):
            title_types.add("实习")

        description = " ".join(str(job_data.get(field, "") or "") for field in (
            "jobDesc", "jobRequire", "工作介绍",
        ))
        clauses = [part.strip() for part in re.split(r"[。；;\n]+", description) if part.strip()]
        normalized_clauses = [re.sub(
            r"(?:不招|不招聘|不接受|不考虑|无需|非)\s*(?:实习生?|intern(?:ship)?)"
            r"|(?:实习|internship)\s*(?:经验|经历)"
            r"|(?:实习生?\s*(?:管理|培训|培养)|管理实习生)",
            " ", clause, flags=re.IGNORECASE,
        ) for clause in clauses]
        description_types = set()

        full_time_patterns = (
            r"(?:招聘|招募|招收|岗位性质|工作性质|岗位类型|职位类型|本岗位|该岗位|岗位|职位)"
            r"[^。；;\n]{0,12}(?:全职|正式员工|正式职员|full[ -]?time)",
            r"(?:全职|正式员工|正式职员|full[ -]?time)"
            r"[^。；;\n]{0,8}(?:岗位|职位|工程师|员工)",
        )
        internship_patterns = (
            r"(?:招聘|招募|招收|面向|适合|岗位性质|工作性质|岗位类型|职位类型|"
            r"本岗位|该岗位|岗位|职位)"
            r"[^。；;\n]{0,12}(?:实习生?|intern(?:ship)?)",
            r"(?:实习生?|intern(?:ship)?)[^。；;\n]{0,8}(?:岗位|职位|招聘|开放)",
            r"(?:实习岗位|实习职位|实习生岗位|internship position)",
        )
        part_time_patterns = (
            r"(?:招聘|招募|招收|岗位性质|工作性质|岗位类型|职位类型|本岗位|该岗位|岗位|职位)"
            r"[^。；;\n]{0,12}(?:兼职|非全日制|part[ -]?time)",
            r"(?:兼职|非全日制|part[ -]?time)[^。；;\n]{0,8}(?:岗位|职位|招聘)",
        )

        if any(re.search(pattern, clause, re.IGNORECASE)
               for clause in normalized_clauses for pattern in full_time_patterns):
            description_types.add("全职")
        if any(re.search(pattern, clause, re.IGNORECASE)
               for clause in normalized_clauses for pattern in internship_patterns):
            description_types.add("实习")
        if any(re.search(pattern, clause, re.IGNORECASE)
               for clause in normalized_clauses for pattern in part_time_patterns):
            description_types.add("兼职")

        if len(description_types) == 1 and not title_types:
            return next(iter(description_types))
        if len(description_types) == 1 and title_types == description_types:
            return next(iter(description_types))
        if description_types or len(structured_types) > 1:
            return "待确认"

        salary = str(job_data.get("salaryDesc", job_data.get("工资", "")) or "")
        monthly_salary = bool(re.search(
            r"(?:\d+(?:\.\d+)?\s*(?:-|~|至)\s*)?\d+(?:\.\d+)?\s*"
            r"(?:万(?:\s*/\s*月)?|k(?:\s*/\s*月)?|元\s*/\s*月|月薪)",
            salary,
            re.IGNORECASE,
        ))
        if monthly_salary and title_types in (set(), {"实习"}):
            return "全职"
        if len(title_types) == 1:
            return next(iter(title_types))
        if title_types:
            return "待确认"
        return "待确认"

    @staticmethod
    def _extract_tech_requirements_from_description(description):
        """从职位描述中智能提取AI应用开发相关技术关键词"""
        if not description:
            return ""
        
        # 分类定义关键词：AI核心技术、应用开发框架、部署工程化、通用基础
        ai_core = [
            r'机器学习', r'深度学习', r'神经网络', r'CNN', r'RNN', r'LSTM',
            r'NLP', r'自然语言处理', r'计算机视觉', r'CV', r'图像识别',
            r'目标检测', r'语义分割', r'OCR', r'语音识别', r'语音合成',
            r'推荐系统', r'知识图谱', r'强化学习', r'联邦学习',
            r'大模型', r'LLM', r'大语言模型', r'生成式AI', r'AIGC',
            r'多模态', r'Transformer', r'Attention', r'BERT', r'GPT',
            r'Diffusion', r'扩散模型', r'Stable Diffusion', r'Midjourney',
            r'PyTorch', r'TensorFlow', r'PaddlePaddle', r'JAX',
            r'模型训练', r'推理优化', r'模型量化', r'模型压缩',
            r'Fine-tuning', r'微调', r'RAG', r'检索增强生成',
            r'Prompt', r'提示工程', r'Chain-of-Thought', r'CoT',
            r'Agent', r'智能体', r'AI Agent', r'Tool Use',
            r'LangChain', r'LlamaIndex', r'LangSmith', r'LlamaIndex',
            r'向量数据库', r'Milvus', r'Pinecone', r'Chroma', r'FAISS'
        ]
        
        ai_app = [
            r'AI应用开发', r'AI开发', r'AI产品', r'AI落地',
            r'LLM应用', r'大模型应用', r'生成式AI应用',
            r'对话系统', r'Chatbot', r'智能客服', r'AI助手',
            r'多模态应用', r'AI绘画', r'AI写作', r'AI翻译',
            r'智能问答', r'知识库', r'文档理解', r'文本生成',
            r'图像生成', r'视频生成', r'TTS', r'STT',
            r'OpenAI', r'ChatGPT', r'Claude', r'文心一言', r'通义千问',
            r'扣子', r'Coze', r'Dify', r'FastGPT', r'MaxKB'
        ]
        
        deploy = [
            r'模型部署', r'推理服务', r'模型服务', r'MLOps',
            r'TensorRT', r'ONNX', r'ONNX Runtime', r'Triton', r'vLLM',
            r'FastAPI', r'Flask', r'Django', r'Streamlit', r'Gradio',
            r'Docker', r'Kubernetes', r'K8s', r'容器化',
            r'API服务', r'RESTful', r'gRPC', r'WebSocket',
            r'云原生', r'Serverless', r'边缘计算'
        ]
        
        general = [
            r'Python', r'Java', r'C\+\+', r'JavaScript', r'TypeScript',
            r'Git', r'Linux', r'SQL', r'NoSQL', r'MySQL', r'PostgreSQL',
            r'MongoDB', r'Redis', r'微服务', r'分布式', r'高并发',
            r'数据采集', r'数据标注', r'数据集构建', r'Eval', r'评估'
        ]
        
        categories = [
            ("AI核心技术", ai_core),
            ("AI应用开发", ai_app),
            ("部署工程化", deploy),
            ("通用基础", general)
        ]
        
        result_parts = []
        for category_name, patterns in categories:
            found = []
            for pattern in patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    found.append(pattern)
            if found:
                result_parts.append(f"{category_name}: {'; '.join(sorted(set(found)))}")
        
        return " | ".join(result_parts) if result_parts else ""

    def parse_job_detail(self,result):
        zp_data = (result or {}).get('zpData') or {}
        job_info = zp_data.get('jobInfo') or {}
        brand_info = zp_data.get('brandComInfo') or {}
        
        # 提取工作介绍
        post_description = self._clean_text(job_info.get('postDescription', ''))
        
        # 优先使用 jobDesc（职位描述），其次从 postDescription 中提取
        job_desc = job_info.get('jobDesc', '')
        if not job_desc:
            job_desc = job_info.get('jobRequire', '')
        
        # 清理 jobDesc
        tech_requirements = self._clean_text(job_desc) if job_desc else ""
        
        # 如果 jobDesc 为空，尝试从 postDescription 中提取技术关键词
        if not tech_requirements and post_description:
            tech_requirements = self._extract_tech_requirements_from_description(post_description)
        
        return{
            "工作介绍":post_description,
            "工作详细地址":self._clean_text(job_info.get('address', '')),
            "公司": self._best_company_name(
                brand_info.get('brandName'),
                brand_info.get('companyName'),
                brand_info.get('name'),
            ),
            "公司介绍":self._clean_text(brand_info.get('introduce', '')),
            "技术要求":tech_requirements
        }
    def is_relevant(self,job_name, skills=None):
        job_name = str(job_name or '')
        whitelist = [
        'AI应用开发', '人工智能', '机器学习', '深度学习',
        '大模型', 'LLM', 'NLP', '自然语言处理',
        '计算机视觉', '算法工程师', '算法', '智能体',
        'Agent', 'Python', 'PyTorch', 'Transformer', '模型',
        'AI', 'ai',
        'AIGC', '生成式AI', '生成式人工智能', '多模态',
        '模型训练', '推理优化', 'MLOps', '提示工程',
        'Prompt', 'RAG', '知识图谱', '语音识别',
        '图像识别', '人脸识别', '目标检测', 'OCR',
        '自动驾驶', '机器人', '大语言模型', 'AI工程师',
        '机器学习工程师', '深度学习工程师', 'NLP工程师',
        '计算机视觉工程师', '算法开发', 'AI开发', '智能开发',
        '扣子', 'Coze', 'Dify', 'OpenClaw', 'Claude',
        '飞书', '工作流', '图像流', '智能体搭建', '智能体开发',
        'AI应用开发工程师', '大模型应用开发工程师', 'RAG/Agent开发工程师', 'AI全栈开发工程师',
        '大模型应用', 'AI全栈', 
    ]
        for kw in whitelist:
            if kw.lower() in job_name.lower():
                return True
        # 标题不命中时再查列表页技能标签（只扩召回，不新增拦截）
        for skill in skills or []:
            text = str(skill or '')
            for kw in whitelist:
                if kw.lower() in text.lower():
                    return True
        return False

    @staticmethod
    def _is_blacklisted_company(company_name):
        """过滤掉人力资源/外包/劳务派遣等非直招公司"""
        if not company_name:
            return False
        
        company_name = str(company_name)
        
        # 公司名包含"某"的（非直招，外包/人力公司常匿名）
        if '某' in company_name:
            return True
        
        # 黑名单关键词
        blacklist_keywords = [
            '人力资源', '人力', '劳务', '派遣', '外包', '企业管理',
            '信息咨询', '商务咨询', '管理咨询', '人才', '猎头',
            '某中型通信/网络设备', '某中型通信',
            '某大型人工智能智能驾驶解决方案公司'
        ]
        for keyword in blacklist_keywords:
            if keyword in company_name:
                return True
        
        return False

    def _human_click_job_action(self, job_list):
        """兼容旧采集入口，复用统一的轻量列表浏览。"""
        self._human_navigate_interlude(job_list)

    def _human_enter_detail_action(self, job_list):
        """兼容旧采集入口，不再额外打开详情或收藏岗位。"""
        self._human_navigate_interlude(job_list)

    def _begin_human_browse(self):
        """Called under browser_lock; all optional browsing shares one cooldown."""
        if not getattr(self, 'humanize_enabled', True):
            return False
        stop_event = getattr(self, 'stop_event', None)
        if stop_event is not None and stop_event.is_set():
            return False
        now = time.monotonic()
        last = getattr(self, '_last_human_browse_at', None)
        if last is not None and now - last < Config['human_browse_cooldown']:
            return False
        if not self._is_search_page(self.page.url):
            return False
        self._last_human_browse_at = now
        return True

    def _human_navigate_interlude(self, job_list):
        """在主流程安全节点执行一次列表浏览，不修改搜索筛选条件。"""
        if not getattr(self, 'humanize_enabled', True) or not job_list:
            return
        with self.browser_lock:
            started = False
            try:
                if not self._begin_human_browse():
                    return
                started = True
                action_type = random.choice(['quick_scan', 'scroll_list'])

                if action_type == 'quick_scan':
                    print(" [拟人浏览] 快速扫描列表")
                    self.page.scroll.to_top()
                    time.sleep(random.uniform(0.3, 0.8))
                    for _ in range(random.randint(8, 15)):
                        if random.random() < 0.15:
                            self.page.scroll.up(random.randint(30, 80))
                            time.sleep(random.uniform(0.2, 0.5))
                        else:
                            self.page.scroll.down(random.randint(25, 60))
                            time.sleep(random.uniform(0.15, 0.4))
                    time.sleep(random.uniform(1.0, 2.5))

                elif action_type == 'scroll_list':
                    print(" [拟人浏览] 上下滚动浏览")
                    for _ in range(random.randint(3, 6)):
                        direction = random.choice(['down', 'up'])
                        distance = random.randint(50, 200)
                        if direction == 'down':
                            self.page.scroll.down(distance)
                        else:
                            self.page.scroll.up(distance)
                        time.sleep(random.uniform(0.5, 1.5))
                    time.sleep(random.uniform(1, 2))

            except Exception as e:
                print(f"  [拟人浏览] 异常: {e}")
            finally:
                if started:
                    self._last_human_browse_at = time.monotonic()

    def crawl(self,max_pages,keyword:str=Config['keyword']):
        if os.path.exists(Config["output_file"]):
            try:
                with open(Config["output_file"], 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        job_id = (row.get('encryptJobId') or '').strip()
                        if job_id:
                            self.seen_job_ids.add(job_id)
                print(f" 历史库加载完成，已过滤 {len(self.seen_job_ids)} 条旧数据")
            except (OSError, csv.Error) as exc:
                print(f"历史数据读取失败，将从空集合开始: {exc}")
        self.start_heartbeat()#启动心跳
        print("开始采集")
        consecutive_empty=0
        for page in range(1,max_pages+1):
            print(f"\n第{page}页，获取列表中")
            list_result=self.api_job_list(page=page,keyword=keyword)
            if not list_result:
                print(f"{page}页列表获取失败")
                break
            job_list=((list_result.get('zpData') or {}).get('jobList') or [])
            if not job_list:
                print("没有更多岗位了")
                break
            self.stats['page'] += 1
            self.stats['jobs_fetched'] += len(job_list)
            new_jobs = []#检测是否有新岗位
            for job in job_list:
                encrypt_job_id = job.get('encryptJobId')
                if encrypt_job_id not in self.seen_job_ids:
                    new_jobs.append(job)
            # 白名单过滤
            relevant_jobs = []
            filtered_count = 0
            for job in new_jobs:
                if self.is_relevant(job.get('jobName'), job.get('skills')):
                    relevant_jobs.append(job)
                else:
                    filtered_count += 1
                    print(f"白名单过滤: {job.get('jobName', '未知岗位')}")
            # 检测连续无新相关岗位
            if len(relevant_jobs) == 0:
                consecutive_empty += 1
                print(f"本页 {len(job_list)} 个岗位全部重复或不相关，连续 {consecutive_empty} 页")
                if consecutive_empty >= 5:
                    print("连续5页无新岗位，停止采集")
                    break
                continue
            else:
                consecutive_empty = 0
                print(f"本页新岗位数: {len(relevant_jobs)}/{len(job_list)}")
            for idx,job in enumerate(relevant_jobs,1):
                encrypt_job_id = job.get('encryptJobId')
                security_id = job.get('securityId')
                job_name = job.get('jobName', '')
                salary = job.get('salaryDesc', '')
                company = job.get('brandName', '')
                
                # 立即黑名单检查：用列表页公司名，不等详情页
                if self._is_blacklisted_company(company):
                    print(f"  [过滤] 跳过黑名单公司: {company}")
                    continue
                if self._is_truncated_name(company):
                    page_company = self._company_name_from_detail_page(job)
                    company = self._best_company_name(company, page_company)
                salary_fields = self._parse_salary(salary)
                experience = job.get('jobExperience', '')
                degree = job.get('jobDegree', '')
                location_fields = self._split_location(job)
                print(f"\n[{idx}/{len(job_list)}] {job_name}")
                print(f"       {salary} | {company}")
                
                # 看到岗位后停顿一下，模拟阅读列表
                time.sleep(random.uniform(0.8, 1.5))
                
                job_data={
                    'encryptJobId':encrypt_job_id,
                    '工作名称':job_name,
                    "工资":salary,
                    **salary_fields,
                    "学历要求":degree,
                    "技术要求":self._format_list(job.get('skills', [])),
                    "工作经验要求":experience,
                    "经验下限年":self._parse_experience(experience),
                    "学历等级":self._degree_level(degree),
                    "工作性质":self._classify_job_type(job),
                    "工作介绍":'',
                    "工作区域":''.join(location_fields.values()),
                    **location_fields,
                    '工作详细地址':'',
                    "详情链接":f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html",
                    "公司":company,
                    '公司阶段':job.get('brandStageName', ''),
                    '公司行业':job.get('brandIndustry', ''),
                    '公司规模':job.get('brandScaleName', ''),
                    '公司介绍':"",
                    '公司福利':self._format_list(job.get('welfareList', []))
                }
                if security_id:
                    # 准备获取详情前停顿，模拟点击前的犹豫
                    time.sleep(random.uniform(0.5, 1.2))
                    
                    detail_result=None
                    for retry in range(2):
                        detail_result=self.api_job_detail(security_id=security_id)
                        if detail_result:
                            break
                        if retry<1:
                            print(f"获取详情失败，发送紧急信号，{Config['retry_delay']}秒后二次重试")
                            self.urgent_event.set()
                            time.sleep(Config["retry_delay"])
                            self.get_cookie_headers()
                    if detail_result:
                        detail_data=self.parse_job_detail(detail_result)
                        
                        # 智能合并技术要求：优先详情，补充列表
                        list_skills = self._format_list(job.get('skills', []))
                        detail_tech = detail_data.get('技术要求', '')
                        
                        if detail_tech:
                            # 详情有技术要求，以详情为准
                            final_tech = detail_tech
                        elif list_skills:
                            # 详情没有，使用列表的 skills
                            final_tech = list_skills
                        else:
                            final_tech = ""
                        
                        detail_data['技术要求'] = final_tech
                        detail_company = detail_data.pop('公司', '')
                        job_data.update(detail_data)
                        if detail_company:
                            # 与并行版保持一致：优先保留列表接口的公司名；
                            # 只有列表名为空或被省略时，才使用详情接口名称。
                            job_data['公司'] = self._best_company_name(
                                job_data.get('公司'), detail_company
                            )
                        # 详情内容可能包含列表接口没有提供的工作性质信息。
                        job_data["工作性质"] = self._classify_job_type(job_data)
                        self.stats['details_success'] += 1
                        
                        # 详情解析完成后停顿，模拟阅读详情页
                        time.sleep(random.uniform(1.0, 2.0))
                    else:
                        print("详情获取失败")
                else:
                    print("缺少securityId")
                if encrypt_job_id:
                    self.seen_job_ids.add(encrypt_job_id)
                
                # 过滤掉黑名单公司
                if self._is_blacklisted_company(job_data.get('公司', '')):
                    print(f"  [过滤] 跳过黑名单公司: {job_data.get('公司', '')}")
                    continue
                
                self.all_jobs.append(job_data)
                
                # Legacy milestones use the same browsing entry and cooldown.
                self.click_job_count += 1
                if self.click_job_count % 3 == 0 or self.click_job_count % 7 == 0:
                    self._human_navigate_interlude(job_list)
                
                delay=random.uniform(*Config["job_delay"])
                time.sleep(delay)
            if page<max_pages:
                # 翻页前插入拟人浏览，而不是干等
                print("翻页前拟人浏览")
                # 翻页前只做随机浏览，不再触发点击职位/进入详细，避免重复叠加
                self._human_navigate_interlude(job_list)
                time.sleep(random.uniform(*Config["page_delay"]))
                # 翻页后额外停顿，模拟加载新页面
                time.sleep(random.uniform(1.0, 2.0))
        print(f"   采集页数: {self.stats['page']}")
        print(f"   获取岗位: {self.stats['jobs_fetched']}")
        print(f"   详情成功: {self.stats['details_success']}")
        print(f"   实际入库: {len(self.all_jobs)}")
        return self.all_jobs
    def save_to_csv(self, filename: str = "boss_jobs.csv"):
        """保存为 CSV 文件"""
        if not self.all_jobs:
            print(" 没有数据可保存")
            return

        file_exists = os.path.isfile(filename) and os.path.getsize(filename) > 0
        if file_exists:
            # 旧版本没有“工作性质”字段时，先迁移表头，避免新数据丢列。
            with open(filename, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                old_fields = reader.fieldnames or []
                old_rows = list(reader)
            if old_fields != CSV_FIELDS:
                for row in old_rows:
                    row.setdefault("工作性质", self._classify_job_type(row))
                with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(
                        f, fieldnames=CSV_FIELDS, extrasaction='ignore'
                    )
                    writer.writeheader()
                    writer.writerows(old_rows)
                print(f"已将旧 CSV 字段迁移为新版格式: {filename}")

        with open(filename, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            
            writer.writerows(self.all_jobs)
        print(f" 数据已追加: {filename}")
                
    #运行
    def run(self):
        try:
            self.login()#登陆
            
            self.crawl(max_pages=Config["max_pages"], keyword=Config["keyword"])
            if self.all_jobs:
                self.save_to_csv(Config["output_file"])
        except KeyboardInterrupt:
            print("\n 用户中断")
            self.save_to_csv(Config["output_file"])
        except Exception as e:
            print(f" 程序异常: {e}")
            import traceback
            traceback.print_exc()
            self.save_to_csv(Config["output_file"])
        finally:
            self.stop_heartbeat()
            # 清理
            try:
                self.page.quit()
            except:
                pass
            print(" 程序结束")


if __name__ == "__main__":
    spider = BossDP()
    spider.run()
