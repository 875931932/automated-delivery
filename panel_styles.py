# -*- coding: utf-8 -*-
"""界面样式表（QSS）：现代浅色工作台设计系统。

设计令牌（集中在这里，便于统一调整）
  画布 canvas   #F5F6F8
  卡片 surface  #FFFFFF / #FAFBFC
  描边 border   #E7E9EE（细）#D5DAE3（强）
  文字 text     #101828 主 / #344054 次 / #667085 辅助（对比度 ≥ 4.5:1）
  强调 accent   #2F5BEA / 深 #1F3DAD / 浅 #EEF3FE
  语义色        成功 #0B7A55 警告 #A15C07 危险 #B42318
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets"


def _url(name: str) -> str:
    """把资源文件转成 QSS 可用的 url() 写法（正斜杠，兼容非 ASCII 路径）。"""
    return (ASSETS_DIR / name).as_posix()


STYLESHEET = f"""
/* ============================ 基础 ============================ */
QWidget {{
    background: transparent;
    color: #101828;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
}}
QToolTip {{
    background: #1D2939; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 6px 9px; font-size: 12px;
}}
QMenu {{
    background: #FFFFFF; border: 1px solid #D5DAE3; border-radius: 10px;
    padding: 6px; color: #101828;
}}
QMenu::item {{ padding: 6px 20px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: #EEF3FE; color: #1F3DAD; }}

/* ============================ 结构容器 ============================ */
QFrame#root {{ background: #F5F6F8; }}
QFrame#header {{
    background: #FFFFFF; border-bottom: 1px solid #E7E9EE;
}}
QFrame#sidebar {{
    background: #131722; border-right: 1px solid #0C0F16;
}}
QFrame#card {{
    background: #FFFFFF; border: 1px solid #E7E9EE; border-radius: 14px;
}}
QFrame#inset {{
    background: #FAFBFC; border: 1px solid #ECEEF2; border-radius: 10px;
}}
QFrame#divider {{
    background: #ECEEF2; border: none; max-height: 1px; min-height: 1px;
}}
QFrame#softDivider {{
    background: #F2F4F7; border: none; max-height: 1px; min-height: 1px;
}}
QFrame#errorBanner {{
    background: #FEF3F2; border: 1px solid #FBD5D1; border-radius: 12px;
}}
QFrame#composer {{
    background: #FFFFFF; border: 1px solid #E1E5EB; border-radius: 14px;
}}
QFrame#bubbleAI {{
    background: #F7F8FA; border: 1px solid #ECEEF2;
    border-radius: 4px 14px 14px 14px;
}}
QFrame#bubbleUser {{
    background: #EEF3FE; border: 1px solid #D9E3FD;
    border-radius: 14px 4px 14px 14px;
}}
QFrame#bubbleError {{
    background: #FEF3F2; border: 1px solid #FBD5D1; border-radius: 14px;
}}
QFrame#avatar {{
    background: #1F3DAD; color: #FFFFFF; border-radius: 13px;
    font-size: 11px; font-weight: bold;
}}
QFrame#avatarUser {{
    background: #EEF3FE; color: #1F3DAD; border: 1px solid #D9E3FD;
    border-radius: 13px; font-size: 11px; font-weight: bold;
}}
QFrame#evidenceCard {{
    background: #FAFBFC; border: 1px solid #ECEEF2; border-radius: 10px;
}}
QFrame#pendingCard {{
    background: #FFFAEB; border: 1px solid #FDE3A7; border-radius: 10px;
}}

