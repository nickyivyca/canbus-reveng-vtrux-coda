"""
Find IDs that drop out (go silent for any meaningful window) during
vtrux_mysterybox_unplug.log.

Phase A (presence/gap scan):
  Per-(bus, id), build a sorted timestamp list. Flag IDs where:
    - max gap > max(1.0 s, 10 x median period)  AND  max gap > 2 s, OR
    - first_t > log_start + 5 s (appears late)
    - last_t  < log_end   - 5 s (silenced before end)

Phase B (multi-gap scan):
  For each ID with median period < 0.5 s, find ALL gaps > max(1 s, 10 x median).
  Useful for spotting disconnect-then-reconnect sequences.

Phase C (15s presence binning):
  Print a per-ID presence map across ten 13-second time bins so
  partial-coverage patterns are easy to read.
"""

import sys
sys.path.insert(0, ".")

from canre.parsers import parse_file
from collections import defaultdict
import statistics

LOG = sys.argv[1] if len(sys.argv) > 1 else "projects/vtrux/logs/vtrux_mysterybox_unplug.log"

PT_ANCHORS = {0x051}
VEH_ANCHORS = {0x1E5, 0x500, 0x514}
OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044}


def fmt_id(arb_id):
    if arb_id > 0x7FF:
        return f"0x{arb_id:08X}"
    return f"0x{arb_id:03X}"


