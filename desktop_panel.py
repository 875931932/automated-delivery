# -*- coding: utf-8 -*-
"""
自动投递桌面工作台（PySide6 / Qt Widgets）

  - 侧边栏导航：候选人画像 / 岗位画像 / 投递结果 / 运行日志 + 各分组配置页
  - 可视化编辑 .env（关键词 / 城市 / AI 阈值 / 每日上限 / 双休与工作时间 / 干跑等）
  - 一键启动 / 停止投递任务（子进程运行 auto_deliver.py）
  - 实时日志窗口 + 投递结果表 + 今日进度

启动: 双击项目内的「启动面板.vbs」。
"""
from process_runtime import configure_quiet_processes

configure_quiet_processes()

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
    QApplication,
    QCheckBox,
    QCompleter,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from dotenv import dotenv_values

from app_paths import get_data_dir
from candidate_profiles import (
    CandidateProfileService,
    CandidateProfileStore,
    InterviewDraft,
    InterviewDraftCacheStore,
    ResumeDigestStore,
    resume_digest_hash,
)
from greeting_prompt import DEFAULT_GREETING_PROMPT
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
from panel_runner import TaskRunner, format_exit_status
from panel_about import AboutDialog
from panel_styles import ASSETS_DIR, STYLESHEET
from panel_widgets import (
    ClickableLabel,
    FieldBlock,
    FlowLayout,
    FormGrid,
    SectionCard,
    StatTile,
    StatusDot,
    ToastNotice,
    ToggleRow,
    WidgetHelpersMixin,
    pad_spinbox_text,
)
from platform_search_filters import (
    platform_filter_options,
    platform_filter_label,
    resolve_platform_filter,
)
from platform_locations import fetch_platform_districts, load_city_codes
from platform_industries import fetch_platform_industries

BASE_DIR = get_data_dir()
ENV_FILE = BASE_DIR / ".env"
LOG_JSON = BASE_DIR / "deliver_log.json"

# 配置项定义: (key, 分组tab, 标签, 类型, 默认值, 备注)
# 类型: text / multiline / int / password / bool / select / multiselect
FIELDS = [
    ("AI_BASE_URL",    "AI 接口", "接口地址", "text", "https://api.deepseek.com/v1", "OpenAI 兼容接口，如 https://api.stepfun.com/step_plan/v1"),
    ("AI_API_KEY",     "AI 接口", "API Key", "password", "", ""),
    ("AI_MODEL",       "AI 接口", "模型名", "text", "deepseek-chat", "如 step-5-preview"),
    ("AI_REASONING_EFFORT", "AI 接口", "思考强度", "select", "low", "low/medium/high；访谈和评分用 low 最快，high 会慢数倍"),
    ("AI_TIMEOUT",     "AI 接口", "请求超时(秒)", "int", "90", ""),
    ("AI_MAX_RETRIES", "AI 接口", "失败重试次数", "int", "2", ""),
    ("GREETING_PROMPT", "打招呼语", "招呼语提示词", "multiline",
     DEFAULT_GREETING_PROMPT,
     "自定义表达方式、语气和长度；简历、已确认画像与岗位信息会自动附在提示词后。事实仍受系统约束。"),

    ("DELIVER_KEYWORD",  "筛选与简历", "搜索关键词", "text", "", ""),
    ("CITY_CODE",        "筛选与简历", "在哪个城市找", "select", "101280600", "决定在哪个城市找工作"),
    ("PLATFORM_AREA_FILTER", "筛选与简历", "平台工作区域", "multiselect", "", "区域按当前城市从 BOSS 加载；保存的是平台区域 ID，不选表示不限"),
    ("PLATFORM_JOB_TYPE", "筛选与简历", "平台求职类型", "select", "不限", "平台侧筛选全职、兼职或实习"),
    ("PLATFORM_PAY_TYPE", "筛选与简历", "平台结算方式", "select", "不限", "按日结、周结、月结或完工结筛选"),
    ("PLATFORM_PART_TIME", "筛选与简历", "平台兼职时段", "select", "不限", "仅平台求职类型选「兼职」时生效"),
    ("PLATFORM_EXPERIENCE", "筛选与简历", "平台经验要求", "select", "不限", "按 BOSS 工作经验筛选"),
    ("PLATFORM_DEGREE", "筛选与简历", "平台学历要求", "select", "不限", "按 BOSS 学历筛选"),
    ("PLATFORM_INDUSTRY", "筛选与简历", "平台行业", "text", "", "可选择行业；也可填逗号分隔的 ID 或粘贴包含 industry 参数的 BOSS 搜索链接"),
    ("PLATFORM_SCALE", "筛选与简历", "平台公司规模", "select", "不限", "按 BOSS 公司规模筛选"),
    ("MATCH_THRESHOLD",  "筛选与简历", "AI匹配阈值", "int", "70", "0-100，低于该分数不投"),
    ("JOB_TYPE_PREFERENCE", "筛选与简历", "优先岗位性质", "select", "实习", "平台不限时用于队列排序；平台选实习/全职时自动同步，选兼职时不适用"),
    ("RESUME_FILE",      "筛选与简历", "简历文件", "text", "resume.md", "markdown 简历路径"),
    ("DELIVER_MAX_PAGES","筛选与简历", "搜索请求基础预算", "int", "10", "目标岗位数不足时仍用于扩大搜索范围；目标数较大时自动扩展补足，单轮最多搜索 50 次"),
    ("AREA_FILTER",      "筛选与简历", "本地区域再筛", "text", "", "按行政区/商圈名称二次筛选；多个名称用英文逗号分隔，留空表示不限"),

    ("REST_DAY_REQUIRE", "工作时间与休息", "休息制度", "select", "不限", "与 JD 明确标注的休息制度不一致时过滤；未知信息放行"),
    ("WORK_TIME_START",  "工作时间与休息", "最早可接受上班时间", "text", "", "如 09:00，过滤早于该时间上班的岗位；09:00及以后通过，留空不启用"),
    ("WORK_TIME_END",    "工作时间与休息", "最晚下班时间", "text", "", "如 19:00，JD 下班晚于该值视为加班过滤，留空不启用"),
    ("WELFARE_REQUIRE",  "工作时间与休息", "期望福利", "multiselect", "", "作为 AI 评分的加分参考；不选表示不限"),

    ("DAILY_LIMIT",   "投递节奏", "每日投递上限", "int", "50", ""),
    ("JOB_DELAY_MIN", "投递节奏", "岗位间隔最小(秒)", "int", "25", ""),
    ("JOB_DELAY_MAX", "投递节奏", "岗位间隔最大(秒)", "int", "50", ""),
    ("HUMAN_EVERY_N", "投递节奏", "每投N个穿插拟人浏览", "int", "5", "0 = 关闭"),

    ("HUMANIZE_ENABLE","拟人行为", "启用拟人浏览", "bool", "true", "关闭额外浏览动作，保留登录信息同步"),
    ("DETAIL_DELAY_MIN","拟人行为", "详情页停留最小(秒)", "int", "3", "点开岗位/公司页后的浏览时长"),
    ("DETAIL_DELAY_MAX","拟人行为", "详情页停留最大(秒)", "int", "6", ""),

    ("DRY_RUN",    "测试模式", "干跑模式（不真实投递）", "bool", "false", ""),
    ("TEST_LIMIT", "匹配与投递", "本轮 AI 评估岗位数", "int", "0", "完成详情和范围筛选后进入 AI 评估尝试的岗位数量；不足时自动继续翻页补足，最多搜索 50 次；0 = 不限（高级设置决定搜索请求上限）"),
    ("LOGIN_WAIT", "测试模式", "登录等待秒数", "int", "0", "0 = 自动检测登录成功后继续；>0 = 最多等N秒"),
    ("KEEP_LOGIN", "测试模式", "保留登录信息", "bool", "true", "固定UA+持久profile，重启免登录；关闭则每次随机UA需重新登录"),
    ("BROWSER_PATH", "高级设置", "浏览器程序路径", "text", "", "留空自动检测随包 Chromium、Chrome 或 Edge；仅在自动检测失败时填写"),
    ("BROWSER_BACKGROUND", "高级设置", "浏览器后台运行", "bool", "true", "正常运行不显示窗口；扫码或验证时显示"),

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
    ("本轮任务", ["DRY_RUN", "TEST_LIMIT", "MATCH_THRESHOLD", "DAILY_LIMIT"]),
    ("在哪儿找工作", [
        "CITY_CODE", "PLATFORM_AREA_FILTER", "AREA_FILTER",
        "PLATFORM_JOB_TYPE", "JOB_TYPE_PREFERENCE", "PLATFORM_PART_TIME",
        "PLATFORM_PAY_TYPE", "PLATFORM_EXPERIENCE", "PLATFORM_DEGREE",
        "PLATFORM_INDUSTRY", "PLATFORM_SCALE",
    ]),
    ("作息与福利", [
        "REST_DAY_REQUIRE", "WORK_TIME_START", "WORK_TIME_END", "WELFARE_REQUIRE",
    ]),
    ("打招呼语", ["GREETING_PROMPT"]),
    ("可选画像搜索", ["TAVILY_ENABLED", "TAVILY_API_KEY"]),
]
ADVANCED_SECTIONS = [
    ("模型细节", ["AI_REASONING_EFFORT", "AI_TIMEOUT", "AI_MAX_RETRIES", "TAVILY_TIMEOUT"]),
    ("采集细节", ["DELIVER_MAX_PAGES"]),
    ("投递节奏", ["JOB_DELAY_MIN", "JOB_DELAY_MAX", "HUMAN_EVERY_N"]),
    ("浏览行为", [
        "HUMANIZE_ENABLE", "DETAIL_DELAY_MIN", "DETAIL_DELAY_MAX",
    ]),
    ("登录与调试", ["LOGIN_WAIT", "KEEP_LOGIN"]),
    ("浏览器", ["BROWSER_PATH", "BROWSER_BACKGROUND"]),
]

