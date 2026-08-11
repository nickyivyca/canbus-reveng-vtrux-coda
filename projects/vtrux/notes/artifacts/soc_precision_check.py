"""
soc_precision_check.py
Check whether 0x411 B0:B1 high-res SoC encoding contains real precision
or just B0-driven correlation with noise in B1.

Formula under test: (B0*64 + (B1>>2)) / 100 = SoC%
Low-res reference:  0x410 B3 * 0.5 = SoC% (bcm_soc, EPRI confirmed)

Tests:
1. B1 lower 2 bits - if always 0, encoding is clean (no sub-resolution noise)
2. Unique B1>>2 values per B0 value - how many fine steps actually occur?
3. Monotonicity of fine value within constant-B0 windows
4. Correlation of fine part (B1>>2) with residual from B0-only estimate
5. Comparison of hi-res vs lo-res SoC over time
"""

import sys
import os
import collections

# ---- parse BUSMASTER log ----
def parse_busmaster(path):
    frames = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("***") or line.startswith("//"):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            try:
                # format: timestamp Rx/Tx channel 0xID frametype DLC data...
                arb_id = int(parts[3], 16)
                dlc = int(parts[5])
                data = [int(x, 16) for x in parts[6:6+dlc]]
                if len(data) < dlc:
                    continue
                channel = parts[2]
                frames.append((arb_id, channel, data))
            except (ValueError, IndexError):
                continue
    return frames

# ---- main ----
def run(log_path):
    print("Loading", log_path)
    frames = parse_busmaster(log_path)
    print(f"Total frames: {len(frames)}")

    frames_411 = [(ch, d) for aid, ch, d in frames if aid == 0x411 and len(d) >= 2]
    frames_410 = [(ch, d) for aid, ch, d in frames if aid == 0x410 and len(d) >= 4]
    print(f"0x411 frames: {len(frames_411)},  0x410 frames: {len(frames_410)}")
    if not frames_411:
        print("No 0x411 frames found.")
        return

    # ---- Test 1: B1 lower 2 bits distribution ----
    b1_low2 = collections.Counter()
    for ch, d in frames_411:
        b1_low2[d[1] & 0x03] += 1
    print("\n--- Test 1: B1 lower 2 bits (should be ~0 if encoding is clean) ---")
    total = sum(b1_low2.values())
    for val in sorted(b1_low2):
        print(f"  B1 & 3 = {val}: {b1_low2[val]} ({100*b1_low2[val]/total:.1f}%)")

    # ---- Test 2: unique fine values per B0 ----
    fine_by_b0 = collections.defaultdict(set)
    for ch, d in frames_411:
        b0, b1 = d[0], d[1]
        fine_by_b0[b0].add(b1 >> 2)
    fine_counts = sorted((len(v), k, sorted(v)) for k, v in fine_by_b0.items())
    print("\n--- Test 2: unique B1>>2 values per B0 (if >1, fine bits are varying) ---")
    multi = [(cnt, b0, vals) for cnt, b0, vals in fine_counts if cnt > 1]
    single = [b0 for cnt, b0, _ in fine_counts if cnt == 1]
    print(f"  B0 values with only 1 fine value: {len(single)}")
    print(f"  B0 values with multiple fine values: {len(multi)}")
    if multi:
        # show a sample
        print("  Sample (up to 10):")
        for cnt, b0, vals in multi[:10]:
            soc_b0_only = b0 * 64 / 100
            print(f"    B0={b0} ({soc_b0_only:.2f}%): fine values = {vals} -> SoC range {(b0*64+min(vals))/100:.2f}% to {(b0*64+max(vals))/100:.2f}%")

    # ---- Test 3: hi-res SoC range and step size ----
    hires = [(d[0]*64 + (d[1]>>2)) / 100.0 for ch, d in frames_411]
    lores = [d[3] * 0.5 for ch, d in frames_410] if frames_410 else []
    print("\n--- Test 3: hi-res SoC range ---")
    print(f"  Hi-res: min={min(hires):.2f}%, max={max(hires):.2f}%, unique values: {len(set(hires))}")
    if lores:
        print(f"  Lo-res: min={min(lores):.2f}%, max={max(lores):.2f}%, unique values: {len(set(lores))}")

    # step size between consecutive changes
    prev = hires[0]
    steps = []
    for v in hires[1:]:
        if v != prev:
            steps.append(abs(v - prev))
            prev = v
    if steps:
        step_counts = collections.Counter(round(s, 4) for s in steps)
        print("  Most common step sizes in hi-res SoC (top 10):")
        for step, cnt in step_counts.most_common(10):
            print(f"    {step:.4f}%: {cnt} times")

    # ---- Test 4: fine bits vs residual ----
    # residual = hires - b0_only (i.e., the contribution of B1>>2 / 100)
    # if fine bits are real, residual should vary between 0 and 0.63 in a meaningful way
    # if noise, residual should be random/uniform
    residuals = [(d[1]>>2) / 100.0 for ch, d in frames_411]
    unique_residuals = sorted(set(residuals))
    print("\n--- Test 4: unique residual values (B1>>2 / 100) ---")
    print(f"  Count: {len(unique_residuals)}")
    if unique_residuals:
        print(f"  Range: {min(unique_residuals):.4f} to {max(unique_residuals):.4f}")
        print(f"  Values: {unique_residuals[:20]}{'...' if len(unique_residuals)>20 else ''}")

    # ---- Test 5: monotonicity check ----
    # In a window where B0 stays constant, does B1>>2 move monotonically?
    print("\n--- Test 5: monotonicity within constant-B0 windows ---")
    windows = []
    cur_b0 = frames_411[0][1][0]
    cur_window = []
    for ch, d in frames_411:
        if d[0] == cur_b0:
            cur_window.append(d[1] >> 2)
        else:
            if len(cur_window) >= 10:
                windows.append((cur_b0, cur_window))
            cur_b0 = d[0]
            cur_window = [d[1] >> 2]
    if cur_window:
        windows.append((cur_b0, cur_window))

    mono_count = 0
    nonmono_count = 0
    for b0, seq in windows:
        if len(seq) < 5:
            continue
        # check if sequence is generally monotone (allow 1 reversal for noise)
        ups = sum(1 for i in range(1, len(seq)) if seq[i] > seq[i-1])
        downs = sum(1 for i in range(1, len(seq)) if seq[i] < seq[i-1])
        dominant = max(ups, downs)
        minority = min(ups, downs)
        if dominant == 0:
            continue  # flat
        ratio = minority / dominant
        soc_range = (b0*64+min(seq))/100
        if ratio < 0.1:
            mono_count += 1
        else:
            nonmono_count += 1
            if nonmono_count <= 5:
                print(f"  Non-monotone: B0={b0} ({b0*64/100:.2f}%), len={len(seq)}, ups={ups}, downs={downs}, seq_sample={seq[:20]}")
    print(f"  Monotone windows (ratio<10%): {mono_count}")
    print(f"  Non-monotone windows: {nonmono_count}")


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else r"projects\vtrux\logs\oghighwaydrive.log"
    run(log)