def main():
    print(f"Parsing {LOG} ...")
    frames = list(parse_file(LOG))
    print(f"Total frames: {len(frames)}")
    if not frames:
        return

    t0 = frames[0].timestamp
    t1 = frames[-1].timestamp
    duration = t1 - t0
    print(f"Log duration: {duration:.2f} s")
    print()

    by_key = defaultdict(list)
    for f in frames:
        by_key[(f.bus, f.arbitration_id)].append(f.timestamp)

    bus_anchor = {}
    for (bus, arb_id), ts in by_key.items():
        if arb_id in PT_ANCHORS:
            bus_anchor[bus] = "PT"
        elif arb_id in VEH_ANCHORS and bus_anchor.get(bus) is None:
            bus_anchor[bus] = "VEH"
        elif arb_id in OBD_ANCHORS and bus_anchor.get(bus) is None:
            bus_anchor[bus] = "OBD"
    print("Bus identification:")
    for bus in sorted(set(b for b, _ in by_key.keys())):
        label = bus_anchor.get(bus, "?")
        n_ids = sum(1 for (b, _) in by_key.keys() if b == bus)
        n_frames = sum(len(v) for (b, _), v in by_key.items() if b == bus)
        print(f"  bus {bus}: {label}  ({n_ids} unique IDs, {n_frames} frames)")
    print()

    rows = []
    for (bus, arb_id), ts in by_key.items():
        ts.sort()
        count = len(ts)
        first_t = ts[0] - t0
        last_t = ts[-1] - t0
        if count >= 2:
            deltas = [b - a for a, b in zip(ts, ts[1:])]
            median_p = statistics.median(deltas)
            max_gap = max(deltas)
            max_gap_idx = deltas.index(max_gap)
            max_gap_at = ts[max_gap_idx] - t0
        else:
            median_p = float("nan")
            max_gap = 0.0
            max_gap_at = float("nan")

        rows.append({
            "bus": bus,
            "bus_label": bus_anchor.get(bus, "?"),
            "id": arb_id,
            "ts": ts,
            "count": count,
            "median_p": median_p,
            "first_t": first_t,
            "last_t": last_t,
            "max_gap": max_gap,
            "max_gap_at": max_gap_at,
        })

    print("=== Phase A: real dropouts (excluding obvious startup-only artifacts) ===")
    print()
    real_drops = []
    for r in rows:
        first_t = r["first_t"]
        last_t = r["last_t"]
        median_p = r["median_p"]
        if r["count"] < 5:
            continue
        if median_p != median_p:
            continue
        late_appear = first_t > 5.0
        early_silence = last_t < duration - 5.0
        big_gap = r["max_gap"] > 2.0 and r["max_gap"] > 10 * median_p
        if late_appear or early_silence or big_gap:
            real_drops.append(r)

    real_drops.sort(key=lambda r: (r["bus"], r["id"]))
    print(f"{'BUS':<3} {'LBL':<4} {'ID':<11} {'COUNT':>7} {'PERIOD':>9} {'FIRST':>8} {'LAST':>8} {'MAXGAP':>9} {'GAP@':>9}")
    print("-" * 80)
    for r in real_drops:
        period = f"{r['median_p']*1000:.1f}ms"
        gap_at = f"{r['max_gap_at']:.1f}s" if r["max_gap_at"] == r["max_gap_at"] else "-"
        print(
            f"{r['bus']:<3} {r['bus_label']:<4} {fmt_id(r['id']):<11} "
            f"{r['count']:>7} {period:>9} {r['first_t']:>7.1f}s {r['last_t']:>7.1f}s "
            f"{r['max_gap']:>8.2f}s {gap_at:>9}"
        )
    if not real_drops:
        print("(none)")
    print()

    print("=== Phase B: multi-gap scan (IDs with multiple gaps > 10x median) ===")
    print()
    for r in rows:
        if r["count"] < 50:
            continue
        median_p = r["median_p"]
        if median_p != median_p or median_p > 0.5:
            continue
        ts = r["ts"]
        threshold = max(1.0, 10 * median_p)
        gaps = []
        for i in range(1, len(ts)):
            d = ts[i] - ts[i-1]
            if d > threshold:
                gaps.append((ts[i-1] - t0, d))
        if len(gaps) >= 2:
            print(f"  bus {r['bus']} ({r['bus_label']}) {fmt_id(r['id'])}  period={median_p*1000:.1f}ms  gaps:")
            for at, dur in gaps:
                print(f"    {dur:.2f}s gap starting at t={at:.1f}s")
    print()

    print("=== Phase C: presence map across 13-second bins ===")
    print()
    n_bins = 10
    bin_size = duration / n_bins
    print(f"Bin size: {bin_size:.1f}s; bin labels in seconds")
    header = f"{'BUS':<3} {'LBL':<4} {'ID':<11} "
    for i in range(n_bins):
        b_start = i * bin_size
        header += f"{int(b_start):>3}-{int(b_start+bin_size):<3} "
    print(header)
    print("-" * len(header))

    only_partial = []
    for r in rows:
        ts = r["ts"]
        present = []
        for i in range(n_bins):
            b_start = t0 + i * bin_size
            b_end = b_start + bin_size
            cnt = sum(1 for t in ts if b_start <= t < b_end)
            present.append(cnt)
        if 0 in present and any(p > 0 for p in present):
            only_partial.append((r, present))

    only_partial.sort(key=lambda x: (x[0]["bus"], x[0]["id"]))
    for r, present in only_partial:
        cells = " ".join(f"{c:>7}" if c > 0 else f"{'.':>7}" for c in present)
        print(f"{r['bus']:<3} {r['bus_label']:<4} {fmt_id(r['id']):<11} {cells}")

    print()
    print("=== Sample byte payloads of suspect dropouts (first/last frames) ===")
    suspect_ids = [(2, 0x475), (3, 0x446)]
    for bus, arb_id in suspect_ids:
        key = (bus, arb_id)
        if key not in by_key:
            continue
        matching = [f for f in frames if f.bus == bus and f.arbitration_id == arb_id]
        if not matching:
            continue
        print(f"  bus {bus} {fmt_id(arb_id)}: {len(matching)} frames")
        for f in matching[:3]:
            data_hex = " ".join(f"{b:02X}" for b in f.data)
            print(f"    t={f.timestamp - t0:>6.2f}s  dlc={len(f.data)}  data={data_hex}")
        print(f"    ...")
        for f in matching[-3:]:
            data_hex = " ".join(f"{b:02X}" for b in f.data)
            print(f"    t={f.timestamp - t0:>6.2f}s  dlc={len(f.data)}  data={data_hex}")


if __name__ == "__main__":
    main()