WORKFLOW_PAGES = (
    "求职设置", "画像查看", "增强画像", "投递结果", "运行日志",
)

PAGE_SUBTITLES = {
    "求职设置": "填好模型接口、简历与目标岗位即可开始；其余筛选项有合理默认值。",
    "画像查看": "对照查看简历解析出的基础画像与经你确认的增强画像。",
    "增强画像": "可选：通过访谈补齐简历没写到的技能与经历，让 AI 匹配更准。",
    "投递结果": "先看投递状态与匹配分，选中岗位可展开完整评估与证据。",
    "运行日志": "查看任务实时进度、当前岗位与完整输出日志。",
    "高级设置": "技术参数：超时重试、投递节奏、拟人行为与登录调试，平时不用改。",
}
DEFAULT_SUBTITLE = "调整求职筛选与自动化任务的运行参数。"

# 分组说明：每个设置分区卡片顶部的一句话解释
SECTION_HINTS = {
    "模型接口（必填）": "AI 评分与打招呼语都走这个接口，填错了所有任务都会失败。",
    "简历与目标岗位": "简历决定画像与证据，目标岗位决定搜索关键词。",
    "本轮任务": "控制这一轮评估多少岗位、投递多少条、是否只做干跑。",
    "在哪儿找工作": "城市、区域与平台侧筛选条件，共同决定抓到哪些岗位。",
    "作息与福利": "与 JD 明确冲突时直接过滤；福利只作为评分加分参考。",
    "打招呼语": "自定义表达方式、语气与长度，简历与画像会自动附在提示词后。",
    "可选画像搜索": "仅用于访谈追问，不会写入技能，也不会搜索你的简历。",
    "模型细节": "思考强度、超时与重试次数，直接影响速度与费用。",
    "采集细节": "搜索请求预算，目标岗位不足时自动扩大搜索范围。",
    "投递节奏": "岗位之间的等待间隔与穿插浏览频率。",
    "浏览行为": "停留时长与收藏门槛，用于降低被风控识别的概率。",
    "登录与调试": "登录等待与登录态保留方式。",
    "浏览器": "留空自动检测随包 Chromium、Chrome 或 Edge。",
}

