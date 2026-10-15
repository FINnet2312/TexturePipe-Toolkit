"""status_banner — 状态栏彩色横幅。

设计:
- 一条彩色横幅(成功/信息绿、警告黄、错误红)+ 文字 + 关闭按钮
- 可临时显示(timeout ms)或永久显示(直到用户关闭或下次覆盖)
- show(level, msg, timeout=0) 一次函数
- 4 个便捷方法: info / success / warning / error
- 主窗口可作为 statusBar 的永久 widget 装入,或作为子控件放任意处
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


# 级别 → (背景色, 文字色, emoji)
LEVEL_STYLES = {
    "info": ("#2b3a4a", "#cfe3ff", "ℹ"),
    "success": ("#1d4a2a", "#b8f0c8", "✓"),
    "warning": ("#5a4a1a", "#ffe7a8", "⚠"),
    "error": ("#5a1d1d", "#ffb0b0", "✗"),
}


class StatusBanner(QWidget):
    """彩色状态横幅,接到主窗口 statusBar 上。"""

    dismissed = Signal()

    DEFAULT_TIMEOUT = {
        "info": 3000,
        "success": 3000,
        "warning": 5000,
        "error": 8000,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(8)

        # 级别标签(emoji)
        self._level_lbl = QLabel("ℹ")
        self._level_lbl.setFixedWidth(16)
        f = self._level_lbl.font()
        f.setPointSize(f.pointSize() + 1)
        self._level_lbl.setFont(f)
        layout.addWidget(self._level_lbl)

        # 消息文字
        self._msg_lbl = QLabel("")
        self._msg_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        f = self._msg_lbl.font()
        self._msg_lbl.setFont(f)
        layout.addWidget(self._msg_lbl, 1)

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setFlat(True)
        self._close_btn.setStyleSheet("QPushButton { color:#aaa; border:none; } QPushButton:hover { color:#fff; }")
        self._close_btn.clicked.connect(self.clear)
        layout.addWidget(self._close_btn)

        self.setAutoFillBackground(True)
        self.clear()

    # -- 公开 API -------------------------------------------------------
    def show_message(self, level: str, msg: str, timeout: int = 0):
        """显示消息。level ∈ {'info', 'success', 'warning', 'error'};timeout=0 用级别默认。"""
        level = level if level in LEVEL_STYLES else "info"
        bg, fg, emoji = LEVEL_STYLES[level]
        self._level_lbl.setText(emoji)
        self._msg_lbl.setText(msg)
        self.setStyleSheet(
            f"StatusBanner {{ background:{bg}; border-radius:3px; }}"
            f"StatusBanner QLabel {{ color:{fg}; }}"
        )
        # 自动消失
        if timeout <= 0:
            timeout = self.DEFAULT_TIMEOUT[level]
        self._timer.start(timeout)

    # 便捷方法
    def info(self, msg: str, timeout: int = 0):    self.show_message("info", msg, timeout)
    def success(self, msg: str, timeout: int = 0): self.show_message("success", msg, timeout)
    def warning(self, msg: str, timeout: int = 0): self.show_message("warning", msg, timeout)
    def error(self, msg: str, timeout: int = 0):   self.show_message("error", msg, timeout)

    def clear(self):
        """清空消息。"""
        self._timer.stop()
        self._level_lbl.setText("")
        self._msg_lbl.setText("")
        self.setStyleSheet("StatusBanner { background:transparent; }")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 22)
