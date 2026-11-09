"""Render the application icon with the existing Qt build dependency."""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(size / 256, size / 256)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2F5BEA"))
        painter.drawRoundedRect(QRectF(4, 4, 248, 248), 40, 40)
        painter.setPen(QPen(QColor("#FFFFFF"), 13, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(45, 88, 166, 116), 12, 12)
        painter.drawRoundedRect(QRectF(93, 57, 70, 31), 8, 8)
        painter.drawLine(47, 126, 209, 126)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0B7A55"))
        painter.drawEllipse(QRectF(143, 143, 83, 83))
        painter.setPen(QPen(QColor("#FFFFFF"), 10, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        check = QPainterPath()
        check.moveTo(163, 184)
        check.lineTo(178, 198)
        check.lineTo(207, 167)
        painter.drawPath(check)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Icon PNG encoding failed")
        images.append((size, bytes(data)))
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    target = Path(__file__).resolve().parents[1] / "assets" / "app.ico"
    target.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(data for _, data in images))
    print(target)


if __name__ == "__main__":
    main()
