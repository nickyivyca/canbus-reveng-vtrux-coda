"""
b3_correlates_scan.py

Scan ALL (ID, byte) pairs in vtruxcurrentlimitingtest.log and correlate each
against 0x373 B3 (battery system temperature reference).

Goal: find other bytes that track the same underlying thermal variable, or that
respond predictably to temperature (e.g. current limits, thermal headroom).

Usage: py -3.12 b3_correlates_scan.py [--log <path>] [--min-r 0.7] [--min-unique 3]
"""
import sys
import math
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers.autodetect import parse_file

DEFAULT_LOG = ROOT / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
REF_ID    = 0x373
REF_BYTE  = 3
ANCHOR_ID = 0x051   # PT bus

# Minimum number of unique values to consider a byte non-constant
MIN_UNIQUE = 3
# Maximum change rate to qualify as "slowly varying" (raw counts per second)
# A byte that flips every frame at 77 Hz is not a temperature signal
MAX_RATE_PER_SEC = 5.0
# Minimum sample count
MIN_SAMPLES = 10


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return float('nan')
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx)**2 for x in xs))
    dy = math.sqrt(sum((y - my)**2 for y in ys))
    if dx == 0 or dy == 0:
        return float('nan')
    return num / (dx * dy)


def interp(series, t_query):
    """Linear interpolation of (t, val) series at t_query."""
    if not series or t_query <= series[0][0]:
        return series[0][1] if series else 0.0
    if t_query >= series[-1][0]:
        return series[-1][1]
    lo, hi = 0, len(series) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= t_query:
            lo = mid
        else:
            hi = mid
    t0, v0 = series[lo]
    t1, v1 = series[hi]
    return v0 + (v1 - v0) * (t_query - t0) / (t1 - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--min-r", type=float, default=0.7,
                    help="Minimum |r| to report (default 0.7)")
    ap.add_argument("--min-unique", type=int, default=MIN_UNIQUE)
    args = ap.parse_args()

    log_path = Path(args.log)
    print("Log: {}".format(log_path.name))
    print("Reference: 0x{:03X} B{}  (battery system temperature)".format(REF_ID, REF_BYTE))
    print()

    # --- Pass 1: collect statistics only (memory-efficient) ---
    # For each (bus, id, byte): track change count, unique values (capped), sample
    # count, first/last time, first/last value. Never store full timeseries here.
    # Also collect the reference timeseries in this pass.

    class ByteStat:
        __slots__ = ('changes', 'last_val', 'uniq', 'n', 't_first', 't_last',
                     'first_val', 'last_val_store')
        def __init__(self):
            self.changes = 0
            self.last_val = None
            self.uniq = set()
            self.n = 0
            self.t_first = None
            self.t_last = None
            self.first_val = None
            self.last_val_store = None

    stats = {}    # (bus, id, byte) -> ByteStat
    bus_ids = {}
    ref_series = []
    ref_bus = None

    print("Pass 1: collecting statistics...")
    for frame in parse_file(log_path):
        bus = frame.bus
        aid = frame.arbitration_id
        bus_ids.setdefault(bus, set()).add(aid)
        data = frame.data
        t = frame.timestamp

        # Capture reference signal
        if aid == REF_ID and len(data) > REF_BYTE:
            ref_series.append((t, data[REF_BYTE]))
            ref_bus = bus

        for b in range(len(data)):
            val = data[b]
            key = (bus, aid, b)
            if key not in stats:
                s = ByteStat()
                s.t_first = t
                s.first_val = val
                stats[key] = s
            else:
                s = stats[key]
            if s.last_val is not None and val != s.last_val:
                s.changes += 1
            s.last_val = val
            s.last_val_store = val
            s.t_last = t
            s.n += 1
            if len(s.uniq) <= 25:   # cap set size
                s.uniq.add(val)

    # Identify PT bus
    pt_bus = next((b for b, ids in bus_ids.items() if ANCHOR_ID in ids), None)
    if pt_bus is None:
        print("ERROR: PT bus not found")
        sys.exit(1)
    print("PT bus = {}".format(pt_bus))

    if not ref_series:
        print("ERROR: Reference 0x{:03X} not found".format(REF_ID))
        sys.exit(1)

    print("Reference 0x{:03X} B{} on bus {}: {} samples, range {}-{}".format(
        REF_ID, REF_BYTE, ref_bus,
        len(ref_series),
        min(v for _, v in ref_series),
        max(v for _, v in ref_series)))

    # --- Filter candidates from statistics ---
    candidates = set()
    for (bus, can_id, b), s in stats.items():
        if can_id == REF_ID:
            continue
        if s.n < MIN_SAMPLES:
            continue
        t_span = (s.t_last or 0) - (s.t_first or 0)
        if t_span < 10:
            continue
        uniq = len(s.uniq)
        if uniq < args.min_unique:
            continue
        rate = s.changes / max(t_span, 1)
        if rate > MAX_RATE_PER_SEC:
            continue
        candidates.add((bus, can_id, b))

    print("Pass 1 done. {} unique (ID, byte) candidates pass slow-vary filter.".format(
        len(candidates)))

    # --- Pass 2: collect full timeseries for candidates only ---
    # Store as sparse change-only series (value, time) to save memory
    cand_series = {k: [] for k in candidates}  # (bus, id, byte) -> [(t, val), ...]
    last_cand_val = {}

    print("Pass 2: collecting candidate timeseries...")
    for frame in parse_file(log_path):
        bus = frame.bus
        aid = frame.arbitration_id
        data = frame.data
        t = frame.timestamp
        for b in range(len(data)):
            key = (bus, aid, b)
            if key in cand_series:
                val = data[b]
                prev = last_cand_val.get(key)
                if prev is None or val != prev:
                    cand_series[key].append((t, val))
                    last_cand_val[key] = val

    # --- Correlate each candidate against reference ---
    results = []

    for key, series in cand_series.items():
        bus, can_id, b = key
        if len(series) < 3:
            continue

        # Expand sparse series to per-sample values at all ref times
        # Only evaluate at times within the candidate's own span
        t_first = series[0][0]
        t_last = series[-1][0]
        t_span = t_last - t_first

        # Resample reference at candidate's sample times (using sparse expansion)
        # For sparse series: build (t, val) expanded by forward-fill
        # and sample at regular ref times within span
        ref_in_span = [(t, v) for t, v in ref_series if t_first <= t <= t_last]
        if len(ref_in_span) < 3:
            continue

        # Forward-fill candidate series at each ref sample time
        bvals = []
        ref_at = []
        cand_idx = 0
        cur_cand_val = series[0][1]

        for t_ref, v_ref in ref_in_span:
            # Advance candidate to latest value at or before t_ref
            while cand_idx + 1 < len(series) and series[cand_idx + 1][0] <= t_ref:
                cand_idx += 1
                cur_cand_val = series[cand_idx][1]
            bvals.append(cur_cand_val)
            ref_at.append(v_ref)

        if len(bvals) < 5:
            continue

        r = pearson_r(ref_at, bvals)
        if math.isnan(r) or abs(r) < args.min_r:
            continue

        uniq_vals = sorted(set(bvals))
        vmin, vmax = uniq_vals[0], uniq_vals[-1]
        mono_rises = sum(1 for a, bv in zip(bvals, bvals[1:]) if bv > a)
        mono_drops = sum(1 for a, bv in zip(bvals, bvals[1:]) if bv < a)
        mono = mono_rises / max(mono_rises + mono_drops, 1)
        rate = stats[key].changes / max(t_span, 1)

        results.append(dict(
            bus=bus, id=can_id, byte=b, r=r,
            unique=len(uniq_vals), vmin=vmin, vmax=vmax,
            rng=vmax - vmin, n=len(bvals),
            mono=mono, first=bvals[0], last=bvals[-1],
            rate=rate,
        ))

    results.sort(key=lambda x: -abs(x['r']))

    # --- Print results ---
    print("=== Bytes correlating with 0x{:03X} B{} (|r| >= {:.2f}) ===".format(
        REF_ID, REF_BYTE, args.min_r))
    hdr = "{:<12} {:>4} {:>3} {:>6} {:>6} {:>5} {:>5} {:>5} {:>6} {:>5} {:>7}"
    print(hdr.format("ID", "B", "bus", "r", "n", "uniq", "rng", "min", "first",
                     "last", "mono%"))
    print("-" * 80)

    for res in results:
        r_str = "{:+.3f}".format(res['r'])
        # Skip the reference ID itself
        id_hex = "0x{:03X}".format(res['id']) if res['id'] < 0x800 else \
                 "0x{:08X}".format(res['id'])
        print(hdr.format(
            id_hex, res['byte'], res['bus'], r_str, res['n'],
            res['unique'], res['rng'], res['vmin'],
            res['first'], res['last'],
            "{:.0f}%".format(res['mono']*100),
        ))

    if not results:
        print("  (none -- try lowering --min-r)")
        print()
        print("Top 20 by |r| from all slow-vary candidates:")
        all_r = []
        for key, series in cand_series.items():
            bus, can_id, b = key
            if can_id == REF_ID or len(series) < 3:
                continue
            t_first = series[0][0]
            t_last  = series[-1][0]
            ref_in_span = [(t, v) for t, v in ref_series if t_first <= t <= t_last]
            if len(ref_in_span) < 3:
                continue
            bvals, ref_at, ci, cur = [], [], 0, series[0][1]
            for t_ref, v_ref in ref_in_span:
                while ci + 1 < len(series) and series[ci+1][0] <= t_ref:
                    ci += 1; cur = series[ci][1]
                bvals.append(cur); ref_at.append(v_ref)
            r = pearson_r(ref_at, bvals)
            if not math.isnan(r):
                all_r.append((abs(r), r, bus, can_id, b, len(bvals)))
        all_r.sort(reverse=True)
        for abs_r, r, bus, cid, b, n in all_r[:20]:
            print("  r={:+.3f}  bus={}  0x{:03X} B{}  n={}".format(r, bus, cid, b, n))

    print()
    print("Notes:")
    print("  Positive r: signal rises as battery temp rises (co-heating)")
    print("  Negative r: signal falls as battery temp rises (limit/headroom/SoC)")
    print("  rate filter: bytes with >5 changes/sec excluded (not slowly-varying)")


if __name__ == "__main__":
    main()
