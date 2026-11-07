# -*- coding: utf-8 -*-
"""
自动投递桌面工作台（PySide6 / Qt Widgets）

  - 侧边栏导航：候选人画像 / 岗位画像 / 投递结果 / 运行日志 + 各分组配置页
  - 可视化编辑 .env（关键词 / 城市 / AI 阈值 / 每日上限 / 双休与工作时间 / 干跑等）
  - 一键启动 / 停止投递任务（子进程运行 auto_deliver.py）
  - 实时日志窗口 + 投递结果表 + 今日进度

启动: D:\\ProgramData\\miniconda3\\envs\\autodeliver\\python.exe desktop_panel.py
"""
import csv
import difflib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QIntValidator,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QCompleter,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from candidate_profiles import (
    CandidateProfileService,
    CandidateProfileStore,
    InterviewDraft,
    InterviewDraftCacheStore,
    ResumeDigestStore,
    resume_digest_hash,
)
from job_type_logic import normalize_job_type_preference, transition_job_type_preference
from panel_config_logic import CONFIG_WARNINGS, INT_LIMITS, parse_hhmm, validate_config_values
from panel_log_parser import (
    CATEGORY_AI,
    CATEGORY_COLORS,
    CATEGORY_ERROR,
    CATEGORY_NORMAL,
    classify_log_line,
    parse_ai_score,
    parse_filter_stats,
    parse_job_line,
)
from panel_runner import TaskRunner
from panel_styles import ASSETS_DIR, STYLESHEET
from panel_widgets import FlowLayout, WidgetHelpersMixin
from platform_search_filters import platform_filter_options, platform_filter_label
from platform_locations import fetch_platform_districts, load_city_codes

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"
LOG_JSON = BASE_DIR / "deliver_log.json"

# 配置项定义: (key, 分组tab, 标签, 类型, 默认值, 备注)
# 类型: text / int / password / bool / select / multiselect
FIELDS = [
    ("AI_BASE_URL",    "AI 接口", "接口地址", "text", "https://api.deepseek.com/v1", "OpenAI 兼容接口，如 https://api.stepfun.com/step_plan/v1"),
    ("AI_API_KEY",     "AI 接口", "API Key", "password", "", ""),
    ("AI_MODEL",       "AI 接口", "模型名", "text", "deepseek-chat", "如 step-5-preview"),
    ("AI_REASONING_EFFORT", "AI 接口", "思考强度", "select", "low", "low/medium/high；访谈和评分用 low 最快，high 会慢数倍"),
    ("AI_TIMEOUT",     "AI 接口", "请求超时(秒)", "int", "90", ""),
    ("AI_MAX_RETRIES", "AI 接口", "失败重试次数", "int", "2", ""),

    ("DELIVER_KEYWORD",  "筛选与简历", "搜索关键词", "text", "", ""),
    ("CITY_CODE",        "筛选与简历", "在哪个城市找", "select", "101280600", "决定在哪个城市找工作"),
    ("PLATFORM_AREA_FILTER", "筛选与简历", "平台工作区域", "multiselect", "", "区域按当前城市从 BOSS 加载；保存的是平台区域 ID，不选表示不限"),
    ("PLATFORM_JOB_TYPE", "筛选与简历", "平台求职类型", "select", "不限", "平台侧筛选全职、兼职或实习"),
    ("PLATFORM_PAY_TYPE", "筛选与简历", "平台结算方式", "select", "不限", "按日结、周结、月结或完工结筛选"),
    ("PLATFORM_PART_TIME", "筛选与简历", "平台兼职时段", "select", "不限", "仅平台求职类型选「兼职」时生效"),
    ("PLATFORM_EXPERIENCE", "筛选与简历", "平台经验要求", "select", "不限", "按 BOSS 工作经验筛选"),
    ("PLATFORM_DEGREE", "筛选与简历", "平台学历要求", "select", "不限", "按 BOSS 学历筛选"),
    ("PLATFORM_INDUSTRY", "筛选与简历", "平台行业 ID", "text", "", "可选；填写 BOSS 行业分类 ID，例如 100020，留空不限"),
    ("PLATFORM_SCALE", "筛选与简历", "平台公司规模", "select", "不限", "按 BOSS 公司规模筛选"),
    ("MATCH_THRESHOLD",  "筛选与简历", "AI匹配阈值", "int", "70", "0-100，低于该分数不投"),
    ("JOB_TYPE_PREFERENCE", "筛选与简历", "优先岗位性质", "select", "实习", "平台不限时用于队列排序；平台选实习/全职时自动同步，选兼职时不适用"),
    ("RESUME_FILE",      "筛选与简历", "简历文件", "text", "resume.md", "markdown 简历路径"),
    ("DELIVER_MAX_PAGES","筛选与简历", "每轮最多翻几页", "int", "3", "每轮采集的列表页数"),
    ("AREA_FILTER",      "筛选与简历", "本地区域再筛", "text", "", "按行政区/商圈文本再筛一次；一般用上面的平台区域即可"),

    ("REST_DAY_REQUIRE", "工作时间与休息", "休息制度", "select", "不限", "与 JD 明确标注的休息制度不一致时过滤；未知信息放行"),
    ("WORK_TIME_START",  "工作时间与休息", "最早上班时间", "text", "", "如 09:30，JD 上班晚于该值则过滤，留空不启用"),
    ("WORK_TIME_END",    "工作时间与休息", "最晚下班时间", "text", "", "如 19:00，JD 下班晚于该值视为加班过滤，留空不启用"),
    ("WELFARE_REQUIRE",  "工作时间与休息", "期望福利", "multiselect", "", "作为 AI 评分的加分参考；不选表示不限"),

    ("DAILY_LIMIT",   "投递节奏", "每日投递上限", "int", "50", ""),
    ("JOB_DELAY_MIN", "投递节奏", "岗位间隔最小(秒)", "int", "25", ""),
    ("JOB_DELAY_MAX", "投递节奏", "岗位间隔最大(秒)", "int", "50", ""),
    ("HUMAN_EVERY_N", "投递节奏", "每投N个穿插拟人浏览", "int", "5", "0 = 关闭"),

    ("HUMANIZE_ENABLE","拟人行为", "启用心跳拟人浏览", "bool", "true", "关闭后心跳只保留登录态恢复，跑得更快"),
    ("FAVORITE_SCORE", "拟人行为", "收藏评分门槛", "int", "75", "心跳收藏只收藏 AI 匹配分高于该值的岗位"),
    ("DETAIL_DELAY_MIN","拟人行为", "详情页停留最小(秒)", "int", "3", "点开岗位/公司页后的浏览时长"),
    ("DETAIL_DELAY_MAX","拟人行为", "详情页停留最大(秒)", "int", "6", ""),

    ("DRY_RUN",    "测试模式", "干跑模式（不真实投递）", "bool", "false", ""),
    ("TEST_LIMIT", "测试模式", "本轮最多处理岗位数", "int", "0", "0 = 不限"),
    ("LOGIN_WAIT", "测试模式", "登录等待秒数", "int", "0", "0 = 自动检测登录成功后继续；>0 = 最多等N秒"),
    ("KEEP_LOGIN", "测试模式", "保留登录信息", "bool", "true", "固定UA+持久profile，重启免登录；关闭则每次随机UA需重新登录"),

    ("TAVILY_ENABLED", "画像搜索", "用 Tavily 补充岗位市场信息", "bool", "true", "仅用于画像访谈追问；不搜索简历，不自动写入候选人技能"),
    ("TAVILY_API_KEY", "画像搜索", "Tavily API Key", "password", "", "仅岗位方向和职位族会发送给 Tavily"),
    ("TAVILY_TIMEOUT", "画像搜索", "搜索超时(秒)", "int", "12", "搜索失败时继续普通简历访谈"),
]

