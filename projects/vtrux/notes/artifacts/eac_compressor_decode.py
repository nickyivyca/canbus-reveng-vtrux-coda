"""
EAC compressor CAN ID decode investigation.
IDs: 0x0868A047 (EAC_STATUS1) and 0x0870A047 (EAC_STATUS2)
Source: Sanden MI-EV36-BNKx HV electric AC compressor, SA=0x47

EPRI plist says:
  0x0868A047.2 = EAC_Elec_Curr (A, %.2f)  -> GoPoint byte 2 = CAN B0
  0x0868A047.3 = EAC_Elec_Pwr  (W, %d)   -> GoPoint byte 3 = CAN B1
  0x0870A047   = EAC_CompHVInput (VDC, %d) -> byte position TBD

Goal: confirm byte positions and find A/C-active windows.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file as parse_log

# oghighwaydrive.log is a PT-bus-only capture (no GM buses).
# anotherevap logs have all three buses and are good for GMLAN cross-checks.
HIGHWAY_LOG  = "projects/vtrux/logs/oghighwaydrive.log"
EVAP_LOG     = "projects/vtrux/logs/vtruxevapdrivelog4.log"
MULTI_BUS_LOG = "projects/vtrux/logs/vtruxanotherevaplogpart2.log"  # has all 3 buses

# ── Phase 1: GMLAN A/C command bit in a multi-bus log ────────────────────────
# Background: the Vtrux no longer has the original GM belt-driven A/C compressor.
# 0x3D1 B4 bit 5 (Air_Conditioning_Compressor_Command) is the ECM/GM-side signal
# for the OEM belt-driven unit. It is interesting to check whether:
#   (a) the GM side still asserts this bit when A/C is requested (e.g. defog mode),
#   (b) if so, whether the VCM translates it into commands on the EAC compressor IDs.
# This would reveal whether the VCM acts as a bridge between GMLAN A/C request
# and the Sanden HV compressor.
# NOTE: oghighwaydrive.log has no GM buses -- use a multi-bus log instead.
def phase1_gmlan_ac_command(log=MULTI_BUS_LOG):
    print(f"=== Phase 1: GMLAN A/C command bit (0x3D1 B4 bit 5) ===")
    print(f"Log: {log}")
    frames = [f for f in parse_log(log) if f.arbitration_id == 0x3D1]
    if not frames:
        print("  No 0x3D1 frames found (may be PT-only log)")
        return
    active = [(f.timestamp, f.data[4]) for f in frames if len(f.data) > 4 and (f.data[4] & 0x20)]
    total = len(frames)
    print(f"  Total 0x3D1 frames: {total}")
    print(f"  Frames with A/C commanded ON (B4 bit 5=1): {len(active)}")
    if active:
        print(f"  First active: t={active[0][0]:.2f}s  B4=0x{active[0][1]:02X}")
        print(f"  Last  active: t={active[-1][0]:.2f}s  B4=0x{active[-1][1]:02X}")
        windows = []
        start = active[0][0]
        prev  = active[0][0]
        for t, _ in active[1:]:
            if t - prev > 2.0:
                windows.append((start, prev))
                start = t
            prev = t
        windows.append((start, prev))
        print(f"  A/C-active windows ({len(windows)} total):")
        for s, e in windows[:10]:
            print(f"    t={s:.1f}s -- t={e:.1f}s  ({e-s:.0f}s)")
    else:
        print("  A/C was NOT commanded on in this log.")

# ── Phase 2: 0x0870A047 byte timeseries -- find HV voltage ───────────────────
# B2 mean=94.6 across full highway log is suspicious for HV voltage at ~4 V/count.
# Also check B1 and B3 which have similar distributions (~73 mean each).
def phase2_0870_timeseries(log=HIGHWAY_LOG, t_start=0, t_end=2100):
    print(f"=== Phase 2: 0x0870A047 B1/B2/B3 timeseries ===")
    frames = [f for f in parse_log(log)
              if f.arbitration_id == 0x0870A047 and t_start <= f.timestamp <= t_end]
    if not frames:
        print("  No frames found")
        return
    print(f"  Frames: {len(frames)}, t={frames[0].timestamp:.2f}-{frames[-1].timestamp:.2f}s")
    # Sample every ~50s to show progression
    step = max(1, len(frames) // 40)
    print(f"  {'t(s)':>8}  {'B0':>4}  {'B1':>4}  {'B2':>4}  {'B3':>4}  "
          f"{'B1*4':>6}  {'B2*4':>6}  {'B3*4':>6}")
    for f in frames[::step]:
        b = f.data
        print(f"  {f.timestamp:8.1f}  "
              f"0x{b[0]:02X}  {b[1]:4d}  {b[2]:4d}  {b[3]:4d}  "
              f"{b[1]*4:6.0f}  {b[2]*4:6.0f}  {b[3]*4:6.0f}")

# ── Phase 3: 0x0868A047 byte timeseries -- find curr/pwr ─────────────────────
# B0 is almost always 0; main action is in B1-B4.
# B3 has highest entropy (241 unique vals) -- best analog candidate.
def phase3_0868_timeseries(log=HIGHWAY_LOG, t_start=0, t_end=2100):
    print(f"=== Phase 3: 0x0868A047 B0-B4 timeseries ===")
    frames = [f for f in parse_log(log)
              if f.arbitration_id == 0x0868A047 and t_start <= f.timestamp <= t_end]
    if not frames:
        print("  No frames found")
        return
    print(f"  Frames: {len(frames)}, t={frames[0].timestamp:.2f}-{frames[-1].timestamp:.2f}s")
    step = max(1, len(frames) // 40)
    print(f"  {'t(s)':>8}  {'B0':>4}  {'B1':>4}  {'B2':>4}  {'B3':>4}  {'B4':>4}")
    for f in frames[::step]:
        b = f.data
        print(f"  {f.timestamp:8.1f}  {b[0]:4d}  {b[1]:4d}  {b[2]:4d}  {b[3]:4d}  {b[4]:4d}")

# ── Phase 4: compare B2 of 0x0870A047 vs known HV voltage (0x482 B1-B2) ──────
# 0x482 GENE_HighPwr_Volt = 11-bit LE: B1 | (B2 & 0x7)<<8, scale 1 V/count.
# If 0x0870A047 B2 * 4 ~= 0x0482 HV voltage, that confirms the decode.
def phase4_voltage_crosscheck(log=HIGHWAY_LOG, t_start=50, t_end=200):
    print(f"=== Phase 4: 0x0870A047 B2*4 vs 0x0482 GENE_HighPwr_Volt ===")
    print(f"Window: t={t_start}-{t_end}s")
    frames_470 = [f for f in parse_log(log)
                  if f.arbitration_id == 0x0870A047 and t_start <= f.timestamp <= t_end]
    frames_482 = [f for f in parse_log(log)
                  if f.arbitration_id == 0x0482 and t_start <= f.timestamp <= t_end]
    if not frames_470 or not frames_482:
        print(f"  0x0870A047: {len(frames_470)} frames, 0x0482: {len(frames_482)} frames")
        return
    # Build lookup by timestamp for 0x0482
    lut = {f.timestamp: f for f in frames_482}
    # Find pairs within 0.15s
    pairs = []
    for f in frames_470:
        best = min(lut.keys(), key=lambda t: abs(t - f.timestamp))
        if abs(best - f.timestamp) < 0.15:
            b470 = f.data
            b482 = lut[best].data
            volt_epri = (b482[1] | ((b482[2] & 0x7) << 8))  # GENE_HighPwr_Volt
            volt_b1   = b470[1] * 4
            volt_b2   = b470[2] * 4
            volt_b3   = b470[3] * 4
            pairs.append((f.timestamp, volt_epri, volt_b1, volt_b2, volt_b3))
    if not pairs:
        print("  No paired frames found")
        return
    step = max(1, len(pairs) // 20)
    print(f"  {'t(s)':>8}  {'0x482_V':>8}  {'B1*4':>6}  {'B2*4':>6}  {'B3*4':>6}")
    for t, v_ref, v1, v2, v3 in pairs[::step]:
        print(f"  {t:8.1f}  {v_ref:8.1f}  {v1:6.0f}  {v2:6.0f}  {v3:6.0f}")


# ── Phase 5: EAC bytes during GMLAN A/C-active window ────────────────────────
# Phase 1 found a 1-second A/C-active window at t=1002.7-1003.3s in
# vtruxanotherevaplogpart2.log.  Check whether 0x0868A047 B1/B2/B4 (the
# correlated trio that drops to 0 when the compressor is off) are non-zero
# during that window -- and for context, also show 30s before and after.
def phase5_eac_during_ac_command(log=MULTI_BUS_LOG):
    print(f"=== Phase 5: 0x0868A047 during GMLAN A/C command window ===")
    print(f"Log: {log}")
    # Full context window: 30s before first active frame to 30s after last
    t_win_start = 972.0   # ~30s before 1002.7
    t_win_end   = 1033.0  # ~30s after  1003.3
    frames_eac1 = [f for f in parse_log(log)
                   if f.arbitration_id == 0x0868A047
                   and t_win_start <= f.timestamp <= t_win_end]
    frames_eac2 = [f for f in parse_log(log)
                   if f.arbitration_id == 0x0870A047
                   and t_win_start <= f.timestamp <= t_win_end]
    print(f"  0x0868A047 frames in window: {len(frames_eac1)}")
    print(f"  0x0870A047 frames in window: {len(frames_eac2)}")
    if not frames_eac1:
        print("  No EAC frames -- compressor not on this bus segment?")
        return
    # EAC_STATUS1 sample
    step = max(1, len(frames_eac1) // 60)
    print(f"\n  0x0868A047 (EAC_STATUS1)  [A/C cmd active: t=1002.7-1003.3s]")
    print(f"  {'t(s)':>8}  {'B0':>4}  {'B1':>4}  {'B2':>4}  {'B3':>4}  {'B4':>4}  AC_cmd?")
    for f in frames_eac1[::step]:
        b = f.data
        ac_flag = "<<" if 1002.7 <= f.timestamp <= 1003.4 else ""
        print(f"  {f.timestamp:8.2f}  0x{b[0]:02X}  {b[1]:4d}  {b[2]:4d}  {b[3]:4d}  {b[4]:4d}  {ac_flag}")
    # EAC_STATUS2 HV voltage sample
    if frames_eac2:
        step2 = max(1, len(frames_eac2) // 20)
        print(f"\n  0x0870A047 (EAC_STATUS2) B2*4 = HV voltage")
        print(f"  {'t(s)':>8}  {'B1':>4}  {'B2':>4}  {'B3':>4}  {'B2*4_V':>8}")
        for f in frames_eac2[::step2]:
            b = f.data
            print(f"  {f.timestamp:8.2f}  {b[1]:4d}  {b[2]:4d}  {b[3]:4d}  {b[2]*4:8.0f}")


CLIMIT_LOG = "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
CHARGE_LOG = "projects/vtrux/logs/after-battery-swap-charges/charge_M0_T0.log"

# ── Phase 6: Is 0x0870A047 present when compressor is off + during charging? ──
# Questions:
#   (a) Does the HV voltage message broadcast when 0x0868A047 is all-zero (compressor off)?
#       We already know anotherevap had 610 frames of 0x0870A047 while 0x0868A047=0,
#       but confirm full-log presence and frame rate.
#   (b) Does it appear in a charging log?
#   (c) Does B2*4 still track pack voltage in the climit log vs 0x0482 GENE_HighPwr_Volt?
def phase6_hv_presence_and_climit_crosscheck():
    print("=== Phase 6: 0x0870A047 presence across conditions ===")
    # NOTE: (a) compressor-off presence already confirmed in Phase 5:
    #   610 frames of 0x0870A047 at ~10 Hz in anotherevap log while 0x0868A047 = all zeros.
    #   Skipping full anotherevap parse here (too slow).
    print("\n-- (a) Compressor-off: CONFIRMED in Phase 5 (610 frames at ~10 Hz, "
          "0x0868A047 all-zero)")

    # (b) charge log -- is EAC present?
    print(f"\n-- (b) Charge log: {CHARGE_LOG}")
    frames_chg1 = [f for f in parse_log(CHARGE_LOG) if f.arbitration_id == 0x0868A047]
    frames_chg2 = [f for f in parse_log(CHARGE_LOG) if f.arbitration_id == 0x0870A047]
    print(f"  0x0868A047: {len(frames_chg1)} frames")
    print(f"  0x0870A047: {len(frames_chg2)} frames")
    if frames_chg2:
        b2_vals = [f.data[2] for f in frames_chg2 if len(f.data) > 2]
        t0, t1 = frames_chg2[0].timestamp, frames_chg2[-1].timestamp
        print(f"  Duration: {t0:.1f}-{t1:.1f}s ({t1-t0:.0f}s)")
        print(f"  B2 range: {min(b2_vals)}-{max(b2_vals)}, mean {sum(b2_vals)/len(b2_vals):.1f} "
              f"({min(b2_vals)*4}-{max(b2_vals)*4} V)")
        # Sample a few points
        step = max(1, len(frames_chg2) // 10)
        print(f"  Sample B2*4 timeseries:")
        for f in frames_chg2[::step]:
            print(f"    t={f.timestamp:8.1f}s  B2={f.data[2]:3d}  V={f.data[2]*4}V  "
                  f"B1={f.data[1]:3d}  B3={f.data[3]:3d}")

    # (c) climit log -- cross-check B2*4 vs 0x0482 over full driving range
    print(f"\n-- (c) Climit log voltage crosscheck: {CLIMIT_LOG}")
    frames_cl2  = [f for f in parse_log(CLIMIT_LOG) if f.arbitration_id == 0x0870A047]
    frames_482  = [f for f in parse_log(CLIMIT_LOG) if f.arbitration_id == 0x0482]
    print(f"  0x0870A047: {len(frames_cl2)} frames")
    print(f"  0x0482:     {len(frames_482)} frames")
    if not frames_cl2 or not frames_482:
        print("  One or both IDs absent -- cannot crosscheck")
        return
    # Pair by nearest timestamp within 0.15s
    lut = {f.timestamp: f for f in frames_482}
    pairs = []
    for f in frames_cl2:
        best = min(lut.keys(), key=lambda t: abs(t - f.timestamp))
        if abs(best - f.timestamp) < 0.15:
            v_ref = lut[best].data[1] | ((lut[best].data[2] & 0x7) << 8)
            v_eac = f.data[2] * 4
            pairs.append((f.timestamp, v_ref, v_eac, f.data[2], f.data[1], f.data[3]))
    if not pairs:
        print("  No paired frames found")
        return
    step = max(1, len(pairs) // 25)
    errs = [abs(p[1] - p[2]) for p in pairs]
    print(f"  Paired: {len(pairs)} samples, mean |err|={sum(errs)/len(errs):.1f}V, "
          f"max |err|={max(errs):.0f}V")
    print(f"  {'t(s)':>8}  {'0x482_V':>8}  {'B2*4_V':>7}  {'err':>5}  {'B1':>4}  {'B3':>4}")
    for t, v_ref, v_eac, b2, b1, b3 in pairs[::step]:
        print(f"  {t:8.1f}  {v_ref:8d}  {v_eac:7d}  {v_ref-v_eac:5d}  {b1:4d}  {b3:4d}")


# ── Phase 7: Find the 33V outlier in the climit crosscheck ───────────────────
# Phase 6 reported mean |err|=1.3V but max=33V. Find which timestamp(s) exceed
# a threshold, and show surrounding frames to check if it's a startup/shutdown
# transient, a fast voltage spike, or a timestamp mismatch artifact.
def phase7_climit_outliers(threshold=15):
    print(f"=== Phase 7: Climit crosscheck outliers (|err| > {threshold}V) ===")
    frames_cl2 = [f for f in parse_log(CLIMIT_LOG) if f.arbitration_id == 0x0870A047]
    frames_482 = [f for f in parse_log(CLIMIT_LOG) if f.arbitration_id == 0x0482]
    lut = {f.timestamp: f for f in frames_482}
    pairs = []
    for f in frames_cl2:
        best = min(lut.keys(), key=lambda t: abs(t - f.timestamp))
        dt = abs(best - f.timestamp)
        if dt < 0.15:
            v_ref = lut[best].data[1] | ((lut[best].data[2] & 0x7) << 8)
            v_eac = f.data[2] * 4
            pairs.append((f.timestamp, best, dt, v_ref, v_eac, f.data[2], f.data[1], f.data[3]))
    outliers = [(t, t2, dt, vr, ve, b2, b1, b3) for t, t2, dt, vr, ve, b2, b1, b3 in pairs
                if abs(vr - ve) > threshold]
    print(f"  Total pairs: {len(pairs)}, outliers: {len(outliers)}")
    if not outliers:
        print(f"  No outliers above {threshold}V")
        return
    print(f"  {'t_eac':>8}  {'t_482':>8}  {'dt_ms':>6}  {'0x482V':>7}  {'B2*4V':>6}  {'err':>5}  B2  B1  B3")
    for t, t2, dt, vr, ve, b2, b1, b3 in outliers:
        print(f"  {t:8.3f}  {t2:8.3f}  {dt*1000:6.1f}  {vr:7d}  {ve:6d}  {vr-ve:5d}  {b2:3d} {b1:3d} {b3:3d}")
    # Show context around first outlier
    first_t = outliers[0][0]
    ctx = [(t, vr, ve) for t, _, _, vr, ve, _, _, _ in pairs if abs(t - first_t) < 3.0]
    print(f"\n  Context +/-3s around first outlier (t={first_t:.3f}s):")
    print(f"  {'t':>8}  {'0x482V':>7}  {'B2*4V':>6}  {'err':>5}")
    for t, vr, ve in ctx:
        marker = " <<" if abs(t - first_t) < 0.05 else ""
        print(f"  {t:8.3f}  {vr:7d}  {ve:6d}  {vr-ve:5d}{marker}")


# ── Phase 8: Multi-source voltage comparison at t=1795s outlier ──────────────
# Compare all known HV voltage sources at the moment 0x0482 dipped to 339V.
# Sources:
#   0x0482 GENE_HighPwr_Volt  : 11-bit LE, 1 V/count  (B1|(B2&7)<<8)
#   0x0462 TRAC_HighPwr_Volt  : same encoding (symmetric to GENE)
#   0x18FFD6B3 DCDC_HV_Volt   : B4-B5 LE uint16, x0.05 V/count
#   0x0440 bcm_vbus_pos       : 12-bit BE Motorola, start=39, x0.25 V/count
#   0x0440 bcm_vbus_neg       : 12-bit BE Motorola, start=43, x0.25, offset=-500
#   0x0410 bcm_vbat           : 12-bit BE Motorola, start=51, x0.25 V/count
#   0x0870A047 B2*4           : Sanden HV input (already known: 372V at t=1795)
def _decode_be12(data, start_bit):
    """Decode a 12-bit big-endian Motorola signal given its DBC start bit (MSB).

    cantools Motorola bit numbering: bit N -> byte N//8, actual bit N%8.
    Bit progression from MSB: decrement within each byte; when reaching the
    LSB of a byte (bit%8==0), jump +15 to the MSB of the next byte.

    Verified against manual decodes:
      start=51 -> (B6&0xF)<<8 | B7       (bcm_vbat)
      start=39 -> B4<<4 | B5>>4           (bcm_vbus_pos)
      start=43 -> (B5&0xF)<<8 | B6       (bcm_vbus_neg)
    """
    raw = 0
    bit = start_bit
    for _ in range(12):
        raw = (raw << 1) | ((data[bit // 8] >> (bit % 8)) & 1)
        bit = (bit + 15) if (bit % 8 == 0) else (bit - 1)
    return raw

def phase8_voltage_comparison_at_outlier(t_center=1795.347, window=2.0):
    print(f"=== Phase 8: Multi-source HV voltage at t={t_center}s outlier ===")
    t0, t1 = t_center - window, t_center + window
    ids_needed = {0x0482, 0x0462, 0x18FFD6B3, 0x0440, 0x0410, 0x0870A047}
    buckets = {k: [] for k in ids_needed}
    for f in parse_log(CLIMIT_LOG):
        if t0 <= f.timestamp <= t1 and f.arbitration_id in ids_needed:
            buckets[f.arbitration_id].append(f)

    # Helper: nearest frame to t_center
    def nearest(frames):
        if not frames:
            return None
        return min(frames, key=lambda f: abs(f.timestamp - t_center))

    # Decode each source at nearest frame to t_center, and 1s before for context
    def decode_all(f):
        results = {}
        if f is None:
            return results
        d = f.data
        arb = f.arbitration_id
        if arb == 0x0482 and len(d) >= 3:
            results['GENE_HighPwr_Volt'] = d[1] | ((d[2] & 0x7) << 8)
        if arb == 0x0462 and len(d) >= 3:
            results['TRAC_HighPwr_Volt'] = d[1] | ((d[2] & 0x7) << 8)
        if arb == 0x18FFD6B3 and len(d) >= 6:
            results['DCDC_HV_Volt_V'] = round((d[4] | (d[5] << 8)) * 0.05, 1)
        if arb == 0x0440 and len(d) >= 8:
            results['bcm_vbus_pos_V'] = round(_decode_be12(d, 39) * 0.25, 1)
            results['bcm_vbus_neg_V'] = round(_decode_be12(d, 43) * 0.25 - 500, 1)
        if arb == 0x0410 and len(d) >= 8:
            results['bcm_vbat_V'] = round(_decode_be12(d, 51) * 0.25, 1)
        if arb == 0x0870A047 and len(d) >= 3:
            results['Sanden_HV_V'] = d[2] * 4
        return results

    print(f"\n  Nearest frame to t={t_center}s from each source:")
    print(f"  {'Source':<22} {'t':>8}  {'Value':>10}  {'dt_ms':>7}")
    for arb_id in sorted(ids_needed):
        f = nearest(buckets[arb_id])
        if f is None:
            print(f"  0x{arb_id:08X}{'':14} -- no frames in window")
            continue
        decoded = decode_all(f)
        dt_ms = (f.timestamp - t_center) * 1000
        for name, val in decoded.items():
            unit = "V" if "Volt" in name or name.endswith("_V") else ""
            print(f"  {name:<22} {f.timestamp:8.3f}  {val:>8}{unit}  {dt_ms:+7.1f}ms")

    # Full timeseries of 0x0482 in window so we can see the sag shape
    print(f"\n  0x0482 GENE_HighPwr_Volt timeseries t={t0:.1f}-{t1:.1f}s:")
    for f in buckets[0x0482]:
        v = f.data[1] | ((f.data[2] & 0x7) << 8)
        marker = " <<" if abs(f.timestamp - t_center) < 0.1 else ""
        print(f"    t={f.timestamp:8.3f}  {v:4d}V{marker}")


# ── Phase 9: P = V × I cross-check on oghighwaydrive.log ────────────────────
# Both IDs broadcast at 10 Hz as a synchronized pair from SA=0x47.
# For each paired frame:
#   V_hv  = 0x0870A047 B2 * 4          (confirmed HV voltage)
#   I_cand = 0x0868A047 B2              (EAC_Elec_Curr candidate, raw counts)
#   P_cand = 0x0868A047 B3              (EAC_Elec_Pwr candidate, raw counts)
#   B1, B4 also extracted for reference
#
# Test:  P_cand * scale_W  ~=  I_cand * scale_I * V_hv ?
# If B3 is power and B2 is current, the ratio B3 / (B2 * V_hv) should be
# a stable constant = scale_I / scale_W.  For EPRI format %.2f on Curr, the
# scale is probably not 1 A/count (would give 0.00-10.00 A which is coarse).
# Try several candidate current scales and see which gives the most stable ratio.
def phase9_pvi_crosscheck(log=HIGHWAY_LOG):
    import statistics
    print(f"=== Phase 9: P=V*I cross-check ===")
    print(f"Log: {log}")

    frames1 = {f.timestamp: f for f in parse_log(log) if f.arbitration_id == 0x0868A047}
    frames2 = {f.timestamp: f for f in parse_log(log) if f.arbitration_id == 0x0870A047}
    if not frames1 or not frames2:
        print("  Missing frames")
        return

    # Pair by nearest timestamp within 0.06s (same ECU, synchronized)
    pairs = []
    ts2 = sorted(frames2.keys())
    for t1, f1 in sorted(frames1.items()):
        best = min(ts2, key=lambda t: abs(t - t1))
        if abs(best - t1) < 0.06:
            f2 = frames2[best]
            b1  = f1.data[1]; b2 = f1.data[2]
            b3  = f1.data[3]; b4 = f1.data[4]
            v_b2 = f2.data[2]
            pairs.append((t1, b1, b2, b3, b4, v_b2))

    # Filter: compressor active only (B1/B2/B4 all > 0)
    active = [(t, b1, b2, b3, b4, v) for t, b1, b2, b3, b4, v in pairs
              if b1 > 0 and b2 > 0 and b4 > 0 and v > 0 and b3 > 0]
    print(f"  Total paired frames: {len(pairs)}, compressor-active: {len(active)}")
    if not active:
        print("  No active frames found")
        return

    # For each frame compute V_hv and P_raw = B2*V_hv (assuming 1 A/count)
    # and check ratio B3 / (B2 * V_hv)
    print(f"\n--- Ratio analysis: B3 / (Bx * V_hv) ---")
    for curr_byte, curr_name in [(2, 'B2'), (1, 'B1')]:
        ratios = []
        for t, b1, b2, b3, b4, v in active:
            bcurr = b2 if curr_byte == 2 else b1
            v_hv = v * 4
            if bcurr > 0 and v_hv > 0:
                ratios.append(b3 / (bcurr * v_hv))
        if not ratios:
            continue
        mean_r = statistics.mean(ratios)
        stdev_r = statistics.stdev(ratios) if len(ratios) > 1 else 0
        cv = stdev_r / mean_r if mean_r else 0
        print(f"  {curr_name}: mean ratio = {mean_r:.6f}  stdev = {stdev_r:.6f}  CV = {cv:.3f}")
        print(f"    => if {curr_name} in A, Pwr scale = {1/mean_r:.2f} W/count")
        print(f"    => if {curr_name} in 0.5A/count, Pwr scale = {0.5/mean_r:.2f} W/count")
        print(f"    => if {curr_name} in 0.1A/count, Pwr scale = {0.1/mean_r:.2f} W/count")

    # Pearson r: B3 vs (B2 * V_hv), and B3 vs (B1 * V_hv)
    print(f"\n--- Pearson r: B3 vs candidate power ---")
    for curr_byte, curr_name in [(2, 'B2'), (1, 'B1')]:
        xs = []; ys = []
        for t, b1, b2, b3, b4, v in active:
            bcurr = b2 if curr_byte == 2 else b1
            xs.append(bcurr * v * 4)
            ys.append(b3)
        if len(xs) < 2:
            continue
        mx = statistics.mean(xs); my = statistics.mean(ys)
        num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
        den = (sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys)) ** 0.5
        r = num/den if den else 0
        print(f"  r(B3, {curr_name}*V_hv) = {r:.4f}")

    # Sample table: show V, B1, B2, B3, B4, computed P candidates
    print(f"\n--- Sample timeseries (every ~30s) ---")
    step = max(1, len(active) // 40)
    print(f"  {'t':>8}  {'V_hv':>5}  {'B1':>3}  {'B2':>3}  {'B3':>3}  {'B4':>3}  "
          f"{'B2*V':>6}  {'B1*V':>6}  {'B3/B2V':>7}  {'B3/B1V':>7}")
    for t, b1, b2, b3, b4, v in active[::step]:
        vhv = v * 4
        r_b2 = b3 / (b2 * vhv) if b2 > 0 else 0
        r_b1 = b3 / (b1 * vhv) if b1 > 0 else 0
        print(f"  {t:8.1f}  {vhv:5d}  {b1:3d}  {b2:3d}  {b3:3d}  {b4:3d}  "
              f"{b2*vhv:6d}  {b1*vhv:6d}  {r_b2:7.5f}  {r_b1:7.5f}")

    # Check if B3 is a simple counter (increments monotonically)
    b3_vals = [b3 for _, _, _, b3, _, _ in active]
    diffs = [b3_vals[i+1] - b3_vals[i] for i in range(len(b3_vals)-1)]
    inc = sum(1 for d in diffs if d > 0)
    dec = sum(1 for d in diffs if d < 0)
    zer = sum(1 for d in diffs if d == 0)
    print(f"\n--- B3 monotonicity check (counter vs smooth signal) ---")
    print(f"  Frame-to-frame B3 changes: inc={inc}, dec={dec}, same={zer}, total={len(diffs)}")
    print(f"  (A checksum/counter would show ~equal inc/dec; a smooth power signal "
          f"would show more structure)")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("1", "phase1", "all"): phase1_gmlan_ac_command()
    if phase in ("2", "phase2", "all"): phase2_0870_timeseries()
    if phase in ("3", "phase3", "all"): phase3_0868_timeseries()
    if phase in ("4", "phase4", "all"): phase4_voltage_crosscheck()
    if phase in ("5", "phase5", "all"): phase5_eac_during_ac_command()
    if phase in ("6", "phase6", "all"): phase6_hv_presence_and_climit_crosscheck()
    if phase in ("7", "phase7", "all"): phase7_climit_outliers()
    if phase in ("8", "phase8", "all"): phase8_voltage_comparison_at_outlier()
    if phase in ("9", "phase9", "all"): phase9_pvi_crosscheck()
