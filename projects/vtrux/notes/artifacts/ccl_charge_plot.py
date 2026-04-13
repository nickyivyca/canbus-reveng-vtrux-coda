"""
Phase 3: Check if 0x050 CCL signal is present in charge sessions and
drops to 0 as SoC goes above 80%.

Signal:  0x050  (B1 & 0x03) << 8 | B0  -- 10-bit DC bus input current limit (CCL)
         0x596  B6                       -- SoC 0-100%
Charger: 0x18FFD7C0  B2-B3 LE signed x0.05 A  -- charger DC output current

Runs on: 'after-battery-swap-charges' folder
Sessions:
  1. charge_M0_T0..T59  (Jan 16-17, ~5h)
  2. another_M0_T1..T55 (Jan 23,    ~9h)
"""

import os
import sys
import glob
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file as detect_and_parse


LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                                       'after-battery-swap-charges'))

SESSIONS = {
    'charge_M0': sorted(glob.glob(os.path.join(LOG_DIR, 'charge_M0_T*.log'))),
    'another_M0': sorted(glob.glob(os.path.join(LOG_DIR, 'another_M0_T*.log'))),
}

CHARGER_ID = 0x18FFD7C0

def decode_ccl(b0, b1):
    return ((b1 & 0x03) << 8) | b0

def decode_charger_current(b2, b3):
    raw = b2 | (b3 << 8)            # LE uint16
    if raw >= 32768:
        raw -= 65536                 # signed
    return raw * 0.05               # A

