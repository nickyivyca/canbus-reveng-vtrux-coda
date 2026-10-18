"""Resolve raw logger channel numbers to named buses, per file.

Channel numbers are arbitrary: they follow dongle insertion order, and the
Android logger re-numbers a bus every time USB re-enumerates.  In an Android
T0 chunk one physical bus can appear on five channels **in sequence**:

    vtrux_20260925_155857_T0   powertrain on ch 8 (0-22.8 s), 10 (31.4-33.0 s),
                               14 (48.3-54.3 s), 16 (75.7-77.1 s), 18 (97.5 s-)

The spans are disjoint -- each channel is the same bus after a re-enumeration,
not a duplicate of it.  Two naive rules both lose data here:

  * "first channel carrying the anchor ID" (what diagnose_vtrux and
    vtrux_charge_failure_analysis used to do) locks to ch 8 and discards every
    later channel -- the whole charge session in that log.
  * "highest-count claimant wins" (tools/influx_upload.identify_buses) keeps
    only ch 18 and discards ch 14, which held the entire failed charge start.

So claimants of the same bus name are resolved by TIME: every claimant is
kept unless its span overlaps a busier claimant's span, in which case it
really is concurrent duplicate traffic and is dropped.

Scoring is identify_buses' step 1 unchanged: each channel is labelled with
the bus whose anchor set it matches by the highest FRACTION of anchors
present (ties -> declared order).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from canre.parsers import parse_file

# Two spans overlapping by less than this are treated as a hand-over, not
# concurrent traffic.
OVERLAP_TOLERANCE_S = 1.0


@dataclass
class ChannelSpan:
    """What one channel of one file carried."""
    count: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    ids: set = field(default_factory=set)


def scan_channels(path: Path | str) -> dict[int, ChannelSpan]:
    """One pass over a file: per raw channel, frame count, time span, ID set.

    Timestamps are parse_file's file-relative seconds, so spans are only
    comparable within one file.
    """
    spans: dict[int, ChannelSpan] = {}
    for fr in parse_file(path):
        s = spans.get(fr.bus)
        if s is None:
            s = spans[fr.bus] = ChannelSpan(first_ts=fr.timestamp)
        s.count += 1
        s.last_ts = fr.timestamp
        s.ids.add(fr.arbitration_id)
    return spans


def resolve_channels(
    spans: dict[int, ChannelSpan],
    bus_anchors: list[tuple[str, set]],
    tolerance_s: float = OVERLAP_TOLERANCE_S,
) -> dict[int, str | None]:
    """Map each raw channel to a bus name, or None.

    None means either no anchor matched, or the channel is concurrent
    duplicate traffic of a busier channel with the same name.
    """
    best: dict[int, str | None] = {}
    for ch, s in spans.items():
        scored = []
        for order, (name, anchors) in enumerate(bus_anchors):
            hits = len(s.ids & anchors)
            if hits:
                scored.append((hits / len(anchors), hits, -order, name))
        best[ch] = max(scored)[3] if scored else None

    mapping: dict[int, str | None] = {ch: None for ch in spans}
    for name in {n for n in best.values() if n is not None}:
        claimants = sorted((ch for ch, n in best.items() if n == name),
                           key=lambda c: spans[c].count, reverse=True)
        kept: list[int] = []
        for ch in claimants:
            s = spans[ch]
            if any(min(s.last_ts, spans[k].last_ts)
                   - max(s.first_ts, spans[k].first_ts) > tolerance_s
                   for k in kept):
                continue
            kept.append(ch)
            mapping[ch] = name
    return mapping


def resolve_files(
    paths: list[Path | str],
    bus_anchors: list[tuple[str, set]],
) -> dict[Path, dict[int, str | None]]:
    """resolve_channels() for every file; the result feeds merge_files(bus_map=...)."""
    return {Path(p): resolve_channels(scan_channels(p), bus_anchors) for p in paths}


def describe(bus_map: dict[Path, dict[int, str | None]]) -> list[str]:
    """One line per file: which raw channels became which bus."""
    lines = []
    for p, m in bus_map.items():
        by_name: dict[str, list[int]] = {}
        for ch, name in sorted(m.items()):
            if name is not None:
                by_name.setdefault(name, []).append(ch)
        parts = [f"{n}=ch{'+'.join(str(c) for c in chs)}"
                 for n, chs in sorted(by_name.items())]
        lines.append(f"{p.name}: {', '.join(parts) if parts else '(no bus identified)'}")
    return lines