/* ============================ 文字 ============================ */
QLabel#brand {{ font-size: 16px; font-weight: bold; color: #101828; }}
QLabel#brandSub {{ font-size: 12px; color: #667085; }}
QLabel#brandMark {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6C97FF, stop:1 #2F5BEA);
    color: #FFFFFF; border-radius: 11px;
    font-size: 17px; font-weight: bold;
}}
QLabel#statusText {{ font-size: 13px; font-weight: bold; color: #101828; }}
QLabel#statusQuota {{ font-size: 13px; font-weight: bold; color: #344054; }}
QFrame#statusCluster {{
    background: #F7F8FA; border: 1px solid #ECEEF2; border-radius: 14px;
}}
QFrame#vDivider {{ background: #E4E7EC; border: none; max-width: 1px; }}
QLabel#statusDotIdle {{
    background: #98A2B3; border: none; border-radius: 5px;
}}
QLabel#statusDotRunning {{
    background: #12B76A; border: none; border-radius: 5px;
}}
QLabel#statusDotDone {{
    background: #2F5BEA; border: none; border-radius: 5px;
}}
QLabel#pageTitle {{ font-size: 21px; font-weight: bold; color: #101828; }}
QLabel#pageSubtitle {{ font-size: 13px; color: #667085; }}
QLabel#section {{ font-size: 15px; font-weight: bold; color: #101828; }}
QLabel#sectionHint {{ font-size: 12px; color: #667085; }}
QLabel#muted {{ font-size: 12px; color: #667085; }}
QLabel#fieldLabel {{ font-size: 13px; font-weight: bold; color: #344054; }}
QLabel#fieldNote {{ font-size: 12px; color: #667085; }}
QLabel#hint {{ font-size: 12px; color: #667085; }}
QLabel#warnText {{ font-size: 12px; color: #A15C07; }}
QLabel#errorText {{ font-size: 12px; color: #B42318; }}
QLabel#draftEmpty {{ color: #667085; font-size: 13px; }}
QLabel#evidenceClaim {{ font-size: 12px; font-weight: bold; color: #101828; }}
QLabel#evidenceQuote {{ font-size: 12px; color: #475467; }}
QLabel#pendingClaim {{ font-size: 12px; font-weight: bold; color: #A15C07; }}
QLabel#pendingQuestion {{ font-size: 12px; color: #7A4A05; }}
QLabel#bubbleNameAI {{ font-size: 11px; font-weight: bold; color: #475467; }}
QLabel#bubbleNameUser {{ font-size: 11px; font-weight: bold; color: #1F3DAD; }}
QLabel#bubbleNameError {{ font-size: 11px; font-weight: bold; color: #B42318; }}
QLabel#bubbleText {{ font-size: 13px; color: #101828; }}
QLabel#bubbleTextError {{ font-size: 13px; color: #912018; }}
QLabel#sourceLink {{ font-size: 11px; color: #2F5BEA; }}
QLabel#statValue {{ font-size: 19px; font-weight: bold; color: #101828; }}
QLabel#statLabel {{ font-size: 12px; color: #667085; }}
QLabel#statHint {{ font-size: 11px; color: #667085; }}
QLabel#scoreBadge {{
    background: #EEF3FE; color: #1F3DAD; border: 1px solid #D9E3FD;
    border-radius: 9px; padding: 4px 10px; font-size: 12px; font-weight: bold;
}}
QLabel#scoreBadgeLow {{
    background: #F2F4F7; color: #475467; border: 1px solid #E4E7EC;
    border-radius: 9px; padding: 4px 10px; font-size: 12px; font-weight: bold;
}}
QLabel#emptyTitle {{ font-size: 14px; font-weight: bold; color: #344054; }}

/* ============================ 状态胶囊 ============================ */
QLabel#statusChipIdle {{
    background: #F2F4F7; color: #475467; border: 1px solid #E4E7EC;
    border-radius: 10px; padding: 5px 11px; font-size: 12px;
}}
QLabel#statusChipWait {{
    background: #EEF3FE; color: #1F3DAD; border: 1px solid #D9E3FD;
    border-radius: 10px; padding: 5px 11px; font-size: 12px;
}}
QLabel#statusChipOk {{
    background: #ECFDF3; color: #05603A; border: 1px solid #ABEFC6;
    border-radius: 10px; padding: 5px 11px; font-size: 12px;
}}
QLabel#statusChipWarn {{
    background: #FFFAEB; color: #93370D; border: 1px solid #FDE3A7;
    border-radius: 10px; padding: 5px 11px; font-size: 12px;
}}
QLabel#chip {{
    background: #EEF3FE; color: #1F3DAD; border: 1px solid #D9E3FD;
    border-radius: 11px; padding: 3px 10px; font-size: 12px;
}}
QLabel#chipMuted {{
    background: #F2F4F7; color: #475467; border: 1px solid #E4E7EC;
    border-radius: 11px; padding: 3px 10px; font-size: 12px;
}}
QLabel#chipDanger {{
    background: #FEF3F2; color: #B42318; border: 1px solid #FBD5D1;
    border-radius: 11px; padding: 3px 10px; font-size: 12px;
}}
QLabel#chipWarn {{
    background: #FFFAEB; color: #93370D; border: 1px solid #FDE3A7;
    border-radius: 11px; padding: 3px 10px; font-size: 12px;
}}

/* ============================ 侧边栏 ============================ */
QLabel#sidebarTitle {{
    font-size: 11px; font-weight: bold; color: #6B7480; padding: 0 4px;
}}
QLabel#navSection {{
    font-size: 11px; font-weight: bold; color: #5A6474;
    padding: 16px 12px 6px 12px;
}}
QPushButton#nav {{
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 10px; color: #9BA5B4; text-align: left;
    padding: 10px 12px 10px 13px; font-size: 13px;
}}
QPushButton#nav:hover {{ background: #1A2130; color: #E4E8EE; }}
QPushButton#nav:checked {{
    background: #212B3F; border-left: 3px solid #5B8CFF; color: #FFFFFF;
    font-weight: bold;
}}
QPushButton#nav:disabled {{ color: #4B5464; }}

