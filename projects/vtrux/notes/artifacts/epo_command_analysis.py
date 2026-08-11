import os
import re

# For each fault log (or ordered set), scan for:
#   - 0x400 B0 bit1 (hsc_bcm_epo) ever set
#   - 0x410 B1 changes (fault state machine transitions)
# Report timing of any epo=1 relative to 0x410 B1 changes

FAULT_LOGS = [
    ("pre-swap actual-failed-charges (June 25 session)", [
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T0.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T1.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T2.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T3.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T4.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T5.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T6.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T7.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T8.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T9.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M0_T10.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M1_T10.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M1_T11.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M1_T12.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M1_T13.log",
        "projects/vtrux/logs/actual-failed-charges/truklog_M1_T14.log",
    ]),
    ("pre-swap full-charge-then-fail", [
        "projects/vtrux/logs/full-charge-then-fail.log",
    ]),
    ("post-swap rainychargedebug", [
        "projects/vtrux/logs/rainychargedebug.log",
    ]),
    ("post-swap rainychargedebug2", [
        "projects/vtrux/logs/rainychargedebug2.log",
    ]),
    ("post-swap rainychargedebug3", [
        "projects/vtrux/logs/rainychargedebug3.log",
    ]),
    ("post-swap rainychargedebug4", [
        "projects/vtrux/logs/rainychargedebug4.log",
    ]),
    ("interlock test 1", [
        "projects/vtrux/logs/vtruxinterlocktest.log",
    ]),
    ("interlock test 2", [
        "projects/vtrux/logs/vtruxinterlocktest2.log",
    ]),
    ("isolation fault test", [
        "projects/vtrux/logs/vtruxisolationtest.log",
    ]),
]

def ts_to_sec(ts):
    parts = ts.split(":")
    if len(parts) == 4:
        try:
            h, m, s, t = parts
            return int(h)*3600 + int(m)*60 + int(s) + int(t)/10000.0
        except ValueError:
            return None
    return None

def parse_logs(files):
    events_400 = []
    events_410 = []

    for fpath in files:
        if not os.path.exists(fpath):
            print(f"  MISSING: {fpath}")
            continue
        fname = os.path.basename(fpath)
        with open(fpath, "r", encoding="latin-1") as f:
            for line in f:
                if line.startswith("*") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 6:
                    continue
                ts_str = parts[0]
                can_id = parts[3]
                frame_type = parts[4]
                if frame_type != "s":
                    continue
                sec = ts_to_sec(ts_str)
                if sec is None:
                    continue
                try:
                    data = [int(x, 16) for x in parts[6:]]
                except ValueError:
                    continue

                if can_id == "0x400" and len(data) >= 1:
                    b0 = data[0]
                    epo = (b0 >> 1) & 1
                    events_400.append((sec, ts_str, fname, b0, epo))

                elif can_id == "0x410" and len(data) >= 2:
                    b1 = data[1]
                    events_410.append((sec, ts_str, fname, b1))

    return events_400, events_410

for label, files in FAULT_LOGS:
    print(f"\n{'='*70}")
    print(f"LOG SET: {label}")
    print(f"{'='*70}")

    events_400, events_410 = parse_logs(files)

    if not events_400:
        print("  0x400: NO FRAMES FOUND")
        continue

    epo_frames = [(s, ts, fn, b0) for s, ts, fn, b0, epo in events_400 if epo == 1]
    all_b0_values = sorted(set(b0 for s, ts, fn, b0, epo in events_400))

    print(f"  0x400 frames: {len(events_400)}")
    print(f"  0x400 B0 unique values: {[hex(v) for v in all_b0_values]}")

    if not epo_frames:
        print("  hsc_bcm_epo (bit1): NEVER SET -- epo=0 throughout")
    else:
        print(f"  hsc_bcm_epo (bit1): SET in {len(epo_frames)} frames")
        print(f"  First epo=1: {epo_frames[0][1]} ({epo_frames[0][2]}) B0=0x{epo_frames[0][3]:02X}")
        print(f"  Last  epo=1: {epo_frames[-1][1]} ({epo_frames[-1][2]}) B0=0x{epo_frames[-1][3]:02X}")

        if events_410:
            epo_first_sec = epo_frames[0][0]
            b1_prev = None
            b1_transitions = [(s, ts, fn, b1) for s, ts, fn, b1 in events_410
                              if b1 != b1_prev]
            b1_transitions_deduped = []
            prev = None
            for ev in events_410:
                if ev[3] != prev:
                    b1_transitions_deduped.append(ev)
                    prev = ev[3]

            print(f"  0x410 B1 transitions:")
            for s, ts, fn, b1 in b1_transitions_deduped:
                rel = s - epo_first_sec
                marker = " <-- FIRST epo=1" if abs(rel) < 0.05 else f"  ({rel:+.3f}s vs first epo=1)"
                print(f"    {ts} ({fn})  B1=0x{b1:02X}{marker}")
        else:
            print("  0x410: NO FRAMES (ext-only or not present)")
