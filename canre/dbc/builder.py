"""Build and modify DBC files programmatically using cantools."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cantools
from cantools.database.can import Database, Message, Signal


class DBCBuilder:
    """Build and modify DBC files programmatically using cantools."""

    def __init__(self, path: Path | str | None = None):
        """Load existing DBC or create empty database.

        Args:
            path: Path to an existing DBC file to load, or the intended
                  save path for a new database.  If the file exists it is
                  loaded; otherwise an empty database is created.
        """
        if path and Path(path).exists():
            self.db: Database = cantools.database.load_file(str(path))
            self.path: Path | None = Path(path)
        else:
            self.db = Database()
            self.path = Path(path) if path else None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        msg_id: int,
        name: str,
        length: int = 8,
        is_extended: bool = False,
        comment: str = "",
        signals: list[Signal] | None = None,
    ) -> Message:
        """Add a new message definition.

        Args:
            msg_id: CAN arbitration ID.
            name: Human-readable message name (e.g. ``"EngineRPM"``).
            length: Payload length in bytes (default 8).
            is_extended: ``True`` for 29-bit extended frames.
            comment: Optional comment/description.
            signals: Optional list of pre-built :class:`Signal` objects.

        Returns:
            The newly created :class:`Message`.
        """
        msg = Message(
            frame_id=msg_id,
            name=name,
            length=length,
            is_extended_frame=is_extended,
            comment=comment or None,
            signals=signals or [],
        )
        # _add_message handles internal bookkeeping (lookup caches etc.)
        try:
            self.db._add_message(msg)
        except AttributeError:
            # Fallback: append directly and refresh caches
            self.db.messages.append(msg)
            self.db.refresh()
        return msg

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def add_signal(
        self,
        msg_id: int,
        name: str,
        start_bit: int,
        length: int,
        byte_order: str = "big_endian",
        is_signed: bool = False,
        scale: float = 1.0,
        offset: float = 0.0,
        minimum: float | None = None,
        maximum: float | None = None,
        unit: str = "",
        comment: str = "",
    ) -> Signal:
        """Add a signal to an existing message.

        The message is identified by *msg_id*.  Because cantools
        :class:`Message` objects are immutable with respect to their
        signal list, the old message is replaced by a new one that
        includes the additional signal.

        Args:
            msg_id: Frame ID of the parent message.
            name: Signal name (e.g. ``"EngineSpeed"``).
            start_bit: Start bit position (per DBC conventions).
            length: Signal length in bits.
            byte_order: ``"big_endian"`` or ``"little_endian"``.
            is_signed: ``True`` for signed values.
            scale: Linear scaling factor (physical = raw * scale + offset).
            offset: Linear offset.
            minimum: Optional physical minimum.
            maximum: Optional physical maximum.
            unit: Engineering unit string (e.g. ``"rpm"``).
            comment: Optional description.

        Returns:
            The newly created :class:`Signal`.
        """
        msg = self.db.get_message_by_frame_id(msg_id)

        signal = Signal(
            name=name,
            start=start_bit,
            length=length,
            byte_order=byte_order,
            is_signed=is_signed,
            scale=scale,
            offset=offset,
            minimum=minimum,
            maximum=maximum,
            unit=unit,
            comment=comment or None,
        )

        # Rebuild the message with the new signal appended.
        new_signals = list(msg.signals) + [signal]

        # Remove the old message (match both frame_id and extended flag).
        self.db.messages = [
            m
            for m in self.db.messages
            if not (
                m.frame_id == msg.frame_id
                and m.is_extended_frame == msg.is_extended_frame
            )
        ]

        new_msg = Message(
            frame_id=msg.frame_id,
            name=msg.name,
            length=msg.length,
            signals=new_signals,
            is_extended_frame=msg.is_extended_frame,
            comment=msg.comment,
        )

        try:
            self.db._add_message(new_msg)
        except AttributeError:
            self.db.messages.append(new_msg)
            self.db.refresh()

        return signal

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        """Save database to a DBC file.

        Args:
            path: Destination path.  Falls back to the path given at
                  construction time.

        Returns:
            The resolved output :class:`Path`.

        Raises:
            ValueError: If no output path is available.
        """
        out = Path(path) if path else self.path
        if not out:
            raise ValueError("No output path specified")
        out.parent.mkdir(parents=True, exist_ok=True)
        cantools.database.dump_file(self.db, str(out))
        return out

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_message(self, msg_id: int) -> Message | None:
        """Get a message by frame ID, or ``None`` if not found."""
        try:
            return self.db.get_message_by_frame_id(msg_id)
        except KeyError:
            return None

    def list_messages(self) -> list[dict]:
        """Return a summary list of all messages sorted by frame ID.

        Each entry is a dict with keys:
        ``id``, ``name``, ``length``, ``signals``, ``extended``.
        """
        return [
            {
                "id": f"0x{m.frame_id:X}",
                "name": m.name,
                "length": m.length,
                "signals": len(m.signals),
                "extended": m.is_extended_frame,
            }
            for m in sorted(self.db.messages, key=lambda m: m.frame_id)
        ]

    def remove_message(self, msg_id: int, is_extended: bool = False) -> bool:
        """Remove a message by frame ID.

        Returns:
            ``True`` if a message was removed, ``False`` otherwise.
        """
        before = len(self.db.messages)
        self.db.messages = [
            m
            for m in self.db.messages
            if not (m.frame_id == msg_id and m.is_extended_frame == is_extended)
        ]
        changed = len(self.db.messages) < before
        if changed:
            self.db.refresh()
        return changed

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.db.messages)

    def __repr__(self) -> str:
        return f"DBCBuilder(messages={len(self.db.messages)}, path={self.path})"