SELECT_OPTIONS = {
    "REST_DAY_REQUIRE": ["不限", "双休", "单休", "大小周"],
    "AI_REASONING_EFFORT": ["low", "medium", "high"],
    "JOB_TYPE_PREFERENCE": ["实习", "全职"],
    "PLATFORM_JOB_TYPE": ["不限", "全职", "兼职", "实习"],
    **{
        key: platform_filter_options(key)
        for key in (
            "PLATFORM_PAY_TYPE", "PLATFORM_PART_TIME", "PLATFORM_EXPERIENCE",
            "PLATFORM_DEGREE", "PLATFORM_SCALE",
        )
    },
    "PLATFORM_AREA_FILTER": [],
    "WELFARE_REQUIRE": [
        "双休", "五险一金", "带薪年假", "弹性工作",
        "餐补", "住房补贴", "节日福利", "定期体检", "年终奖",
    ],
}
# 城市名 ↔ 平台城市代码（.env 里存代码，界面显示城市名）
CITY_CHOICES = load_city_codes()
CITY_NAME_BY_CODE = {code: name for name, code in CITY_CHOICES.items()}
SELECT_OPTIONS["CITY_CODE"] = list(CITY_CHOICES)

FIELD_BY_KEY = {field[0]: field for field in FIELDS}

# 面板呈现分组：只决定控件出现在哪个页面，不改变 .env 写入顺序。
# 「投递设置」= 用户日常要选/要改的业务参数；「高级设置」= 技术参数。
SETTINGS_SECTIONS = [
    ("模型接口（必填）", ["AI_BASE_URL", "AI_API_KEY", "AI_MODEL"]),
    ("简历与目标岗位", ["RESUME_FILE", "DELIVER_KEYWORD"]),
    ("在哪儿找工作", [
        "CITY_CODE", "PLATFORM_AREA_FILTER",
        "PLATFORM_JOB_TYPE", "PLATFORM_PART_TIME", "PLATFORM_PAY_TYPE",
        "PLATFORM_EXPERIENCE", "PLATFORM_DEGREE", "PLATFORM_INDUSTRY",
        "PLATFORM_SCALE", "JOB_TYPE_PREFERENCE",
    ]),
    ("作息与福利", [
        "REST_DAY_REQUIRE", "WORK_TIME_START", "WORK_TIME_END", "WELFARE_REQUIRE",
    ]),
    ("匹配与投递", ["MATCH_THRESHOLD", "DAILY_LIMIT", "DRY_RUN", "TEST_LIMIT"]),
    ("画像搜索", ["TAVILY_ENABLED", "TAVILY_API_KEY"]),
]
ADVANCED_SECTIONS = [
    ("模型细节", ["AI_REASONING_EFFORT", "AI_TIMEOUT", "AI_MAX_RETRIES", "TAVILY_TIMEOUT"]),
    ("采集细节", ["DELIVER_MAX_PAGES", "AREA_FILTER"]),
    ("投递节奏", ["JOB_DELAY_MIN", "JOB_DELAY_MAX", "HUMAN_EVERY_N"]),
    ("拟人行为（防风控）", [
        "HUMANIZE_ENABLE", "FAVORITE_SCORE", "DETAIL_DELAY_MIN", "DETAIL_DELAY_MAX",
    ]),
    ("登录与调试", ["LOGIN_WAIT", "KEEP_LOGIN"]),
]

PAGE_SUBTITLES = {
    "求职设置": "简历、目标岗位、城市区域、工作性质、作息与福利——只填这几项就能开始投递。",
    "画像查看": "分别查看简历解析得到的基础画像和经你确认的增强画像。",
    "增强画像": "可选：通过访谈补充简历没写到的技能与经历，提升 AI 匹配准确度。",
    "运行与结果": "查看任务实时进度、日志与投递结果明细。",
    "高级设置": "技术参数：超时重试、投递间隔、拟人行为与登录调试。一般不用修改。",
}
DEFAULT_SUBTITLE = "调整求职筛选与自动化任务的运行参数。"

# 侧边栏导航图标（assets 目录下的 SVG 线性图标）
NAV_ICONS = {
    "求职设置": "nav-settings.svg",
    "画像查看": "nav-user.svg",
    "增强画像": "nav-chat.svg",
    "运行与结果": "nav-chart.svg",
    "高级设置": "nav-tools.svg",
}


def read_env_dict() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
    return values


def write_env_file(values: dict):
    """按 FIELDS 分组重写 .env。"""
    if ENV_FILE.exists():
        values = {**read_env_dict(), **values}
    field_keys = {field[0] for field in FIELDS}
    groups = []
    for _, group, *_ in FIELDS:
        if group not in groups:
            groups.append(group)
    lines = ["# ================= 自动投递配置（桌面面板生成，可手工修改） ================="]
    for group in groups:
        lines += ["", f"# ===== {group} ====="]
        for key, g, label, ftype, default, note in FIELDS:
            if g != group:
                continue
            val = str(values.get(key, default))
            if ftype == "bool":
                val = val.strip().lower() if val.strip().lower() in ("true", "false") else default
            lines.append(f"{key}={val}")
    unknown = [(key, value) for key, value in values.items() if key not in field_keys]
    if unknown:
        lines += ["", "# ===== 未在面板展示的设置 ====="]
        lines.extend(f"{key}={value}" for key, value in unknown)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def candidate_profile_startup_error(store=None) -> str | None:
    """返回阻塞性错误；画像缺失不算错误（按基础画像运行，规范允许不使用增强画像）。"""
    store = store or CandidateProfileStore()
    try:
        store.load()
    except ValueError as exc:
        return f"候选人画像配置无效：{exc}"
    return None


def target_job_startup_error(target=None) -> str | None:
    """启动前检查：目标岗位必须填写（岗位画像由系统按目标岗位自动派生）。"""
    if target is None:
        target = read_env_dict().get("DELIVER_KEYWORD", "")
    target = str(target or "").strip()
    if not target:
        return "请先在「求职设置」填写目标岗位（例如：AI 应用工程师）后再启动。"
    return None


def current_deliver_config() -> dict:
    """运行时现读 .env 中的 AI/搜索配置（保存即生效）。

    DELIVER_CONFIG 是 delivery_config import 时的快照，面板保存配置后不会更新；
    本函数把 .env 里已出现的键覆盖到快照上，缺失的键沿用快照默认值。
    """
    from delivery_config import DELIVER_CONFIG

    merged = dict(DELIVER_CONFIG)
    values = read_env_dict()
    mapping = {
        "AI_BASE_URL": "ai_base_url",
        "AI_API_KEY": "ai_api_key",
        "AI_MODEL": "ai_model",
        "AI_REASONING_EFFORT": "ai_reasoning_effort",
        "AI_TIMEOUT": "ai_timeout",
        "AI_MAX_RETRIES": "ai_max_retries",
        "TAVILY_ENABLED": "tavily_enabled",
        "TAVILY_API_KEY": "tavily_api_key",
        "TAVILY_TIMEOUT": "tavily_timeout",
    }
    for env_key, cfg_key in mapping.items():
        if env_key not in values:
            continue
        raw = str(values[env_key] or "").strip()
        if cfg_key in {"ai_timeout", "ai_max_retries", "tavily_timeout"}:
            try:
                merged[cfg_key] = int(raw) if raw else DELIVER_CONFIG[cfg_key]
            except ValueError:
                continue
        elif cfg_key == "tavily_enabled":
            merged[cfg_key] = raw.lower() == "true"
        elif cfg_key == "ai_reasoning_effort":
            merged[cfg_key] = raw.lower()
        else:
            merged[cfg_key] = raw
    return merged


