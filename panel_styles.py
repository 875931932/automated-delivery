# -*- coding: utf-8 -*-
"""界面设计系统：设计令牌 + 全局样式表。

所有视觉常量集中在这里，页面代码只使用语义化的 objectName，
避免各处随手写颜色/间距导致的「太杂太乱」。

设计令牌
  间距   4px 基准刻度：4 / 8 / 12 / 16 / 20 / 24 / 32
  圆角   小 8 / 中 10 / 大 14
  文字   主 13px / 标题 19px / 区块 15px / 说明 12px
  强调   #2F5BEA（浅底 #EEF3FE）
  语义   成功 #0B7A55 / 警告 #A15C07 / 危险 #B42318
"""
from pathlib import Path
from string import Template

ASSETS_DIR = Path(__file__).parent / "assets"


def _url(name: str) -> str:
    """把资源文件转成 QSS 可用的 url() 写法（正斜杠，兼容非 ASCII 路径）。"""
    return (ASSETS_DIR / name).as_posix()


# ---------------------------------------------------------------- 设计令牌
TOKENS = {
    # 画布与表面
    "canvas": "#F1F3F7",
    "surface": "#FFFFFF",
    "surfaceAlt": "#F8FAFC",
    "surfaceSunken": "#F4F6FA",
    # 描边
    "border": "#E3E7EE",
    "borderStrong": "#CBD2DE",
    "borderSoft": "#EDF0F5",
    # 文字
    "text": "#0F172A",
    "textSecondary": "#414C5C",
    "textMuted": "#6B7688",
    "textFaint": "#93A0B4",
    # 强调色
    "accent": "#2F5BEA",
    "accentHover": "#2447C7",
    "accentDeep": "#1B3599",
    "accentSoft": "#EDF2FE",
    "accentBorder": "#D3DEFB",
    # 语义色
    "success": "#0B7A55",
    "successSoft": "#E9F7F1",
    "successBorder": "#BFE8D6",
    "warning": "#9A5B08",
    "warningSoft": "#FEF6E7",
    "warningBorder": "#F5DCA9",
    "danger": "#B42318",
    "dangerSoft": "#FEF2F1",
    "dangerBorder": "#F8CFCB",
    # 侧边栏
    "sidebarTop": "#171C29",
    "sidebarBottom": "#10141F",
    "sidebarText": "#A8B2C4",
    "sidebarTextActive": "#FFFFFF",
    "sidebarHover": "#1E2432",
    "sidebarActive": "#242C3E",
    "sidebarBorder": "#262D3D",
    # 终端日志区
    "console": "#0E131C",
    "consoleBorder": "#1B2230",
    "consoleText": "#C6D2E3",
}

# 间距刻度（供 Python 侧布局复用，单位 px）
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 24, "xxxl": 32}

