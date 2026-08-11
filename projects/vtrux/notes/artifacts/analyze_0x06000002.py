"""
Analyze 0x06000002 B0-B4 and B7 in the drivetrain overheat test log.
Key event timestamps:
  t~393s:  pump unplugged
  t~1953s: torque cutback onset
  t~2253s: pump reconnected

B5/B6 already confirmed: 10-bit LE at startbit 46, (B6<<2)|(B5>>6), scale 2.0 C/count.
Goal: characterize B0-B4 and B7.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
import collections

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                   'vtruxdrivetrainoverheattest.log')

def main():
    print("Loading log...")
    frames = [f for f in parse_file(LOG)
              if f.bus == 3 and f.arbitration_id == 0x06000002]
    print(f"Total 0x06000002 frames on bus 3: {len(frames)}")
    if not frames:
        print("No frames found!")
        return

    print(f"\nFirst frame: t={frames[0].timestamp:.3f}s  data={frames[0].data.hex()}")
    print(f"Last  frame: t={frames[-1].timestamp:.3f}s  data={frames[-1].data.hex()}")
    print(f"Duration: {frames[-1].timestamp - frames[0].timestamp:.1f}s")
    print(f"Rate: {len(frames) / (frames[-1].timestamp - frames[0].timestamp):.1f} Hz")

    # --- Unique value counts per byte ---
    print("\n--- Unique values per byte ---")
    by_byte = [[] for _ in range(8)]
    for f in frames:
        for i, b in enumerate(f.data):
            by_byte[i].append(b)
    for i, vals in enumerate(by_byte):
        uvals = sorted(set(vals))
        print(f"  B{i}: {len(uvals)} unique, min={min(uvals)}, max={max(uvals)}, "
              f"range={max(uvals)-min(uvals)}")
        if len(uvals) <= 20:
            print(f"       values: {uvals}")

    # --- Sample at key timestamps ---
    KEY_TIMES = [50, 200, 390, 400, 700, 1000, 1400, 1900, 1953, 1970, 2000,
                 2100, 2253, 2270, 2400, 2500, 2600, 2637]
    print("\n--- Samples at key timestamps ---")
    print(f"{'t_key':>7} {'actual':>8}  {'hex':18}  {'B0':>4} {'B1':>4} {'B2':>4} {'B3':>4} {'B4':>4}  "
          f"{'B5bin':>10}  {'B6':>4} {'B7':>4}  {'temp_C':>7}")
    for t_key in KEY_TIMES:
        f = min(frames, key=lambda x: abs(x.timestamp - t_key))
        d = f.data
        b56_raw = (d[6] << 2) | (d[5] >> 6)
        print(f"{t_key:>7} {f.timestamp:>8.1f}  {d.hex():18}  "
              f"{d[0]:>4} {d[1]:>4} {d[2]:>4} {d[3]:>4} {d[4]:>4}  "
              f"{d[5]:08b}  {d[6]:>4} {d[7]:>4}  {b56_raw*2.0:>7.1f}C")

    # --- Delta analysis (frame-to-frame changes) ---
    print("\n--- Frame-to-frame delta stats per byte ---")
    deltas = [[] for _ in range(8)]
    for i in range(1, len(frames)):
        for b_idx in range(8):
            delta = frames[i].data[b_idx] - frames[i-1].data[b_idx]
            deltas[b_idx].append(delta)
    for b_idx in range(8):
        d_set = sorted(set(deltas[b_idx]))
        nonzero = [d for d in deltas[b_idx] if d != 0]
        print(f"  B{b_idx}: nonzero_changes={len(nonzero)}, "
              f"delta_values={d_set[:20]}{'...' if len(d_set) > 20 else ''}")

    # --- B0 detailed inspection: bit decomposition ---
    print("\n--- B0 bit decomposition ---")
    b0_vals = sorted(set(f.data[0] for f in frames))
    print(f"  B0 unique values ({len(b0_vals)}): {b0_vals}")
    for v in b0_vals[:30]:
        print(f"  B0=0x{v:02X} ({v:3d}) = {v:08b}")

    # --- B1 detailed inspection ---
    print("\n--- B1 values ---")
    b1_vals = sorted(set(f.data[1] for f in frames))
    print(f"  B1 unique values ({len(b1_vals)}): {b1_vals[:30]}")

    # --- B2, B3, B4 ---
    for bi in [2, 3, 4]:
        vals = sorted(set(f.data[bi] for f in frames))
        print(f"\n--- B{bi} values ---")
        print(f"  B{bi} unique values ({len(vals)}): {vals[:40]}")

    # --- B7 ---
    print("\n--- B7 values ---")
    b7_vals = sorted(set(f.data[7] for f in frames))
    print(f"  B7 unique values ({len(b7_vals)}): {b7_vals}")

    # --- Correlate B0-B4, B7 against B56 temp ---
    print("\n--- Pearson r of B0-B4, B7 vs B5/B6 motor temp ---")
    import math
    temp_raw = [(f.data[6] << 2) | (f.data[5] >> 6) for f in frames]
    mean_t = sum(temp_raw) / len(temp_raw)
    std_t = math.sqrt(sum((x - mean_t)**2 for x in temp_raw) / len(temp_raw))
    for bi in [0, 1, 2, 3, 4, 7]:
        vals = [f.data[bi] for f in frames]
        mean_v = sum(vals) / len(vals)
        std_v = math.sqrt(sum((x - mean_v)**2 for x in vals) / max(1, len(vals)))
        if std_v < 1e-9:
            print(f"  B{bi} vs temp: constant, r=N/A")
            continue
        cov = sum((vals[i] - mean_v) * (temp_raw[i] - mean_t)
                  for i in range(len(frames))) / len(frames)
        r = cov / (std_v * std_t)
        print(f"  B{bi} vs temp: r={r:.4f}  (range {min(vals)}-{max(vals)}, std={std_v:.2f})")

    # --- Check for rolling counters (regular sequential steps) ---
    print("\n--- Rolling counter check (B0-B4, B7) ---")
    for bi in [0, 1, 2, 3, 4, 7]:
        deltas_bi = [frames[i].data[bi] - frames[i-1].data[bi]
                     for i in range(1, len(frames))]
        # Modular: treat as 8-bit
        deltas_mod = [(d % 256) if d < 0 else d for d in deltas_bi]
        cnt = collections.Counter(deltas_mod)
        top3 = cnt.most_common(3)
        print(f"  B{bi} delta dist (top 3): {top3}  (total changes: {sum(1 for d in deltas_bi if d != 0)})")

    # --- Check LE16 pairs (B0B1, B1B2, B2B3, B3B4) vs temp ---
    print("\n--- LE uint16 pairs vs temp ---")
    for lo, hi in [(0,1),(1,2),(2,3),(3,4)]:
        pair_vals = [(f.data[lo] | (f.data[hi] << 8)) for f in frames]
        mean_p = sum(pair_vals) / len(pair_vals)
        std_p = math.sqrt(sum((x-mean_p)**2 for x in pair_vals)/len(pair_vals))
        if std_p < 1e-9:
            print(f"  B{lo}B{hi} LE16: constant={pair_vals[0]}")
            continue
        cov = sum((pair_vals[i]-mean_p)*(temp_raw[i]-mean_t) for i in range(len(frames)))/len(frames)
        r = cov/(std_p*std_t) if std_p > 0 and std_t > 0 else 0
        print(f"  B{lo}B{hi} LE16: r={r:.4f} vs temp, range={min(pair_vals)}-{max(pair_vals)}, mean={mean_p:.1f}")

    # --- Extract timeseries for B0-B4, B7 around event windows ---
    print("\n--- Timeseries at pump-unplug window (t=380-420s) ---")
    window = [f for f in frames if 380 <= f.timestamp <= 420]
    if window:
        print(f"{'t':>8}  {'hex':18}  B0   B1   B2   B3   B4   B7  temp_C")
        for f in window[::5]:  # every 5th frame
            d = f.data
            b56 = (d[6]<<2)|(d[5]>>6)
            print(f"{f.timestamp:8.2f}  {d.hex():18}  {d[0]:3d}  {d[1]:3d}  {d[2]:3d}  "
                  f"{d[3]:3d}  {d[4]:3d}  {d[7]:3d}  {b56*2.0:.1f}C")

    print("\n--- Timeseries at cutback window (t=1940-1970s) ---")
    window = [f for f in frames if 1940 <= f.timestamp <= 1970]
    if window:
        print(f"{'t':>8}  {'hex':18}  B0   B1   B2   B3   B4   B7  temp_C")
        for f in window:
            d = f.data
            b56 = (d[6]<<2)|(d[5]>>6)
            print(f"{f.timestamp:8.2f}  {d.hex():18}  {d[0]:3d}  {d[1]:3d}  {d[2]:3d}  "
                  f"{d[3]:3d}  {d[4]:3d}  {d[7]:3d}  {b56*2.0:.1f}C")

    print("\n--- Timeseries at pump-reconnect window (t=2245-2270s) ---")
    window = [f for f in frames if 2245 <= f.timestamp <= 2270]
    if window:
        print(f"{'t':>8}  {'hex':18}  B0   B1   B2   B3   B4   B7  temp_C")
        for f in window:
            d = f.data
            b56 = (d[6]<<2)|(d[5]>>6)
            print(f"{f.timestamp:8.2f}  {d.hex():18}  {d[0]:3d}  {d[1]:3d}  {d[2]:3d}  "
                  f"{d[3]:3d}  {d[4]:3d}  {d[7]:3d}  {b56*2.0:.1f}C")

    print("\nDone.")

if __name__ == '__main__':
    main()
