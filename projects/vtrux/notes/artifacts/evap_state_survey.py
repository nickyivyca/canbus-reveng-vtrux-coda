"""
Wide survey of 0x649 evap state across all vtrux drive logs.
For each log: captures first/last 0x649 frame (B0, B4, B5, ec),
whether generator ran (0x600 bit4 or 0x63C B6>6), and any B0 transitions.
Skips logs with no 0x649 frames.
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOGS_DIR = Path(r"projects\vtrux\logs")

TARGET_IDS = {0x649, 0x600, 0x63C}

def ec(d):
    b2, b3 = d[2], d[3]
    if b2 is None or b3 is None:
        return None
    return ((b2 & 0x0F) << 8) | b3

def survey_log(log_path):
    first_649 = last_649 = None
    b0_values = set()
    gen_ran = False
    evap_completed = False
    n_frames = 0
    prev_b0 = None

    try:
        for f in parse_file(str(log_path)):
            n_frames += 1
            data = list(f.data) + [None] * (8 - len(f.data))
            arb = f.arbitration_id

            if arb == 0x649:
                if first_649 is None:
                    first_649 = (f.timestamp, data[:8])
                last_649 = (f.timestamp, data[:8])
                b0 = data[0]
                if b0 is not None:
                    b0_values.add(b0)
                    if prev_b0 is not None and (prev_b0 >> 7) & 1 and not ((b0 >> 7) & 1):
                        evap_completed = True
                    prev_b0 = b0

            elif arb == 0x600:
                b0 = data[0]
                if b0 is not None and (b0 >> 4) & 1:
                    gen_ran = True

            elif arb == 0x63C:
                b6 = data[6]
                if b6 is not None and b6 > 6:
                    gen_ran = True

    except Exception as e:
        return None, str(e)

    if first_649 is None:
        return None, "no 0x649"

    t0, d0 = first_649
    t1, d1 = last_649
    result = {
        "t_start": t0,
        "t_end": t1,
        "b0_start": d0[0],
        "b4_start": d0[4],
        "b5_start": d0[5],
        "ec_start": ec(d0),
        "b0_end": d1[0],
        "ec_end": ec(d1),
        "b0_values": sorted(b0_values),
        "gen_ran": gen_ran,
        "evap_completed": evap_completed,
        "n_frames": n_frames,
    }
    return result, None

logs = sorted(LOGS_DIR.glob("*.log"))
print(f"Surveying {len(logs)} logs...\n", flush=True)

print(f"{'log':<50}  {'B0_start':>8}  {'ec_start':>8}  {'ec_end':>7}  {'gen':>4}  {'cmp':>4}  {'B0_all'}")
print("-" * 120)

no_649 = []
errors = []

for log_path in logs:
    result, err = survey_log(log_path)
    if result is None:
        if err == "no 0x649":
            no_649.append(log_path.name)
        else:
            errors.append((log_path.name, err))
        continue

    evap_flag = "ON " if result["b0_start"] is not None and (result["b0_start"] >> 7) & 1 else "off"
    b0_all = " ".join(f"{v:#04x}" for v in result["b0_values"])
    cmp = "YES" if result["evap_completed"] else "---"
    gen = "YES" if result["gen_ran"] else "---"
    b0s = f"{result['b0_start']:#04x}" if result["b0_start"] is not None else "None"
    ecs = f"{result['ec_start']:#05x}" if result["ec_start"] is not None else " None"
    ece = f"{result['ec_end']:#05x}" if result["ec_end"] is not None else " None"
    name = log_path.name[:50]
    print(f"{name:<50}  {b0s:>8}  {ecs:>8}  {ece:>7}  {gen:>4}  {cmp:>4}  {b0_all}")
    sys.stdout.flush()

print(f"\n{len(no_649)} logs with no 0x649 frames (likely charge-only or short test logs):")
for n in no_649:
    print(f"  {n}")

if errors:
    print(f"\n{len(errors)} errors:")
    for n, e in errors:
        print(f"  {n}: {e}")

print("\nDone.")
