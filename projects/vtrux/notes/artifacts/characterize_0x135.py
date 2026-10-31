"""
Characterize 0x135 B2 across Vtrux logs.

For each log:
  - Report all unique 0x135 B2 values seen and frame count
  - If 0x649 B0 transitions from non-zero to 0x00 (evap completion), report
    B2 before and after the transition, and at what time it occurs
  - Also report 0x649 B0 modal value as context

Goal: determine if B2 acts as a days-since-evap counter by checking:
  1. Does B2 = 0 (or reset) at evap completion?
  2. Does B2 match expected day-offset across logs of known date?
"""

import sys
sys.path.insert(0, ".")

from pathlib import Path

LOGS_DIR = Path(r"projects\vtrux\logs")
OUT_PATH = Path(r"projects\vtrux\notes\artifacts\characterize_0x135_results.txt")

LOGS = [
    ("oghighwaydrive.log",                   "2025-08-21", "evap-complete at t=1223s"),
    ("debuglog_M0_T7.log",                   "2025-08-21?","post-evap session T7"),
    ("debuglog_M0.log",                      "2025-08-21?","same-session oghighway"),
    ("full-charge-then-fail.log",            "2025-08-22?","+1d charge"),
    ("vtruxevapdrivelog4.log",               "2026-02-25", "evap day part1, no completion"),
    ("vtruxevapdrivelog4part2.log",          "2026-02-25", "evap-complete at t=10.5s"),
    ("vtruxchargeafterevaplog-failed.log",   "2026-02-26", "+1d charge"),
    ("vtruxchargeafterevaplogattempt2.log",  "2026-02-26", "+1d charge"),
    ("vtruxcurrentlimitingtest.log",         "2026-02-26", "+1d drive (post_a)"),
    ("vtruxstartingat20.log",                "2026-02-26", "+1d drive (post_b)"),
    ("vtruxoverflowrecoverytest.log",        "2026-02-26", "+1d overflow test"),
    ("vtruxoverflowrecoverytest3.log",       "2026-02-26", "+1d overflow test3"),
    ("vtruxoverflowrecoverytest4.log",       "2026-02-26", "+1d"),
    ("vtruxoverflowrecoverytest5.log",       "2026-02-26", "+1d"),
    ("vtruxoverflowrecoverytest6.log",       "2026-02-27?","+2d?"),
    ("vtruxoverflowrecoverytest7.log",       "2026-02-27?","+2d?"),
    ("vtruxoverflowrecoverytest8.log",       "2026-02-27?","+2d?"),
    ("vtruxoverflowrecoverytest9.log",       "2026-02-27?","+2d?"),
    ("vtruxoverflowrecoverytest10.log",      "2026-02-27?","+2d?"),
    ("vtruxexporttest.log",                  "2026-03-03?","+6d?"),
    ("vtruxunpluggedpumpoverheattest.log",   "2026-03-03?","+6d?"),
    ("vtruxanotherevaplogpart1.log",         "2026-03-04", "+7d (pre_next, evap pending)"),
    ("vtruxanotherevaplogpart2.log",         "2026-03-04", "evap-complete at t=1386.8s"),
    ("vtruxanotherevaplogpart3.log",         "2026-03-04", "post-evap same day"),
    ("vtruxanotherevaplogpart4-batteryonly.log","2026-03-05","+1d from 2nd evap"),
    ("vtruxscottsvalleydrive.log",           "2026-03-05", "+1d from 2nd evap"),
    ("vtruxextensioncabletest.log",          "2026-03-05?","+1d charge/test"),
    ("vtruxchargeafterscottsvalley.log",     "2026-03-05?","+1d charge"),
    ("vtruxchargeafterscottsvalley2-16asetpoint.log","2026-03-05?","+1d charge"),
    ("vtruxgeneratoroverheattest.log",       "2026-03-18", "3rd evap, t=764.8s"),
    ("vtruxchargeafteroverheattest-16asetpoint.log","2026-03-18?","after 3rd evap"),
    ("vtruxchargeafteroverheattest-32asetpoint.log","2026-03-18?","after 3rd evap"),
    ("movingaroundindriveway.log",           "unknown",    "short driveway moves"),
    ("generator-on-then-off.log",            "unknown",    "M-mode only"),
    ("vtruxwoodwardbconnectordisconnected.log","2026-03-06","VCM B-conn disconnect test"),
    ("vtrux_no_gene_inv_fuse.log",           "2026-04-17", "gene inv fuse removed"),
    ("vtrux_partstruck_testdrive.log",       "2026-04-?",  "parts truck drive"),
    ("vtrux_partstruck_testdrive_part2.log", "2026-04-?",  "parts truck drive2"),
    ("vtrux_partstruck_testdrive_part3_engine.log","2026-04-?","parts truck drive3"),
    ("vtrux_partstruck_evapfuseexperiment.log","2026-04-?","parts truck evap fuse"),
    ("vtrux_partstruck_driveaftercharge.log","2026-04-?",  "parts truck drive after charge"),
]

