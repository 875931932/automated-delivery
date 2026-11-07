# -*- coding: utf-8 -*-
"""通用小部件：自动换行布局与常用控件构造工具。"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QVBoxLayout


class FlowLayout(QLayout):
    """自动换行的横向布局，用于职位族/排除项等标签。"""

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



class WidgetHelpersMixin:
    # ---------------- 通用小部件 --------------
    @staticmethod
    def _card(margins=(20, 18, 20, 18), spacing=10) -> tuple:
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

