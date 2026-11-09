# -*- coding: utf-8 -*-
"""通用组件库：自适应表单网格、字段块、开关行、指标卡、区块卡片。

所有页面共用这里的组件，保证卡片间距、标题层级、控件高度完全一致，
避免各页面各写一套导致「间隔混乱 / 排版不统一」。
"""
from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAccessible, QAccessibleEvent, QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def pad_spinbox_text(spinbox, left=12):
    """给数字框的文字留出左边距。

    Fusion 风格下 QSpinBox 的文字由样式直接绘制，QSS 的 padding 会被忽略，
    只有内部 lineEdit 的 textMargins 才生效。
    """
    editor = spinbox.lineEdit()
    if editor is not None:
        editor.setTextMargins(left, 0, 0, 0)


class StatusDot(QWidget):
    """状态圆点。

    QSS 的 border-radius 不会裁剪 QLabel 的背景（画出来是方块），
    所以这里直接用 QPainter 画椭圆，保证任何缩放下都是正圆。
    """

    COLORS = {
        "statusDotIdle": "#98A2B3",
        "statusDotRunning": "#12B76A",
        "statusDotDone": "#2F5BEA",
    }

    def __init__(self, parent=None, size=8):
        super().__init__(parent)
        self.setObjectName("statusDotIdle")
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.COLORS.get(self.objectName(), "#98A2B3")))
        painter.drawEllipse(self.rect())