# 侧边栏导航图标（assets 目录下的 SVG 线性图标）
NAV_ICONS = {
    "求职设置": "nav-settings.svg",
    "画像查看": "nav-user.svg",
    "增强画像": "nav-chat.svg",
    "投递结果": "nav-chart.svg",
    "运行日志": "nav-tools.svg",
    "高级设置": "nav-gear.svg",
}

# 启动前检查项：(显示名, 取值键)
SETUP_CHECKS = (
    ("AI 接口", "AI_API_KEY"),
    ("目标岗位", "DELIVER_KEYWORD"),
    ("简历文件", "RESUME_FILE"),
    ("工作城市", "CITY_CODE"),
)

SETUP_CHECK_LABELS = {key: label for label, key in SETUP_CHECKS}

# 独占整行的字段：多行文本、多选胶囊与带按钮的长输入
WIDE_FIELD_KEYS = {
    "GREETING_PROMPT",
    "PLATFORM_AREA_FILTER",
    "WELFARE_REQUIRE",
    "RESUME_FILE",
    "AI_BASE_URL",
    "PLATFORM_INDUSTRY",
    "AREA_FILTER",
}


def is_wide_field(key: str) -> bool:
    """该字段是否需要独占整行。"""
    return key in WIDE_FIELD_KEYS


# 输入控件的最大宽度：避免在宽屏下被拉成上千像素的空盒子，文字贴左显得孤立。
# 独占整行的字段有更宽的空间，给出更大的上限；窄字段保持紧凑。
FIELD_WIDTH = {
    "text": 420,
    "password": 420,
    "select": 300,
    "int": 170,
}
WIDE_FIELD_WIDTH = {
    "text": 620,
    "password": 620,
    "select": 360,
}


def key_label(key: str) -> str:
    """取字段的中文显示名。"""
    field = FIELD_BY_KEY.get(key)
    if field:
        return field[2]
    return SETUP_CHECK_LABELS.get(key, key)


def read_env_dict() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
        parsed = dotenv_values(ENV_FILE, interpolate=False)
        if "GREETING_PROMPT" in parsed:
            values["GREETING_PROMPT"] = parsed["GREETING_PROMPT"] or ""
    return values