/* ============================ 按钮 ============================ */
QPushButton {{
    background: #FFFFFF; color: #344054;
    border: 1px solid #D5DAE3; border-radius: 9px;
    padding: 8px 15px; font-size: 13px;
}}
QPushButton:hover {{ background: #F7F8FA; border-color: #B9C1CE; color: #101828; }}
QPushButton:pressed {{ background: #EFF1F5; }}
QPushButton:disabled {{
    color: #98A2B3; background: #FAFBFC; border-color: #E7E9EE;
}}
QPushButton#primary {{
    background: #2F5BEA; border: 1px solid #2F5BEA; color: #FFFFFF; font-weight: bold;
}}
QPushButton#primary:hover {{ background: #2649C8; border-color: #2649C8; }}
QPushButton#primary:pressed {{ background: #1F3DAD; border-color: #1F3DAD; }}
QPushButton#primary:disabled {{
    background: #B9C6F5; border-color: #B9C6F5; color: #FFFFFF;
}}
QPushButton#danger {{
    color: #B42318; background: #FFFFFF; border: 1px solid #F0C8C3;
}}
QPushButton#danger:hover {{ background: #FEF3F2; border-color: #E29D95; color: #912018; }}
QPushButton#danger:pressed {{ background: #FCE4E1; }}
QPushButton#danger:disabled {{
    color: #D8A7A1; background: #FAFBFC; border-color: #F2E2E0;
}}
QPushButton#ghost {{
    background: transparent; border: none; color: #475467;
    padding: 6px 10px; font-size: 12px;
}}
QPushButton#ghost:hover {{ background: #F2F4F7; color: #101828; }}
QPushButton#ghost:disabled {{ color: #98A2B3; background: transparent; }}
QPushButton#soft {{
    background: #F7F8FA; color: #344054; border: 1px solid #E7E9EE;
}}
QPushButton#soft:hover {{ background: #EDEFF3; border-color: #D5DAE3; color: #101828; }}
QPushButton#link {{
    border: none; background: transparent; color: #2F5BEA;
    padding: 2px 0; font-size: 12px; text-align: left;
}}
QPushButton#link:hover {{ color: #1F3DAD; }}

