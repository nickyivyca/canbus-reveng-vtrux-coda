"""Stable per-message definition hashes, for detecting DBC drift.

The incremental uploader needs to answer one question cheaply: *has the way we
decode this CAN ID changed since we uploaded it?* Comparing the uploaded signal
names against the DBC (the "L1" data-derived diff) catches renames, additions
and removals, but is blind to a scale, offset, bit-position or endianness
change -- the signal name is identical and only the values differ. A recorded
hash of the message definition is what closes that gap.

What is hashed
--------------
Only properties that change a decoded value: name, start bit, length, byte
order, signedness, scale, offset, minimum, maximum, multiplexer ids, and
whether the signal is the multiplexer.

Deliberately NOT hashed: comments, value tables, receiver lists, message name,
message comment. Editing a ``CM_`` or renaming a message must not trigger a
re-upload of millions of points.

The exclusion rules are folded in, because a signal excluded on a bus is not
written and so is not part of what was uploaded. Two buses can therefore get
different hashes for the same CAN ID -- which is correct, since the Vtrux
gateway means `0x0C9` on `obd` and on `vehicle` genuinely carry different
signal sets.

Multi-DBC merge order mirrors ``influx_upload.decode_frame``: a later DBC wins
on a signal-name collision. 49 of 270 Vtrux (bus, can_id) definitions and 5 of
181 Coda ones come from more than one DBC, so this is not a corner case.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

__all__ = ["signal_fingerprint", "message_hashes", "HASH_LEN"]

HASH_LEN = 12


def signal_fingerprint(sig) -> tuple:
    """Every property of a cantools Signal that changes its decoded value."""
    return (
        sig.name,
        sig.start,
        sig.length,
        sig.byte_order,
        bool(sig.is_signed),
        float(sig.scale),
        float(sig.offset),
        None if sig.minimum is None else float(sig.minimum),
        None if sig.maximum is None else float(sig.maximum),
        tuple(sig.multiplexer_ids) if sig.multiplexer_ids else None,
        bool(sig.is_multiplexer),
    )


def message_hashes(
    databases,
    buses,
    *,
    exclude_global=frozenset(),
    exclude_bus_signal=frozenset(),
    exclude_id=frozenset(),
    exclude_bus_id=frozenset(),
) -> dict:
    """-> {(bus_name, "0xNNN"): "<12 hex>"} for every message that would upload.

    databases: list of (name, cantools.Database) in load order, as
               ``influx_upload.load_databases`` returns.
    buses:     bus names to evaluate, e.g. ["powertrain", "vehicle", "obd"].

    The four exclusion sets have the same shapes
    ``influx_upload.build_exclude_sets`` produces.
    """
    merged: dict[int, dict] = defaultdict(dict)
    for _name, db in databases:
        for msg in db.messages:
            for sig in msg.signals:
                merged[msg.frame_id][sig.name] = signal_fingerprint(sig)

    out: dict = {}
    for frame_id, sigmap in merged.items():
        # Mask the cantools extended-ID marker so the key matches the `can_id`
        # tag the uploader writes.
        can_id = f"0x{frame_id & 0x1FFFFFFF:03X}"
        if frame_id in exclude_id:
            continue
        for bus in buses:
            if (bus, frame_id) in exclude_bus_id:
                continue
            kept = {
                n: fp for n, fp in sigmap.items()
                if n not in exclude_global and (bus, n) not in exclude_bus_signal
            }
            if not kept:
                continue
            blob = json.dumps(sorted(kept.values()), sort_keys=True, default=str)
            out[(bus, can_id)] = hashlib.sha256(
                blob.encode()).hexdigest()[:HASH_LEN]
    return out
