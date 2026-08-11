"""Phase 8: does the 12V (LV) load step up at 20:37:04 when 0x508 engages?

If 0x508 = battery cooler/fan, its ~several-amp 12V load should show as a step in
DCDC_LV_Curr (0x18FFD6B3 B2-B3, x0.05 A) coincident with the 0x508 on/off edges.

Compares mean LV current in before/after windows at each 0x508 edge, and prints a
sampled LV-current trace across the whole session for context.
"""
import sys
sys.path.insert(0, ".")

import subprocess
from datetime import datetime, timedelta

import cantools

from battery_fan_signature import chunk_files, parse_header_time, decode_line, fmt

db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
MSG = db.get_message_by_frame_id(0x18FFD6B3)


def scan():
    rows = []  # (t, lv_curr, lv_volt)
    for path in chunk_files():
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x18FFD6B3 ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb != 0x18FFD6B3 or len(data) < 4:
                continue
            try:
                s = MSG.decode(data, decode_choices=False, allow_truncated=True)
            except Exception:
                continue
            rows.append((t, s.get("DCDC_LV_Curr"), s.get("DCDC_LV_Volt")))
    rows.sort(key=lambda x: x[0])
    return rows


def mean_window(rows, ts, te, key=1):
    vals = [r[key] for r in rows if ts <= r[0] < te and r[key] is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


if __name__ == "__main__":
    rows = scan()
    t0 = rows[0][0]
    print(f"0x18FFD6B3 frames: {len(rows)}")
    d = lambda h, m, s=0: datetime(2026, 7, 14, h, m, s)

    edges = [
        ("short-drive ON", d(17, 58, 20)),
        ("short-drive OFF", d(18, 27, 41)),
        ("EVENING-CHARGE ON", d(20, 37, 4)),
        ("charge-end OFF", d(21, 55, 53)),
        ("final-drive ON", d(21, 59, 14)),
        ("final-drive OFF", d(22, 45, 31)),
    ]
    print("\n=== LV (12V) current mean: 3-min BEFORE vs 3-min AFTER each 0x508 edge ===")
    for name, t in edges:
        before, nb = mean_window(rows, t - timedelta(minutes=3), t)
        after, na = mean_window(rows, t, t + timedelta(minutes=3))
        if before is None or after is None:
            print(f"  {name:20s} {t.strftime('%H:%M:%S')}: insufficient data")
            continue
        print(f"  {name:20s} {t.strftime('%H:%M:%S')}: "
              f"{before:5.1f}A (n={nb}) -> {after:5.1f}A (n={na})   "
              f"delta {after-before:+5.1f}A")

    print("\n=== LV current: charge baselines ===")
    for label, a, b in [
        ("4pm charge (16:20-17:10)", d(16, 20), d(17, 10)),
        ("evening charge PRE-0x508 (19:00-20:35)", d(19, 0), d(20, 35)),
        ("evening charge 0x508-ON (20:39-21:55)", d(20, 39), d(21, 55)),
    ]:
        m, n = mean_window(rows, a, b)
        mv, _ = mean_window(rows, a, b, key=2)
        print(f"  {label}: LV_curr={m:.1f}A  LV_volt={mv:.2f}V  (n={n})")

    print("\n=== sampled LV current trace ===")
    step = max(1, len(rows) // 45)
    for i in range(0, len(rows), step):
        t, c, v = rows[i]
        if c is None:
            continue
        print(f"  {fmt(t,t0)}  LV_curr={c:5.1f}A  LV_volt={v:5.2f}V")