def process_session(name, files):
    print(f"\n{'='*60}")
    print(f"Session: {name}  ({len(files)} files)")
    print(f"{'='*60}")

    if not files:
        print("  No files found -- skipping")
        return

    # Quick scan: just the first and last few files + every Nth for trend
    # For full analysis we process all but down-sample output

    pt_bus = None    # will be identified from first file

    # Storage for full timeseries
    soc_series = []      # (t, soc)
    ccl_series = []      # (t, ccl)
    charger_series = []  # (t, I_charge_A)

    n_0x050_frames = 0
    n_0x596_frames = 0
    n_charger_frames = 0
    prev_soc = None
    soc80_crossed = False
    chunk_offset = 0.0   # cumulative time across chunks (BUSMASTER resets per chunk)

    for fpath in files:
        fname = os.path.basename(fpath)
        try:
            frames = list(detect_and_parse(fpath))
        except Exception as e:
            print(f"  {fname}: parse error -- {e}")
            continue

        if not frames:
            continue

        # Identify PT bus from first file
        if pt_bus is None:
            bus_id_counts = {}
            for f in frames:
                key = (f.bus, f.arbitration_id)
                bus_id_counts[key] = bus_id_counts.get(key, 0) + 1
            # PT bus has 0x051 at ~100 Hz
            for (b, cid), cnt in bus_id_counts.items():
                if cid == 0x051 and cnt > 50:
                    pt_bus = b
                    print(f"  PT bus identified: bus {pt_bus}")
                    break
            if pt_bus is None:
                print(f"  WARNING: could not identify PT bus -- will try all buses")

        last_ts_in_chunk = frames[-1].timestamp

        for f in frames:
            t = chunk_offset + f.timestamp

            # SoC (PT bus, 0x596)
            if f.arbitration_id == 0x596 and (pt_bus is None or f.bus == pt_bus):
                if len(f.data) >= 7:
                    soc = f.data[6]
                    n_0x596_frames += 1
                    soc_series.append((t, soc))
                    prev_soc = soc
                    if not soc80_crossed and soc >= 80:
                        soc80_crossed = True
                        ccl_at_80 = ccl_series[-1][1] if ccl_series else None
                        print(f"  SoC reached 80% at t={t:.1f}s  CCL at that point: {ccl_at_80}")

            # CCL (PT bus, 0x050)
            elif f.arbitration_id == 0x050 and (pt_bus is None or f.bus == pt_bus):
                if len(f.data) >= 2:
                    ccl = decode_ccl(f.data[0], f.data[1])
                    n_0x050_frames += 1
                    ccl_series.append((t, ccl))

            # Charger DC current (extended ID, any bus)
            elif f.arbitration_id == CHARGER_ID:
                if len(f.data) >= 4:
                    i_chg = decode_charger_current(f.data[2], f.data[3])
                    n_charger_frames += 1
                    charger_series.append((t, i_chg))

        # Accumulate time offset for next chunk
        chunk_offset += last_ts_in_chunk

    # Summary stats
    print(f"\n  Frames found:")
    print(f"    0x050 (CCL):        {n_0x050_frames}")
    print(f"    0x596 (SoC):        {n_0x596_frames}")
    print(f"    {CHARGER_ID:#x} (charger I): {n_charger_frames}")

    if not ccl_series:
        print("\n  0x050 NOT PRESENT in this session -- CCL analysis not possible")
        return
    if not soc_series:
        print("\n  0x596 NOT PRESENT in this session -- SoC unavailable")
        return

    total_t = ccl_series[-1][0] if ccl_series else 0
    print(f"\n  Session duration: {total_t:.0f}s ({total_t/3600:.2f}h)")
    print(f"  SoC range: {soc_series[0][1]:.0f}% -> {soc_series[-1][1]:.0f}%")

    ccl_vals = [v for _, v in ccl_series]
    print(f"  CCL range: {min(ccl_vals)} -> {max(ccl_vals)} (mean {sum(ccl_vals)/len(ccl_vals):.1f})")

    # CCL near-zero events
    zero_thresh = 10
    zero_events = [(t, v) for t, v in ccl_series if v <= zero_thresh]
    print(f"  CCL <= {zero_thresh} count: {len(zero_events)}")
    if zero_events:
        t_first_zero = zero_events[0][0]
        # SoC at first zero
        soc_at_zero = None
        for ts, s in soc_series:
            if ts >= t_first_zero:
                soc_at_zero = s
                break
        print(f"  First CCL<=10 at t={t_first_zero:.1f}s, SoC~{soc_at_zero}%")

    # Print CCL + SoC profile at ~5-minute intervals
    print(f"\n  CCL + SoC trend (one sample per ~5 min):")
    print(f"  {'t(s)':>8}  {'t(h)':>6}  {'SoC%':>5}  {'CCL_raw':>7}  {'I_chg(A)':>10}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*7}  {'-'*10}")

    interval = 300  # seconds
    next_t = 0
    soc_idx = 0
    chg_idx = 0
    for t, ccl in ccl_series:
        if t < next_t:
            continue
        # Find nearest SoC
        while soc_idx + 1 < len(soc_series) and soc_series[soc_idx+1][0] <= t:
            soc_idx += 1
        soc = soc_series[soc_idx][1] if soc_series else '?'
        # Find nearest charger current
        while chg_idx + 1 < len(charger_series) and charger_series[chg_idx+1][0] <= t:
            chg_idx += 1
        i_chg = f"{charger_series[chg_idx][1]:.2f}" if charger_series else '?'
        print(f"  {t:>8.0f}  {t/3600:>6.3f}  {soc:>5}  {ccl:>7}  {i_chg:>10}")
        next_t = t + interval

    # Look at CCL behavior around SoC=80% boundary
    print(f"\n  CCL behavior around SoC 75-100% boundary:")
    prev_soc_val = None
    for ts, soc in soc_series:
        if soc < 75:
            prev_soc_val = soc
            continue
        if prev_soc_val is not None and prev_soc_val < 75:
            # Find CCL closest to this timestamp
            best = min(ccl_series, key=lambda x: abs(x[0] - ts))
            print(f"    SoC crossed 75% at t={ts:.0f}s, CCL={best[1]}")
        prev_soc_val = soc
        # Print every SoC change from 75 onward
        if soc != (prev_soc_val if prev_soc_val is not None else -1):
            best = min(ccl_series, key=lambda x: abs(x[0] - ts))
            i_at = None
            if charger_series:
                best_c = min(charger_series, key=lambda x: abs(x[0] - ts))
                i_at = best_c[1]
            line = f"    t={ts:>7.0f}s  SoC={soc:>3}%  CCL={best[1]:>5}"
            if i_at is not None:
                line += f"  I_chg={i_at:>7.2f}A"
            print(line)
        prev_soc_val = soc


def main():
    print("Phase 3: CCL (0x050) presence and SoC>80% behavior in charge sessions")
    print(f"Log dir: {LOG_DIR}")

    for name, files in SESSIONS.items():
        process_session(name, files)

    print("\nDone.")


if __name__ == '__main__':
    main()
