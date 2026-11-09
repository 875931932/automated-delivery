"""Application attribution and bundled usage notice."""

import html
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
    QTextBrowser, QVBoxLayout,
)

from app_paths import get_resource_dir


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        resources = get_resource_dir()
        info = json.loads((resources / "author_info.json").read_text(encoding="utf-8"))
        self.setWindowTitle("关于 AutoDeliver")
        self.setWindowIcon(QIcon(str(resources / "assets" / "app.ico")))
        self.resize(700, 650)
        self.setMinimumSize(540, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        icon = QLabel(self)
        icon.setPixmap(self.windowIcon().pixmap(48, 48))
        icon.setFixedSize(48, 48)
        heading.addWidget(icon)
        titles = QVBoxLayout()
        title = QLabel(info["app_name"], self)
        title.setObjectName("sectionTitle")
        title.setWordWrap(True)
        titles.addWidget(title)
        byline = QLabel(f"版本 {info['version']}  |  作者 {info['author']}", self)
        byline.setObjectName("muted")
        titles.addWidget(byline)
        heading.addLayout(titles, 1)
        layout.addLayout(heading)
        contacts = QGridLayout()
        contacts.setHorizontalSpacing(16)
        contacts.setVerticalSpacing(8)
        for row, (caption, key) in enumerate((("邮箱", "email"), ("GitHub", "github"), ("Gitee", "gitee"))):
            label = QLabel(caption, self)
            label.setObjectName("muted")
            contacts.addWidget(label, row, 0)
            value = info[key]
            url = f"mailto:{value}" if key == "email" else value
            link = QLabel(f'<a href="{html.escape(url, quote=True)}">{html.escape(value)}</a>', self)
            link.setObjectName(f"author_{key}")
            link.setWordWrap(True)
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextBrowserInteraction)
            contacts.addWidget(link, row, 1)
        contacts.setColumnStretch(1, 1)
        layout.addLayout(contacts)
        self.notice = QTextBrowser(self)
        self.notice.setObjectName("detailView")
        self.notice.setOpenExternalLinks(True)
        self.notice.setMarkdown((resources / "DISCLAIMER.md").read_text(encoding="utf-8"))
        layout.addWidget(self.notice, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
