"""Profile HV bus and 12V during the CLOSE_MAINR window for Truck 3's POST-contactor-swap log.

Decisive test: in the pre-swap log (2026-05-15) the HV bus rose to pack voltage DURING
CLOSE_MAINR, before MAINN was ever commanded -> welded MAINN hypothesis. truck3-has since
replaced his contactors but the truck still won't start and he no longer hears contactors
click. Question: does the HV bus still rise during CLOSE_MAINR (weld still present / new
contactor also stuck), or does it now stay flat at 0V (contactors not actuating at all)?

Signals:
  - 0x440 BMS_DATA2   mainc_stat, vbus_pos, vbus_neg  (BMS internal HV sense, lowest lag)
  - 0x870A047 EAC B2  * 4V  HV bus proxy (12V powered, continuous regardless of HV state)
  - 0x430 BMS_DATA1   lvbat (12V rail health during the attempt)
"""

import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

DBC = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")

NEW_LOG = ("truck3-POST-swap (2026-07)",
           "projects/vtrux/logs/truck3-logs/truck3log2.log")
OLD_LOG = ("truck3-PRE-swap (welded MAINN, 2026-05)",
           "projects/vtrux/logs/truck3-logs/truck3-canlog.log")
NORMAL = ("Normal startup (M3_T11)",
          "projects/vtrux/logs/debuglog_M3_T11.log")


def state_changes(frames):
    out, last = [], None
    for f in frames:
        if f.arbitration_id != 0x440:
            continue
        try:
            d = DBC.decode_message(0x440, f.data)
        except Exception:
            continue
        s = d.get("bcm_mainc_stat")
        if s != last:
            out.append((f.timestamp, s))
            last = s
    return out


def find_mainr(frames):
    mainr_t, end_t, end_s = None, None, None
    for t, s in state_changes(frames):
        if s == "CLOSE_MAINR" and mainr_t is None:
            mainr_t = t
        elif mainr_t is not None and s not in (None, "CLOSE_MAINR"):
            end_t, end_s = t, s
            break
    return mainr_t, end_t, end_s


def profile(label, path):
    frames = list(parse_file(path))
    mainr_t, end_t, end_s = find_mainr(frames)
    print("\n" + "=" * 74)
    print(label)
    print("=" * 74)
    if mainr_t is None:
        print("  no CLOSE_MAINR found")
        return
    dur = (end_t - mainr_t) if end_t else 1.0
    print(f"  CLOSE_MAINR at t={mainr_t:.3f}s -> {end_s} at t={end_t:.3f}s ({dur*1000:.0f}ms)")
    print(f"  {'rel_ms':>8}  {'mainc_stat':<20}  {'vbusP':>8}  {'vbusN':>8}  {'EAC':>7}  {'lvbat':>7}")

    last = {'vp': None, 'vn': None, 'eac': None, 'lv': None, 'mc': None}
    printed = set()
    for f in frames:
        if f.timestamp < mainr_t - 0.02:
            continue
        if f.timestamp > mainr_t + dur + 0.20:
            break
        if f.arbitration_id == 0x440:
            try:
                d = DBC.decode_message(0x440, f.data)
                last['vp'] = d.get("bcm_vbus_pos")
                last['vn'] = d.get("bcm_vbus_neg")
                last['mc'] = d.get("bcm_mainc_stat")
            except Exception:
                pass
        elif f.arbitration_id == 0x430:
            try:
                last['lv'] = DBC.decode_message(0x430, f.data).get("bcm_lvbat")
            except Exception:
                pass
        elif f.arbitration_id == 0x870A047:
            try:
                last['eac'] = f.data[2] * 4.0
            except Exception:
                pass
        ms = (f.timestamp - mainr_t) * 1000.0
        bucket = round(ms / 25) * 25
        if bucket in printed:
            continue
        printed.add(bucket)
        vp = f"{last['vp']:.1f}V" if last['vp'] is not None else "  -  "
        vn = f"{last['vn']:.1f}V" if last['vn'] is not None else "  -  "
        ec = f"{last['eac']:.0f}V" if last['eac'] is not None else "  -  "
        lv = f"{last['lv']:.2f}V" if last['lv'] is not None else "  -  "
        mc = str(last['mc']) if last['mc'] else "?"
        print(f"  {ms:>8.1f}  {mc:<20}  {vp:>8}  {vn:>8}  {ec:>7}  {lv:>7}")


if __name__ == "__main__":
    for label, path in (NEW_LOG, OLD_LOG, NORMAL):
        profile(label, path)
