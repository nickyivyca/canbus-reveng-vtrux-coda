"""
Correlate 0x06000002 B0-B4 against known reference signals:
  - 0x5A2 B2-B3: motor RPM (LE uint16, centered 32768)
  - 0x5A2 B4-B5: motor torque feedback (LE uint16, centered 32768)
  - 0x592 B2-B3: throttle (LE uint16, 0=off)
  - 0x598 B4-B5: drivetrain current (LE uint16, centered 32768)

Also test 16-bit candidate interpretations of B0/B1/B2/B4.
"""
import sys, os, math, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                   'vtruxdrivetrainoverheattest.log')

def interp(ts_ref, vals_ref, ts_query):
    """Linear interpolation of vals_ref@ts_ref to ts_query timestamps."""
    result = []
    j = 0
    n = len(ts_ref)
    for t in ts_query:
        while j < n-1 and ts_ref[j+1] < t:
            j += 1
        if j >= n-1:
            result.append(vals_ref[-1])
        elif j == 0:
            result.append(vals_ref[0])
        else:
            frac = (t - ts_ref[j]) / max(1e-9, ts_ref[j+1] - ts_ref[j])
            result.append(vals_ref[j] * (1-frac) + vals_ref[j+1] * frac)
    return result

def pearson(x, y):
    n = len(x)
    mx = sum(x)/n; my = sum(y)/n
    sx = math.sqrt(sum((v-mx)**2 for v in x)/n)
    sy = math.sqrt(sum((v-my)**2 for v in y)/n)
    if sx < 1e-9 or sy < 1e-9:
        return float('nan')
    cov = sum((x[i]-mx)*(y[i]-my) for i in range(n))/n
    return cov/(sx*sy)

