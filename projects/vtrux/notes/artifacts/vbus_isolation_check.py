"""
vbus_isolation_check.py
Decode bcm_vbus_pos and bcm_vbus_neg (0x0440) from Vtrux PT bus logs.
Prints per-log stats and periodic samples to check isolation meter behavior.

Usage:
  py -3.12 projects/vtrux/notes/artifacts/vbus_isolation_check.py [phase]
Phases: stats, samples
"""

import sys
import os
import cantools

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
DBC_PATH = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")

LOGS = {
    "og_highway_drive":  os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs", "oghighwaydrive.log"),
    "parts_truck_M1_T0": os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs", "truk1log_M1_T0.log"),
}

TARGET_ID = 0x440
PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}  # BCM/MCU IDs only on PT bus

def parse_busmaster_line(line):
    """Return (timestamp_s, bus, can_id, data_bytes) or None."""
    line = line.strip()
    if not line or line.startswith("***") or line.startswith("Start") or line.startswith("***"):
        return None
    parts = line.split()
    # BUSMASTER format: HH:MM:SS:TTTT Rx/Tx bus_ch  ID  DLC  B0 B1 ...
    if len(parts) < 6:
        return None
    try:
        ts_str = parts[0]
        hh, mm, ss, tt = ts_str.split(":")
        ts = int(hh)*3600 + int(mm)*60 + int(ss) + int(tt)/10000.0
        # format: timestamp Rx/Tx channel CAN_ID frame_type DLC B0 B1 ...
        bus = int(parts[2])
        can_id = int(parts[3], 16)
        # parts[4] = frame type 's'/'e', parts[5] = DLC
        dlc = int(parts[5])
        data = bytes(int(x, 16) for x in parts[6:6+dlc])
        return (ts, bus, can_id, data)
    except Exception:
        return None

def identify_pt_bus(log_path):
    """Identify the bus channel carrying PT bus messages by anchor ID presence."""
    counts = {}
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            r = parse_busmaster_line(line)
            if r is None:
                continue
            ts, bus, can_id, data = r
            if can_id in PT_BUS_ANCHOR_IDS:
                counts[bus] = counts.get(bus, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)

def decode_vbus(db, data):
    """Decode bcm_vbus_pos and bcm_vbus_neg from 0x440 frame data bytes."""
    try:
        msg = db.get_message_by_frame_id(TARGET_ID)
        decoded = msg.decode(data, decode_choices=False)
        return decoded.get("bcm_vbus_pos"), decoded.get("bcm_vbus_neg")
    except Exception:
        return None, None

def run_stats(log_name, log_path, db):
    print(f"\n=== {log_name} ===")
    pt_bus = identify_pt_bus(log_path)
    if pt_bus is None:
        print("  Could not identify PT bus channel")
        return
    print(f"  PT bus channel: {pt_bus}")

    pos_vals = []
    neg_vals = []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            r = parse_busmaster_line(line)
            if r is None:
                continue
            ts, bus, can_id, data = r
            if bus != pt_bus or can_id != TARGET_ID:
                continue
            vpos, vneg = decode_vbus(db, data)
            if vpos is not None:
                pos_vals.append(vpos)
            if vneg is not None:
                neg_vals.append(vneg)

    if not pos_vals:
        print("  No 0x440 frames decoded")
        return

    diffs = [p + abs(n) if n < 0 else p - n for p, n in zip(pos_vals, neg_vals)]

    print(f"  Frames decoded: {len(pos_vals)}")
    print(f"  bcm_vbus_pos : min={min(pos_vals):.2f}  max={max(pos_vals):.2f}  mean={sum(pos_vals)/len(pos_vals):.2f} V")
    print(f"  bcm_vbus_neg : min={min(neg_vals):.2f}  max={max(neg_vals):.2f}  mean={sum(neg_vals)/len(neg_vals):.2f} V")
    print(f"  pos+neg (sum, ~0 if symmetric): min={min(diffs):.2f}  max={max(diffs):.2f}  mean={sum(diffs)/len(diffs):.2f} V")
    # "distance from chassis" -- if isolated, |pos| ~ |neg|, sum ~ 0
    # if chassis tied to neg: neg -> 0, pos -> full pack voltage
    # if chassis tied to pos: pos -> 0, neg -> -full pack voltage

