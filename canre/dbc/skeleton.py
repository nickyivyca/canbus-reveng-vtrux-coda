"""Generate a skeleton DBC file from observed CAN traffic."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from cantools.database.can import Signal

from canre.parsers.base import CANFrame
from canre.dbc.builder import DBCBuilder


@dataclass
class _MessageStats:
    """Accumulator for per-message statistics during the survey pass."""

    bus: int = 0
    arb_id: int = 0
    is_extended: bool = False
    dlc: int = 0
    count: int = 0
    first_ts: float = float("inf")
    last_ts: float = float("-inf")
    byte_min: list[int] = field(default_factory=lambda: [255] * 8)
    byte_max: list[int] = field(default_factory=lambda: [0] * 8)

    @property
    def duration(self) -> float:
        """Total observation window in seconds."""
        d = self.last_ts - self.first_ts
        return d if d > 0 else 0.0

    @property
    def frequency(self) -> float:
        """Average frames-per-second (0 when only one frame seen)."""
        if self.count < 2 or self.duration == 0:
            return 0.0
        return (self.count - 1) / self.duration


def _survey(
    frames_iter: Iterable[CANFrame],
    bus_filter: int | None = None,
) -> dict[tuple[int, int, bool], _MessageStats]:
    """Single pass over the frame stream to collect per-message statistics.

    The dict key is ``(bus, arbitration_id, is_extended)``.
    """
    stats: dict[tuple[int, int, bool], _MessageStats] = {}

    for frame in frames_iter:
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        key = (frame.bus, frame.arbitration_id, frame.is_extended)
        if key not in stats:
            st = _MessageStats(
                bus=frame.bus,
                arb_id=frame.arbitration_id,
                is_extended=frame.is_extended,
                dlc=frame.dlc,
            )
            stats[key] = st
        else:
            st = stats[key]
            # Keep the largest DLC observed
            if frame.dlc > st.dlc:
                st.dlc = frame.dlc

        st.count += 1
        if frame.timestamp < st.first_ts:
            st.first_ts = frame.timestamp
        if frame.timestamp > st.last_ts:
            st.last_ts = frame.timestamp

        for i, b in enumerate(frame.data):
            if i >= 8:
                break
            if b < st.byte_min[i]:
                st.byte_min[i] = b
            if b > st.byte_max[i]:
                st.byte_max[i] = b

    return stats


def _make_msg_name(arb_id: int, is_extended: bool) -> str:
    """Generate a DBC-safe message name from the arbitration ID."""
    if is_extended:
        return f"MSG_0x{arb_id:08X}"
    return f"MSG_0x{arb_id:03X}"


def _make_byte_signals(dlc: int) -> list[Signal]:
    """Create one 8-bit unsigned signal per payload byte.

    Uses little-endian (Intel) byte order with each signal starting at
    the first bit of its respective byte.
    """
    signals: list[Signal] = []
    for i in range(dlc):
        sig = Signal(
            name=f"byte{i}",
            start=i * 8,
            length=8,
            byte_order="little_endian",
            is_signed=False,
            scale=1,
            offset=0,
            minimum=0,
            maximum=255,
            unit="",
            comment=None,
        )
        signals.append(sig)
    return signals


def generate_skeleton(
    frames_iter: Iterable[CANFrame],
    output_path: Path | str,
    bus_filter: int | None = None,
) -> Path:
    """Generate a skeleton DBC file from observed CAN traffic.

    Creates one message per unique ``(bus, arbitration_id)`` with:

    * Message named ``MSG_0x123`` (or ``MSG_0x18FF0320`` for extended).
    * Length set to the largest observed DLC.
    * One raw 8-bit unsigned signal per byte: ``byte0`` .. ``byte{dlc-1}``.
    * A comment on each message noting frame count and average frequency.

    Args:
        frames_iter: Iterable (or generator) of :class:`CANFrame` objects.
        output_path: Destination ``.dbc`` file path.
        bus_filter: If given, only include frames from this bus number.

    Returns:
        The resolved output :class:`Path`.
    """
    output_path = Path(output_path)

    # -- Pass 1: survey the traffic -----------------------------------------
    stats = _survey(frames_iter, bus_filter=bus_filter)

    if not stats:
        raise ValueError("No frames matched the filter -- nothing to write.")

    # -- Pass 2: build the DBC -----------------------------------------------
    builder = DBCBuilder(path=output_path)

    for key in sorted(stats, key=lambda k: (k[0], k[1])):
        st = stats[key]
        dlc = st.dlc if st.dlc > 0 else 8
        msg_name = _make_msg_name(st.arb_id, st.is_extended)
        signals = _make_byte_signals(dlc)

        freq_str = f"{st.frequency:.1f} Hz" if st.frequency > 0 else "single frame"
        comment = (
            f"Bus {st.bus} | {st.count} frames | {freq_str} | "
            f"observed {st.duration:.2f}s"
        )

        # Add byte-range info per byte
        range_parts: list[str] = []
        for i in range(dlc):
            lo = st.byte_min[i]
            hi = st.byte_max[i]
            if lo == hi:
                range_parts.append(f"B{i}=0x{lo:02X}")
            else:
                range_parts.append(f"B{i}=[0x{lo:02X}-0x{hi:02X}]")
        comment += " | " + " ".join(range_parts)

        builder.add_message(
            msg_id=st.arb_id,
            name=msg_name,
            length=dlc,
            is_extended=st.is_extended,
            comment=comment,
            signals=signals,
        )

    return builder.save(output_path)
