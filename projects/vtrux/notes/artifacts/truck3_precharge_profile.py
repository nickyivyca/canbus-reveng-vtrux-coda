"""Extract truck3-truck's 12V and HV bus profile during the failed precharge window,
for direct comparison against the documented main-orig intermittent failures and
the corpus of normal sequences.

Truck 3's MAINR window per truck3-diagnose.txt: t=3.944s -> t=4.446s (502ms)
Fault latch: t=4.450s

Signals of interest:
  - 0x410 BMS_STATUS    vbat
  - 0x430 BMS_DATA1     lvbat (B7, 0.0588V/count per vtrux DBC)
  - 0x440 BMS_DATA2     mainc_stat, vbus_pos, vbus_neg
  - 0x870A047 EAC       B2 * 4V proxy for HV bus (12V powered, broadcasts regardless of HV state)

Also pulls equivalent profiles for one of the documented main-orig failure logs
(debuglog_M4_T20.log) for side-by-side, and one normal startup
(debuglog_M3_T11.log) for the baseline.
"""

import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

DBC = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")

LOGS = [
    ("Truck 3 (welded MAINN)",
     "projects/vtrux/logs/truck3-logs/truck3-canlog.log",
     3.944, 0.502),
    ("Failed main-orig (M4_T20)",
     "projects/vtrux/logs/debuglog_M4_T20.log",
     None, None),
    ("Normal startup (M3_T11)",
     "projects/vtrux/logs/debuglog_M3_T11.log",
     None, None),
]


def find_mainr_window(frames):
    """Locate the CLOSE_MAINR -> next state transition by scanning 0x440."""
    state_changes = []
    last_state = None
    for f in frames:
        if f.arbitration_id != 0x440:
            continue
        try:
            d = DBC.decode_message(0x440, f.data)
        except Exception:
            continue
        s = d.get("bcm_mainc_stat") or d.get("mainc_stat")
        if s != last_state:
            state_changes.append((f.timestamp, s))
            last_state = s
    return state_changes


def sample_window(frames, t0, dur, want_eac=True):
    """Return samples within [t0, t0+dur] for lvbat, vbus_pos, vbus_neg, eac."""
    rows = []
    last_lvbat = None
    last_vbusp = None
    last_vbusn = None
    last_eac = None
    last_mainc = None

    for f in frames:
        if f.timestamp < t0 - 0.05:
            continue
        if f.timestamp > t0 + dur + 0.2:
            break

        if f.arbitration_id == 0x430:
            try:
                d = DBC.decode_message(0x430, f.data)
                last_lvbat = d.get("bcm_lvbat")
            except Exception:
                pass

        if f.arbitration_id == 0x440:
            try:
                d = DBC.decode_message(0x440, f.data)
                last_vbusp = d.get("bcm_vbus_pos")
                last_vbusn = d.get("bcm_vbus_neg")
                last_mainc = d.get("bcm_mainc_stat") or d.get("mainc_stat")
            except Exception:
                pass

        if want_eac and f.arbitration_id == 0x870A047:
            try:
                last_eac = f.data[2] * 4.0
            except Exception:
                pass

        if t0 - 0.01 <= f.timestamp <= t0 + dur + 0.15:
            rows.append({
                "rel_ms": (f.timestamp - t0) * 1000.0,
                "lvbat": last_lvbat,
                "vbus_pos": last_vbusp,
                "vbus_neg": last_vbusn,
                "eac": last_eac,
                "mainc": last_mainc,
            })

    return rows


def phase_1_locate_sequences():
    print("=" * 78)
    print("PHASE 1: Locate precharge sequence in each log")
    print("=" * 78)
    for label, path, _, _ in LOGS:
        frames = list(parse_file(path))
        print(f"\n--- {label} ---")
        print(f"  frames: {len(frames):,}, t_first: {frames[0].timestamp:.3f}s, t_last: {frames[-1].timestamp:.3f}s")
        changes = find_mainr_window(frames)
        for t, s in changes[:12]:
            print(f"    t={t:.3f}s  mainc_stat -> {s}")


def phase_2_sample_windows():
    print("\n" + "=" * 78)
    print("PHASE 2: Sample 12V / HV bus during MAINR (and MAINN if present)")
    print("=" * 78)

    targets = []
    for label, path, t0_hint, dur_hint in LOGS:
        frames = list(parse_file(path))
        changes = find_mainr_window(frames)
        mainr_t = None
        end_t = None
        for i, (t, s) in enumerate(changes):
            if s == "CLOSE_MAINR" and mainr_t is None:
                mainr_t = t
            elif mainr_t is not None and end_t is None and s not in (None, "CLOSE_MAINR"):
                if s in ("CLOSE_MAINN", "WAIT_PRECHARGE", "CLOSE_MAINP",
                         "MAIN_PN_CLOSED_DRIVE", "ALL_OPEN_SHUTDOWN", "ALL_OPEN"):
                    end_t = t
                    break
        if mainr_t is None:
            print(f"\n{label}: no CLOSE_MAINR found")
            continue
        if end_t is None:
            end_t = mainr_t + 1.0
        dur = end_t - mainr_t + 0.5
        targets.append((label, path, mainr_t, dur, frames))

    for label, path, t0, dur, frames in targets:
        print(f"\n--- {label} ---")
        print(f"  CLOSE_MAINR enters at t={t0:.3f}s, window dur={dur*1000:.0f}ms")
        rows = sample_window(frames, t0, dur)

        print(f"  {'rel_ms':>8}  {'mainc':<22}  {'lvbat':>7}  {'vbusP':>7}  {'vbusN':>7}  {'EAC':>7}")
        seen_lv = set()
        seen_eac = set()
        for r in rows:
            ms = r["rel_ms"]
            if -10 <= ms <= dur * 1000 + 100:
                lv = f"{r['lvbat']:.2f}V" if r['lvbat'] is not None else "  -  "
                vp = f"{r['vbus_pos']:.1f}V" if r['vbus_pos'] is not None else "  -  "
                vn = f"{r['vbus_neg']:.1f}V" if r['vbus_neg'] is not None else "  -  "
                ec = f"{r['eac']:.0f}V" if r['eac'] is not None else "  -  "
                mc = str(r['mainc']) if r['mainc'] is not None else "?"

                key_lv = (round(ms / 25) * 25, lv)
                key_eac = (round(ms / 25) * 25, ec)
                if key_lv in seen_lv and key_eac in seen_eac:
                    continue
                seen_lv.add(key_lv)
                seen_eac.add(key_eac)

                print(f"  {ms:>8.1f}  {mc:<22}  {lv:>7}  {vp:>7}  {vn:>7}  {ec:>7}")

        lvs = [r['lvbat'] for r in rows if r['lvbat'] is not None and -10 <= r['rel_ms'] <= dur * 1000]
        if lvs:
            print(f"  lvbat min/max during window: {min(lvs):.2f}V / {max(lvs):.2f}V")


if __name__ == "__main__":
    phase_1_locate_sequences()
    phase_2_sample_windows()