_QSS = """
/* ============================ 基础 ============================ */
QWidget {
    background: transparent;
    color: $text;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
}
QToolTip {
    background: #1B2436; color: #FFFFFF; border: none;
    border-radius: 8px; padding: 7px 10px; font-size: 12px;
}
QMenu {
    background: $surface; border: 1px solid $border; border-radius: 12px;
    padding: 6px; color: $text;
}
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 8px; }
QMenu::item:selected { background: $accentSoft; color: $accentDeep; }
QMenu::separator { height: 1px; background: $borderSoft; margin: 4px 8px; }

/* ============================ 结构容器 ============================ */
QFrame#root { background: $canvas; }
QFrame#header {
    background: $surface; border-bottom: 1px solid $border;
}
QFrame#sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $sidebarTop, stop:1 $sidebarBottom);
    border-right: 1px solid $sidebarBorder;
}
QFrame#sideFooter {
    background: #1B2231; border: 1px solid $sidebarBorder; border-radius: 12px;
}
QFrame#card {
    background: $surface; border: 1px solid $border; border-radius: 14px;
}
QFrame#inset {
    background: $surfaceSunken; border: 1px solid $borderSoft; border-radius: 12px;
}
QFrame#divider { background: $border; border: none; max-height: 1px; min-height: 1px; }
QFrame#softDivider { background: $borderSoft; border: none; max-height: 1px; min-height: 1px; }
QFrame#errorBanner {
    background: $dangerSoft; border: 1px solid $dangerBorder; border-radius: 12px;
}
QFrame#composer {
    background: $surface; border: 1px solid $borderStrong; border-radius: 14px;
}
QFrame#bubbleAI {
    background: $surfaceAlt; border: 1px solid $borderSoft;
    border-radius: 4px 14px 14px 14px;
}
QFrame#bubbleUser {
    background: $accentSoft; border: 1px solid $accentBorder;
    border-radius: 14px 4px 14px 14px;
}
QFrame#bubbleError {
    background: $dangerSoft; border: 1px solid $dangerBorder; border-radius: 14px;
}
QFrame#avatar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6C97FF, stop:1 #2F5BEA);
    color: #FFFFFF; border-radius: 14px; font-size: 11px; font-weight: bold;
}
QFrame#avatarUser {
    background: $accentSoft; color: $accentDeep; border: 1px solid $accentBorder;
    border-radius: 14px; font-size: 11px; font-weight: bold;
}
QFrame#evidenceCard {
    background: $surfaceAlt; border: 1px solid $borderSoft; border-radius: 12px;
}
QFrame#pendingCard {
    background: $warningSoft; border: 1px solid $warningBorder; border-radius: 12px;
}
QFrame#toastNotice {
    background: $successSoft; border: 1px solid $success; border-radius: 8px;
}
QFrame#toastNotice[kind="error"] {
    background: $dangerSoft; border-color: $danger;
}
QFrame#toastNotice QLabel#toastMessage { color: $success; font-weight: bold; }
QFrame#toastNotice[kind="error"] QLabel#toastMessage { color: $danger; }
QToolButton#toastClose { border: none; border-radius: 4px; padding: 0; }
QToolButton#toastClose:hover { background: $surface; }
QToolButton#toastClose:focus { border: 1px solid $accent; }

/* ============================ 品牌与页头 ============================ */
QLabel#sidebarLogo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6C97FF, stop:1 #2F5BEA);
    color: #FFFFFF; border-radius: 12px; font-size: 18px; font-weight: bold;
}
QLabel#sidebarBrand { font-size: 15px; font-weight: bold; color: #FFFFFF; }
QLabel#sidebarTag { font-size: 11px; color: #6E7A90; }
QLabel#pageTitle { font-size: 19px; font-weight: bold; color: $text; }
QLabel#pageSubtitle { font-size: 12px; color: $textMuted; }

/* ============================ 文字语义 ============================ */
QLabel#section { font-size: 15px; font-weight: bold; color: $text; }
QLabel#sectionHint { font-size: 12px; color: $textMuted; }
QLabel#fieldTitle { font-size: 13px; font-weight: bold; color: $textSecondary; }
QLabel#fieldLabel { font-size: 13px; font-weight: bold; color: $textSecondary; }
QLabel#fieldNote { font-size: 12px; color: $textMuted; }
QLabel#muted { font-size: 12px; color: $textMuted; }
QLabel#hint { font-size: 12px; color: $textMuted; }
QLabel#warnText { font-size: 12px; color: $warning; }
QLabel#errorText { font-size: 12px; color: $danger; }
QLabel#draftEmpty { color: $textMuted; font-size: 13px; }
QLabel#evidenceClaim { font-size: 12px; font-weight: bold; color: $text; }
QLabel#evidenceQuote { font-size: 12px; color: $textSecondary; }
QLabel#pendingClaim { font-size: 12px; font-weight: bold; color: $warning; }
QLabel#pendingQuestion { font-size: 12px; color: #7A4A05; }
QLabel#bubbleNameAI { font-size: 11px; font-weight: bold; color: $textMuted; }
QLabel#bubbleNameUser { font-size: 11px; font-weight: bold; color: $accentDeep; }
QLabel#bubbleNameError { font-size: 11px; font-weight: bold; color: $danger; }
QLabel#bubbleText { font-size: 13px; color: $text; }
QLabel#bubbleTextError { font-size: 13px; color: #8C1810; }
QLabel#sourceLink { font-size: 11px; color: $accent; }
QLabel#emptyTitle { font-size: 14px; font-weight: bold; color: $textSecondary; }
QLabel#emptyHint { font-size: 12px; color: $textMuted; }

/* ============================ 指标卡 ============================ */
QLabel#statValue { font-size: 22px; font-weight: bold; color: $text; }
QLabel#statLabel { font-size: 12px; color: $textMuted; }
QLabel#statHint { font-size: 11px; color: $textFaint; }
QLabel#scoreBadge {
    background: $accentSoft; color: $accentDeep; border: 1px solid $accentBorder;
    border-radius: 10px; padding: 4px 11px; font-size: 12px; font-weight: bold;
}
QLabel#scoreBadgeLow {
    background: $surfaceSunken; color: $textMuted; border: 1px solid $border;
    border-radius: 10px; padding: 4px 11px; font-size: 12px; font-weight: bold;
}
QLabel#resultTitle { font-size: 18px; font-weight: bold; color: $text; }
QLabel#resultSectionTitle { font-size: 14px; font-weight: bold; color: $text; }
QLabel#resultMetaValue { font-size: 12px; color: $textSecondary; }
QLabel#resultProfileName { font-size: 13px; font-weight: bold; color: $text; }
QLabel#resultMetric {
    background: $accentSoft; color: $accentDeep; border: 1px solid $accentBorder;
    border-radius: 5px; padding: 3px 7px; font-size: 11px; font-weight: bold;
}
QLabel#resultInfoKey { color: $textMuted; font-size: 12px; }
QLabel#resultInfoValue { color: $textSecondary; font-size: 12px; }
QLabel#resultEvidenceLabel { color: $textSecondary; font-size: 12px; font-weight: bold; }
QLabel#resultGapTag {
    background: $dangerSoft; color: $danger; border: 1px solid $dangerBorder;
    border-radius: 5px; padding: 6px 8px; font-size: 12px;
}
QLabel#resultWarnTag {
    background: $warningSoft; color: $warning; border: 1px solid $warningBorder;
    border-radius: 5px; padding: 6px 8px; font-size: 12px;
}
QLabel#resultWarningText { color: $warning; font-size: 12px; }
QFrame#resultStatusChip { border-radius: 6px; }
QFrame#resultMetaPanel {
    background: $surfaceAlt; border: 1px solid $borderSoft; border-radius: 6px;
}
QFrame#resultQuote {
    background: $accentSoft; border: 1px solid $accentBorder;
    border-left: 3px solid $accent; border-radius: 6px;
}
QFrame#resultProfile {
    background: $surfaceAlt; border: 1px solid $borderSoft; border-radius: 6px;
}
QFrame#resultWarning {
    background: $warningSoft; border: 1px solid $warningBorder; border-radius: 6px;
}

/* ============================ 状态胶囊 ============================ */
QFrame#statusCluster {
    background: $surfaceSunken; border: 1px solid $border; border-radius: 17px;
}
QLabel#statusText {
    font-size: 13px; font-weight: bold; color: $textSecondary;
    background: transparent; border: none;
}
QLabel#statusChipIdle {
    background: $surfaceSunken; color: $textSecondary; border: 1px solid $border;
    border-radius: 12px; padding: 5px 12px; font-size: 12px;
}
QLabel#statusChipWait {
    background: $accentSoft; color: $accentDeep; border: 1px solid $accentBorder;
    border-radius: 12px; padding: 5px 12px; font-size: 12px;
}
QLabel#statusChipOk {
    background: $successSoft; color: $success; border: 1px solid $successBorder;
    border-radius: 12px; padding: 5px 12px; font-size: 12px;
}
QLabel#statusChipWarn {
    background: $warningSoft; color: $warning; border: 1px solid $warningBorder;
    border-radius: 12px; padding: 5px 12px; font-size: 12px; font-size: 12px;
}
QLabel#chip {
    background: $accentSoft; color: $accentDeep; border: 1px solid $accentBorder;
    border-radius: 11px; padding: 4px 11px; font-size: 12px;
}
QLabel#chipMuted {
    background: $surfaceSunken; color: $textSecondary; border: 1px solid $border;
    border-radius: 11px; padding: 4px 11px; font-size: 12px;
}
QLabel#chipDanger {
    background: $dangerSoft; color: $danger; border: 1px solid $dangerBorder;
    border-radius: 11px; padding: 4px 11px; font-size: 12px;
}
QLabel#chipWarn {
    background: $warningSoft; color: $warning; border: 1px solid $warningBorder;
    border-radius: 11px; padding: 4px 11px; font-size: 12px;
}
QLabel#checkOk {
    background: $successSoft; color: $success; border: 1px solid $successBorder;
    border-radius: 11px; padding: 5px 12px; font-size: 12px;
}
QLabel#checkTodo {
    background: $warningSoft; color: $warning; border: 1px solid $warningBorder;
    border-radius: 11px; padding: 5px 12px; font-size: 12px;
}
QLabel#checkTodo:hover { background: #FDEBC8; border-color: #EFCB87; }

/* ============================ 侧边栏 ============================ */
QLabel#navSection {
    font-size: 11px; font-weight: bold; color: #5A6579;
    padding: 18px 10px 6px 10px;
}
QPushButton#nav {
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 10px; color: $sidebarText; text-align: left;
    padding: 9px 12px 9px 11px; font-size: 13px;
}
QPushButton#nav:hover { background: $sidebarHover; color: #DCE3EE; }
QPushButton#nav:checked {
    background: $sidebarActive; border-left: 3px solid #5B8CFF; color: $sidebarTextActive;
    font-weight: bold;
}
QPushButton#nav:disabled { color: #4A5364; }
QLabel#sideCaption { font-size: 11px; color: #6E7A90; }
QLabel#sideMetric { font-size: 12px; font-weight: bold; color: #C8D2E2; }

/* ============================ 按钮 ============================ */
QPushButton {
    background: $surface; color: $textSecondary;
    border: 1px solid $borderStrong; border-radius: 10px;
    padding: 8px 16px; font-size: 13px;
}
QPushButton:hover { background: $surfaceAlt; border-color: #B4BDCC; color: $text; }
QPushButton:pressed { background: $surfaceSunken; }
QPushButton:disabled {
    color: $textFaint; background: $surfaceAlt; border-color: $border;
}
QPushButton#primary {
    background: $accent; border: 1px solid $accent; color: #FFFFFF; font-weight: bold;
}
QPushButton#primary:hover { background: $accentHover; border-color: $accentHover; }
QPushButton#primary:pressed { background: $accentDeep; border-color: $accentDeep; }
QPushButton#primary:disabled { background: #B7C4F2; border-color: #B7C4F2; color: #FFFFFF; }
QPushButton#danger {
    color: $danger; background: $surface; border: 1px solid $dangerBorder;
}
QPushButton#danger:hover { background: $dangerSoft; border-color: #E9A8A1; color: #8C1810; }
QPushButton#danger:pressed { background: #FBE0DD; }
QPushButton#danger:disabled { color: #D8A7A1; background: $surfaceAlt; border-color: $borderSoft; }
QPushButton#ghost {
    background: transparent; border: none; color: $textSecondary;
    padding: 6px 10px; font-size: 12px; border-radius: 8px;
}
QPushButton#ghost:hover { background: $surfaceSunken; color: $text; }
QPushButton#ghost:disabled { color: $textFaint; background: transparent; }
QPushButton#soft {
    background: $surfaceSunken; color: $textSecondary; border: 1px solid $border;
}
QPushButton#soft:hover { background: #EAEEF5; border-color: $borderStrong; color: $text; }
QPushButton#soft:checked {
    background: $accentSoft; border-color: $accentBorder; color: $accentDeep;
}
QPushButton#resultMarkGood {
    color: $success; background: $successSoft; border: 1px solid $successBorder;
    border-radius: 6px; padding: 6px 11px; font-weight: bold;
}
QPushButton#resultMarkGood:hover, QPushButton#resultMarkGood:checked {
    background: #DDF2E9; border-color: #8DD2B4;
}
QPushButton#resultMarkBad {
    color: $danger; background: $dangerSoft; border: 1px solid $dangerBorder;
    border-radius: 6px; padding: 6px 11px; font-weight: bold;
}
QPushButton#resultMarkBad:hover, QPushButton#resultMarkBad:checked {
    background: #FBE4E1; border-color: #E9A8A1;
}
QPushButton#resultMarkMistake {
    color: $warning; background: $warningSoft; border: 1px solid $warningBorder;
    border-radius: 6px; padding: 6px 11px; font-weight: bold;
}
QPushButton#resultMarkMistake:hover, QPushButton#resultMarkMistake:checked {
    background: #FCECCF; border-color: #E7C47E;
}
QPushButton#resultIconButton {
    background: transparent; border: none; border-radius: 6px; padding: 6px;
}
QPushButton#resultIconButton:hover { background: $surfaceSunken; }
QPushButton#resultEvidenceToggle {
    background: transparent; color: $accentDeep; border: none;
    border-radius: 6px; padding: 8px 2px; text-align: left; font-weight: bold;
}
QPushButton#resultEvidenceToggle:hover { background: $surfaceAlt; }
QPushButton#resultEvidenceToggle:disabled { color: $textFaint; }
QPushButton#resultLinkButton {
    background: transparent; color: $accent; border: none; border-radius: 5px;
    padding: 4px 2px; font-weight: bold; text-align: left;
}
QPushButton#resultLinkButton:hover { color: $accentDeep; background: $accentSoft; }
QPushButton#link {
    border: none; background: transparent; color: $accent;
    padding: 3px 0; font-size: 12px; text-align: left; border-radius: 6px;
}
QPushButton#link:hover { color: $accentDeep; }

/* ============================ 输入控件 ============================ */
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox {
    background: $surface; border: 1px solid $borderStrong; border-radius: 10px;
    color: $text; padding: 9px 14px;
    selection-background-color: $accent; selection-color: #FFFFFF;
}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #B4BDCC;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid $accent; background: $surface;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {
    background: $surfaceSunken; color: $textFaint; border-color: $border;
}
QLineEdit::placeholder { color: $textFaint; }
QTextBrowser { read-only: }

QComboBox {
    background: $surface; border: 1px solid $borderStrong; border-radius: 10px;
    color: $text; padding: 9px 36px 9px 14px;
    selection-background-color: $accent; selection-color: #FFFFFF;
}
QComboBox:hover { border-color: #B4BDCC; }
QComboBox:focus { border: 1px solid $accent; }
QComboBox:disabled { background: $surfaceSunken; color: $textFaint; border-color: $border; }
QComboBox::drop-down { border: none; width: 32px; }
QComboBox::down-arrow { image: url($chevronDown); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; border-radius: 12px;
    padding: 6px; outline: none;
    selection-background-color: $accentSoft; selection-color: $accentDeep;
}
QComboBox QAbstractItemView::item { padding: 7px 9px; border-radius: 8px; min-height: 22px; }

QSpinBox, QDoubleSpinBox { padding-right: 28px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 26px; height: 16px; border: none; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 26px; height: 16px; border: none; background: transparent;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $surfaceSunken; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($chevronUp); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($chevronDown); width: 10px; height: 10px; }

/* ============================ 勾选与单选 ============================ */
QCheckBox { color: $textSecondary; font-size: 13px; spacing: 9px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid #B4BDCC;
    border-radius: 5px; background: $surface;
}
QCheckBox::indicator:hover { border-color: $accent; background: #F7F9FF; }
QCheckBox::indicator:checked {
    background: $accent; border-color: $accent; image: url($check);
}
QCheckBox::indicator:disabled { border-color: $border; background: $surfaceSunken; }
QCheckBox::indicator:checked:disabled {
    background: #B7C4F2; border-color: #B7C4F2; image: url($check);
}
QCheckBox:disabled { color: $textFaint; }
QCheckBox#chipCheck {
    background: $surface; border: 1px solid $border; border-radius: 14px;
    padding: 5px 13px 5px 10px; color: $textSecondary; font-size: 12px;
}
QCheckBox#chipCheck:hover { background: $surfaceAlt; border-color: $accentBorder; }
QCheckBox#chipCheck:checked {
    background: $accentSoft; border-color: $accentBorder; color: $accentDeep; font-weight: bold;
}
QCheckBox#chipCheck::indicator { width: 15px; height: 15px; border-radius: 4px; }
QCheckBox#chipCheck:disabled { background: $surfaceSunken; color: $textFaint; }

QCheckBox#switch { spacing: 0; }
QCheckBox#switch::indicator {
    width: 40px; height: 22px; border-radius: 11px;
    border: none; background: transparent; image: url($switchOff);
}
QCheckBox#switch::indicator:hover { background: transparent; }
QCheckBox#switch::indicator:checked { background: transparent; image: url($switchOn); }
QCheckBox#switch::indicator:disabled { background: transparent; image: url($switchOff); }

QRadioButton { color: $textSecondary; font-size: 13px; spacing: 9px; }
QRadioButton::indicator {
    width: 18px; height: 18px; border: 1px solid #B4BDCC;
    border-radius: 9px; background: $surface;
}
QRadioButton::indicator:checked { border: 5px solid $accent; }

/* ============================ 标签页 ============================ */
QTabWidget::pane { border: none; background: transparent; top: -1px; }
QTabBar { background: transparent; qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent; color: $textMuted; border: none;
    border-radius: 10px; padding: 9px 16px; margin-right: 6px; font-size: 13px;
}
QTabBar::tab:hover { background: $surfaceSunken; color: $textSecondary; }
QTabBar::tab:selected {
    background: $surface; color: $accentDeep; font-weight: bold;
    border: 1px solid $accentBorder;
}

/* ============================ 表格 ============================ */
QTableWidget {
    background: $surface; border: none; gridline-color: transparent;
    alternate-background-color: $surfaceAlt;
    selection-background-color: $accentSoft; selection-color: $accentDeep;
    outline: none;
}
QTableWidget::item { padding: 9px 12px; border-bottom: 1px solid $borderSoft; }
QTableWidget::item:selected { background: $accentSoft; color: $accentDeep; }
QHeaderView::section {
    background: $surfaceAlt; color: $textSecondary; border: none;
    border-bottom: 1px solid $border; padding: 11px 12px; font-size: 12px;
    font-weight: bold;
}
QTableCornerButton::section { background: $surfaceAlt; border: none; }

/* ============================ 列表 ============================ */
QListWidget {
    background: $surface; border: 1px solid $border; border-radius: 12px; padding: 6px;
}
QListWidget::item { padding: 10px 12px; border-radius: 9px; color: $textSecondary; }
QListWidget::item:hover { background: $surfaceAlt; }
QListWidget::item:selected { background: $accentSoft; color: $accentDeep; }

/* ============================ 进度条 / 滚动条 ============================ */
QProgressBar {
    background: $surfaceSunken; border: none; border-radius: 8px;
    text-align: center; color: $textSecondary; font-size: 11px; font-weight: bold;
    height: 16px;
}
QProgressBar::chunk { background: $accent; border-radius: 8px; }
QProgressBar#quotaBar {
    background: #E2E7EF; border: none; border-radius: 3px; height: 6px;
}
QProgressBar#quotaBar::chunk { background: #12B76A; border-radius: 3px; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 4px 3px; }
QScrollBar::handle:vertical { background: #CFD6E1; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: #AFB9C8; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 3px 4px; }
QScrollBar::handle:horizontal { background: #CFD6E1; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: #AFB9C8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: #DCE3F7; }

/* ============================ 文本域 ============================ */
QPlainTextEdit#logView {
    background: $console; border: 1px solid $consoleBorder; border-radius: 12px;
    color: $consoleText; padding: 14px 16px;
    font-family: "Cascadia Mono", "Consolas"; font-size: 12px;
    selection-background-color: $accent; selection-color: #FFFFFF;
}
QPlainTextEdit#envPreview {
    background: $surfaceAlt; border: 1px solid $border; border-radius: 12px;
    font-family: "Cascadia Mono", "Consolas"; font-size: 11px; color: $textSecondary;
}
QTextBrowser#detailView {
    background: transparent; border: none; padding: 4px 6px; color: $text;
}
QScrollArea#resultDetailScroll { background: transparent; border: none; }
QScrollArea#resultDetailScroll QWidget#resultDetailContent { background: transparent; }
QScrollArea#resultDetailScroll QScrollBar:vertical {
    width: 7px; background: transparent; margin: 3px 1px 3px 0;
}
QScrollArea#resultDetailScroll QScrollBar::handle:vertical {
    min-height: 28px; background: $borderStrong; border-radius: 3px;
}
QScrollArea#resultDetailScroll QScrollBar::handle:vertical:hover { background: $textFaint; }
QScrollArea#resultDetailScroll QScrollBar::add-line:vertical,
QScrollArea#resultDetailScroll QScrollBar::sub-line:vertical { height: 0; }
QScrollArea#resultDetailScroll QScrollBar::add-page:vertical,
QScrollArea#resultDetailScroll QScrollBar::sub-page:vertical { background: transparent; }
QWidget#drawerMask { background: rgba(16, 24, 40, 0.44); }
QFrame#drawerPanel { background: $surface; border: none; border-left: 1px solid $border; }
QScrollArea#chatScroll { background: $surfaceAlt; }
QWidget#chatInner { background: $surfaceAlt; }

/* ============================ 对话框 ============================ */
QDialog, QMessageBox { background: $surface; }
QMessageBox QLabel { background: transparent; color: $text; }
QMessageBox QPushButton { min-width: 88px; }
"""

STYLESHEET = Template(_QSS).substitute(
    TOKENS,
    chevronDown=_url("chevron-down.svg"),
    chevronUp=_url("chevron-up.svg"),
    check=_url("check.svg"),
    switchOff=_url("switch-off.svg"),
    switchOn=_url("switch-on.svg"),
)
