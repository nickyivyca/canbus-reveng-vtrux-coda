"""
bcm_ibat offset investigation.
Goal: determine whether bcm_ibat (0x0410) has a hidden offset (like bcm_vbus_neg),
or is truly unsigned magnitude-only.

Phase 1: Look at raw ibat values in "generator on then off.log".
  Generator running = battery current near 0 (generator supplying traction load).
  Generator off = battery discharging.
  If offset exists, raw~0A should cluster near some mid-range value (not 0).

Phase 2 (separate -- Ghidra): look for add/subtract constant after the 0.25 multiply
  in the 0x0410 handler.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

GEN_LOG = "projects/vtrux/logs/generator on then off.log"

def phase1_ibat_raw_vs_generator():
    print("=== Phase 1: bcm_ibat raw values vs generator state ===")
    print(f"Log: {GEN_LOG}")

    frames_0410 = [f for f in parse_file(GEN_LOG) if f.arbitration_id == 0x0410]
    # Generator RPM from 0x0054: GENE_RotSpd = int16_LE(B0:B1) - 32767
    frames_0054 = [f for f in parse_file(GEN_LOG) if f.arbitration_id == 0x0054]

    print(f"  0x0410 frames: {len(frames_0410)}")
    print(f"  0x0054 frames: {len(frames_0054)}")

    if not frames_0410:
        print("  No 0x0410 frames -- wrong bus?")
        return

    # Build RPM lookup by timestamp
    rpm_lut = {}
    for f in frames_0054:
        if len(f.data) >= 2:
            raw = f.data[0] | (f.data[1] << 8)
            rpm_lut[f.timestamp] = raw - 32767

    def nearest_rpm(t):
        if not rpm_lut:
            return None
        best = min(rpm_lut, key=lambda x: abs(x - t))
        if abs(best - t) < 1.0:
            return rpm_lut[best]
        return None

    # Decode ibat raw: 12-bit = (B1 & 0xF) << 8 | B2
    def ibat_raw(f):
        return ((f.data[1] & 0xF) << 8) | f.data[2]

    # Sample timeseries
    step = max(1, len(frames_0410) // 60)
    print(f"\n  Timeseries (every {step} frames):")
    print(f"  {'t(s)':>8}  {'ibat_raw':>8}  {'*0.25A':>8}  {'GENE_rpm':>9}")
    for f in frames_0410[::step]:
        raw = ibat_raw(f)
        rpm = nearest_rpm(f.timestamp)
        rpm_str = f"{rpm:+6d}" if rpm is not None else "   n/a"
        print(f"  {f.timestamp:8.2f}  {raw:8d}  {raw*0.25:8.2f}  {rpm_str}")

    # Summary stats split by generator state
    all_raws = [(f.timestamp, ibat_raw(f), nearest_rpm(f.timestamp)) for f in frames_0410]
    gen_on  = [r for t, r, rpm in all_raws if rpm is not None and rpm > 100]
    gen_off = [r for t, r, rpm in all_raws if rpm is not None and rpm <= 100]
    no_rpm  = [r for t, r, rpm in all_raws if rpm is None]

    print(f"\n  Summary by generator state:")
    for label, raws in [("gen ON (rpm>100)", gen_on),
                         ("gen OFF (rpm<=100)", gen_off),
                         ("no RPM match", no_rpm)]:
        if raws:
            print(f"  {label}: n={len(raws)}, "
                  f"raw min={min(raws)} ({min(raws)*0.25:.2f}A), "
                  f"max={max(raws)} ({max(raws)*0.25:.2f}A), "
                  f"mean={sum(raws)/len(raws):.0f} ({sum(raws)/len(raws)*0.25:.2f}A)")

    # Histogram of raw values to see if distribution is symmetric around a midpoint
    print(f"\n  Raw value distribution (all frames, bucket size 128):")
    buckets = {}
    for _, r, _ in all_raws:
        b = (r // 128) * 128
        buckets[b] = buckets.get(b, 0) + 1
    for b in sorted(buckets):
        bar = '#' * (buckets[b] // max(1, max(buckets.values()) // 40))
        print(f"  raw {b:4d}-{b+127:4d}: {buckets[b]:5d}  {bar}")


def phase2_check_b4b5_in_generator_log():
    """
    Ghidra analysis shows two signals in 0x0410:
      signal_A (B1-B2): raw * 0.25, no offset
      signal_B (B4-B5): raw_BE16 * DAT_0002b5f0 + DAT_0002b5f8  (gfd, -1000 offset)
    These are passed to the format string but it's ambiguous which maps to bcm_gfd vs bcm_ibat
    in the variadic call.  Check B4-B5 values here to see which raw value makes physical
    sense as current near 0 during generator-on.
    """
    print("=== Phase 2: 0x0410 B1-B2 and B4-B5 raw values in generator log ===")
    print(f"Log: {GEN_LOG}")

    frames = [f for f in parse_file(GEN_LOG) if f.arbitration_id == 0x0410]
    if not frames:
        print("  No 0x0410 frames")
        return

    step = max(1, len(frames) // 40)
    print(f"\n  signal_A = B1-B2 (12-bit): (B1&0xF)<<8|B2, no offset -> raw*0.25")
    print(f"  signal_B = B4-B5 (16-bit BE): (B4<<8)|B5 with scale/offset (gfd formula)")
    print(f"\n  {'t(s)':>8}  {'A_raw':>6}  {'A*0.25':>7}  {'B_raw':>6}  {'B*0.025-1000':>14}  {'B4':>4} {'B5':>4}")
    for f in frames[::step]:
        d = f.data
        a_raw = ((d[1] & 0xF) << 8) | d[2]
        b_raw = (d[4] << 8) | d[5]
        a_val = a_raw * 0.25
        b_val = b_raw * 0.025 - 1000.0
        valid_a = "(INV)" if a_raw == 0xFFE else ""
        valid_b = "(INV)" if (b_raw & 0xFFFE) == 0xFFFE else ""
        print(f"  {f.timestamp:8.2f}  {a_raw:6d}  {a_val:7.2f}{valid_a:<6} "
              f"{b_raw:6d}  {b_val:14.2f}{valid_b:<6}  "
              f"0x{d[4]:02X} 0x{d[5]:02X}")

    # Summary
    a_raws = [((f.data[1] & 0xF) << 8) | f.data[2] for f in frames]
    b_raws = [(f.data[4] << 8) | f.data[5] for f in frames]
    a_valid = [r for r in a_raws if r != 0xFFE]
    b_valid = [r for r in b_raws if (r & 0xFFFE) != 0xFFFE]
    print(f"\n  signal_A valid frames: {len(a_valid)}/{len(frames)}")
    if a_valid:
        print(f"    raw range: {min(a_valid)}-{max(a_valid)}, mean {sum(a_valid)/len(a_valid):.0f}")
        print(f"    decoded range: {min(a_valid)*0.25:.2f}-{max(a_valid)*0.25:.2f} A (*0.25)")
    print(f"  signal_B valid frames: {len(b_valid)}/{len(frames)}")
    if b_valid:
        print(f"    raw range: {min(b_valid)}-{max(b_valid)}, mean {sum(b_valid)/len(b_valid):.0f}")
        print(f"    decoded range: {min(b_valid)*0.025-1000:.2f}-{max(b_valid)*0.025-1000:.2f} (*0.025-1000)")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "1"
    if phase in ("1", "phase1"):
        phase1_ibat_raw_vs_generator()
    if phase in ("2", "phase2"):
        phase2_check_b4b5_in_generator_log()