# 页面 mixin 依赖本模块的共享工具（BASE_DIR / read_env_dict 等），
# 必须在上述定义之后导入，以避免与 desktop_panel 形成循环导入。
# 以脚本方式运行时本模块名为 __main__，mixin 会按名字 import desktop_panel，
# 提前注册别名让两次导入共用同一模块对象，避免整份模块（含重型依赖）重复执行。
sys.modules.setdefault("desktop_panel", sys.modules[__name__])
from panel_candidate_profile import CandidateProfilePageMixin
from panel_result_page import ResultPageMixin


# ================= 主窗口 =================
class PanelApp(
    WidgetHelpersMixin,
    CandidateProfilePageMixin,
    ResultPageMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("求职工作台")
        self.resize(1420, 900)
        self.setMinimumSize(1180, 760)

        self.runner = TaskRunner()
        self.vars = {}                 # key -> (控件, 类型, 默认值)
        self.multiselect_checks = {}   # key -> [(选项, QCheckBox)]
        self.platform_area_choices = []
        self._last_platform_job_type = "不限"
        self._unrestricted_job_type_preference = "实习"
        self.pending_platform_area_values = []
        self.location_events = queue.Queue()
        self.location_generation = 0
        self.location_city_code = ""
        self._loading_env = False
        self.status_text = "空闲"
        self.profile_events = queue.Queue()
        self.digest_events = queue.Queue()
        self.resume_struct_button = None
        self.resume_digest_status = None
        self.profile_generation = 0
        self.profile_service = None
        self.profile_draft = None
        self.profile_json_generated = ""
        self.profile_busy = False
        self.profile_retry_action = None
        self.profile_rendered_history = 0
        self.profile_message_rows = []
        self.profile_resume = ""
        self.profile_wait_row = None
        self.profile_wait_label = None
        self.profile_wait_base = ""
        self.profile_wait_started = 0.0
        self.profile_pending_user_text = None
        self.result_rows = []
        self.log_records = []            # [(类别, 原始行)] 全量日志（不受显示过滤影响）
        self.run_stage_counts = {}       # [筛选统计] 解析出的阶段计数
        self.run_job = None              # 当前岗位卡（[岗位 n/m] 解析结果）
        self.run_job_score_value = None  # 当前岗位 AI 分数
        self.field_hints = {}            # key -> 行内校验/危险提示 QLabel
        self.env_previews = []           # [(切换按钮, .env 预览框)]
        self._settings = QSettings("autodeliver", "panel")

        self.profile_wait_timer = QTimer(self)
        self.profile_wait_timer.timeout.connect(self._tick_profile_wait)
        self._interview_deps = None
        self._profile_cache = None
        self._draft_prewarm_started = False
        self._draft_prewarm_thread = None

        self._build_ui()
        self._load_env()
        self.refresh_results()
        self._restore_window_settings()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(300)

    # ---------------- 窗口尺寸/位置记忆 ----------------
    def _restore_window_settings(self):
        geometry = self._settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_window_settings(self):
        self._settings.setValue("window/geometry", self.saveGeometry())

    # ---------------- 布局骨架 ----------------
    def _build_ui(self):
        root = QFrame()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_content(), 1)
        root_layout.addWidget(body, 1)

        self._show_page("求职设置")

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(76)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)

        mark = QLabel("职")
        mark.setObjectName("brandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(mark)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(3)
        brand = QLabel("求职工作台")
        brand.setObjectName("brand")
        subtitle = QLabel("岗位筛选与简历匹配")
        subtitle.setObjectName("brandSub")
        titles.addWidget(brand)
        titles.addWidget(subtitle)
        layout.addLayout(titles)

        layout.addStretch(1)
        layout.addWidget(self._build_status_cluster())
        layout.addSpacing(6)
        layout.addWidget(self._vdivider())
        layout.addSpacing(6)

        self.btn_refresh = QPushButton("刷新结果")
        self.btn_refresh.setObjectName("ghost")
        self.btn_refresh.setIcon(QIcon(str(ASSETS_DIR / "refresh.svg")))
        self.btn_refresh.setIconSize(QSize(15, 15))
        self.btn_refresh.setToolTip("重新读取结果文件与画像数据")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_results)
        layout.addWidget(self.btn_refresh)

        self.btn_save = QPushButton("保存配置")
        self.btn_save.setToolTip("把当前面板配置写入 .env")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_config)
        layout.addWidget(self.btn_save)

        self.btn_stop = QPushButton("停止任务")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setIcon(QIcon(str(ASSETS_DIR / "stop.svg")))
        self.btn_stop.setIconSize(QSize(14, 14))
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self.stop_task)
        layout.addWidget(self.btn_stop)

        self.btn_start = QPushButton("启动任务")
        self.btn_start.setObjectName("primary")
        self.btn_start.setIcon(QIcon(str(ASSETS_DIR / "play.svg")))
        self.btn_start.setIconSize(QSize(14, 14))
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_task)
        layout.addWidget(self.btn_start)
        return header

    def _build_status_cluster(self) -> QWidget:
        """状态区：状态点 + 状态文案 + 今日投递配额进度，避免裸文字标签。"""
        holder = QWidget()
        holder.setObjectName("statusCluster")
        row = QHBoxLayout(holder)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDotIdle")
        self.status_dot.setFixedSize(10, 10)
        row.addWidget(self.status_dot)

        self.status_label = QLabel(self.status_text)
        self.status_label.setObjectName("statusText")
        row.addWidget(self.status_label)

        row.addWidget(self._vdivider())

        row.addWidget(self._label("今日投递", "hint"))
        self.status_quota = QLabel("0 / 0")
        self.status_quota.setObjectName("statusQuota")
        row.addWidget(self.status_quota)

        self.status_bar = QProgressBar()
        self.status_bar.setObjectName("quotaBar")
        self.status_bar.setRange(0, 50)
        self.status_bar.setValue(0)
        self.status_bar.setTextVisible(False)
        self.status_bar.setFixedSize(104, 6)
        row.addWidget(self.status_bar)
        return holder

    @staticmethod
    def _vdivider():
        line = QFrame()
        line.setObjectName("vDivider")
        line.setFixedWidth(1)
        line.setFixedHeight(20)
        return line

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 18)
        layout.setSpacing(2)

        title = QLabel("工作区")
        title.setObjectName("sidebarTitle")
        layout.addWidget(title)
        layout.addSpacing(6)

        workflow = ["求职设置", "画像查看", "增强画像", "运行与结果"]
        settings = ["高级设置"]

        self.nav_buttons = {}
        self._add_nav_section(sidebar, layout, "求职流程", workflow)
        self._add_nav_section(sidebar, layout, "参数设置", settings)
        layout.addStretch(1)
        return sidebar

    def _add_nav_section(self, sidebar, layout, title, names):
        label = QLabel(title)
        label.setObjectName("navSection")
        layout.addWidget(label)
        for name in names:
            button = QPushButton(name, sidebar)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.PointingHandCursor)
            icon_name = NAV_ICONS.get(name)
            if icon_name:
                icon = QIcon(str(ASSETS_DIR / icon_name))
                button.setIcon(icon)
                button.setIconSize(QSize(17, 17))
            button.clicked.connect(lambda _checked=False, page=name: self._show_page(page))
            layout.addWidget(button)
            self.nav_buttons[name] = button

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(0)

        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("pageSubtitle")
        layout.addWidget(self.page_title)
        layout.addWidget(self.page_subtitle)
        layout.addSpacing(16)

        self.page_stack = QStackedWidget()
        self.pages = {}
        workflow = ["求职设置", "画像查看", "增强画像", "运行与结果"]
        settings = ["高级设置"]

        builders = {
            "求职设置": lambda: self._build_settings_page(SETTINGS_SECTIONS),
            "画像查看": self._build_profile_view_page,
            "增强画像": self._build_candidate_profile_page,
            "高级设置": lambda: self._build_settings_page(ADVANCED_SECTIONS),
            "运行与结果": self._build_run_page,
        }
        for name in workflow + settings:
            page = builders[name]()
            self.pages[name] = page
            self.page_stack.addWidget(page)

        layout.addWidget(self.page_stack, 1)
        return content

    def _show_page(self, name):
        if name not in self.pages:
            return
        self.page_stack.setCurrentWidget(self.pages[name])
        self.page_title.setText(name)
        self.page_subtitle.setText(PAGE_SUBTITLES.get(name, DEFAULT_SUBTITLE))
        button = self.nav_buttons.get(name)
        if button is not None:
            button.setChecked(True)
        if name == "增强画像":
            self._maybe_prewarm_draft()
        elif name == "画像查看":
            self._refresh_candidate_profile_view()

    # ---------------- 通用小部件 --------------
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                PanelApp._clear_layout(item.layout())

    # ---------------- 设置页 ----------------
    def _build_settings_page(self, sections):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 0, 2, 0)
        toolbar.addWidget(self._label(
            "修改后点右上角「保存配置」写入 .env 并立即生效", "hint"))
        toolbar.addStretch(1)
        env_toggle = QPushButton("查看原始 .env")
        env_toggle.setCheckable(True)
        env_toggle.setObjectName("ghost")
        env_toggle.setCursor(Qt.PointingHandCursor)
        env_toggle.clicked.connect(self._toggle_env_preview)
        toolbar.addWidget(env_toggle)
        page_layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 6, 6)
        inner_layout.setSpacing(14)

        env_preview = QPlainTextEdit()
        env_preview.setObjectName("envPreview")
        env_preview.setReadOnly(True)
        env_preview.setVisible(False)
        env_preview.setFixedHeight(180)
        env_preview.setPlaceholderText("（.env 文件为空）")
        self.env_previews.append((env_toggle, env_preview))

        for title, keys in sections:
            inner_layout.addWidget(self._build_config_section(title, keys))
        inner_layout.addWidget(env_preview)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        page_layout.addWidget(scroll, 1)
        return page

    def _build_config_section(self, title, keys):
        card, card_layout = self._card((22, 16, 22, 18), 0)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)
        head_layout.addWidget(self._label(title, "section"))
        head_layout.addStretch(1)
        reset_button = QPushButton("恢复默认值")
        reset_button.setObjectName("ghost")
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.setToolTip("把本组配置恢复为内置默认值（点「保存配置」后写入 .env）")
        reset_button.clicked.connect(
            lambda _checked=False, k=list(keys), t=title: self._reset_section_defaults(k, t)
        )
        head_layout.addWidget(reset_button)
        card_layout.addWidget(head)
        card_layout.addWidget(self._divider())

        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for index, key in enumerate(keys):
            if index:
                rows.addWidget(self._divider())
            rows.addWidget(self._build_field_row(key))
        card_layout.addLayout(rows)
        return card

    def _build_field_row(self, key):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(26)
        row_layout.addWidget(self._build_field_label(key))
        row_layout.addWidget(self._build_field_control(key), 1)
        return row

    def _build_field_label(self, key):
        """左列：字段名 + 说明文字（说明不再占用右侧空白列）。"""
        _, _group, label, ftype, _default, note = FIELD_BY_KEY[key]
        holder = QWidget()
        holder.setMinimumWidth(216)
        holder.setMaximumWidth(268)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 13, 0, 13)
        layout.setSpacing(4)
        if ftype != "bool":
            title = QLabel(label)
            title.setObjectName("fieldLabel")
            title.setWordWrap(True)
            layout.addWidget(title)
        if note:
            note_label = QLabel(note)
            note_label.setObjectName("fieldNote")
            note_label.setWordWrap(True)
            layout.addWidget(note_label)
        layout.addStretch(1)
        return holder

    def _build_field_control(self, key):
        """右列：输入控件（多选为可勾选胶囊，其余为输入框 / 下拉 / 数字）。"""
        _, _group, label, ftype, default, _note = FIELD_BY_KEY[key]

        if ftype == "bool":
            widget = QCheckBox(label)
            widget.setCursor(Qt.PointingHandCursor)
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 12, 0, 12)
            holder_layout.setSpacing(4)
            holder_layout.addWidget(widget)
            if key in CONFIG_WARNINGS:
                hint = self._label("", "warnText", wrap=True)
                self.field_hints[key] = hint
                holder_layout.addWidget(hint)
                widget.toggled.connect(self._refresh_field_hints)
            holder_layout.addStretch(1)
            self.vars[key] = (widget, ftype, default)
            return holder

        if ftype == "multiselect":
            host = QWidget()
            flow = FlowLayout(host, spacing=8)
            checks = []
            for option in SELECT_OPTIONS[key]:
                check = QCheckBox(option)
                check.setObjectName("chipCheck")
                check.setCursor(Qt.PointingHandCursor)
                check.setParent(host)
                flow.addWidget(check)
                checks.append((option, check))
            if key == "PLATFORM_AREA_FILTER":
                self.platform_area_flow = flow
                self.platform_area_status = self._label("正在读取所选城市的区域…", "muted", wrap=True)
                self.platform_area_refresh = QPushButton("刷新区域")
                self.platform_area_refresh.setToolTip("重新读取当前城市在 BOSS 上可筛选的区域")
                self.platform_area_refresh.clicked.connect(self._refresh_platform_areas)
                flow.addWidget(self.platform_area_status)
                self.platform_area_choices = checks
                self.multiselect_checks[key] = checks
                flow.addWidget(self.platform_area_refresh)
            else:
                self.multiselect_checks[key] = checks
            self.vars[key] = (host, ftype, default)
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 12, 0, 12)
            holder_layout.addWidget(host)
            holder_layout.addStretch(1)
            return holder

        if ftype == "select":
            widget = QComboBox()
            widget.addItems(SELECT_OPTIONS[key])
            widget.setMaximumWidth(260)
            widget.setCursor(Qt.PointingHandCursor)
            if key == "CITY_CODE":
                widget.setEditable(True)
                widget.setInsertPolicy(QComboBox.NoInsert)
                completer = QCompleter(SELECT_OPTIONS[key], widget)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                widget.setCompleter(completer)
                widget.activated.connect(self._on_city_selection_changed)
                widget.lineEdit().editingFinished.connect(self._on_city_selection_changed)
        elif ftype == "password":
            widget = QLineEdit()
            widget.setEchoMode(QLineEdit.Password)
            widget.setPlaceholderText(default or "未填写")
            widget.setMaximumWidth(420)
        elif ftype == "int":
            low, high = INT_LIMITS.get(key, (0, 999999))
            widget = QSpinBox()
            widget.setRange(low, high)
            try:
                widget.setValue(int(default))
            except ValueError:
                widget.setValue(low)
            widget.setAccelerated(True)
            widget.setMaximumWidth(160)
        else:
            widget = QLineEdit()
            widget.setMaximumWidth(420)

        if key == "RESUME_FILE":
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 12, 0, 12)
            holder_layout.setSpacing(6)
            input_row = QHBoxLayout()
            input_row.setContentsMargins(0, 0, 0, 0)
            input_row.setSpacing(8)
            input_row.addWidget(widget)
            browse_button = QPushButton("选择文件")
            browse_button.setToolTip("浏览并选择简历文件（markdown 或文本）")
            browse_button.setCursor(Qt.PointingHandCursor)
            browse_button.clicked.connect(self._browse_resume)
            input_row.addWidget(browse_button)
            self.resume_struct_button = QPushButton("结构化简历")
            self.resume_struct_button.setToolTip(
                "调用模型把简历提取为结构化摘要（逐字摘录），供画像访谈与岗位评分使用"
            )
            self.resume_struct_button.setCursor(Qt.PointingHandCursor)
            self.resume_struct_button.clicked.connect(self._structure_resume)
            input_row.addWidget(self.resume_struct_button)
            input_row.addStretch(1)
            holder_layout.addLayout(input_row)
            self.resume_digest_status = self._label("", "muted", wrap=True)
            holder_layout.addWidget(self.resume_digest_status)
            hint = self._label("", "errorText", wrap=True)
            self.field_hints[key] = hint
            holder_layout.addWidget(hint)
        elif key in ("WORK_TIME_START", "WORK_TIME_END"):
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 12, 0, 12)
            holder_layout.setSpacing(4)
            holder_layout.addWidget(widget)
            hint = self._label("", "errorText", wrap=True)
            self.field_hints[key] = hint
            holder_layout.addWidget(hint)
        else:
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 12, 0, 12)
            holder_layout.addWidget(widget)
            holder_layout.addStretch(1)

        self.vars[key] = (widget, ftype, default)
        if key == "PLATFORM_JOB_TYPE":
            widget.currentTextChanged.connect(self._on_platform_job_type_changed)
        elif key == "JOB_TYPE_PREFERENCE":
            widget.currentTextChanged.connect(self._on_job_type_preference_changed)
        if key in ("RESUME_FILE", "WORK_TIME_START", "WORK_TIME_END"):
            widget.textChanged.connect(self._refresh_field_hints)
        return holder

    def _toggle_env_preview(self, checked=False):
        button = self.sender()
        if button is None:
            return
        for toggle, preview in self.env_previews:
            if toggle is button:
                preview.setVisible(bool(checked))
                if checked:
                    try:
                        preview.setPlainText(ENV_FILE.read_text(encoding="utf-8"))
                    except OSError as exc:
                        preview.setPlainText(f"读取 .env 失败：{exc}")
                break

    def _reset_section_defaults(self, keys, title):
        for key in keys:
            _, _group, label, ftype, default, note = FIELD_BY_KEY[key]
            widget, _ftype, _default = self.vars[key]
            if ftype == "bool":
                widget.setChecked(str(default).strip().lower() == "true")
            elif ftype == "multiselect":
                selected = [item.strip() for item in str(default).split(",") if item.strip()]
                if key == "PLATFORM_AREA_FILTER":
                    self.pending_platform_area_values = []
                    for _code, check in self.platform_area_choices:
                        check.setChecked(False)
                    continue
                for option, check in self.multiselect_checks.get(key, []):
                    check.setChecked(option in selected)
            elif ftype == "select":
                default_text = (
                    CITY_NAME_BY_CODE.get(str(default), str(default))
                    if key == "CITY_CODE" else str(default)
                )
                index = widget.findText(default_text)
                widget.setCurrentIndex(index if index >= 0 else 0)
            elif ftype == "int":
                try:
                    widget.setValue(int(default))
                except ValueError:
                    pass
            else:
                widget.setText(str(default))
        self._refresh_field_hints()
        QMessageBox.information(
            self, "恢复默认值",
            f"「{title}」已恢复为内置默认值，点击「保存配置」后写入 .env 生效。",
        )

    def _resume_file_exists(self, value) -> bool:
        path = Path((value or "").strip() or "resume.md")
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.exists()

    def _refresh_field_hints(self, *_args):
        if not self.field_hints:
            return
        for key in ("WORK_TIME_START", "WORK_TIME_END"):
            hint = self.field_hints.get(key)
            if hint is None:
                continue
            value = self.vars[key][0].text().strip()
            message = (
                "" if not value or parse_hhmm(value) is not None
                else "时间格式应为 hh:mm（如 09:30）"
            )
            hint.setText(message)
        hint = self.field_hints.get("RESUME_FILE")
        if hint is not None:
            value = self.vars["RESUME_FILE"][0].text().strip()
            hint.setText(
                "" if not value or self._resume_file_exists(value)
                else f"简历文件不存在：{value}"
            )
        for key, table in CONFIG_WARNINGS.items():
            hint = self.field_hints.get(key)
            if hint is None:
                continue
            widget, ftype, _default = self.vars[key]
            current = "true" if widget.isChecked() else "false" if ftype == "bool" else ""
            hint.setText(table.get(current, ""))
        for hint in self.field_hints.values():
            hint.setVisible(bool(hint.text()))

    def _load_env(self):
        saved = read_env_dict()
        self._loading_env = True
        for key, (widget, ftype, default) in self.vars.items():
            val = str(saved.get(key, default))
            if ftype == "bool":
                widget.setChecked(val.strip().lower() == "true")
            elif ftype == "multiselect":
                selected = [item.strip() for item in val.split(",") if item.strip()]
                if key == "PLATFORM_AREA_FILTER":
                    self.pending_platform_area_values = selected
                    continue
                for option, check in self.multiselect_checks.get(key, []):
                    check.setChecked(option in selected)
            elif ftype == "select":
                if key == "CITY_CODE":
                    val = CITY_NAME_BY_CODE.get(val, val)
                else:
                    val = platform_filter_label(key, val)
                index = widget.findText(val)
                if index < 0:
                    widget.addItem(val)
                    index = widget.findText(val)
                widget.setCurrentIndex(index)
            elif ftype == "int":
                try:
                    widget.setValue(int(val or default))
                except ValueError:
                    widget.setValue(int(default))
            else:
                widget.setText(val)
        self._loading_env = False
        platform_type = self.vars["PLATFORM_JOB_TYPE"][0].currentText().strip()
        preference = self.vars["JOB_TYPE_PREFERENCE"][0].currentText().strip()
        remembered = preference
        if platform_type in ("实习", "全职", "兼职"):
            remembered = self._settings.value("jobType/unrestrictedPreference", preference)
        self._unrestricted_job_type_preference = (
            remembered if remembered in ("实习", "全职") else "实习"
        )
        self._last_platform_job_type = platform_type
        preference, self._unrestricted_job_type_preference = transition_job_type_preference(
            platform_type,
            platform_type,
            preference,
            self._unrestricted_job_type_preference,
        )
        preference_widget = self.vars["JOB_TYPE_PREFERENCE"][0]
        preference_widget.setCurrentText(preference)
        self._update_job_type_preference_control(platform_type)
        self._update_part_time_filter_control(platform_type)
        self._refresh_digest_status()
        self._refresh_field_hints()
        self._refresh_platform_areas()

    def _on_platform_job_type_changed(self, platform_type):
        if self._loading_env:
            return
        preference_widget = self.vars["JOB_TYPE_PREFERENCE"][0]
        preference, remembered = transition_job_type_preference(
            self._last_platform_job_type,
            platform_type,
            preference_widget.currentText(),
            self._unrestricted_job_type_preference,
        )
        self._last_platform_job_type = platform_type
        self._unrestricted_job_type_preference = remembered
        self._settings.setValue("jobType/unrestrictedPreference", remembered)
        preference_widget.setCurrentText(preference)
        self._update_job_type_preference_control(platform_type)
        self._update_part_time_filter_control(platform_type)

    def _update_part_time_filter_control(self, platform_type):
        widget = self.vars.get("PLATFORM_PART_TIME", (None,))[0]
        if widget is None:
            return
        enabled = str(platform_type or "").strip() == "兼职"
        widget.setEnabled(enabled)
        widget.setToolTip(
            "仅兼职岗位支持该筛选" if enabled else "选择「兼职」后可设置兼职时段"
        )

    def _on_job_type_preference_changed(self, preference):
        if self._loading_env:
            return
        platform_type = self.vars["PLATFORM_JOB_TYPE"][0].currentText().strip()
        if platform_type == "不限" and preference in ("实习", "全职"):
            self._unrestricted_job_type_preference = preference
            self._settings.setValue("jobType/unrestrictedPreference", preference)

    def _update_job_type_preference_control(self, platform_type):
        widget = self.vars["JOB_TYPE_PREFERENCE"][0]
        widget.setEnabled(platform_type not in ("实习", "全职", "兼职"))
        if platform_type in ("实习", "全职"):
            widget.setToolTip(
                f"平台已筛选为{platform_type}，本项已同步锁定；切回不限后可恢复原排序偏好。"
            )
        elif platform_type == "兼职":
            widget.setToolTip(
                "平台已筛选为兼职，实习/全职排序不适用；切回不限后可恢复原排序偏好。"
            )
        else:
            widget.setToolTip("平台不限职位性质时，按所选性质优先处理；其他岗位仍保留在队列。")

    def _current_city_code(self):
        city_name = self.vars["CITY_CODE"][0].currentText().strip()
        return CITY_CHOICES.get(city_name, "")

    def _on_city_selection_changed(self, *_args):
        if self._loading_env:
            return
        city_code = self._current_city_code()
        if city_code == self.location_city_code:
            return
        self.pending_platform_area_values = []
        for _code, check in self.platform_area_choices:
            check.setChecked(False)
            check.setEnabled(False)
        self._refresh_platform_areas()

    def _refresh_platform_areas(self, *_args):
        city_code = self._current_city_code()
        if city_code and city_code == self.location_city_code:
            if self.platform_area_choices:
                self.pending_platform_area_values = [
                    code for code, check in self.platform_area_choices if check.isChecked()
                ]
        for _code, check in self.platform_area_choices:
            check.setEnabled(False)
        self.location_generation += 1
        generation = self.location_generation
        self.location_city_code = city_code
        self.platform_area_refresh.setEnabled(False)
        if not city_code:
            self.platform_area_status.setText("请选择有效城市后加载区域。")
            self.platform_area_refresh.setEnabled(True)
            return
        self.platform_area_status.setText("正在读取所选城市的区域…")

        def fetch():
            try:
                result = fetch_platform_districts(city_code)
                payload = (generation, city_code, result, "")
            except Exception as exc:
                payload = (generation, city_code, [], str(exc))
            self.location_events.put(payload)

        threading.Thread(target=fetch, daemon=True).start()

    def _apply_platform_areas(self, generation, city_code, districts, error):
        if generation != self.location_generation or city_code != self._current_city_code():
            return
        self.platform_area_refresh.setEnabled(True)
        if error:
            self._clear_platform_area_options()
            self.platform_area_choices = []
            self.platform_area_status.setText(f"区域加载失败：{error}")
            self.platform_area_flow.addWidget(self.platform_area_status)
            self.platform_area_flow.addWidget(self.platform_area_refresh)
            return

        selected = set(self.pending_platform_area_values)
        self._clear_platform_area_options()

        self.platform_area_choices = []
        for district in districts:
            code = str(district["code"])
            name = str(district["name"])
            check = QCheckBox(name)
            check.setObjectName("chipCheck")
            check.setCursor(Qt.PointingHandCursor)
            check.setParent(self.vars["PLATFORM_AREA_FILTER"][0])
            check.setChecked(code in selected or name in selected)
            self.platform_area_flow.addWidget(check)
            self.platform_area_choices.append((code, check))

        status_text = (
            f"已加载 {len(districts)} 个行政区，可按需多选。"
            if districts else "BOSS 未返回可选行政区。"
        )
        self.platform_area_status.setText(status_text)
        self.platform_area_flow.addWidget(self.platform_area_status)
        self.platform_area_flow.addWidget(self.platform_area_refresh)
        self.pending_platform_area_values = []

    def _clear_platform_area_options(self):
        while self.platform_area_flow.count():
            item = self.platform_area_flow.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in (
                self.platform_area_status,
                self.platform_area_refresh,
            ):
                widget.deleteLater()
            elif widget is not None:
                widget.setParent(self.vars["PLATFORM_AREA_FILTER"][0])

    def _read_widget_values(self) -> dict:
        """把控件当前取值收集为 key->字符串 dict（不做校验）。"""
        values = {}
        for key, group, label, ftype, default, note in FIELDS:
            widget, _ftype, _default = self.vars[key]
            if ftype == "bool":
                values[key] = "true" if widget.isChecked() else "false"
            elif ftype == "multiselect":
                if key == "PLATFORM_AREA_FILTER":
                    selected_codes = [
                        code for code, check in self.platform_area_choices
                        if check.isChecked()
                    ]
                    pending_codes = [
                        str(code).strip() for code in self.pending_platform_area_values
                        if str(code).strip()
                    ]
                    values[key] = ",".join(dict.fromkeys(
                        selected_codes + pending_codes
                    ))
                else:
                    values[key] = ",".join(
                        option for option, check in self.multiselect_checks.get(key, [])
                        if check.isChecked()
                    )
            elif ftype == "select":
                text = widget.currentText().strip()
                values[key] = CITY_CHOICES.get(text, "") if key == "CITY_CODE" else text
            elif ftype == "int":
                values[key] = str(widget.value())
            else:
                values[key] = widget.text().strip()
        values["JOB_TYPE_PREFERENCE"] = normalize_job_type_preference(
            values.get("PLATFORM_JOB_TYPE", "不限"),
            values.get("JOB_TYPE_PREFERENCE", "实习"),
        )
        return values

    def _collect_values(self):
        """收集面板配置为 dict；校验失败时汇总展示全部错误并返回 None。"""
        values = self._read_widget_values()
        if not values.get("CITY_CODE"):
            QMessageBox.critical(self, "配置校验未通过", "请选择 city_codes.json 中的有效城市。")
            return None
        errors = validate_config_values(
            values, resume_exists=self._resume_file_exists(values.get("RESUME_FILE", ""))
        )
        if errors:
            detail = "\n".join(
                f"{index}. {message}" for index, message in enumerate(errors, 1)
            )
            QMessageBox.critical(
                self, "配置校验未通过",
                f"请修正以下 {len(errors)} 个问题后再保存：\n\n{detail}",
            )
            return None
        return values

    def save_config(self):
        values = self._collect_values()
        if values is None:
            return
        write_env_file(values)
        self.append_log(f"[面板] {time.strftime('%H:%M:%S')} 配置已保存到 .env")
        QMessageBox.information(self, "保存配置", "配置已保存。运行中的任务不受影响，下次启动生效。")

    # ---------------- 运行日志页 ----------------
    def _build_run_page(self):
        """运行与结果：日志监控与投递结果合并为两个 Tab。"""
        tabs = QTabWidget()
        self.run_tabs = tabs
        tabs.addTab(self._build_log_page(), "运行日志")
        tabs.addTab(self._build_result_page(), "投递结果")
        tabs.currentChanged.connect(self._on_run_tab_changed)
        return tabs

    def _on_run_tab_changed(self, index):
        # 切到结果 Tab 时刷新，避免看到过期数据
        if index == 1:
            try:
                self.refresh_results()
            except Exception as exc:
                print(f"[面板] 刷新结果失败: {exc}")

    def _build_log_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 状态区：进度条 + 统计 + 当前岗位卡
        status_card, status_layout = self._card((20, 16, 20, 18), 14)
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(self._label("运行监控", "section"))
        head_layout.addStretch(1)
        self.run_state_chip = self._label("空闲", "statusChipIdle")
        head_layout.addWidget(self.run_state_chip)
        status_layout.addWidget(head)

        progress_row = QWidget()
        progress_layout = QHBoxLayout(progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(12)
        progress_layout.addWidget(self._label("评分进度", "fieldLabel"))
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 1)
        self.run_progress.setValue(0)
        self.run_progress.setTextVisible(False)
        self.run_progress.setFixedHeight(10)
        progress_layout.addWidget(self.run_progress, 1)
        self.run_progress_label = self._label("等待输出…", "hint")
        self.run_progress_label.setFixedWidth(132)
        self.run_progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_layout.addWidget(self.run_progress_label)
        status_layout.addWidget(progress_row)

        stats_row = QWidget()
        stats_layout = QHBoxLayout(stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(10)
        self.run_stat_scored = self._stat_tile("已评分", "0")
        self.run_stat_delivered = self._stat_tile("已投递", "0")
        self.run_stat_today = self._stat_tile("今日投递", "0 / 0")
        for tile, _value in (self.run_stat_scored, self.run_stat_delivered,
                             self.run_stat_today):
            stats_layout.addWidget(tile)
        stats_layout.addStretch(1)
        status_layout.addWidget(stats_row)

        job_card, job_layout = self._card((16, 12, 16, 12), 6)
        job_head = QWidget()
        job_head_layout = QHBoxLayout(job_head)
        job_head_layout.setContentsMargins(0, 0, 0, 0)
        job_head_layout.addWidget(self._label("当前岗位", "fieldLabel"))
        job_head_layout.addStretch(1)
        self.run_job_score_label = self._label("AI 分数 –", "scoreBadgeLow")
        job_head_layout.addWidget(self.run_job_score_label)
        job_layout.addWidget(job_head)
        self.run_job_title = self._label("暂无进行中的岗位", "section", wrap=True)
        job_layout.addWidget(self.run_job_title)
        self.run_job_meta = self._label(
            "任务启动后，这里显示当前处理的岗位、公司与 AI 分数。", "muted", wrap=True
        )
        job_layout.addWidget(self.run_job_meta)
        status_layout.addWidget(job_card)
        layout.addWidget(status_card)

        card, card_layout = self._card((16, 14, 16, 16), 10)
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(self._label("任务输出", "section"))
        toolbar_layout.addStretch(1)
        self.log_filter_ai = QCheckBox("只看 AI 相关")
        self.log_filter_ai.setToolTip("只显示 [AI] 行；不影响日志写入")
        self.log_filter_ai.setCursor(Qt.PointingHandCursor)
        self.log_filter_ai.toggled.connect(self._rebuild_log_view)
        toolbar_layout.addWidget(self.log_filter_ai)
        self.log_filter_error = QCheckBox("只看错误")
        self.log_filter_error.setToolTip("只显示错误行；不影响日志写入")
        self.log_filter_error.setCursor(Qt.PointingHandCursor)
        self.log_filter_error.toggled.connect(self._rebuild_log_view)
        toolbar_layout.addWidget(self.log_filter_error)
        clear = QPushButton("清空日志")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear_log)
        toolbar_layout.addWidget(clear)
        card_layout.addWidget(toolbar)

        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("logView")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(4000)
        self.log_box.setFont(QFont("Cascadia Mono", 9))
        self.log_box.setPlaceholderText(
            "暂无日志。点击右上角「启动任务」开始投递，运行输出会实时显示在这里。"
        )
        card_layout.addWidget(self.log_box, 1)
        layout.addWidget(card, 1)
        return page

    def _stat_tile(self, label, value):
        """统计小卡：返回 (卡片, 数值标签)。"""
        tile = QFrame()
        tile.setObjectName("inset")
        tile.setMinimumWidth(128)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        label_label = QLabel(label)
        label_label.setObjectName("statLabel")
        layout.addWidget(value_label)
        layout.addWidget(label_label)
        return tile, value_label

    def _clear_log(self):
        self.log_records = []
        self.log_box.clear()

    def _log_visible(self, category) -> bool:
        filter_ai = getattr(self, "log_filter_ai", None)
        filter_error = getattr(self, "log_filter_error", None)
        if filter_error is not None and filter_error.isChecked() and category != CATEGORY_ERROR:
            return False
        if filter_ai is not None and filter_ai.isChecked() and category != CATEGORY_AI:
            return False
        return True

    def _append_log_line(self, category, text):
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        char_format = QTextCharFormat()
        char_format.setForeground(QColor(
            CATEGORY_COLORS.get(category, CATEGORY_COLORS[CATEGORY_NORMAL])
        ))
        cursor.insertText(text + "\n", char_format)
        self.log_box.ensureCursorVisible()

    def _rebuild_log_view(self, *_args):
        self.log_box.clear()
        for category, text in self.log_records:
            if self._log_visible(category):
                self._append_log_line(category, text)

    def append_log(self, text: str):
        category = classify_log_line(text)
        self.log_records.append((category, text))
        self._update_run_monitor(text, category)
        if self._log_visible(category):
            self._append_log_line(category, text)

    # ---------------- 运行监控（状态区） ----------------
    def _update_run_monitor(self, text, category):
        if "启动任务 auto_deliver.py" in text:
            self.run_stage_counts = {}
            self.run_job = None
            self.run_job_score_value = None
            self._refresh_run_progress()
            self._refresh_run_job()
        stats = parse_filter_stats(text)
        if stats is not None:
            self.run_stage_counts = stats
            self._refresh_run_progress()
            return
        job = parse_job_line(text)
        if job is not None:
            self.run_job = job
            self.run_job_score_value = None
            self._refresh_run_job()
            return
        if category == CATEGORY_AI:
            score = parse_ai_score(text)
            if score is not None:
                self.run_job_score_value = score
                self._refresh_run_job()

    def _refresh_run_progress(self):
        counts = self.run_stage_counts
        scored = counts.get("AI评分完成", 0)
        failed = counts.get("AI调用失败", 0)
        delivered = counts.get("投递成功", 0)
        total = max(counts.get("进入AI评分", 0), scored + failed, 1)
        self.run_progress.setRange(0, total)
        self.run_progress.setValue(min(scored + failed, total))
        self.run_progress_label.setText(f"评分 {scored + failed} / {total}")
        self.run_stat_scored[1].setText(str(scored))
        self.run_stat_delivered[1].setText(str(delivered))

    def _refresh_run_job(self):
        job = self.run_job
        if not job:
            self.run_job_title.setText("暂无进行中的岗位")
            self.run_job_meta.setText("任务启动后，这里显示当前处理的岗位、公司与 AI 分数。")
            self.run_job_score_label.setText("AI 分数 –")
            self._set_widget_style(self.run_job_score_label, "scoreBadgeLow")
            return
        self.run_job_title.setText(job.get("name") or "未命名岗位")
        self.run_job_meta.setText(
            f"第 {job['index']}/{job['total']} 个 · 本轮第 {job['round']} 个 · "
            f"{job.get('company', '')} · {job.get('type', '')}"
        )
        score = self.run_job_score_value
        self.run_job_score_label.setText(
            f"AI 分数 {score:g}" if score is not None else "AI 评分中…"
        )
        self._set_widget_style(
            self.run_job_score_label, "scoreBadge" if score is not None else "scoreBadgeLow"
        )

    # ---------------- 简历文件：选文件 / 结构化 ----------------
    def _browse_resume(self):
        widget, _ftype, _default = self.vars["RESUME_FILE"]
        start_dir = str(BASE_DIR)
        current = widget.text().strip()
        if current:
            current_path = Path(current)
            if not current_path.is_absolute():
                current_path = BASE_DIR / current_path
            if current_path.exists():
                start_dir = str(current_path.parent)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择简历文件", start_dir, "简历文件 (*.md *.txt *.markdown);;所有文件 (*.*)"
        )
        if not path:
            return
        chosen = Path(path)
        try:
            widget.setText(str(chosen.relative_to(BASE_DIR)))
        except ValueError:
            widget.setText(str(chosen))
        self._refresh_digest_status()
        self._refresh_field_hints()

    def _structure_resume(self):
        """「结构化简历」按钮：调用模型提取结构化摘要并缓存，供画像访谈与评分使用。"""
        values = self._collect_values()
        if values is None:
            return
        resume_path = Path(values.get("RESUME_FILE", "resume.md"))
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            resume = resume_path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "结构化失败", f"简历文件读取失败：{exc}")
            return
        if not resume.strip():
            QMessageBox.critical(self, "结构化失败", "简历文件为空。")
            return
        config = {
            "ai_model": values.get("AI_MODEL", ""),
            "ai_api_key": values.get("AI_API_KEY", ""),
            "ai_base_url": values.get("AI_BASE_URL", ""),
            "ai_timeout": values.get("AI_TIMEOUT", "90"),
            "ai_max_retries": values.get("AI_MAX_RETRIES", "2"),
            "ai_reasoning_effort": values.get("AI_REASONING_EFFORT", "low"),
        }
        if not config["ai_model"] or not config["ai_api_key"] or not config["ai_base_url"]:
            QMessageBox.critical(self, "结构化失败", "请先在「AI 接口」页填写接口地址、API Key 与模型名。")
            return
        self.resume_struct_button.setEnabled(False)
        self.resume_struct_button.setText("结构化中…")
        self.resume_digest_status.setText("正在调用模型提取结构化摘要，约需数十秒…")
        threading.Thread(
            target=self._run_digest_generation,
            args=(resume, config),
            daemon=True,
        ).start()

    def _run_digest_generation(self, resume, config):
        try:
            from ai_chains import ResumeDigestChain, build_chat_model

            digest = ResumeDigestChain(model=build_chat_model(config)).invoke(resume)
            ResumeDigestStore().save(resume, digest)
            self.digest_events.put(("ok", digest))
        except Exception as exc:
            self.digest_events.put(("error", str(exc)))

    def _handle_digest_event(self, kind, payload):
        self.resume_struct_button.setEnabled(True)
        if kind == "ok":
            digest = payload
            self.resume_struct_button.setText("重新结构化")
            self.resume_digest_status.setText(
                f"已结构化：技能 {len(digest.skills)} 条 · 项目 {len(digest.projects)} 条 · "
                f"教育 {len(digest.education)} 条 · 偏好 {len(digest.preferences)} 条。"
                "画像访谈与评分将优先使用摘要；修改简历后需重新结构化。"
            )
            self.append_log(f"[画像] {time.strftime('%H:%M:%S')} 简历结构化完成")
            self._refresh_candidate_profile_view()
        else:
            self.resume_struct_button.setText("结构化简历")
            self.resume_digest_status.setText(f"结构化失败：{self._friendly_error(payload)}")

    def _refresh_digest_status(self):
        if self.resume_struct_button is None:
            return
        widget, _ftype, _default = self.vars.get("RESUME_FILE", (None, "", ""))
        resume_path = Path((widget.text().strip() if widget else "") or "resume.md")
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            resume = resume_path.read_text(encoding="utf-8")
        except OSError:
            resume = ""
        if not resume.strip():
            self.resume_struct_button.setText("结构化简历")
            self.resume_digest_status.setText("未找到简历文件；可点「选择文件」指定简历路径。")
            return
        digest = ResumeDigestStore().load_for(resume)
        if digest is not None:
            self.resume_struct_button.setText("重新结构化")
            total = (
                len(digest.skills) + len(digest.projects)
                + len(digest.education) + len(digest.preferences)
            )
            self.resume_digest_status.setText(
                f"已结构化（{total} 条逐字摘录）· 画像访谈与评分优先使用摘要；修改简历后需重新结构化。"
            )
        else:
            self.resume_struct_button.setText("结构化简历")
            self.resume_digest_status.setText("尚未结构化；点击按钮调用模型生成结构化摘要。")

    @staticmethod
    def _ai_config_signature(config):
        return (
            config.get("ai_model"), config.get("ai_base_url"), config.get("ai_api_key"),
            config.get("ai_timeout"), config.get("ai_max_retries"),
            config.get("ai_reasoning_effort"),
        )

    @staticmethod
    def _resolve_model(deps):
        config = current_deliver_config()
        signature = PanelApp._ai_config_signature(config)
        model = deps.get("model")
        if model is None or deps.get("signature") != signature:
            model = deps["build_chat_model"](config)
            deps["model"] = model
            deps["signature"] = signature
        return model

    # ---------------- 任务控制 ----------------
    def start_task(self):
        profile_error = candidate_profile_startup_error()
        if profile_error:
            QMessageBox.warning(self, "候选人画像配置无效", profile_error)
            return
        values = self._collect_values()
        if values is None:
            return
        jobs_error = target_job_startup_error(values.get("DELIVER_KEYWORD"))
        if jobs_error:
            QMessageBox.warning(self, "需要先填写目标岗位", jobs_error)
            self._show_page("求职设置")
            return
        if CandidateProfileStore().load() is None:
            self.append_log(
                f"[面板] {time.strftime('%H:%M:%S')} 未确认候选人画像，将按基础画像运行"
            )
        # 先落盘当前面板配置，保证启动即用面板里的设置
        write_env_file(values)

        msg = self.runner.start()
        if not self.runner.running():
            QMessageBox.warning(self, "启动失败", msg)
        self.append_log(f"[面板] {time.strftime('%H:%M:%S')} {msg}（面板配置已自动保存）")

    def stop_task(self):
        msg = self.runner.stop()
        self.append_log(f"[面板] {time.strftime('%H:%M:%S')} {msg}")

    # ---------------- 周期刷新 ----------------
    def _poll(self):
        while True:
            try:
                generation, city_code, districts, error = self.location_events.get_nowait()
            except queue.Empty:
                break
            self._apply_platform_areas(generation, city_code, districts, error)
        while True:
            try:
                generation, kind, payload = self.profile_events.get_nowait()
            except queue.Empty:
                break
            self._handle_profile_event(generation, kind, payload)
        while True:
            try:
                kind, payload = self.digest_events.get_nowait()
            except queue.Empty:
                break
            self._handle_digest_event(kind, payload)
        while True:
            try:
                line = self.runner.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(line)

        running = self.runner.running()
        today_count, limit = self._today_count()
        self.run_stat_today[1].setText(f"{today_count} / {limit}")
        self.status_quota.setText(f"{today_count} / {limit}")
        self.status_bar.setRange(0, max(limit, 1))
        self.status_bar.setValue(min(today_count, limit))
        if running:
            mins = int((time.time() - self.runner.started_at) / 60)
            self.status_label.setText(f"运行中 · {mins} 分钟")
            self._set_widget_style(self.status_dot, "statusDotRunning")
            self._set_widget_style(self.run_state_chip, "statusChipOk")
            self.run_state_chip.setText("运行中")
            self.btn_start.setVisible(False)
            self.btn_stop.setVisible(True)
        else:
            exit_code = self.runner.exit_code
            self.status_label.setText("空闲" if exit_code is None else f"已结束 · 退出码 {exit_code}")
            self._set_widget_style(
                self.status_dot, "statusDotDone" if exit_code == 0 else "statusDotIdle"
            )
            self._set_widget_style(self.run_state_chip, "statusChipIdle")
            self.run_state_chip.setText("空闲")
            self.btn_stop.setVisible(False)
            self.btn_start.setVisible(True)

    @staticmethod
    def _today_count():
        try:
            if LOG_JSON.exists():
                data = json.loads(LOG_JSON.read_text(encoding="utf-8"))
                if data.get("date") == time.strftime("%Y-%m-%d"):
                    return data.get("count", 0), PanelApp._env_limit()
                return 0, PanelApp._env_limit()
        except (OSError, json.JSONDecodeError):
            pass
        return 0, PanelApp._env_limit()

    @staticmethod
    def _env_limit():
        try:
            return int(read_env_dict().get("DAILY_LIMIT", "50"))
        except ValueError:
            return 50

    # ---------------- 退出保护 ----------------
    def closeEvent(self, event):
        self._save_window_settings()
        self.profile_generation += 1
        if self.profile_service is not None:
            self.profile_service.cancel()
        if self.runner.running():
            reply = QMessageBox.question(
                self, "退出", "任务正在运行，确定要停止任务并退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.runner.stop()
        event.accept()


def main():
    if sys.stdout is not None:
        print("正在加载界面…", flush=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = PanelApp()
    window.show()
    if sys.stdout is not None:
        print("求职工作台已启动，关闭窗口即可退出。", flush=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