def run_samples(log_name, log_path, db, every_n=50):
    """Print every Nth decoded frame to show time trend."""
    print(f"\n=== {log_name} -- time samples (every {every_n} frames) ===")
    pt_bus = identify_pt_bus(log_path)
    if pt_bus is None:
        print("  Could not identify PT bus channel")
        return

    n = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            r = parse_busmaster_line(line)
            if r is None:
                continue
            ts, bus, can_id, data = r
            if bus != pt_bus or can_id != TARGET_ID:
                continue
            vpos, vneg = decode_vbus(db, data)
            if vpos is None:
                continue
            if n % every_n == 0:
                vsum = vpos + vneg
                print(f"  t={ts:9.2f}s  pos={vpos:7.2f} V  neg={vneg:7.2f} V  sum={vsum:+7.2f} V")
            n += 1

if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "stats"
    db = cantools.db.load_file(DBC_PATH)

    if phase == "stats":
        for name, path in LOGS.items():
            if "isolation" in name:
                continue  # skip isolation for now
            run_stats(name, path, db)
    elif phase == "samples":
        for name, path in LOGS.items():
            if "isolation" in name:
                continue
            run_samples(name, path, db, every_n=30)
    elif phase == "isolation_stats":
        run_stats("isolation_test", LOGS["isolation_test"], db)
    elif phase == "isolation_samples":
        run_samples("isolation_test", LOGS["isolation_test"], db, every_n=10)
    elif phase == "status_bits":
        # Decode all 0x440 status fields and show transitions + summary per log
        import collections
        fields = ["bcm_mainc_stat", "bcm_fault_mon", "bcm_balancing", "bcm_fgd", "bcm_balancing_cnt"]
        for name, path in LOGS.items():
            print(f"\n=== {name} ===")
            pt_bus = identify_pt_bus(path)
            if pt_bus is None:
                print("  Could not identify PT bus"); continue
            msg = db.get_message_by_frame_id(TARGET_ID)
            prev = None
            counts = {f: collections.Counter() for f in fields}
            transitions = {f: [] for f in fields}
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_busmaster_line(line)
                    if r is None: continue
                    ts, bus, can_id, data = r
                    if bus != pt_bus or can_id != TARGET_ID: continue
                    try:
                        dec = msg.decode(data, decode_choices=False)
                    except Exception:
                        continue
                    for field in fields:
                        val = dec.get(field)
                        if val is None: continue
                        counts[field][val] += 1
                        if prev is not None and prev.get(field) != val:
                            transitions[field].append((ts, prev.get(field), val))
                    prev = dec
            for field in fields:
                uniq = sorted(counts[field].keys())
                total = sum(counts[field].values())
                print(f"  {field}: {len(uniq)} unique values {uniq}  (total frames: {total})")
                for ts, old, new in transitions[field]:
                    print(f"    t={ts:.2f}s  {old} -> {new}")
    elif phase == "shutdown":
        # Print last 60 decoded frames from each non-isolation log to see shutdown behavior
        for name, path in LOGS.items():
            if "isolation" in name:
                continue
            print(f"\n=== {name} -- last 60 frames ===")
            pt_bus = identify_pt_bus(path)
            if pt_bus is None:
                print("  Could not identify PT bus"); continue
            frames = []
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_busmaster_line(line)
                    if r is None: continue
                    ts, bus, can_id, data = r
                    if bus != pt_bus or can_id != TARGET_ID: continue
                    vpos, vneg = decode_vbus(db, data)
                    if vpos is not None:
                        frames.append((ts, vpos, vneg))
            for ts, vpos, vneg in frames[-60:]:
                vsum = vpos + vneg
                print(f"  t={ts:9.2f}s  pos={vpos:7.2f} V  neg={vneg:7.2f} V  sum={vsum:+7.2f} V")
    elif phase == "bcm_status":
        # 0x410 status bits: alarm, epo, ready, hvil_mon, on_plug, cpwr_cmd, chg_done
        # Show unique values and every transition per log
        import collections
        STATUS_ID = 0x410
        STATUS_FIELDS = ["bcm_alarm", "bcm_epo", "bcm_ready", "bcm_hvil_mon",
                         "bcm_on_plug", "bcm_cpwr_cmd", "bcm_chg_done",
                         "bcm_mainc_stat", "bcm_chgc_stat"]
        msg = db.get_message_by_frame_id(STATUS_ID)
        for name, path in LOGS.items():
            print(f"\n=== {name} ===")
            pt_bus = identify_pt_bus(path)
            if pt_bus is None:
                print("  Could not identify PT bus"); continue
            prev = None
            counts = {f: collections.Counter() for f in STATUS_FIELDS}
            transitions = {f: [] for f in STATUS_FIELDS}
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_busmaster_line(line)
                    if r is None: continue
                    ts, bus, can_id, data = r
                    if bus != pt_bus or can_id != STATUS_ID: continue
                    try:
                        dec = msg.decode(data, decode_choices=True)
                    except Exception:
                        continue
                    for field in STATUS_FIELDS:
                        val = str(dec.get(field))
                        if val == 'None': continue
                        counts[field][val] += 1
                        if prev is not None and prev.get(field) != val:
                            transitions[field].append((ts, prev.get(field), val))
                    prev = {f: str(dec.get(f)) for f in STATUS_FIELDS}
            for field in STATUS_FIELDS:
                uniq = sorted(str(k) for k in counts[field].keys())
                print(f"  {field}: {uniq}")
                for ts, old, new in transitions[field]:
                    print(f"    t={ts:.2f}s  {old} -> {new}")

    elif phase == "gfd":
        # bcm_gfd from 0x410: show stats + transitions across all logs
        GFD_ID = 0x410
        msg = db.get_message_by_frame_id(GFD_ID)
        for name, path in LOGS.items():
            print(f"\n=== {name} ===")
            pt_bus = identify_pt_bus(path)
            if pt_bus is None:
                print("  Could not identify PT bus"); continue
            vals = []
            transitions = []
            prev_val = None
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_busmaster_line(line)
                    if r is None: continue
                    ts, bus, can_id, data = r
                    if bus != pt_bus or can_id != GFD_ID: continue
                    try:
                        dec = msg.decode(data, decode_choices=False)
                    except Exception:
                        continue
                    gfd = dec.get("bcm_gfd")
                    if gfd is None: continue
                    # exclude sentinel (raw==0xFFE -> value==1023.5)
                    if abs(gfd - 1023.5) < 0.1: continue
                    vals.append((ts, gfd))
                    if prev_val is not None and abs(gfd - prev_val) > 0.5:
                        transitions.append((ts, prev_val, gfd))
                    prev_val = gfd
            if not vals:
                print("  No valid gfd frames"); continue
            gfd_only = [v for _, v in vals]
            print(f"  Frames: {len(gfd_only)}  min={min(gfd_only):.2f}  max={max(gfd_only):.2f}  mean={sum(gfd_only)/len(gfd_only):.2f}")
            print(f"  Unique values ({len(set(gfd_only))}): {sorted(set(gfd_only))[:20]}{'...' if len(set(gfd_only))>20 else ''}")
            if transitions:
                print(f"  Transitions (>{0.5} step):")
                for ts, old, new in transitions:
                    print(f"    t={ts:.2f}s  {old:.2f} -> {new:.2f}")
            else:
                print("  No transitions (signal stable throughout)")

    else:
        print(f"Unknown phase: {phase}")