/* ============================ 输入控件 ============================ */
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF; border: 1px solid #D5DAE3; border-radius: 9px;
    color: #101828; padding: 8px 11px;
    selection-background-color: #2F5BEA; selection-color: #FFFFFF;
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #B9C1CE;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid #2F5BEA;
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    background: #F7F8FA; color: #98A2B3; border-color: #E7E9EE;
}}
QLineEdit::placeholder {{ color: #7A8494; }}

QComboBox {{
    background: #FFFFFF; border: 1px solid #D5DAE3; border-radius: 9px;
    color: #101828; padding: 8px 32px 8px 11px;
    selection-background-color: #2F5BEA; selection-color: #FFFFFF;
}}
QComboBox:hover {{ border-color: #B9C1CE; }}
QComboBox:focus {{ border: 1px solid #2F5BEA; }}
QComboBox:disabled {{ background: #F7F8FA; color: #98A2B3; border-color: #E7E9EE; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox::down-arrow {{
    image: url({_url("chevron-down.svg")}); width: 14px; height: 14px;
}}
QComboBox QAbstractItemView {{
    background: #FFFFFF; border: 1px solid #D5DAE3; border-radius: 10px;
    padding: 4px; outline: none;
    selection-background-color: #EEF3FE; selection-color: #1F3DAD;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 8px; border-radius: 6px; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; height: 15px; border: none; background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 24px; height: 15px; border: none; background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #F2F4F7;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({_url("chevron-up.svg")}); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({_url("chevron-down.svg")}); width: 10px; height: 10px;
}}

/* ============================ 勾选框 ============================ */
QCheckBox {{ color: #344054; font-size: 13px; spacing: 9px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border: 1px solid #B9C1CE;
    border-radius: 5px; background: #FFFFFF;
}}
QCheckBox::indicator:hover {{ border-color: #2F5BEA; background: #F7F9FF; }}
QCheckBox::indicator:checked {{
    background: #2F5BEA; border-color: #2F5BEA;
    image: url({_url("check.svg")});
}}
QCheckBox::indicator:disabled {{ border-color: #DDE1E7; background: #F2F4F7; }}
QCheckBox::indicator:checked:disabled {{
    background: #B9C6F5; border-color: #B9C6F5;
    image: url({_url("check.svg")});
}}
QCheckBox:disabled {{ color: #98A2B3; }}
QCheckBox#chipCheck {{
    background: #FFFFFF; border: 1px solid #E1E5EB; border-radius: 15px;
    padding: 6px 13px 6px 10px; color: #475467; font-size: 12px;
}}
QCheckBox#chipCheck:hover {{ background: #FAFBFF; border-color: #B9C6F0; }}
QCheckBox#chipCheck:checked {{
    background: #EEF3FE; border-color: #C3D2FB; color: #1F3DAD; font-weight: bold;
}}
QCheckBox#chipCheck::indicator {{ width: 14px; height: 14px; border-radius: 4px; }}
QCheckBox#chipCheck:disabled {{ background: #F7F8FA; color: #98A2B3; }}

QRadioButton {{ color: #344054; font-size: 13px; spacing: 9px; }}
QRadioButton::indicator {{
    width: 17px; height: 17px; border: 1px solid #B9C1CE;
    border-radius: 9px; background: #FFFFFF;
}}
QRadioButton::indicator:checked {{
    border: 1px solid #2F5BEA;
    image: url({_url("radio-dot.svg")}); width: 17px; height: 17px;
}}

/* ============================ 标签页 ============================ */
QTabWidget::pane {{ border: none; background: transparent; top: -1px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: #667085; border: none;
    border-radius: 9px; padding: 9px 16px; margin-right: 6px; font-size: 13px;
}}
QTabBar::tab:hover {{ background: #EDEFF3; color: #344054; }}
QTabBar::tab:selected {{
    background: #FFFFFF; color: #1F3DAD; font-weight: bold;
    border: 1px solid #D9E3FD;
}}

/* ============================ 表格 ============================ */
QTableWidget {{
    background: #FFFFFF; border: none; gridline-color: transparent;
    alternate-background-color: #FAFBFC;
    selection-background-color: #EEF3FE; selection-color: #1F3DAD;
    outline: none;
}}
QTableWidget::item {{ padding: 8px 10px; border-bottom: 1px solid #F1F3F6; }}
QTableWidget::item:selected {{ background: #EEF3FE; color: #1F3DAD; }}
QHeaderView::section {{
    background: #FAFBFC; color: #475467; border: none;
    border-bottom: 1px solid #E7E9EE; padding: 10px; font-size: 12px;
    font-weight: bold;
}}
QTableCornerButton::section {{ background: #FAFBFC; border: none; }}
QTableWidget QTableCornerButton::section {{ background: #FAFBFC; }}

/* ============================ 列表 ============================ */
QListWidget {{
    background: #FFFFFF; border: 1px solid #E7E9EE; border-radius: 12px; padding: 5px;
}}
QListWidget::item {{ padding: 9px 11px; border-radius: 8px; color: #344054; }}
QListWidget::item:hover {{ background: #F7F8FA; }}
QListWidget::item:selected {{ background: #EEF3FE; color: #1F3DAD; }}

/* ============================ 进度条 / 滚动条 ============================ */
QProgressBar {{
    background: #EDEFF3; border: none; border-radius: 8px;
    text-align: center; color: #344054; font-size: 11px; font-weight: bold;
    height: 16px;
}}
QProgressBar::chunk {{ background: #2F5BEA; border-radius: 8px; }}
QProgressBar#quotaBar {{
    background: #E4E7EC; border: none; border-radius: 3px; height: 6px;
}}
QProgressBar#quotaBar::chunk {{ background: #12B76A; border-radius: 3px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 3px; }}
QScrollBar::handle:vertical {{
    background: #D3D8E0; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #B2BAC6; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 3px 4px; }}
QScrollBar::handle:horizontal {{
    background: #D3D8E0; border-radius: 4px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: #B2BAC6; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: #DCE3F7; }}

/* ============================ 文本域 ============================ */
QPlainTextEdit#logView {{
    background: #0E131C; border: 1px solid #0E131C; border-radius: 12px;
    color: #C9D4E3; padding: 14px;
    font-family: "Cascadia Mono", "Consolas"; font-size: 12px;
    selection-background-color: #2F5BEA; selection-color: #FFFFFF;
}}
QPlainTextEdit#envPreview {{
    background: #FAFBFC; border: 1px solid #E7E9EE; border-radius: 10px;
    font-family: "Cascadia Mono", "Consolas"; font-size: 11px; color: #344054;
}}
QTextBrowser#detailView {{
    background: transparent; border: none; padding: 14px 18px; color: #101828;
}}
QScrollArea#chatScroll {{ background: #FAFBFC; }}
QWidget#chatInner {{ background: #FAFBFC; }}

/* ============================ 对话框 ============================ */
QDialog, QMessageBox {{ background: #FFFFFF; }}
QMessageBox QLabel {{ background: transparent; color: #101828; }}
QMessageBox QPushButton {{ min-width: 84px; }}
QMessageBox QPushButton:hover {{ background: #F7F8FA; border-color: #B9C1CE; }}
"""