def main():
    print("Loading log (this takes a while)...")
    all_frames = list(parse_file(LOG))
    print(f"Total frames: {len(all_frames)}")

    # Filter by bus 3
    bus3 = [f for f in all_frames if f.bus == 3]
    print(f"Bus 3 frames: {len(bus3)}")

    # Extract reference signals
    frames_5A2 = [f for f in bus3 if f.arbitration_id == 0x5A2]
    frames_592 = [f for f in bus3 if f.arbitration_id == 0x592]
    frames_598 = [f for f in bus3 if f.arbitration_id == 0x598]
    frames_target = [f for f in bus3 if f.arbitration_id == 0x06000002]

    print(f"0x5A2 frames: {len(frames_5A2)}")
    print(f"0x592 frames: {len(frames_592)}")
    print(f"0x598 frames: {len(frames_598)}")
    print(f"0x06000002 frames: {len(frames_target)}")

    # Build reference timeseries
    ts_5A2 = [f.timestamp for f in frames_5A2]
    rpm_vals = [(f.data[2]|(f.data[3]<<8)) - 32768 for f in frames_5A2]   # motor RPM signed
    torque_vals = [(f.data[4]|(f.data[5]<<8)) - 32768 for f in frames_5A2] # torque signed

    ts_592 = [f.timestamp for f in frames_592]
    throttle_vals = [f.data[2]|(f.data[3]<<8) for f in frames_592]  # 0=off

    ts_598 = [f.timestamp for f in frames_598]
    dcurr_vals = [(f.data[4]|(f.data[5]<<8)) - 32768 for f in frames_598]  # drivetrain current

    # Target timestamps
    ts_t = [f.timestamp for f in frames_target]

    # Interpolate references to target timestamps
    rpm_i = interp(ts_5A2, rpm_vals, ts_t)
    torque_i = interp(ts_5A2, torque_vals, ts_t)
    throttle_i = interp(ts_592, throttle_vals, ts_t)
    dcurr_i = interp(ts_598, dcurr_vals, ts_t)

    refs = {
        'motor_RPM': rpm_i,
        'motor_torque': torque_i,
        'throttle': throttle_i,
        'drivetrain_I': dcurr_i,
        'abs_torque': [abs(v) for v in torque_i],
        'abs_RPM': [abs(v) for v in rpm_i],
    }

    # Build candidate signals from target bytes
    candidates = {}
    for bi in range(8):
        candidates[f'B{bi}'] = [f.data[bi] for f in frames_target]

    # B0[7:2] (6-bit field)
    candidates['B0_6bit'] = [f.data[0] >> 2 for f in frames_target]
    # B4[7:1] (7-bit field)
    candidates['B4_7bit'] = [f.data[4] >> 1 for f in frames_target]
    # B1[7:6] (2-bit sub-count)
    candidates['B1_hi2'] = [f.data[1] >> 6 for f in frames_target]
    # B1 low 6 bits
    candidates['B1_lo6'] = [f.data[1] & 0x3F for f in frames_target]

    # 16-bit pairs (LE)
    for lo, hi in [(0,1),(1,2),(2,3),(3,4)]:
        v = [(f.data[lo]|(f.data[hi]<<8)) for f in frames_target]
        candidates[f'B{lo}B{hi}_LE16'] = v
        candidates[f'B{lo}B{hi}_LE16_c'] = [x - 32768 for x in v]  # centered

    # BE 16-bit pairs
    for hi2, lo2 in [(0,1),(1,2),(2,3)]:
        v = [(f.data[lo2]|(f.data[hi2]<<8)) for f in frames_target]
        candidates[f'B{hi2}B{lo2}_BE16_c'] = [x - 32768 for x in v]

    # B3B4 centered
    v = [(f.data[3]|(f.data[4]<<8)) - 32768 for f in frames_target]
    candidates['B3B4_LE16_c'] = v

    print("\n--- Pearson r matrix: candidates vs reference signals ---")
    print(f"{'Candidate':<20}", end="")
    for ref_name in refs:
        print(f"{ref_name:>14}", end="")
    print()
    print("-" * 120)

    # Sort by max abs r across references
    scored = []
    for cname, cvals in candidates.items():
        scores = {}
        for rname, rvals in refs.items():
            r = pearson(cvals, rvals)
            scores[rname] = r
        max_r = max(abs(v) for v in scores.values() if not math.isnan(v))
        scored.append((cname, scores, max_r))

    scored.sort(key=lambda x: -x[2])

    for cname, scores, max_r in scored:
        print(f"{cname:<20}", end="")
        for rname in refs:
            r = scores[rname]
            if math.isnan(r):
                print(f"{'N/A':>14}", end="")
            else:
                print(f"{r:>14.4f}", end="")
        print()

    # Windowed correlation (t=1600-1953 = heavy load run-up to cutback)
    print("\n--- Windowed Pearson r (t=1600-1953s, heavy load window) ---")
    mask = [i for i, f in enumerate(frames_target) if 1600 <= f.timestamp <= 1953]
    ts_w = [frames_target[i].timestamp for i in mask]
    rpm_w = interp(ts_5A2, rpm_vals, ts_w)
    torque_w = interp(ts_5A2, torque_vals, ts_w)
    dcurr_w = interp(ts_598, dcurr_vals, ts_w)
    throttle_w = interp(ts_592, throttle_vals, ts_w)
    refs_w = {'motor_RPM': rpm_w, 'motor_torque': torque_w,
              'abs_torque': [abs(v) for v in torque_w],
              'drivetrain_I': dcurr_w, 'throttle': throttle_w}

    print(f"Window size: {len(mask)} frames")
    scored_w = []
    for cname, cvals_full in candidates.items():
        cvals_w = [cvals_full[i] for i in mask]
        scores = {}
        for rname, rvals in refs_w.items():
            r = pearson(cvals_w, rvals)
            scores[rname] = r
        max_r = max(abs(v) for v in scores.values() if not math.isnan(v))
        scored_w.append((cname, scores, max_r))
    scored_w.sort(key=lambda x: -x[2])

    print(f"{'Candidate':<20}", end="")
    for ref_name in refs_w:
        print(f"{ref_name:>14}", end="")
    print()
    print("-" * 90)
    for cname, scores, max_r in scored_w[:20]:
        print(f"{cname:<20}", end="")
        for rname in refs_w:
            r = scores[rname]
            if math.isnan(r):
                print(f"{'N/A':>14}", end="")
            else:
                print(f"{r:>14.4f}", end="")
        print()

    # Delta correlation (frame-to-frame differences vs delta references)
    print("\n--- Delta (frame-to-frame) correlation in heavy load window ---")
    d_b4 = [candidates['B4'][mask[i]] - candidates['B4'][mask[i-1]]
            for i in range(1, len(mask))]
    d_b0 = [candidates['B0'][mask[i]] - candidates['B0'][mask[i-1]]
            for i in range(1, len(mask))]
    d_torque = [torque_w[i] - torque_w[i-1] for i in range(1, len(torque_w))]
    d_rpm = [rpm_w[i] - rpm_w[i-1] for i in range(1, len(rpm_w))]
    print(f"  r(delta_B4, delta_torque)={pearson(d_b4, d_torque):.4f}")
    print(f"  r(delta_B4, delta_RPM)={pearson(d_b4, d_rpm):.4f}")
    print(f"  r(delta_B0, delta_torque)={pearson(d_b0, d_torque):.4f}")
    print(f"  r(delta_B0, delta_RPM)={pearson(d_b0, d_rpm):.4f}")

    print("\nDone.")

if __name__ == '__main__':
    main()
