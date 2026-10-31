"""Millisecond ordering of every DBC-decoded PT-bus signal change around a
charge start, for vtrux_20260925_155857 (first charger failed ~3 s into
state 12; second charger worked).

PT channels are folded (Android T0 bus churn: the PT bus appears as 10, 14
and 18 in T0). Timestamps are parse_file's per-file t (first frame = 0), which
for T0 matches vtrux_charge_failure_analysis' merged t.

Signals that change more than NOISY times inside the window are summarised
(first/min/max/last) instead of listed.

Usage: python3.13 <this> LOG T_START T_END [T_REF]
"""
import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

DBCS = ["projects/vtrux/BelInverter-v2.dbc",
        "projects/vtrux/epri-pt-bus.dbc",
        "projects/vtrux/vtrux-powertrain-experimental.dbc"]
PT_ANCHORS = {0x410, 0x420, 0x430, 0x440, 0x18FFD4C0, 0x18FFD9C0}
NOISY = 12


def message_for(dbs, cid):
    for db in dbs:
        for fid in (cid, cid | 0x80000000):
            try:
                m = db.get_message_by_frame_id(fid)
            except KeyError:
                continue
            if m.signals:
                return m
    return None


def main():
    path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    tref = float(sys.argv[4]) if len(sys.argv) > 4 else t0
    dbs = [cantools.database.load_file(p, strict=False) for p in DBCS]
    cache = {}
    frames = []
    chans = set()
    for fr in parse_file(path):
        if fr.timestamp > t1 + 1:
            break
        if fr.arbitration_id in PT_ANCHORS:
            chans.add(fr.bus)
        if fr.timestamp >= t0 - 3:
            frames.append(fr)
    print(f"PT channels: {sorted(chans)}")
    last = {}
    changes = {}
    for fr in frames:
        if fr.bus not in chans:
            continue
        cid = fr.arbitration_id
        if cid not in cache:
            cache[cid] = message_for(dbs, cid)
        msg = cache[cid]
        if msg is None:
            continue
        try:
            dec = msg.decode(bytes(fr.data), decode_choices=True,
                             allow_truncated=True)
        except Exception:
            continue
        for n, v in dec.items():
            k = (msg.name, n)
            was = last.get(k)
            last[k] = v
            if fr.timestamp < t0 or was is None or was == v:
                continue
            changes.setdefault(k, []).append((fr.timestamp, was, v))
    events = []
    noisy = []
    for k, ch in changes.items():
        if len(ch) > NOISY:
            vals = [c[2] for c in ch if isinstance(c[2], (int, float))]
            if vals:
                noisy.append((k, len(ch), ch[0][1], min(vals), max(vals), ch[-1][2]))
            continue
        for t, was, v in ch:
            events.append((t, k, was, v))
    events.sort(key=lambda e: e[0])
    print(f"window {t0:.2f}..{t1:.2f} s, dt relative to {tref:.2f} s\n")
    for t, (m, n), was, v in events:
        print(f"t={t:9.3f}  dt={(t - tref) * 1000:+9.1f} ms  {m:32s} {n:40s} {was} -> {v}")
    print("\nNoisy signals (changes, first, min, max, last):")
    for (m, n), cnt, first, lo, hi, lastv in sorted(noisy):
        print(f"  {m:32s} {n:40s} n={cnt:4d} first={first} min={lo} max={hi} last={lastv}")


if __name__ == "__main__":
    main()