def write_env_file(values: dict):
    """按 FIELDS 分组重写 .env。"""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
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
            elif ftype == "multiline":
                val = "'" + val.replace("\\", "\\\\").replace("'", "\\'") + "'"
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
        "GREETING_PROMPT": "greeting_prompt",
        "TAVILY_ENABLED": "tavily_enabled",
        "TAVILY_API_KEY": "tavily_api_key",
        "TAVILY_TIMEOUT": "tavily_timeout",
    }
    for env_key, cfg_key in mapping.items():
        if env_key not in values:
            continue
        raw = str(values[env_key] or "")
        if cfg_key != "greeting_prompt":
            raw = raw.strip()
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
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "app.ico")))
        self.resize(1420, 900)
        self.setMinimumSize(1180, 760)

        self.runner = TaskRunner()
        self.vars = {}                 # key -> (控件, 类型, 默认值)
        self.field_blocks = {}         # key -> 该配置项的字段块（用于定位跳转）
        self.field_pages = {}          # key -> 所在页面名
        self.multiselect_checks = {}   # key -> [(选项, QCheckBox)]
        self.platform_area_choices = []
        self._last_platform_job_type = "不限"
        self._unrestricted_job_type_preference = "实习"
        self.pending_platform_area_values = []
        self.location_events = queue.Queue()
        self.location_generation = 0
        self.location_city_code = ""
        self.industry_events = queue.Queue()
        self.industry_generation = 0
        self.platform_industry_groups = []
        self.platform_industry_choices = {}
        self.platform_industry_names = {}
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

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_workspace(), 1)
        root_layout.addWidget(body, 1)

        self._show_page("求职设置")

    def _build_workspace(self) -> QWidget:
        """右侧工作区：顶部标题条 + 页面内容。"""
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_topbar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 20, 28, 26)
        content_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        self.pages = {}
        settings = ["高级设置"]

        builders = {
            "求职设置": lambda: self._build_settings_page(SETTINGS_SECTIONS, True, "求职设置"),
            "画像查看": self._build_profile_view_page,
            "增强画像": self._build_candidate_profile_page,
            "高级设置": lambda: self._build_settings_page(ADVANCED_SECTIONS, False, "高级设置"),
            "投递结果": self._build_result_page,
            "运行日志": self._build_log_page,
        }
        for name in (*WORKFLOW_PAGES, *settings):
            page = builders[name]()
            self.pages[name] = page
            self.page_stack.addWidget(page)

        content_layout.addWidget(self.page_stack, 1)
        workspace_layout.addWidget(content, 1)
        self.config_notice = ToastNotice(workspace)
        return workspace

    def _build_topbar(self) -> QFrame:
        """顶部标题条：左侧当前页标题，右侧全局状态与主操作。"""
        topbar = QFrame()
        topbar.setObjectName("header")
        topbar.setFixedHeight(76)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(28, 0, 24, 0)
        layout.setSpacing(14)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(3)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        layout.addWidget(self._build_status_chip())

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("ghost")
        self.btn_refresh.setIcon(QIcon(str(ASSETS_DIR / "refresh.svg")))
        self.btn_refresh.setIconSize(QSize(15, 15))
        self.btn_refresh.setToolTip("重新读取结果文件与画像数据")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_results)
        layout.addWidget(self.btn_refresh)

        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("soft")
        self.btn_save.setIcon(QIcon(str(ASSETS_DIR / "save.svg")))
        self.btn_save.setIconSize(QSize(15, 15))
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
        return topbar

    def _build_status_chip(self) -> QFrame:
        """运行状态胶囊：状态点 + 状态文案（固定高度，不随顶栏拉伸）。"""
        holder = QFrame()
        holder.setObjectName("statusCluster")
        holder.setFixedHeight(34)
        holder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row = QHBoxLayout(holder)
        row.setContentsMargins(13, 0, 15, 0)
        row.setSpacing(9)

        self.status_dot = StatusDot()
        row.addWidget(self.status_dot, 0, Qt.AlignVCenter)

        self.status_label = QLabel(self.status_text)
        self.status_label.setObjectName("statusText")
        row.addWidget(self.status_label, 0, Qt.AlignVCenter)
        return holder

    def _build_sidebar(self) -> QFrame:
        """左侧导航栏：品牌区 + 分组导航 + 底部今日配额。"""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 16)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 0, 4, 0)
        brand_row.setSpacing(11)
        mark = QLabel("职")
        mark.setObjectName("sidebarLogo")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        brand_row.addWidget(mark)
        brand_texts = QVBoxLayout()
        brand_texts.setContentsMargins(0, 0, 0, 0)
        brand_texts.setSpacing(2)
        brand = QLabel("求职工作台")
        brand.setObjectName("sidebarBrand")
        brand_texts.addWidget(brand)
        tagline = QLabel("岗位筛选与简历匹配")
        tagline.setObjectName("sidebarTag")
        brand_texts.addWidget(tagline)
        brand_row.addLayout(brand_texts)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(18)

        self.nav_buttons = {}
        self._add_nav_section(
            sidebar, layout, "求职流程",
            ["求职设置", "增强画像", "投递结果", "运行日志"],
        )
        self._add_nav_section(
            sidebar, layout, "查看与配置", ["画像查看", "高级设置"],
        )
        layout.addStretch(1)
        layout.addWidget(self._build_sidebar_footer())
        self.btn_about = QPushButton("关于", sidebar)
        self.btn_about.setObjectName("nav")
        self.btn_about.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.btn_about.setIconSize(QSize(16, 16))
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.setToolTip("作者信息与免责声明")
        self.btn_about.clicked.connect(self._open_about)
        layout.addWidget(self.btn_about)
        return sidebar

    def _open_about(self):
        AboutDialog(self).exec()

    def _build_sidebar_footer(self) -> QFrame:
        """侧边栏底部：今日投递配额与进度。"""
        card = QFrame()
        card.setObjectName("sideFooter")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 13)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        caption = QLabel("今日投递")
        caption.setObjectName("sideCaption")
        row.addWidget(caption)
        row.addStretch(1)
        self.status_quota = QLabel("0 / 0")
        self.status_quota.setObjectName("sideMetric")
        row.addWidget(self.status_quota)
        layout.addLayout(row)

        self.status_bar = QProgressBar()
        self.status_bar.setObjectName("quotaBar")
        self.status_bar.setRange(0, 50)
        self.status_bar.setValue(0)
        self.status_bar.setTextVisible(False)
        self.status_bar.setFixedHeight(6)
        layout.addWidget(self.status_bar)
        return card

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
        elif name == "投递结果":
            try:
                self.refresh_results()
            except Exception as exc:
                print(f"[面板] 刷新结果失败: {exc}")

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
    def _build_settings_page(self, sections, show_checklist=False, page_name=""):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 0, 2, 0)
        toolbar.addWidget(self._label("启动任务时会自动保存当前设置", "hint"))
        toolbar.addStretch(1)
        env_toggle = QPushButton("查看原始 .env")
        env_toggle.setCheckable(True)
        env_toggle.setObjectName("ghost")
        env_toggle.setCursor(Qt.PointingHandCursor)
        env_toggle.clicked.connect(self._toggle_env_preview)
        toolbar.addWidget(env_toggle)
        page_layout.addLayout(toolbar)
        page_layout.addSpacing(12)

        env_preview = QPlainTextEdit()
        env_preview.setObjectName("envPreview")
        env_preview.setReadOnly(True)
        env_preview.setVisible(False)
        env_preview.setFixedHeight(190)
        env_preview.setPlaceholderText("（.env 文件为空）")
        self.env_previews.append((env_toggle, env_preview))
        page_layout.addWidget(env_preview)
        page_layout.addSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 8)
        inner_layout.setSpacing(16)

        if show_checklist:
            inner_layout.addWidget(self._build_setup_checklist())

        for title, keys in sections:
            inner_layout.addWidget(self._build_config_section(title, keys, page_name))

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        page_layout.addWidget(scroll, 1)
        return page

    def _build_setup_checklist(self):
        """启动前检查：把「还差什么」直接摆出来，点击可跳到对应输入框。"""
        card = SectionCard(
            "启动前检查", "这四项填好就能直接启动投递任务，其余筛选项都有默认值。"
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.setup_check_labels = {}
        for name, key in SETUP_CHECKS:
            chip = ClickableLabel(f"○ {name}")
            chip.setObjectName("checkTodo")
            chip.setToolTip(f"点击定位到「{name}」的设置项")
            chip.clicked.connect(lambda _=False, k=key: self._focus_field(k))
            row.addWidget(chip)
            self.setup_check_labels[key] = chip
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _focus_field(self, key):
        """跳到指定配置项并聚焦它的输入框。"""
        block = self.field_blocks.get(key)
        if block is None:
            return
        page_name = self.field_pages.get(key)
        if page_name:
            self._show_page(page_name)
        widget = self.vars.get(key, (None, "", ""))[0]
        scroll = self._find_scroll_area(block)
        if scroll is not None:
            scroll.ensureWidgetVisible(block, 0, 40)
        if widget is not None and hasattr(widget, "setFocus"):
            widget.setFocus()
        self.statusBar().showMessage(f"已定位到「{key_label(key)}」", 2500)

    @staticmethod
    def _find_scroll_area(widget):
        """向上找到包裹该控件的 QScrollArea（找不到则返回 None）。"""
        parent = widget.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parent()
        return None

    def _refresh_setup_checks(self, *_args):
        """更新启动前检查条：逐项标记是否已就绪。"""
        labels = getattr(self, "setup_check_labels", None)
        if not labels:
            return
        for (name, key), chip in zip(SETUP_CHECKS, labels.values()):
            widget = self.vars.get(key, (None, "", ""))[0]
            if widget is None:
                continue
            if key == "CITY_CODE":
                value = widget.currentText().strip()
            else:
                value = widget.text().strip() if hasattr(widget, "text") else ""
            ready = bool(value)
            if ready and key == "RESUME_FILE":
                ready = self._resume_file_exists(value)
            chip.setText(f"✓ {name}" if ready else f"○ {name}")
            self._set_widget_style(chip, "checkOk" if ready else "checkTodo")

    def _build_config_section(self, title, keys, page_name=""):
        """一个设置分区：卡片头 + 自适应两列表单。"""
        card = SectionCard(title, SECTION_HINTS.get(title, ""))

        reset_button = QPushButton("恢复默认值")
        reset_button.setObjectName("ghost")
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.setToolTip("把本组配置恢复为内置默认值（点「保存配置」后写入 .env）")
        reset_button.clicked.connect(
            lambda _checked=False, k=list(keys), t=title: self._reset_section_defaults(k, t)
        )
        card.header_actions.addWidget(reset_button)

        grid = FormGrid()
        for key in keys:
            # 开关行与输入框结构不同，混排会错位，单独占整行更整齐。
            block = self._build_field_block(key)
            self.field_blocks[key] = block
            if page_name:
                self.field_pages[key] = page_name
            grid.add(
                block,
                full_width=is_wide_field(key) or FIELD_BY_KEY[key][3] == "bool",
            )
        card.body.addWidget(grid)
        return card

    def _build_field_block(self, key):
        """单个配置项：布尔用开关行，其余用「标题 + 控件 + 说明」。"""
        _, _group, label, ftype, default, note = FIELD_BY_KEY[key]

        if ftype == "bool":
            row = ToggleRow(label, note)
            self.vars[key] = (row, ftype, default)
            if key in CONFIG_WARNINGS:
                hint = self._label("", "warnText", wrap=True)
                self.field_hints[key] = hint
                row.add_message(hint)
                row.toggled.connect(self._refresh_field_hints)
            row.toggled.connect(self._refresh_setup_checks)
            return row

        control = self._build_field_control(key)
        block = FieldBlock(label, control, note)
        return block

    def _build_field_control(self, key):
        """构造输入控件，返回可直接放进 FieldBlock 的控件。"""
        _, _group, label, ftype, default, _note = FIELD_BY_KEY[key]
        # 独占整行的字段有更宽的空间，用更宽松的上限
        limits = WIDE_FIELD_WIDTH if is_wide_field(key) else FIELD_WIDTH

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
                self.platform_area_choices = checks
                self.multiselect_checks[key] = checks
                self.platform_area_status = self._label("正在读取所选城市的区域…", "muted", wrap=True)
                self.platform_area_refresh = QPushButton("刷新区域")
                self.platform_area_refresh.setObjectName("soft")
                self.platform_area_refresh.setToolTip("重新读取当前城市在 BOSS 上可筛选的区域")
                self.platform_area_refresh.clicked.connect(self._refresh_platform_areas)
                container = QWidget()
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.setSpacing(8)
                container_layout.addWidget(host)
                status_row = QHBoxLayout()
                status_row.setContentsMargins(0, 0, 0, 0)
                status_row.setSpacing(8)
                status_row.addWidget(self.platform_area_status, 1)
                status_row.addWidget(self.platform_area_refresh)
                container_layout.addLayout(status_row)
                self.vars[key] = (host, ftype, default)
                return container
            self.multiselect_checks[key] = checks
            self.vars[key] = (host, ftype, default)
            return host

        if ftype == "select":
            widget = QComboBox()
            widget.addItems(SELECT_OPTIONS[key])
            widget.setCursor(Qt.PointingHandCursor)
            widget.setMaximumWidth(limits["select"])
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
            widget.setMaximumWidth(limits["password"])
        elif ftype == "multiline":
            widget = QPlainTextEdit()
            widget.setMinimumHeight(170)
            widget.setMaximumHeight(240)
            widget.setTabChangesFocus(False)
        elif ftype == "int":
            low, high = INT_LIMITS.get(key, (0, 999999))
            widget = QSpinBox()
            widget.setRange(low, high)
            try:
                widget.setValue(int(default))
            except ValueError:
                widget.setValue(low)
            widget.setAccelerated(True)
            widget.setMaximumWidth(FIELD_WIDTH["int"])
            pad_spinbox_text(widget)
        else:
            widget = QLineEdit()
            widget.setMaximumWidth(limits["text"])

        if ftype == "multiline":
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            container_layout.addWidget(widget)
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(4)

            reset_prompt = QPushButton("恢复默认提示词")
            reset_prompt.setObjectName("ghost")
            reset_prompt.setToolTip("只重置提示词编辑框，不会自动保存")
            reset_prompt.clicked.connect(
                lambda: widget.setPlainText(DEFAULT_GREETING_PROMPT)
            )
            actions.addWidget(reset_prompt)

            test_prompt = QPushButton("测试提示词")
            test_prompt.setObjectName("ghost")
            test_prompt.setToolTip("用当前编辑中的提示词生成一条测试招呼语，不会投递")
            test_prompt.clicked.connect(self._open_greeting_prompt_test)
            actions.addWidget(test_prompt)
            actions.addStretch(1)
            container_layout.addLayout(actions)
            self.vars[key] = (widget, ftype, default)
            return container

        if key == "RESUME_FILE":
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            input_row = QHBoxLayout()
            input_row.setContentsMargins(0, 0, 0, 0)
            input_row.setSpacing(8)
            # 简历路径后面跟着两个按钮，输入框留出足够空间而不撑爆整行
            widget.setMaximumWidth(430)
            input_row.addWidget(widget, 1)
            browse_button = QPushButton("选择文件")
            browse_button.setObjectName("soft")
            browse_button.setToolTip("浏览并选择简历文件（markdown 或文本）")
            browse_button.setCursor(Qt.PointingHandCursor)
            browse_button.clicked.connect(self._browse_resume)
            input_row.addWidget(browse_button)
            self.resume_struct_button = QPushButton("结构化简历")
            self.resume_struct_button.setObjectName("soft")
            self.resume_struct_button.setToolTip(
                "调用模型把简历提取为结构化摘要（逐字摘录），供画像访谈与岗位评分使用"
            )
            self.resume_struct_button.setCursor(Qt.PointingHandCursor)
            self.resume_struct_button.clicked.connect(self._structure_resume)
            input_row.addWidget(self.resume_struct_button)
            container_layout.addLayout(input_row)
            self.resume_digest_status = self._label("", "muted", wrap=True)
            container_layout.addWidget(self.resume_digest_status)
            hint = self._label("", "errorText", wrap=True)
            self.field_hints[key] = hint
            container_layout.addWidget(hint)
            self.vars[key] = (widget, ftype, default)
            widget.textChanged.connect(self._refresh_field_hints)
            widget.textChanged.connect(self._refresh_setup_checks)
            return container

        self.vars[key] = (widget, ftype, default)
        if key == "PLATFORM_INDUSTRY":
            return self._build_industry_picker(widget)
        if key == "PLATFORM_JOB_TYPE":
            widget.currentTextChanged.connect(self._on_platform_job_type_changed)
        elif key == "JOB_TYPE_PREFERENCE":
            widget.currentTextChanged.connect(self._on_job_type_preference_changed)
        if key in ("AI_API_KEY", "DELIVER_KEYWORD"):
            widget.textChanged.connect(self._refresh_setup_checks)
        if key == "CITY_CODE":
            widget.currentTextChanged.connect(self._refresh_setup_checks)
        if key not in ("WORK_TIME_START", "WORK_TIME_END"):
            return widget

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)
        container_layout.addWidget(widget)
        hint = self._label("", "errorText", wrap=True)
        self.field_hints[key] = hint
        container_layout.addWidget(hint)
        widget.textChanged.connect(self._refresh_field_hints)
        return container

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
            elif ftype == "multiline":
                widget.setPlainText(str(default))
            else:
                widget.setText(str(default))
        self._refresh_field_hints()
        self._refresh_setup_checks()
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
            elif ftype == "multiline":
                widget.setPlainText(val)
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
        self._refresh_setup_checks()
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

    def _build_industry_picker(self, field):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        field.setPlaceholderText("行业 ID，或包含 industry 参数的搜索链接")
        row.addWidget(field, 1)
        self.platform_industry_refresh = QPushButton("加载行业")
        self.platform_industry_refresh.setObjectName("soft")
        self.platform_industry_refresh.setCursor(Qt.PointingHandCursor)
        self.platform_industry_refresh.setToolTip("从 BOSS 读取可筛选的行业分类")
        self.platform_industry_refresh.clicked.connect(self._refresh_platform_industries)
        row.addWidget(self.platform_industry_refresh)
        layout.addLayout(row)

        self.platform_industry_category = QComboBox()
        self.platform_industry_category.addItem("请选择行业分类")
        self.platform_industry_category.setEnabled(False)
        self.platform_industry_category.setMaximumWidth(WIDE_FIELD_WIDTH["select"])
        self.platform_industry_category.currentIndexChanged.connect(self._show_industry_category)
        layout.addWidget(self.platform_industry_category)

        self.platform_industry_scroll = QScrollArea()
        self.platform_industry_scroll.setWidgetResizable(True)
        self.platform_industry_scroll.setFixedHeight(168)
        self.platform_industry_scroll.setVisible(False)
        list_host = QWidget()
        self.platform_industry_list = QVBoxLayout(list_host)
        self.platform_industry_list.setContentsMargins(8, 6, 8, 6)
        self.platform_industry_list.setSpacing(6)
        self.platform_industry_list.setAlignment(Qt.AlignTop)
        self.platform_industry_scroll.setWidget(list_host)
        layout.addWidget(self.platform_industry_scroll)

        self.platform_industry_status = self._label(
            "可加载行业分类，或直接填写行业 ID / 搜索链接。", "muted", wrap=True
        )
        self.platform_industry_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.platform_industry_status)
        field.textChanged.connect(self._sync_industry_choices)
        return container

    def _refresh_platform_industries(self, *_args):
        self.industry_generation += 1
        generation = self.industry_generation
        self.platform_industry_refresh.setEnabled(False)
        self.platform_industry_status.setText("正在读取行业分类…")

        def fetch():
            try:
                payload = (generation, fetch_platform_industries(), "")
            except Exception as exc:
                payload = (generation, [], str(exc))
            self.industry_events.put(payload)

        threading.Thread(target=fetch, daemon=True).start()

    def _apply_platform_industries(self, generation, groups, error):
        if generation != self.industry_generation:
            return
        self.platform_industry_refresh.setEnabled(True)
        self.platform_industry_refresh.setText("刷新行业")
        self.platform_industry_groups = groups if not error else []
        self.platform_industry_names = {
            child["code"]: child["name"]
            for group in self.platform_industry_groups
            for child in group["children"]
        }
        self.platform_industry_category.blockSignals(True)
        self.platform_industry_category.clear()
        self.platform_industry_category.addItem("请选择行业分类")
        for group in self.platform_industry_groups:
            self.platform_industry_category.addItem(group["name"], group["code"])
        self.platform_industry_category.blockSignals(False)
        self.platform_industry_category.setEnabled(bool(self.platform_industry_groups))
        if error or not groups:
            self._clear_industry_choices()
            self.platform_industry_scroll.setVisible(False)
            self.platform_industry_status.setText(
                f"行业加载失败：{error}" if error else "平台未返回行业分类；仍可手填 ID。"
            )
            return

        selected = resolve_platform_filter(
            "PLATFORM_INDUSTRY", self.vars["PLATFORM_INDUSTRY"][0].text()
        ).split(",")
        first = next((
            index for index, group in enumerate(groups, 1)
            if any(child["code"] in selected for child in group["children"])
        ), 1)
        self.platform_industry_category.setCurrentIndex(first)
        self._update_industry_status()

    def _clear_industry_choices(self):
        self.platform_industry_choices = {}
        while self.platform_industry_list.count():
            item = self.platform_industry_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _show_industry_category(self, index):
        self._clear_industry_choices()
        if index < 1 or index > len(self.platform_industry_groups):
            self.platform_industry_scroll.setVisible(False)
            return
        selected = set(resolve_platform_filter(
            "PLATFORM_INDUSTRY", self.vars["PLATFORM_INDUSTRY"][0].text()
        ).split(","))
        for child in self.platform_industry_groups[index - 1]["children"]:
            code = child["code"]
            check = QCheckBox(child["name"])
            check.setObjectName("chipCheck")
            check.setCursor(Qt.PointingHandCursor)
            check.setToolTip(f"{child['name']} ({code})")
            check.setChecked(code in selected)
            check.toggled.connect(
                lambda checked, industry_code=code:
                self._on_industry_choice_toggled(industry_code, checked)
            )
            self.platform_industry_list.addWidget(check)
            self.platform_industry_choices[code] = check
        self.platform_industry_scroll.setVisible(True)

    def _sync_industry_choices(self, *_args):
        text = self.vars["PLATFORM_INDUSTRY"][0].text()
        selected = set(resolve_platform_filter("PLATFORM_INDUSTRY", text).split(","))
        for code, check in self.platform_industry_choices.items():
            check.blockSignals(True)
            check.setChecked(code in selected)
            check.blockSignals(False)
        if self.platform_industry_groups:
            self._update_industry_status()

    def _on_industry_choice_toggled(self, code, checked):
        field = self.vars["PLATFORM_INDUSTRY"][0]
        text = field.text().strip()
        normalized = resolve_platform_filter("PLATFORM_INDUSTRY", text)
        if text and not normalized:
            self._sync_industry_choices()
            self.platform_industry_status.setText("请先修正行业 ID 或搜索链接，再选择行业。")
            return
        selected = [part for part in normalized.split(",") if part]
        if checked and code not in selected:
            if len(selected) >= 3:
                self._sync_industry_choices()
                self.platform_industry_status.setText("平台最多选择 3 个行业；请先取消一个。")
                return
            selected.append(code)
        elif not checked:
            selected = [item for item in selected if item != code]
        field.setText(",".join(selected))
        self._update_industry_status()

    def _update_industry_status(self):
        text = self.vars["PLATFORM_INDUSTRY"][0].text().strip()
        normalized = resolve_platform_filter("PLATFORM_INDUSTRY", text)
        if text and not normalized:
            self.platform_industry_status.setText(
                "已加载行业分类；当前手填值无效，请检查 ID 或搜索链接。"
            )
            return
        selected = [part for part in normalized.split(",") if part]
        names = "、".join(self.platform_industry_names.get(code, code) for code in selected)
        self.platform_industry_status.setText(
            f"已加载 {len(self.platform_industry_groups)} 个分类；"
            + (f"已选：{names}" if selected else "未选择行业")
        )

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
        self.pending_platform_area_values = []

    def _clear_platform_area_options(self):
        while self.platform_area_flow.count():
            item = self.platform_area_flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_greeting_prompt_test(self):
        values = self._read_widget_values()
        api_key = str(values.get("AI_API_KEY", "")).strip()
        if not api_key:
            QMessageBox.warning(self, "无法测试招呼语", "请先填写 AI API Key。")
            return

        resume_path = Path(values.get("RESUME_FILE", "resume.md").strip() or "resume.md")
        if not resume_path.is_absolute():
            resume_path = BASE_DIR / resume_path
        try:
            resume = resume_path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "无法测试招呼语", f"简历读取失败：{exc}")
            return
        if not resume.strip():
            QMessageBox.warning(self, "无法测试招呼语", "简历文件为空。")
            return
        try:
            candidate_profile = CandidateProfileStore().load()
        except ValueError as exc:
            QMessageBox.warning(self, "无法测试招呼语", f"候选人画像无效：{exc}")
            return

        config = current_deliver_config()
        config.update({
            "ai_base_url": values.get("AI_BASE_URL", "").strip()
            or "https://api.deepseek.com/v1",
            "ai_api_key": api_key,
            "ai_model": values.get("AI_MODEL", "").strip() or "deepseek-chat",
            "ai_timeout": int(values.get("AI_TIMEOUT", 90) or 90),
            "ai_max_retries": int(values.get("AI_MAX_RETRIES", 2) or 0),
            "greeting_prompt": values.get("GREETING_PROMPT", DEFAULT_GREETING_PROMPT),
        })

        dialog = QDialog(self)
        dialog.setWindowTitle("测试招呼语提示词")
        dialog.setMinimumSize(700, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addWidget(self._label("岗位名称", "fieldLabel"), 0, 0)
        job_title = QLineEdit("AI 应用开发实习生")
        form.addWidget(job_title, 0, 1)
        form.addWidget(self._label("公司名称", "fieldLabel"), 1, 0)
        company = QLineEdit("示例公司")
        form.addWidget(company, 1, 1)
        form.addWidget(self._label("岗位描述", "fieldLabel"), 2, 0, Qt.AlignTop)
        job_description = QPlainTextEdit()
        job_description.setMinimumHeight(110)
        job_description.setPlainText("负责 AI 应用开发、RAG 检索与后端接口维护。")
        form.addWidget(job_description, 2, 1)
        layout.addLayout(form)

        layout.addWidget(self._label("生成结果", "fieldLabel"))
        result = QPlainTextEdit()
        result.setReadOnly(True)
        result.setPlaceholderText("测试招呼语会显示在这里")
        layout.addWidget(result, 1)
        status = self._label(
            "使用当前简历、候选人画像和编辑中的提示词；不会保存或投递。",
            "hint", wrap=True,
        )
        layout.addWidget(status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        generate = QPushButton("生成测试语")
        close = QPushButton("关闭")
        close.clicked.connect(dialog.reject)
        actions.addWidget(generate)
        actions.addWidget(close)
        layout.addLayout(actions)

        events = queue.Queue()
        timer = QTimer(dialog)

        def poll_result():
            try:
                kind, payload = events.get_nowait()
            except queue.Empty:
                return
            timer.stop()
            generate.setEnabled(True)
            if kind == "error":
                status.setText(f"生成失败：{payload}")
                result.clear()
            elif payload:
                result.setPlainText(payload)
                status.setText("生成完成。")
            else:
                result.clear()
                status.setText("模型未返回招呼语，请检查接口配置或稍后重试。")

        def generate_greeting():
            job = {
                "工作名称": job_title.text().strip(),
                "公司": company.text().strip(),
                "技术要求": "",
                "工作介绍": job_description.toPlainText().strip(),
            }
            generate.setEnabled(False)
            result.clear()
            status.setText("正在调用模型生成…")
            timer.start(100)

            def worker():
                try:
                    # 延迟导入：ai_client 会连带加载 LangChain，冷启动时不必付出这段耗时
                    from ai_client import AIClient

                    greeting = AIClient(config).gen_greeting(
                        resume, job, candidate_profile=candidate_profile
                    )
                    events.put(("ok", greeting))
                except Exception as exc:
                    events.put(("error", str(exc)))

            threading.Thread(target=worker, daemon=True).start()

        timer.timeout.connect(poll_result)
        generate.clicked.connect(generate_greeting)
        dialog.exec()

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
            elif ftype == "multiline":
                values[key] = widget.toPlainText()
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
            self.config_notice.dismiss()
            return
        if not self._persist_config(values):
            return
        self.append_log(f"[面板] {time.strftime('%H:%M:%S')} 配置已保存到 .env")
        self.statusBar().showMessage("配置已保存", 2500)
        message = "配置已保存，下次启动任务时生效" if self.runner.running() else "配置已保存"
        self.config_notice.show_message(message)

    def _persist_config(self, values):
        try:
            write_env_file(values)
        except (OSError, UnicodeError) as exc:
            if isinstance(exc, PermissionError):
                reason = "无法写入配置文件，请检查文件权限后重试"
            elif isinstance(exc, UnicodeError):
                reason = "配置中有无法保存的字符，请检查输入后重试"
            else:
                reason = "无法写入配置文件，请检查存储空间和文件状态后重试"
            self.config_notice.show_message(f"配置保存失败：{reason}", kind="error")
            self.append_log(f"[面板] {time.strftime('%H:%M:%S')} 配置保存失败：{exc}")
            return False
        return True

    # ---------------- 运行日志页 ----------------
    def _build_log_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # 状态区：进度条 + 统计 + 当前岗位卡
        status_card = SectionCard("运行监控", "任务启动后这里实时显示评分进度与当前岗位。")
        self.run_state_chip = self._label("空闲", "statusChipIdle")
        status_card.header_actions.addWidget(self.run_state_chip)

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
        status_card.body.addWidget(progress_row)

        stats_row = QWidget()
        stats_layout = QHBoxLayout(stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(10)
        self.run_stat_scored = self._stat_tile("已评分", "0")
        self.run_stat_delivered = self._stat_tile("已投递", "0")
        self.run_stat_today = self._stat_tile("今日投递", "0 / 0")
        for tile, _value in (self.run_stat_scored, self.run_stat_delivered,
                             self.run_stat_today):
            stats_layout.addWidget(tile, 1)
        status_card.body.addWidget(stats_row)

        job_card, job_layout = self._card((16, 13, 16, 13), 6)
        job_head = QWidget()
        job_head_layout = QHBoxLayout(job_head)
        job_head_layout.setContentsMargins(0, 0, 0, 0)
        job_head_layout.setSpacing(8)
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
        status_card.body.addWidget(job_card)
        layout.addWidget(status_card)

        card, card_layout = self._card((20, 16, 20, 18), 12)
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)
        toolbar_layout.addWidget(self._label("任务输出", "section"))
        toolbar_layout.addStretch(1)
        self.log_filter_ai = QCheckBox("只看 AI 相关")
        self.log_filter_ai.setObjectName("chipCheck")
        self.log_filter_ai.setToolTip("只显示 [AI] 行；不影响日志写入")
        self.log_filter_ai.setCursor(Qt.PointingHandCursor)
        self.log_filter_ai.toggled.connect(self._rebuild_log_view)
        toolbar_layout.addWidget(self.log_filter_ai)
        self.log_filter_error = QCheckBox("只看错误")
        self.log_filter_error.setObjectName("chipCheck")
        self.log_filter_error.setToolTip("只显示错误行；不影响日志写入")
        self.log_filter_error.setCursor(Qt.PointingHandCursor)
        self.log_filter_error.toggled.connect(self._rebuild_log_view)
        toolbar_layout.addWidget(self.log_filter_error)
        clear = QPushButton("清空日志")
        clear.setObjectName("ghost")
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
        tile = StatTile(label, value)
        tile.setMinimumWidth(128)
        return tile, tile.value_label

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
        if not self._persist_config(values):
            return

        msg = self.runner.start()
        if not self.runner.running():
            self.config_notice.show_message("配置已保存，但任务未能启动", kind="error")
            QMessageBox.warning(self, "启动失败", msg)
        else:
            self.config_notice.show_message("配置已保存，任务已启动")
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
                generation, groups, error = self.industry_events.get_nowait()
            except queue.Empty:
                break
            self._apply_platform_industries(generation, groups, error)
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
            manually_stopped = getattr(self.runner, "stop_requested", False)
            self.status_label.setText(
                format_exit_status(exit_code, manually_stopped)
            )
            if exit_code is None:
                self._set_widget_style(self.status_dot, "statusDotIdle")
                self._set_widget_style(self.run_state_chip, "statusChipIdle")
                self.run_state_chip.setText("空闲")
            elif manually_stopped:
                self._set_widget_style(self.status_dot, "statusDotIdle")
                self._set_widget_style(self.run_state_chip, "statusChipIdle")
                self.run_state_chip.setText("已停止")
            elif exit_code == 0:
                self._set_widget_style(self.status_dot, "statusDotDone")
                self._set_widget_style(self.run_state_chip, "statusChipOk")
                self.run_state_chip.setText("正常结束")
            elif exit_code == 130:
                self._set_widget_style(self.status_dot, "statusDotIdle")
                self._set_widget_style(self.run_state_chip, "statusChipWarn")
                self.run_state_chip.setText("已中断")
            else:
                self._set_widget_style(self.status_dot, "statusDotIdle")
                self._set_widget_style(self.run_state_chip, "statusChipWarn")
                self.run_state_chip.setText("运行失败")
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
