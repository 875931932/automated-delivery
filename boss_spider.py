from DrissionPage import ChromiumPage,ChromiumOptions
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
from urllib.parse import quote, urlencode
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
    "heart_time": 15,
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
    def _kill_stale_chrome(profile_dir):
        """清理仍占用本程序专用 profile 的残留 Chrome（上次异常退出/面板强杀后常见）。
        同一个 --user-data-dir 只允许一个实例：残留进程会让新启动的 Chrome 直接转发 URL 后退出，
        结果 DrissionPage 连不上新端口、页面始终不跳转。
        只匹配「含本 profile 路径且带调试端口」的进程，不影响用户日常 Chrome。"""
        import subprocess
        try:
            env = os.environ.copy()
            env['BOSS_PROFILE'] = profile_dir
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like \"*$env:BOSS_PROFILE*\" "
                "-and $_.CommandLine -like '*--remote-debugging-port*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
                "$_.ProcessId }"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                env=env, capture_output=True, text=True, timeout=20,
            )
            killed = [x.strip() for x in (result.stdout or '').splitlines() if x.strip()]
            if killed:
                print(f"[浏览器] 清理残留 Chrome 进程: {', '.join(killed)}")
                time.sleep(1.5)
        except Exception as exc:
            print(f"[浏览器] 清理残留进程失败（可忽略）: {exc}")

    def __init__(self):
        self.urgent_event=threading.Event()#设置紧急心跳信号
        self.stop_event = threading.Event()
        self.browser_lock=threading.RLock()#心跳线程和主线程共用浏览器
        self.click_job_count = 0  # 点击职位计数
        self.enter_detail_count = 0  # 进入详细页面计数
        # 登录态保持开关：开启时 UA 固定 + 持久 profile；关闭时随机 UA（更隐蔽但需重新登录）
        self.keep_login = Config.get("keep_login", True)
        if self.keep_login:
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

        co=ChromiumOptions()
        co.set_browser_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        co.set_local_port(self._pick_free_port())  # 随机空闲端口，替代 auto_port（见 _pick_free_port 注释）
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')#初始化了浏览器模拟浏览器指纹
        co.set_user_agent(self.user_agent)
        co.set_argument('--window-size','1920,1080')
        # 窗口被用户最小化后，后台标签仍要正常加载，不被 Chrome 节流冻结
        co.set_argument('--disable-background-timer-throttling')
        co.set_argument('--disable-backgrounding-occluded-windows')
        co.set_argument('--disable-renderer-backgrounding')

        # 使用独立 profile，避免污染主 Chrome（必须用官方 API，set_argument 会与内部默认值冲突）
        if profile_dir:
            self._kill_stale_chrome(profile_dir)  # 先清理残留实例，否则新窗口不会跳转
            co.set_user_data_path(profile_dir)
            # 使用 Default profile，确保登录态持久化
            co.set_argument('--profile-directory=Default')
        
        self.page=ChromiumPage(co)
        self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source='''
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
    def login(self):
        #登陆账号，准备获取cookies
        self.page.get(Config['start_url'])
        print("准备登陆")
        input("登陆完成后回车继续任务")
        #同步初始cookies和headers
        self.get_cookie_headers()
        
    def get_cookie_headers(self):
        try:
            with self.browser_lock:
                cookies_list = self.page.cookies()
            # 将列表转换为字典
            cookies_dict = {}
            for cookie in cookies_list:
                if 'name' in cookie and 'value' in cookie:
                    cookies_dict[cookie['name']] = cookie['value']
            self.session.cookies.clear()
            for k, v in cookies_dict.items():
                self.session.cookies.set(k, v)
            self.current_cookies = cookies_dict
            self.session.cookies.update(cookies_dict)
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

    # ================= 心跳线程（定期模拟操作保活） =================
    def start_heartbeat(self):
        """后台线程：定期执行拟人操作，维持 cookies 有效"""
        def heartbeat_task():
            print(f"[心跳线程] 启动，每 {Config['heart_time']} 秒执行一次拟人操作\n")
            time.sleep(5)

            while not self.stop_event.is_set():
                is_urgent = self.urgent_event.wait(timeout=Config['heart_time'])
                if is_urgent:
                    print(f"【心跳】收到紧急信号，立刻执行")
                    self.urgent_event.clear()
                try:
                    # 尝试获取浏览器锁，最多等5秒，超时就跳过本轮不阻塞主流程
                    if not self.browser_lock.acquire(timeout=5):
                        print(f" [心跳] 浏览器正忙，跳过本轮")
                        continue
                    try:
                        current_url = self.page.url
                        is_homepage = current_url == "https://www.zhipin.com/"
                        if is_homepage:
                            print(f" [心跳] 检测到跳转到首页，重新加载列表页...")
                            self.page.get(Config['start_url'])
                            time.sleep(3)
                            self.get_cookie_headers()
                            continue

                        # 拟人行为可选：关闭时只保留"首页恢复"这一保底功能
                        if not getattr(self, 'humanize_enabled', True):
                            continue

                        # 随机选择一种拟人行为（轻量为主，效率优先）
                        action_type = random.choices(
                            ['quick_scan', 'hesitate_click', 'deep_read',
                             'compare_jobs', 'filter_check', 'favorite_job'],
                            weights=[32, 28, 15, 10, 5, 10],
                            k=1
                        )[0]

                        start_time = time.time()
                        if action_type == 'quick_scan':
                            self._human_quick_scan()
                        elif action_type == 'hesitate_click':
                            self._human_hesitate_click()
                        elif action_type == 'deep_read':
                            self._human_deep_read()
                        elif action_type == 'compare_jobs':
                            self._human_compare_jobs()
                        elif action_type == 'filter_check':
                            self._human_filter_check()
                        elif action_type == 'favorite_job':
                            self._human_favorite_job()

                        elapsed = time.time() - start_time
                        if elapsed > 20:
                            print(f" [心跳] ⚠️ 心跳行为超时 ({elapsed:.1f}s)，强制跳过本轮")
                            try:
                                self.page.get(Config['start_url'])
                                time.sleep(2)
                                self.get_cookie_headers()
                            except Exception:
                                pass
                    finally:
                        self.browser_lock.release()

                except Exception as e:
                    print(f" 心跳线程异常: {e}")
                    try:
                        self.browser_lock.release()
                    except Exception:
                        pass
        thread = threading.Thread(target=heartbeat_task, daemon=True)
        thread.start()

    # ================= 拟人操作 =================
    def _human_quick_scan(self):
        """快速扫描列表页：快速滚几屏，什么都不点（模拟快速筛选，占比30%）"""
        print(" [心跳] 快速扫描列表")
        # 先快速向上滚到顶部（模拟刚回来从新看）
        self.page.scroll.to_top()
        time.sleep(random.uniform(0.3, 0.8))

        scan_count = random.randint(8, 15)
        for i in range(scan_count):
            # 偶尔向上回滚（模拟看到感兴趣的又回去看）
            if random.random() < 0.15:
                self.page.scroll.up(random.randint(30, 80))
                time.sleep(random.uniform(0.2, 0.5))
            else:
                self.page.scroll.down(random.randint(25, 60))
                time.sleep(random.uniform(0.15, 0.4))
        time.sleep(random.uniform(1.0, 2.5))

    def _human_hesitate_click(self):
        """犹豫点击：看到感兴趣岗位，犹豫一会，点进去快速看，返回（占比25%）"""
        print(" [心跳] 犹豫点击岗位")
        job_list_ele = self.page.ele('.rec-job-list', timeout=5)
        if not job_list_ele:
            return
        jobs = job_list_ele.eles('.job-card-box', timeout=3)
        if not jobs:
            return

        # 偏好前10个岗位（简历预览区域通常在前面的岗位最先吸引注意）
        idx = random.randint(0, min(9, len(jobs) - 1))
        target_job = jobs[idx]
        job_name_ele = target_job.ele(".job-name", timeout=2)
        job_name = job_name_ele.text if job_name_ele else f"岗位{idx+1}"

        # 犹豫期：先滚动几次靠近目标，偶尔滚过头再回来
        for _ in range(random.randint(2, 4)):
            dist = random.randint(20, 60)
            if random.random() < 0.3:
                # 30%概率滚过头（模拟看走眼）
                self.page.scroll.down(dist + random.randint(20, 40))
                time.sleep(random.uniform(0.2, 0.5))
                self.page.scroll.up(random.randint(20, 40))
            else:
                self.page.scroll.down(dist)
            time.sleep(random.uniform(0.3, 0.8))
        time.sleep(random.uniform(0.8, 2.0))  # 停顿犹豫

        # 点击
        print(f" [心跳] 点击: {job_name}")
        target_job.click()
        time.sleep(random.uniform(1.5, 3))

        # 详情页快速浏览
        for _ in range(random.randint(1, 3)):
            self.page.scroll.down(random.randint(40, 100))
            time.sleep(random.uniform(0.3, 0.8))
        time.sleep(random.uniform(1.0, 3.0))
        # 不做返回列表操作，模拟在列表页内查看详情（同页面切换）

    def _human_deep_read(self):
        """深度阅读：认真看一个岗位，来回滚动（权重15%，缩短版）"""
        print(" [心跳] 深度阅读岗位")
        job_list_ele = self.page.ele('.rec-job-list', timeout=5)
        if not job_list_ele:
            return
        jobs = job_list_ele.eles('.job-card-box', timeout=3)
        if not jobs:
            return

        idx = random.randint(0, min(7, len(jobs) - 1))
        target_job = jobs[idx]
        job_name_ele = target_job.ele(".job-name", timeout=2)
        job_name = job_name_ele.text if job_name_ele else f"岗位{idx+1}"

        try:
            job_id = target_job.ele('tag:a', timeout=2).link
            if job_id:
                job_id = job_id.split('/')[-1].replace('.html', '')
        except:
            job_id = None

        if not job_id:
            return

        print(f" [心跳] 深度阅读: {job_name}")
        detail_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
        self.page.get(detail_url)
        time.sleep(random.uniform(2, 4))

        # 来回滚动阅读（缩短：2-4轮，5秒内完成）
        scroll_rounds = random.randint(2, 4)
        for r in range(scroll_rounds):
            for _ in range(random.randint(1, 3)):
                self.page.scroll.down(random.randint(60, 120))
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(0.3, 1.0))
            for _ in range(random.randint(1, 2)):
                self.page.scroll.up(random.randint(50, 100))
                time.sleep(random.uniform(0.2, 0.6))

        time.sleep(random.uniform(2, 5))  # 阅读停留

        # 深度阅读时"感兴趣"：AI相关岗位有概率收藏
        if self._is_ai_related(job_name) and random.random() < 0.1:
            try:
                fav_btn = self.page.ele('.op-btn.op-btn-like', timeout=3)
                if fav_btn and '已收藏' not in fav_btn.text:
                    fav_btn.click()
                    print(f" [心跳-感兴趣] 收藏: {job_name}")
                    time.sleep(random.uniform(1, 2))
            except Exception:
                pass

        print(" [心跳] 返回列表")
        self.page.get(Config['start_url'])
        time.sleep(random.uniform(2, 4))
        self.get_cookie_headers()

    def _human_compare_jobs(self):
        """对比操作：随机看1-2个岗位（权重12%，缩短版）"""
        print(" [心跳] 对比岗位")
        job_list_ele = self.page.ele('.rec-job-list', timeout=5)
        if not job_list_ele:
            return
        jobs = job_list_ele.eles('.job-card-box', timeout=3)
        if not jobs or len(jobs) < 2:
            return

        # 随机看 1-2 个岗位
        job_list_data = jobs[:min(8, len(jobs))]
        compare_count = random.randint(1, min(2, len(job_list_data)))
        selected = random.sample(job_list_data, compare_count)

        for i, job in enumerate(selected, 1):
            job_name_ele = job.ele(".job-name", timeout=2)
            job_name = job_name_ele.text if job_name_ele else f"岗位{i}"
            print(f" [心跳] 查看对比: {job_name}")
            job.click()
            time.sleep(random.uniform(1.5, 3))
            for _ in range(random.randint(1, 3)):
                self.page.scroll.down(random.randint(40, 100))
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(1.0, 2.5))
            self.page.get(Config['start_url'])
            time.sleep(random.uniform(1.5, 3))
            self.get_cookie_headers()

    def _human_filter_check(self):
        """切换筛选条件（占比10%）：模拟用户调整筛选器"""
        print(" [心跳] 检查筛选条件")
        # 偶尔切换一下工作性质筛选（实习/全职切换）
        try:
            job_type_ele = self.page.ele('text:工作性质', timeout=3)
            if job_type_ele:
                parent = job_type_ele.parent()
                # 点击展开/收起筛选
                parent.click()
                time.sleep(random.uniform(1.0, 2.0))
                # 可能点一个筛选选项
                options = self.page.eles('.filter-checkbox', timeout=2)
                if options:
                    random.choice(options).click()
                    time.sleep(random.uniform(1.0, 2.0))
                # 关闭筛选面板
                close_btn = self.page.ele('.btn-sure', timeout=2) or \
                            self.page.ele('.filter-confirm', timeout=2)
                if close_btn:
                    close_btn.click()
                    time.sleep(random.uniform(1.0, 2.0))
        except:
            pass

        self.get_cookie_headers()

    def _human_favorite_job(self):
        """随机收藏/取消收藏岗位（占比20%）：只收藏AI应用相关岗位"""
        print(" [心跳-收藏] 随机收藏岗位操作")
        try:
            # 查找列表页的职位卡片
            job_cards = self.page.eles('.job-card-box', timeout=5)
            if not job_cards or len(job_cards) == 0:
                print(" [心跳-收藏] 未找到岗位卡片")
                return

            # 随机选1-2个卡片
            count = random.randint(1, min(2, len(job_cards)))
            targets = random.sample(job_cards, count)

            for card in targets:
                # 获取岗位名称
                name_ele = card.ele('.job-name', timeout=2)
                job_name = name_ele.text if name_ele else "未知岗位"

                # 判断是否为 AI 应用相关岗位
                if not self._is_ai_related(job_name):
                    print(f" [心跳-收藏] 跳过（非AI岗位）: {job_name}")
                    continue

                # 随机决定：收藏 还是 取消收藏
                will_favorite = random.random() < 0.7  # 70%收藏，30%取消

                card.click()
                time.sleep(random.uniform(1.0, 2.0))

                if will_favorite:
                    # 点击收藏按钮
                    fav_btn = self.page.ele('.op-btn.op-btn-like', timeout=3)
                    if fav_btn and '已收藏' not in fav_btn.text:
                        fav_btn.click()
                        print(f" [心跳-收藏] 收藏: {job_name}")
                        time.sleep(random.uniform(3, 6))  # 阅读一会儿
                        # 取消收藏
                        fav_btn = self.page.ele('.op-btn.op-btn-like', timeout=3)
                        if fav_btn and '已收藏' in fav_btn.text:
                            fav_btn.click()
                            time.sleep(random.uniform(0.5, 1.0))
                            print(f" [心跳-收藏] 取消收藏: {job_name}")
                    else:
                        print(f" [心跳-收藏] 已收藏或按钮不存在: {job_name}")
                else:
                    print(f" [心跳-收藏] 本次不操作: {job_name}")

                # 返回列表
                self.page.get(Config['start_url'])
                time.sleep(random.uniform(2, 4))
                self.get_cookie_headers()

        except Exception as e:
            print(f" [心跳-收藏] 异常: {e}")
            try:
                self.page.get(Config['start_url'])
                time.sleep(2)
                self.get_cookie_headers()
            except Exception:
                pass

    def _is_ai_related(self, job_name: str) -> bool:
        """判断岗位是否为 AI 应用相关"""
        ai_keywords = Config.get('ai_whitelist', [
            'AI应用开发', '大模型应用', 'RAG', 'Agent开发', 'AI全栈',
            'AI应用', '人工智能', '机器学习', '深度学习', '大模型',
            'AIGC', 'AI工程师', 'AI开发', '智能体', 'NLPer',
            'AI产品', 'NLP', 'LLM', '提示词工程', '多模态',
            'AI Agent', 'AI应用工程师', '大模型应用开发',
            'RAG开发', 'AI应用开发工程师', 'AI全栈开发工程师',
            '大模型开发', 'AI研发', '机器学习工程师', '深度学习工程师',
        ])
        name_lower = job_name.lower()
        return any(kw.lower() in name_lower for kw in ai_keywords)

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

    def _request_json(self, method: str, url: str, label: str, **kwargs):
        """请求 JSON 接口，统一处理网络、HTTP、JSON 和业务错误。"""
        # 检查 API 请求上限
        if self.api_request_count >= self.max_api_requests:
            print(f"⚠️ 已达到单次最大 API 请求数上限 ({self.max_api_requests})，停止请求")
            return None
        
        # 请求间随机延迟，模拟真人操作节奏
        delay = random.uniform(1.5, 4.0)
        time.sleep(delay)
        
        for attempt in range(Config["max_retries"]):
            try:
                # 正常情况下复用当前登录态；只有首次请求或重试时重新同步。
                if not self.current_cookies and not self.get_cookie_headers():
                    raise requests.RequestException("登录态同步失败")
                
                # 增加请求计数
                self.api_request_count += 1
                current_count = self.api_request_count
                
                # 每 20 次请求打印一次计数，方便监控
                if current_count % 20 == 0:
                    print(f"  [API] 累计请求 {current_count} 次")
                
                response = self.session.request(
                    method, url, headers=self.current_headers,
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
    def api_job_detail(self,security_id:str):#通过api获得详情信息
        url=f"{Config['base_url']}/wapi/zpgeek/job/detail.json"
        return self._request_json(
            "get", url, label="详情", params={"securityId": security_id}
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
        """每3次点击触发：犹豫点击行为（新拟人逻辑）"""
        if not job_list:
            return
        with self.browser_lock:
            try:
                job_list_ele = self.page.ele('.rec-job-list', timeout=5)
                if not job_list_ele:
                    return
                jobs = job_list_ele.eles('.job-card-box', timeout=3)
                if not jobs:
                    return

                # 偏好前10个岗位
                idx = random.randint(0, min(9, len(jobs) - 1))
                target_job = jobs[idx]
                job_name_ele = target_job.ele(".job-name", timeout=2)
                job_name = job_name_ele.text if job_name_ele else f"岗位{idx+1}"

                # 犹豫期：先滚动靠近目标，偶尔滚过头
                for _ in range(random.randint(2, 4)):
                    dist = random.randint(20, 60)
                    if random.random() < 0.3:
                        self.page.scroll.down(dist + random.randint(20, 40))
                        time.sleep(random.uniform(0.2, 0.5))
                        self.page.scroll.up(random.randint(20, 40))
                    else:
                        self.page.scroll.down(dist)
                    time.sleep(random.uniform(0.3, 0.8))
                time.sleep(random.uniform(0.8, 2.0))

                print(f" [拟人-点击职位] 点击: {job_name}")
                target_job.click()
                time.sleep(random.uniform(1.5, 3))

                # 快速浏览后返回
                for _ in range(random.randint(1, 3)):
                    self.page.scroll.down(random.randint(40, 100))
                    time.sleep(random.uniform(0.3, 0.8))
                time.sleep(random.uniform(1.0, 3.0))
                print(" [拟人-点击职位] 返回列表页")
                self.page.get(Config['start_url'])
                time.sleep(random.uniform(1.5, 3))
                self.get_cookie_headers()
            except Exception as e:
                print(f"  [拟人-点击职位] 异常: {e}")
                try:
                    self.page.get(Config['start_url'])
                    time.sleep(2)
                    self.get_cookie_headers()
                except Exception:
                    pass

    def _human_enter_detail_action(self, job_list):
        """每7次点击触发：深度阅读行为（新拟人逻辑）"""
        if not job_list:
            return
        with self.browser_lock:
            try:
                job = random.choice(job_list[:min(8, len(job_list))])
                job_name = job.get('jobName', '')
                job_id = job.get('encryptJobId')

                if job_id:
                    detail_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
                    print(f"  [拟人-深入] 深度阅读: {job_name}")
                    self.page.get(detail_url)
                    time.sleep(random.uniform(2, 4))

                    # 来回滚动阅读
                    scroll_rounds = random.randint(3, 6)
                    for r in range(scroll_rounds):
                        for _ in range(random.randint(2, 4)):
                            self.page.scroll.down(random.randint(60, 150))
                            time.sleep(random.uniform(0.4, 1.0))
                        time.sleep(random.uniform(0.5, 1.5))
                        for _ in range(random.randint(1, 3)):
                            self.page.scroll.up(random.randint(50, 120))
                            time.sleep(random.uniform(0.3, 0.8))

                    time.sleep(random.uniform(3, 7))
                    print("  [拟人-深入] 返回列表页")
                    self.page.get(Config['start_url'])
                    time.sleep(random.uniform(2, 4))
                    self.get_cookie_headers()
            except Exception as e:
                print(f"  [拟人-深入] 异常: {e}")
                try:
                    self.page.get(Config['start_url'])
                    time.sleep(2)
                    self.get_cookie_headers()
                except Exception:
                    pass

    def _human_navigate_interlude(self, job_list):
        """翻页前：随机浏览行为（新拟人逻辑）"""
        if not job_list:
            return
        with self.browser_lock:
            try:
                action_type = random.choice(['quick_scan', 'scroll_list', 'open_detail_back', 'check_filters'])

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

                elif action_type == 'open_detail_back':
                    job = random.choice(job_list[:min(10, len(job_list))])
                    job_id = job.get('encryptJobId')
                    if job_id:
                        detail_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
                        print(f" [拟人浏览] 快速打开: {job.get('jobName', '')}")
                        self.page.get(detail_url)
                        time.sleep(random.uniform(2, 4))
                        for _ in range(random.randint(1, 3)):
                            self.page.scroll.down(random.randint(50, 150))
                            time.sleep(random.uniform(0.3, 0.8))
                        time.sleep(random.uniform(1, 2))
                        print(" [拟人浏览] 返回列表")
                        self.page.get(Config['start_url'])
                        time.sleep(random.uniform(1.5, 3))
                        self.get_cookie_headers()

                elif action_type == 'check_filters':
                    print(" [拟人浏览] 查看筛选条件")
                    self.page.scroll.to_top()
                    time.sleep(random.uniform(0.5, 1.0))
                    try:
                        city_ele = self.page.ele('text:城市', timeout=2)
                        if city_ele:
                            city_ele.click()
                            time.sleep(random.uniform(0.8, 1.5))
                            self.page.get(Config['start_url'])
                            time.sleep(random.uniform(1.5, 3))
                    except:
                        pass
                    self.get_cookie_headers()
            except Exception as e:
                print(f"  [拟人浏览] 异常: {e}")
                try:
                    self.page.get(Config['start_url'])
                    time.sleep(2)
                    self.get_cookie_headers()
                except Exception:
                    pass

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
                        self.page.close()
                else:
                    print("缺少securityId")
                if encrypt_job_id:
                    self.seen_job_ids.add(encrypt_job_id)
                
                # 过滤掉黑名单公司
                if self._is_blacklisted_company(job_data.get('公司', '')):
                    print(f"  [过滤] 跳过黑名单公司: {job_data.get('公司', '')}")
                    continue
                
                self.all_jobs.append(job_data)
                
                # 每3次点击触发一次点击职位行为，每7次点击触发一次进入详细行为
                self.click_job_count += 1
                if self.click_job_count % 3 == 0:
                    print(f"\n  [{idx}/{len(relevant_jobs)}] [拟人] 每3次点击职位行为...")
                    self._human_click_job_action(job_list)
                    self.get_cookie_headers()
                
                if self.click_job_count % 7 == 0:
                    print(f"\n  [{idx}/{len(relevant_jobs)}] [拟人] 每7次点击职位进入详细行为...")
                    self._human_enter_detail_action(job_list)
                    self.get_cookie_headers()
                    # 拟人操作后停顿，模拟回到列表继续浏览
                    time.sleep(random.uniform(2.0, 4.0))
                
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
            self.stop_event.set()
            # 清理
            try:
                self.page.quit()
            except:
                pass
            print(" 程序结束")


if __name__ == "__main__":
    spider = BossDP()
    spider.run()
