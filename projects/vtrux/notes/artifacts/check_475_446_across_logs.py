"""
Check whether PT 0x475 and OBD 0x446 always drop out at ~60s into a log,
or whether the dropout is specific to vtrux_mysterybox_unplug.log.

For each log: report first/last appearance, count, total log duration,
and a histogram of timestamps in 10s bins.
"""

import sys
sys.path.insert(0, ".")

from canre.parsers import parse_file
from collections import defaultdict
import os

LOGS = [
    "projects/vtrux/logs/vtrux_mysterybox_unplug.log",
    "projects/vtrux/logs/vtrux_mysterybox_unplug_export.log",
    "projects/vtrux/logs/generator-on-then-off.log",
    "projects/vtrux/logs/oghighwaydrive.log",
    "projects/vtrux/logs/exportpowerattempt.log",
    "projects/vtrux/logs/movingaroundindriveway.log",
    "projects/vtrux/logs/full-charge-then-fail.log",
    "projects/vtrux/logs/vtrux_app_disconnect_test.log",
]

TARGET_IDS = [0x475, 0x446]


def check_log(path):
    if not os.path.exists(path):
        print(f"[skip] {path} (not found)")
        return
    print(f"\n=== {os.path.basename(path)} ===")
    try:
        frames = list(parse_file(path))
    except Exception as e:
        print(f"  parse error: {e}")
        return
    if not frames:
        print("  empty")
        return
    t0 = frames[0].timestamp
    t1 = frames[-1].timestamp
    duration = t1 - t0
    print(f"  duration: {duration:.1f}s, total frames: {len(frames)}")

    by_key = defaultdict(list)
    payloads = defaultdict(set)
    for f in frames:
        if f.arbitration_id in TARGET_IDS:
            by_key[(f.bus, f.arbitration_id)].append(f.timestamp)
            payloads[(f.bus, f.arbitration_id)].add(bytes(f.data))

    if not by_key:
        print("  no 0x475 / 0x446 frames present")
        return

    for (bus, arb_id), ts in sorted(by_key.items()):
        first = ts[0] - t0
        last = ts[-1] - t0
        n = len(ts)
        unique_payloads = len(payloads[(bus, arb_id)])
        all_zero = unique_payloads == 1 and bytes(8) in payloads[(bus, arb_id)]
        zero_tag = "all-zero" if all_zero else f"{unique_payloads} distinct payloads"
        print(f"  bus {bus} 0x{arb_id:03X}: n={n}, first={first:.1f}s, last={last:.1f}s, span={last-first:.1f}s of {duration:.1f}s, {zero_tag}")
        n_bins = max(6, min(20, int(duration // 10) + 1))
        bin_size = duration / n_bins
        bins = [0] * n_bins
        for t in ts:
            idx = min(n_bins - 1, int((t - t0) / bin_size))
            bins[idx] += 1
        bar = "".join("#" if b > 0 else "." for b in bins)
        print(f"    bins (each={bin_size:.1f}s): {bar}")


def main():
    for path in LOGS:
        check_log(path)


if __name__ == "__main__":
    main()
