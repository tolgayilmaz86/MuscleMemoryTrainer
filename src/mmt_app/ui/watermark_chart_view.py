from __future__ import annotations

from typing import Optional

from PySide6.QtCharts import QChart, QChartView
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QWidget


class WatermarkChartView(QChartView):
    """QChartView with a large translucent watermark centered in the plot area."""

    def __init__(
        self,
        chart: QChart,
        *,
        text_color: QColor = QColor(148, 163, 184, 100),
        height_ratio: float = 0.75,
        vertical_offset_ratio: float = 0.08,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(chart, parent)
        self._watermark_text = ""
        self._visible = True
        self._height_ratio = height_ratio
        self._vertical_offset_ratio = vertical_offset_ratio
        self.setRenderHint(QPainter.Antialiasing)

        self._label = QLabel(self.viewport())
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            f"color: rgba({text_color.red()}, {text_color.green()}, {text_color.blue()}, {text_color.alpha()}); "
            "background: transparent; font-weight: 600;"
        )
        self._update_geometry()

    def set_watermark_text(self, text: str) -> None:
        text = str(text)
        if text == self._watermark_text:
            return
        self._watermark_text = text
        self._label.setText(self._watermark_text)
        self._sync_visibility()
        self._update_geometry()
        self._label.raise_()
        self._label.update()

    def set_watermark_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._sync_visibility()
        self._label.raise_()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_geometry()

    def _update_geometry(self) -> None:
        rect = self.viewport().rect()
        offset = int(rect.height() * self._vertical_offset_ratio)
        adjusted = rect.adjusted(0, -offset, 0, -offset)
        if adjusted.height() <= 0:
            adjusted = rect
        self._label.setGeometry(adjusted)
        self._resize_font(rect)
        self._label.raise_()

    def _resize_font(self, rect) -> None:
        if not self._watermark_text:
            return
        font = self._label.font()
        target_height = int(rect.height() * self._height_ratio) or 24
        font.setPixelSize(max(12, target_height))

        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(self._watermark_text)
        if text_width > rect.width() * 0.95 and text_width > 0:
            scale = (rect.width() * 0.95) / text_width
            font.setPixelSize(max(12, int(font.pixelSize() * scale)))

        self._label.setFont(font)

    def _sync_visibility(self) -> None:
        self._label.setVisible(self._visible and bool(self._watermark_text))