lines_out = []

def emit(s=""):
    lines_out.append(str(s))
    print(s, flush=True)


def parse_busmaster_line(line):
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        ts = parts[0]
        hms, ticks = ts.rsplit(":", 1)
        h, m, s = hms.split(":")
        t = int(h)*3600 + int(m)*60 + int(s) + int(ticks)*0.0001
        if parts[1].lower() in ("rx", "tx"):
            id_str = parts[3]
            dlc    = int(parts[5])
            data   = [int(x, 16) for x in parts[6:6+dlc]]
        else:
            id_str = parts[2]
            dlc    = int(parts[4])
            data   = [int(x, 16) for x in parts[5:5+dlc]]
        aid = int(id_str, 16)
        if len(data) != dlc or dlc == 0:
            return None
        return t, aid, data
    except Exception:
        return None


def scan_log(path):
    """
    Returns:
      b2_vals: list of (t, b2) for all 0x135 frames
      b0_vals: list of (t, b0) for all 0x649 frames
    """
    b2_vals = []
    b0_vals = []
    with open(path, encoding="latin-1", errors="replace") as fh:
        for line in fh:
            parsed = parse_busmaster_line(line)
            if parsed is None:
                continue
            t, aid, data = parsed
            if aid == 0x135 and len(data) >= 3:
                b2_vals.append((t, data[2]))
            elif aid == 0x649 and len(data) >= 1:
                b0_vals.append((t, data[0]))
    return b2_vals, b0_vals


def find_evap_completion(b0_vals):
    """
    Returns list of (t, b0_before, b0_after) for transitions where b0 goes
    from a value with bit7 set to 0x00.
    """
    events = []
    for i in range(1, len(b0_vals)):
        t_prev, v_prev = b0_vals[i-1]
        t_cur,  v_cur  = b0_vals[i]
        if (v_prev & 0x80) and v_cur == 0x00:
            events.append((t_cur, v_prev, v_cur))
    return events


emit("=== 0x135 B2 characterization across Vtrux logs ===")
emit()

for fname, date_hint, role in LOGS:
    path = LOGS_DIR / fname
    # Seven captures were quarantined to logs/unidentified-bus/ on 2026-10-04
    # (each has a channel matching no anchor set, so its bus cannot be named).
    # This list mixes moved and unmoved names -- vtruxoverflowrecoverytest
    # moved while test5/6/7 did not -- so resolve rather than hardcode either
    # location. Without this the moved ones would quietly print SKIP and the
    # run would look complete.
    if not path.exists():
        alt = LOGS_DIR / "unidentified-bus" / fname
        if alt.exists():
            path = alt
    if not path.exists():
        emit(f"  SKIP  {fname}  ({date_hint}) -- not found")
        continue

    b2_vals, b0_vals = scan_log(path)

    if not b2_vals:
        b2_summary = "NO 0x135 FRAMES"
    else:
        b2_unique = sorted(set(v for _, v in b2_vals))
        b2_modal  = max(b2_unique, key=lambda v: sum(1 for _, x in b2_vals if x == v))
        b2_transitions = sum(
            1 for i in range(1, len(b2_vals)) if b2_vals[i][1] != b2_vals[i-1][1]
        )
        b2_summary = (
            f"n={len(b2_vals)}  modal=0x{b2_modal:02x}={b2_modal}"
            f"  uq={len(b2_unique)}"
            f"  range=[0x{b2_unique[0]:02x}..0x{b2_unique[-1]:02x}]"
            f"  transitions={b2_transitions}"
        )

    if not b0_vals:
        b0_summary = "NO 0x649 FRAMES"
    else:
        b0_first = b0_vals[0][1]
        b0_last  = b0_vals[-1][1]
        b0_summary = f"B0: 0x{b0_first:02x} -> 0x{b0_last:02x}"

    evap_events = find_evap_completion(b0_vals) if b0_vals else []

    emit(f"[{date_hint}] {fname}")
    emit(f"  role: {role}")
    emit(f"  0x135 B2: {b2_summary}")
    emit(f"  0x649:    {b0_summary}")

    if evap_events:
        for t_ev, v_before, v_after in evap_events:
            b2_at_evap = "N/A"
            if b2_vals:
                candidates = [(abs(t - t_ev), v) for t, v in b2_vals]
                candidates.sort()
                b2_at_evap = f"0x{candidates[0][1]:02x}={candidates[0][1]}"
            emit(f"  ** EVAP COMPLETE at t={t_ev:.1f}s: 0x649 B0 0x{v_before:02x}->0x{v_after:02x}  0x135 B2 nearest={b2_at_evap}")

    emit()

emit("Done.")
OUT_PATH.write_text("\n".join(lines_out), encoding="utf-8")
print(f"Written to {OUT_PATH}", flush=True)
