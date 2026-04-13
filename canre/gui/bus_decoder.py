"""CAN signal decoder: loads DBC files and maintains a decoded signal cache.

Frames are fed via process(); current values are read via get() and get_display().
decode_choices=False is used throughout so all values are numeric (int/float),
making mode predicates straightforward integer comparisons. VAL_ lookup for
display strings is done separately via get_display().
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class BusDecoder:
    """Decodes CAN frames via cantools and caches current signal values.

    Cache layout:
        _cache[(bus_name, msg_id, signal_name)] = float/int value
        _last_seen[(bus_name, msg_id)]          = time.time() of most recent frame
    """

    def __init__(self, dbc_paths: Dict[str, str], project_root: Path):
        """
        Args:
            dbc_paths:    {bus_name: dbc_path_relative_to_project_root}
            project_root: absolute path to the project root directory
        """
        import cantools

        self._dbs: Dict[str, Any] = {}
        for bus, rel_path in dbc_paths.items():
            full = project_root / rel_path
            if full.exists():
                try:
                    self._dbs[bus] = cantools.db.load_file(str(full), strict=False)
                    logger.info(f"Loaded DBC for {bus}: {full.name}")
                except Exception as exc:
                    logger.warning(f"Failed to load DBC {full}: {exc}")
            else:
                logger.warning(f"DBC not found for bus '{bus}': {full}")

        self._cache: Dict[Tuple, Any] = {}        # (bus, msg_id, signal) -> value
        self._last_seen: Dict[Tuple, float] = {}  # (bus, msg_id) -> timestamp

    # ------------------------------------------------------------------
    # Frame processing
    # ------------------------------------------------------------------

    def process(self, bus: str, msg_id: int, data: bytes) -> None:
        """Decode a frame and update the signal cache."""
        self._last_seen[(bus, msg_id)] = time.time()

        db = self._dbs.get(bus)
        if db is None:
            return

        try:
            decoded = db.decode_message(msg_id, data, decode_choices=False)
            for sig_name, value in decoded.items():
                self._cache[(bus, msg_id, sig_name)] = value
        except Exception:
            pass  # unknown ID or decode error — silently skip

    # ------------------------------------------------------------------
    # Value access
    # ------------------------------------------------------------------

    def get(self, bus: str, msg_id: int, signal: str) -> Optional[float]:
        """Return the latest decoded numeric value, or None if not yet seen."""
        return self._cache.get((bus, msg_id, signal))

    def get_display(
        self,
        bus: str,
        msg_id: int,
        signal: str,
        fmt: str = "{:.1f}",
        fallback: str = "--",
        unit: str = "",
    ) -> str:
        """Return a human-readable string for a signal value.

        Uses the DBC VAL_ table if available (e.g. HVPowermode -> "HV On Charge").
        Falls back to fmt.format(value) + unit for numeric-only signals.
        """
        val = self._cache.get((bus, msg_id, signal))
        if val is None:
            return fallback

        db = self._dbs.get(bus)
        if db is not None:
            try:
                msg_obj = db.get_message_by_frame_id(msg_id)
                sig_obj = msg_obj.get_signal_by_name(signal)
                if sig_obj.choices:
                    key = int(round(val))
                    if key in sig_obj.choices:
                        return str(sig_obj.choices[key])
            except Exception:
                pass

        text = fmt.format(val)
        if unit:
            text += " " + unit
        return text

    # ------------------------------------------------------------------
    # Presence / timing
    # ------------------------------------------------------------------

    def id_present(self, bus: str, msg_id: int, max_age_s: float = 10.0) -> bool:
        """True if a frame with this ID was seen within max_age_s seconds."""
        last = self._last_seen.get((bus, msg_id))
        return last is not None and (time.time() - last) <= max_age_s

    def bus_active(self, bus: str, max_age_s: float = 10.0) -> bool:
        """True if any frame on this bus was seen within max_age_s seconds."""
        now = time.time()
        return any(
            (now - ts) <= max_age_s
            for (b, _), ts in self._last_seen.items()
            if b == bus
        )
