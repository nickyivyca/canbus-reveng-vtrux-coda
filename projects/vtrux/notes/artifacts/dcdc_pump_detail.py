"""
Phase 2 detail: inspect the 3 non-D6 DCDC IDs and plot fine-resolution
timeseries for B2-B3 LE (LV current candidate) in 0x18FFD6B3.
Goal: find the pump plug-in step change timestamp in B2-B3 and see if any
other DCDC message or byte also steps at that same time.
"""

import sys, os, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers.autodetect import parse_file as parse_log

LOG = "projects/vtrux/logs/vtrux_partstruck_pumpplugin.log"

print("Loading log...")
frames = list(parse_log(LOG))
total_t = [f.timestamp for f in frames]
t_start = min(total_t)
t_end = max(total_t)
print(f"  {len(frames)} frames, t=[{t_start:.1f}, {t_end:.1f}] s  (span={t_end-t_start:.1f} s)")

TARGET_IDS = {
    0x18E8FFB3: "DCDC_Request",
    0x18FECAB3: "DCDC_FECAB3",
    0x18FFD4B3: "DCDC_FFD4B3",
    0x18FFD6B3: "DCDC_Feedback",
}

print("\n--- Raw byte samples from each DCDC ID ---")
for id_, name in TARGET_IDS.items():
    id_frames = [f for f in frames if f.arbitration_id == id_]
    if not id_frames:
        print(f"  {name} (0x{id_:08X}): NO FRAMES")
        continue
    print(f"\n  {name} (0x{id_:08X})  {len(id_frames)} frames")
    n_bytes = min(max(f.dlc for f in id_frames), 8)
    print(f"  DLC={n_bytes}")

    sample_times = [t_start + (t_end-t_start)*frac for frac in [0.05, 0.25, 0.5, 0.75, 0.95]]
    for st in sample_times:
        closest = min(id_frames, key=lambda f: abs(f.timestamp - st))
        raw = " ".join(f"{b:02X}" for b in closest.data)
        print(f"    t={closest.timestamp:8.1f}s  [{raw}]")

    print(f"  Unique byte patterns (B0): {len(set(fr.data[0] for fr in id_frames if len(fr.data)>=1))}")
    for bi in range(n_bytes):
        bvals = [f.data[bi] for f in id_frames if len(f.data) > bi]
        if not bvals:
            continue
        uniq = len(set(bvals))
        bmin, bmax = min(bvals), max(bvals)
        print(f"    B{bi}: range=[{bmin},{bmax}]  unique={uniq}")

print("\n\n--- Fine-resolution timeseries for 0x18FFD6B3 all bytes ---")
d6_frames = [f for f in frames if f.arbitration_id == 0x18FFD6B3]
d6_frames.sort(key=lambda f: f.timestamp)
print(f"  {len(d6_frames)} frames  t=[{d6_frames[0].timestamp:.1f}, {d6_frames[-1].timestamp:.1f}] s")

span = d6_frames[-1].timestamp - d6_frames[0].timestamp
N_BINS = 40
bin_size = span / N_BINS
t0 = d6_frames[0].timestamp

print(f"\n  {N_BINS}-bin timeseries (each bin ~{bin_size:.1f}s):")
print(f"  {'Bin':>3} {'t_mid':>7}  {'B0-1 LE':>7} {'B2-3 LE':>8} {'B4-5 LE':>8} {'B6-7 LE':>8}  notes")
print("  " + "-"*70)

prev_b23 = None
prev_b67 = None
for b in range(N_BINS):
    t_lo = t0 + b * bin_size
    t_hi = t0 + (b+1) * bin_size
    t_mid = (t_lo + t_hi) / 2
    bframes = [f for f in d6_frames if t_lo <= f.timestamp < t_hi]
    if not bframes:
        print(f"  {b:3d} {t_mid:7.1f}  (no frames)")
        continue
    data = [f.data for f in bframes if len(f.data) >= 8]
    if not data:
        continue
    b01 = [d[0] | (d[1]<<8) for d in data]
    b23 = [d[2] | (d[3]<<8) for d in data]
    b45 = [d[4] | (d[5]<<8) for d in data]
    b67 = [d[6] | (d[7]<<8) for d in data]
    m01 = round(statistics.median(b01))
    m23 = round(statistics.median(b23))
    m45 = round(statistics.median(b45))
    m67 = round(statistics.median(b67))
    notes = []
    if prev_b23 is not None and abs(m23 - prev_b23) > 150:
        notes.append(f"B2-3 STEP +{m23-prev_b23}" if m23 > prev_b23 else f"B2-3 STEP {m23-prev_b23}")
    if prev_b67 is not None and abs(m67 - prev_b67) > 3:
        notes.append(f"B6-7 step +{m67-prev_b67}" if m67 > prev_b67 else f"B6-7 step {m67-prev_b67}")
    note_str = "  <-- " + ", ".join(notes) if notes else ""
    print(f"  {b:3d} {t_mid:7.1f}  {m01:7} {m23:8} {m45:8} {m67:8}{note_str}")
    prev_b23 = m23
    prev_b67 = m67

print("\n\n--- Physical values for D6B3 (confirmed scale: x0.05 for V/A, x0.1 for temp signed) ---")
print("  Signed B6-B7 LE: values above 32767 are negative (two's complement 16-bit)")
print(f"  {'Bin':>3} {'t_mid':>7}  {'LV_V(V)':>8} {'LV_I(A)':>8} {'HV_V(V)':>8} {'Temp(C)':>8}")
print("  " + "-"*60)
for b in range(N_BINS):
    t_lo = t0 + b * bin_size
    t_hi = t0 + (b+1) * bin_size
    t_mid = (t_lo + t_hi) / 2
    bframes = [f for f in d6_frames if t_lo <= f.timestamp < t_hi]
    if not bframes:
        continue
    data = [f.data for f in bframes if len(f.data) >= 8]
    if not data:
        continue
    b01 = [d[0] | (d[1]<<8) for d in data]
    b23 = [d[2] | (d[3]<<8) for d in data]
    b45 = [d[4] | (d[5]<<8) for d in data]
    b67_raw = [d[6] | (d[7]<<8) for d in data]
    b67_signed = [v - 65536 if v > 32767 else v for v in b67_raw]
    lv_v = round(statistics.median(b01) * 0.05, 2)
    lv_i = round(statistics.median(b23) * 0.05, 2)
    hv_v = round(statistics.median(b45) * 0.05, 2)
    temp = round(statistics.median(b67_signed) * 0.1, 1)
    print(f"  {b:3d} {t_mid:7.1f}  {lv_v:8.2f} {lv_i:8.2f} {hv_v:8.2f} {temp:8.1f}")