class ToastNotice(QFrame):
    """A single non-modal notice anchored inside the workspace."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toastNotice")
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(20, 20)
        layout.addWidget(self.icon_label, 0, Qt.AlignTop)
        self.message_label = QLabel(self)
        self.message_label.setObjectName("toastMessage")
        self.message_label.setTextFormat(Qt.PlainText)
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumWidth(1)
        layout.addWidget(self.message_label, 1)

        self.close_button = QToolButton(self)
        self.close_button.setObjectName("toastClose")
        self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.setIconSize(QSize(14, 14))
        self.close_button.setFixedSize(24, 24)
        self.close_button.setToolTip("关闭提示")
        self.close_button.setAccessibleName("关闭提示")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignTop)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)

    def show_message(self, message, kind="success", duration=None):
        kind = "error" if kind == "error" else "success"
        self.setProperty("kind", kind)
        for widget in (self, self.message_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        icon = QStyle.SP_MessageBoxCritical if kind == "error" else QStyle.SP_DialogApplyButton
        self.icon_label.setPixmap(self.style().standardIcon(icon).pixmap(20, 20))
        self.message_label.setText(message)
        self.setAccessibleName(message)
        self._sync_geometry()
        self.show()
        self.raise_()
        self.timer.start(duration if duration is not None else (6000 if kind == "error" else 3200))
        QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))

    def dismiss(self):
        self.timer.stop()
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def _sync_geometry(self):
        host = self.parentWidget()
        self.ensurePolished()
        width = min(520, max(1, host.width() - 40))
        height = max(48, self.layout().totalHeightForWidth(width))
        self.setGeometry(
            max(0, (host.width() - width) // 2),
            max(0, host.height() - height - 24),
            width, height,
        )


class FlowLayout(QLayout):
    """自动换行的横向布局，用于胶囊标签等一行放不下的元素。"""

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y, line_height = effective.x(), effective.y(), 0
        spacing = self.spacing()
        for item in self._items:
            widget = item.widget()
            hint = widget.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class ClickableLabel(QLabel):
    """可点击的标题标签（点击等价于操作旁边的控件）。"""

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class FormGrid(QWidget):
    """自适应表单网格：窄字段两列并排，宽字段独占整行。

    宽度不足时自动降为单列，避免控件被压扁或文字被硬挤换行。
    """

    def __init__(self, parent=None, min_column_width=340, max_columns=2,
                 h_spacing=28, v_spacing=16):
        super().__init__(parent)
        self._entries = []
        self._min_column_width = min_column_width
        self._max_columns = max_columns
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(h_spacing)
        self._grid.setVerticalSpacing(v_spacing)

    def add(self, widget, full_width=False):
        """加入一个字段块；full_width=True 时独占整行。"""
        self._entries.append((widget, full_width))
        self._relayout()
        return widget

    def _column_count(self):
        width = self.width()
        if width <= 0:
            return 1
        columns = int((width + 24) // (self._min_column_width + 24))
        return max(1, min(self._max_columns, columns))

    def _relayout(self):
        columns = self._column_count()
        if columns == self._columns:
            return
        self._columns = columns
        for widget, _full in self._entries:
            self._grid.removeWidget(widget)
        while self._grid.count():
            self._grid.takeAt(0)
        row = 0
        column = 0
        for widget, full in self._entries:
            if full or columns == 1:
                if column:
                    row += 1
                    column = 0
                self._grid.addWidget(widget, row, 0, 1, columns)
                row += 1
                continue
            self._grid.addWidget(widget, row, column, 1, 1)
            column += 1
            if column >= columns:
                column = 0
                row += 1
        for index in range(columns):
            self._grid.setColumnStretch(index, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()


class FieldBlock(QWidget):
    """单个表单项：标题在上、控件在中、提示与说明在下。"""

    def __init__(self, title, control, note="", parent=None):
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(7)

        # 标题固定单行：字段名都很短，固定高度可保证同一行两列的控件严格对齐。
        # 若标题可伸展，当同行另一列更高时，多余高度会全被标题吃掉导致错位。
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("fieldTitle")
        self.title_label.setMinimumWidth(1)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.title_label.setVisible(bool(title))
        self.layout_.addWidget(self.title_label)

        self.control = control
        self.layout_.addWidget(control)

        self.messages = QVBoxLayout()
        self.messages.setContentsMargins(0, 0, 0, 0)
        self.messages.setSpacing(4)
        self.layout_.addLayout(self.messages)

        self.note_label = QLabel(note, self)
        self.note_label.setObjectName("fieldNote")
        self.note_label.setWordWrap(True)
        self.note_label.setMinimumWidth(1)
        self.note_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.note_label.setVisible(bool(note))
        self.layout_.addWidget(self.note_label)

        # 末尾弹簧：把整行多余高度吃掉，避免标题/说明被拉伸变形。
        self.layout_.addStretch(1)

    def add_message(self, label):
        """在控件下方插入一条校验 / 提示信息。"""
        self.messages.addWidget(label)


class ToggleRow(QWidget):
    """开关行：左侧标题与说明，右侧开关。用于布尔型配置。"""

    toggled = Signal(bool)

    def __init__(self, title, note="", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)
        self.title_label = ClickableLabel(title)
        self.title_label.setObjectName("fieldTitle")
        self.title_label.setMinimumWidth(1)
        text_column.addWidget(self.title_label)
        self.note_label = QLabel(note, self)
        self.note_label.setObjectName("fieldNote")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(bool(note))
        text_column.addWidget(self.note_label)
        text_column.addStretch(1)
        layout.addLayout(text_column, 1)

        self.switch = QCheckBox()
        self.switch.setObjectName("switch")
        self.switch.setCursor(Qt.PointingHandCursor)
        self.switch.toggled.connect(self.toggled)
        layout.addWidget(self.switch, 0, Qt.AlignTop)
        outer.addLayout(layout)

        self.messages = QVBoxLayout()
        self.messages.setContentsMargins(0, 0, 0, 0)
        self.messages.setSpacing(4)
        outer.addLayout(self.messages)

        self.title_label.clicked.connect(self.switch.toggle)

    def add_message(self, label):
        self.messages.addWidget(label)

    def setChecked(self, value):
        self.switch.setChecked(bool(value))

    def isChecked(self):
        return self.switch.isChecked()


class StatTile(QFrame):
    """指标小卡：数值 + 标签 + 可选补充说明。"""

    def __init__(self, label, value="0", hint="", parent=None):
        super().__init__(parent)
        self.setObjectName("inset")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(3)
        self.value_label = QLabel(str(value))
        self.value_label.setObjectName("statValue")
        self.label_label = QLabel(label)
        self.label_label.setObjectName("statLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.label_label)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("statHint")
        self.hint_label.setVisible(bool(hint))
        layout.addWidget(self.hint_label)

    def set_value(self, value):
        self.value_label.setText(str(value))


class SectionCard(QFrame):
    """区块卡片：标题栏（可带右侧操作）+ 分隔线 + 内容区。"""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 20)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("section")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("sectionHint")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle_label)
        header.addLayout(titles, 1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setContentsMargins(0, 0, 0, 0)
        self.header_actions.setSpacing(6)
        header.addLayout(self.header_actions)
        outer.addLayout(header)

        self.divider = QFrame()
        self.divider.setObjectName("divider")
        self.divider.setFixedHeight(1)
        outer.addWidget(self.divider)
        outer.addSpacing(16)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(14)
        outer.addLayout(self.body)


class EmptyState(QWidget):
    """居中的空状态提示。"""

    def __init__(self, title, hint="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        self.hint_label = QLabel(hint, self)
        self.hint_label.setObjectName("emptyHint")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(hint))
        layout.addWidget(self.hint_label)
        layout.addStretch(1)


class WidgetHelpersMixin:
    """面板内共用的轻量构造工具（保持既有调用签名不变）。"""

    @staticmethod
    def _card(margins=(22, 18, 22, 20), spacing=10) -> tuple:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        return card, layout

    @staticmethod
    def _label(text, name="muted", wrap=False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        if wrap:
            label.setWordWrap(True)
        return label

    @staticmethod
    def _divider(name="softDivider") -> QFrame:
        line = QFrame()
        line.setObjectName(name)
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _add_chip(layout, text, style="chip"):
        label = QLabel(text)
        label.setObjectName(style)
        layout.addWidget(label)

    @staticmethod
    def _set_widget_style(widget, name):
        if widget.objectName() == name:
            return
        widget.setObjectName(name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class _DrawerPanel(QFrame):
    """抽屉面板：吞掉自身区域的鼠标点击，避免点面板空白处误触遮罩关闭。"""

    def mousePressEvent(self, event):
        event.accept()


class SideDrawer(QWidget):
    """悬浮侧边抽屉：右侧滑入 + 半透明遮罩，不参与父级布局、不挤压内容。

    用法：
        drawer = SideDrawer(page, width=560)
        drawer.panel_layout().addWidget(...)   # 往面板里放内容
        drawer.open_drawer() / drawer.close_drawer()
    点遮罩或按 Esc 关闭；父容器尺寸变化时自动跟随。
    """

    closed = Signal()

    def __init__(self, parent, width=560):
        super().__init__(parent)
        self._drawer_width = width
        self._anim = None
        self.hide()

        # 遮罩：半透明暗色，铺满父容器
        self._mask = QWidget(self)
        self._mask.setObjectName("drawerMask")
        self._mask.setAttribute(Qt.WA_StyledBackground, True)

        # 面板：右侧固定宽度，内容由调用方填充
        self._panel = _DrawerPanel(self)
        self._panel.setObjectName("drawerPanel")
        self._panel.setFocusPolicy(Qt.StrongFocus)
        self._panel_layout = QVBoxLayout(self._panel)
        self._panel_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_layout.setSpacing(0)

        # Esc 在面板获得焦点时关闭
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self._panel)
        esc.setContext(Qt.WidgetShortcut)
        esc.activated.connect(self.close_drawer)

        # 跟随父容器尺寸变化
        parent.installEventFilter(self)

    def panel_layout(self) -> QVBoxLayout:
        return self._panel_layout

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        # 面板会吞掉自己的点击，能到达这里的只有遮罩区域
        self.close_drawer()
        event.accept()

    def _sync_geometry(self):
        page = self.parentWidget()
        if page is None:
            return
        self.setGeometry(page.rect())
        self._mask.setGeometry(0, 0, page.width(), page.height())
        width = min(self._drawer_width, page.width())
        if self.isVisible():
            self._panel.setGeometry(max(0, page.width() - width), 0, width, page.height())
        else:
            # 隐藏时停在屏幕外，打开时从右侧滑入
            self._panel.setGeometry(page.width(), 0, width, page.height())

    def open_drawer(self):
        page = self.parentWidget()
        if page is None:
            return
        self._sync_geometry()
        self.show()
        self.raise_()
        self._panel.setFocus()
        width = min(self._drawer_width, page.width())
        anim = QPropertyAnimation(self._panel, b"pos", self)
        anim.setDuration(180)
        anim.setStartValue(QPoint(page.width(), 0))
        anim.setEndValue(QPoint(max(0, page.width() - width), 0))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim = anim
        anim.start()

    def close_drawer(self):
        page = self.parentWidget()
        if page is None or not self.isVisible():
            return
        anim = QPropertyAnimation(self._panel, b"pos", self)
        anim.setDuration(150)
        anim.setStartValue(self._panel.pos())
        anim.setEndValue(QPoint(page.width(), 0))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.hide)
        self._anim = anim
        anim.start()
        self.closed.emit()
