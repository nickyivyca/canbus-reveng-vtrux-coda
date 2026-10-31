"""A capture -> time-ordered frame streams, each labelled with its bus BY CONTENT.

Bus identification follows AGENTS.md "A discriminator that cannot fail": a
channel is labelled only when it carries >= MIN_ANCHORS distinct audited-exclusive
anchors of one bus AND ZERO of every other bus. Anything else is UNRESOLVED and
carries its reason. Asking for a bus no channel resolved to raises rather than
returning a nearest match. A single-channel capture is held to exactly the same
test -- being the only channel is not evidence.

Anchors: `projects/coda/README.md`, audited by `anchor_exclusivity_audit.py`.
Withdrawn ids (0x1D5, 0x275, 0x383, 0x274-0x27D, 0x212) are gateway rebroadcasts
and are deliberately absent; 0x00C and 0x004 are absent because those ids also carry
other traffic on B (0x004, 0x00C) and D (0x00C) CAN.

`canre.utils.buses.resolve_channels` is NOT used: it labels a channel with the
highest anchor FRACTION and never requires the others to be empty, so it always
returns a winner (2026-10-09, flagged to the user, not changed here).

Times are integer microseconds from the parser's t=0 (first frame in FILE order),
and every (bus, id) series is sorted before use, since file order is not time
order (AGENTS.md "Two thresholds that look like measurements").
"""

import os
import sys
from collections import defaultdict

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from canre.parsers import parse_file          # noqa: E402
from canre.utils.timebase import read_header_datetime  # noqa: E402

ANCHORS = {
    "D": frozenset({0x308, 0x312, 0x325, 0x330, 0x580}),
    "B": frozenset({0x48A, 0x381}),
    # 0x00C and 0x004 are NOT anchors: 0x00C is also a different, rare message on D CAN
    # (3 of 1082 captures) and B CAN (14), payloads like 00 00 04 00 00 00 00 01; 0x004
    # appears on the B CAN channel of 28 captures with an all-zero payload. Neither is
    # ever cell voltages there (corpus sweep 2026-10-09; projects/coda/README.md).
    "C": frozenset(range(0x000, 0x01A)) - {0x00C, 0x004},
}
MIN_ANCHORS = 2


class BusError(LookupError):
    pass


def classify(ids):
    """(label or None, reason) for one channel's id set."""
    hits = {b: len(ids & a) for b, a in ANCHORS.items()}
    winners = [b for b, n in hits.items() if n >= MIN_ANCHORS]
    others_zero = {b: all(hits[o] == 0 for o in hits if o != b) for b in winners}
    ok = [b for b in winners if others_zero[b]]
    if len(ok) == 1:
        return ok[0], "anchors %s" % hits
    if not winners:
        return None, "no bus has >= %d anchors: %s" % (MIN_ANCHORS, hits)
    return None, "anchors of more than one bus present: %s" % hits


class Capture:
    def __init__(self, path):
        self.path = path
        self.stem = os.path.splitext(os.path.basename(path))[0]
        self.start_wall = read_header_datetime(path)
        per_ch = defaultdict(lambda: defaultdict(list))
        for f in parse_file(path):
            per_ch[f.bus][f.arbitration_id].append(
                (int(round(f.timestamp * 1e6)), bytes(f.data)))
        self.channels = {}
        self.streams = {}
        for ch, by_id in per_ch.items():
            label, why = classify(set(by_id))
            self.channels[ch] = (label, why, sum(len(v) for v in by_id.values()))
            if label is None:
                continue
            for fid, rows in by_id.items():
                if (label, fid) in self.streams:
                    raise BusError("%s: two channels both resolve to %s CAN (%s) -- "
                                   "refusing to merge" % (self.stem, label, self.channels))
                rows.sort(key=lambda r: r[0])
                self.streams[(label, fid)] = rows

    def buses(self):
        return sorted({lab for lab, _, _ in self.channels.values() if lab})

    def require(self, bus):
        if bus not in self.buses():
            raise BusError("%s: no channel resolves to %s CAN; channels: %s"
                           % (self.stem, bus, self.channels))

    def frames(self, bus, fid):
        """Sorted [(t_us, data)] for one id on one bus. Raises if the bus is
        unresolved; returns [] if the bus is present but the id never appears --
        callers that need the id must check (Mode 1: empty is not a negative)."""
        self.require(bus)
        return self.streams.get((bus, fid), [])

    def span_us(self):
        ts = [r[0][0] for r in self.streams.values()] + [r[-1][0] for r in self.streams.values()]
        return (min(ts), max(ts)) if ts else (0, 0)

    def describe(self):
        s = "capture %s  start %s" % (self.stem, self.start_wall)
        for ch, (lab, why, n) in sorted(self.channels.items(), key=lambda kv: str(kv[0])):
            s += "\n  ch %s -> %s  (%d frames; %s)" % (ch, lab or "UNRESOLVED", n, why)
        return s


def load(path):
    return Capture(path)
