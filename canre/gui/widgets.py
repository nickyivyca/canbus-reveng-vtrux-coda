"""Reusable live-updating Qt widgets for the CAN monitor GUI.

All value widgets display a right-aligned label and a left-aligned value.
Call update_value(float_or_None) or update_text(str) to refresh.

Widget classes:
    LiveValue      label + numeric/text value
    LiveBar        label + QProgressBar (for SoC, PWM, etc.)
    LiveIndicator  label + colored dot (for boolean flags)

Helper:
    make_group(title, widgets) -> QGroupBox
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

_LABEL_WIDTH = 170   # px, right-aligned label column
_VALUE_WIDTH = 110   # px, minimum value column width


class LiveValue(QWidget):
    """A label : value display row.

    update_value(float)  -- formats with self._fmt and optional unit suffix
    update_text(str)     -- sets value label to arbitrary string
    set_alert(bool)      -- turns value label red/bold when True
    """

    def __init__(
        self,
        label: str,
        unit: str = "",
        fmt: str = "{:.1f}",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._fmt  = fmt
        self._unit = unit

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)

        lbl = QLabel(label + ":")
        lbl.setFixedWidth(_LABEL_WIDTH)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        self._val = QLabel("--")
        self._val.setMinimumWidth(_VALUE_WIDTH)
        self._val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._val)
        layout.addStretch()

    def update_value(self, value: Optional[float]) -> None:
        if value is None:
            self._val.setText("--")
            return
        text = self._fmt.format(value)
        if self._unit:
            text += " " + self._unit
        self._val.setText(text)

    def update_text(self, text: str) -> None:
        self._val.setText(text)

    def set_alert(self, active: bool) -> None:
        if active:
            self._val.setStyleSheet("color: #DD2200; font-weight: bold;")
        else:
            self._val.setStyleSheet("")


class LiveBar(QWidget):
    """A label + progress bar (header row shows label and current value).

    Useful for SoC, PWM percentages, etc.
    """

    def __init__(
        self,
        label: str,
        min_val: float = 0.0,
        max_val: float = 100.0,
        unit: str = "%",
        fmt: str = "{:.1f}",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._min  = min_val
        self._max  = max_val
        self._fmt  = fmt
        self._unit = unit

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 1, 0, 1)
        outer.setSpacing(2)

        # Header: label left, value right
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: bold;")
        self._val = QLabel("--")
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(lbl)
        header.addWidget(self._val)
        outer.addLayout(header)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(1000)  # 1000 steps for 0.1-unit resolution
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(18)
        outer.addWidget(self._bar)

    def update_value(self, value: Optional[float]) -> None:
        if value is None:
            self._val.setText("--")
            self._bar.setValue(0)
            return
        span   = self._max - self._min
        frac   = (max(self._min, min(self._max, value)) - self._min) / span if span else 0
        self._bar.setValue(int(frac * 1000))
        text = self._fmt.format(value)
        if self._unit:
            text += " " + self._unit
        self._val.setText(text)


class LiveIndicator(QWidget):
    """A label + colored dot for boolean/flag signals.

    set_state(True)  -> green dot
    set_state(False) -> grey dot (off/inactive, not necessarily a fault)
    set_state(None)  -> grey dot (unknown/no data)
    """

    _COLORS = {
        True:  "#00CC44",
        False: "#888888",
        None:  "#888888",
    }

    def __init__(self, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)

        lbl = QLabel(label + ":")
        lbl.setFixedWidth(_LABEL_WIDTH)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        self._dot = QLabel("●")
        self._dot.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._dot)
        layout.addStretch()

        self.set_state(None)

    def set_state(self, active: Optional[bool]) -> None:
        color = self._COLORS.get(active, "#888888")
        self._dot.setStyleSheet(f"color: {color};")


def make_group(title: str, widgets: list, parent: Optional[QWidget] = None) -> QGroupBox:
    """Wrap a list of widgets in a titled QGroupBox with a compact QVBoxLayout."""
    box = QGroupBox(title, parent)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 4, 8, 4)
    layout.setSpacing(2)
    for w in widgets:
        layout.addWidget(w)
    return box
