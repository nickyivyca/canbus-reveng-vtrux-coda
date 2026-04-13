"""CAN monitor main window.

Drains the CAN message queue on a 50 ms timer (20 Hz), decodes frames via
BusDecoder, evaluates the active vehicle mode, and calls profile.update().

Optional simultaneous BUSMASTER log write: pass a BUSMASTERWriter instance
as `writer` and frames are written in the same timer loop.
"""
from __future__ import annotations

import logging
import time
from queue import Empty, Queue
from typing import Dict, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QLabel,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from canre.gui.base_profile import VehicleProfile
from canre.gui.bus_decoder import BusDecoder

logger = logging.getLogger(__name__)

_TIMER_MS      = 50    # timer interval (20 Hz UI updates)
_DRAIN_LIMIT   = 500   # max frames to drain per tick (avoids UI freeze on burst)


class CANMonitorWindow(QMainWindow):
    """Main GUI window for live CAN monitoring.

    Args:
        profile:          Vehicle profile (provides mode rules, builds layouts)
        decoder:          BusDecoder loaded with vehicle DBCs
        queue:            Message queue filled by CANBusLogger threads
                          (4-tuples: timestamp, bus_id, msg, direction)
        bus_assignments:  {channel_id: bus_name} from anchor detection
        writer:           Optional BUSMASTERWriter for simultaneous file logging
    """

    def __init__(
        self,
        profile: VehicleProfile,
        decoder: BusDecoder,
        queue: Queue,
        bus_assignments: Dict[int, str],
        writer=None,
    ):
        super().__init__()
        self._profile         = profile
        self._decoder         = decoder
        self._queue           = queue
        self._bus_assignments = bus_assignments
        self._writer          = writer

        self._current_mode: Optional[str] = None
        self._frame_count   = 0
        self._rate_frames   = 0
        self._last_rate_t   = time.time()

        self._setup_ui()
        self._start_timer()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"CAN Monitor  --  {self._profile.vehicle_name.upper()}")
        self.resize(1100, 750)

        # Mode banner
        self._mode_banner = QLabel("Waiting for CAN data...")
        self._mode_banner.setAlignment(Qt.AlignCenter)
        self._mode_banner.setStyleSheet(
            "font-size: 15px; font-weight: bold; padding: 5px;"
            "background: #222; color: #EEE;"
        )
        self._mode_banner.setFixedHeight(32)

        # One scrollable layout per mode
        self._stacked = QStackedWidget()
        self._mode_index: Dict[str, int] = {}

        for mode in self._profile.modes:
            inner = self._profile.build_layout(mode)
            # Wrap in a scroll area so content doesn't get clipped on small screens
            scroll = QScrollArea()
            scroll.setWidget(inner)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            idx = self._stacked.addWidget(scroll)
            self._mode_index[mode] = idx

        # Persistent panel (optional — provided by profile)
        self._persistent_panel = self._profile.build_persistent_panel()

        # Central container
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._mode_banner)
        if self._persistent_panel is not None:
            vbox.addWidget(self._persistent_panel)
        vbox.addWidget(self._stacked)
        self.setCentralWidget(container)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_label = QLabel()
        sb.addPermanentWidget(self._status_label)

        # Show default mode immediately
        self._switch_mode(self._profile.default_mode())

    def _start_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_TIMER_MS)

    # ------------------------------------------------------------------
    # Timer tick: drain queue -> decode -> mode check -> update widgets
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        drained = 0
        while drained < _DRAIN_LIMIT:
            try:
                timestamp, bus_id, msg, direction = self._queue.get_nowait()
            except Empty:
                break
            drained += 1

            bus_name = self._bus_assignments.get(bus_id)
            if bus_name and direction == "Rx":
                self._decoder.process(bus_name, msg.arbitration_id, bytes(msg.data))

            if self._writer is not None:
                try:
                    self._writer.write_message(timestamp, bus_id, msg, direction)
                except Exception:
                    pass

        self._frame_count += drained
        self._rate_frames += drained

        # Re-evaluate active mode
        new_mode = self._detect_mode()
        if new_mode != self._current_mode:
            self._switch_mode(new_mode)

        # Push updated values to widgets
        try:
            self._profile.update_always(self._decoder)
        except Exception as exc:
            logger.debug(f"profile.update_always() error: {exc}")

        if self._current_mode:
            try:
                self._profile.update(self._current_mode, self._decoder)
            except Exception as exc:
                logger.debug(f"profile.update() error: {exc}")

        # Refresh status bar once per second
        now = time.time()
        elapsed = now - self._last_rate_t
        if elapsed >= 1.0:
            rate = self._rate_frames / elapsed
            bus_str = "  ".join(
                f"{name}={ch}"
                for ch, name in sorted(self._bus_assignments.items())
            )
            self._status_label.setText(
                f"Mode: {self._current_mode or '?'}  |  "
                f"{rate:.0f} fr/s  |  total {self._frame_count}  |  "
                f"buses: {bus_str or 'none assigned'}"
            )
            self._rate_frames = 0
            self._last_rate_t  = now

    # ------------------------------------------------------------------
    # Mode evaluation
    # ------------------------------------------------------------------

    def _detect_mode(self) -> str:
        rules = self._profile.get_mode_rules()
        for mode in self._profile.modes:
            for rule in rules.get(mode, []):
                if rule.evaluate(self._decoder):
                    return mode
        return self._profile.default_mode()

    def _switch_mode(self, mode: str) -> None:
        self._current_mode = mode
        idx = self._mode_index.get(mode)
        if idx is not None:
            self._stacked.setCurrentIndex(idx)
        display = mode.replace("_", " ").title()
        self._mode_banner.setText(f"Mode: {display}")
        logger.info(f"Mode switched to: {mode}")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
