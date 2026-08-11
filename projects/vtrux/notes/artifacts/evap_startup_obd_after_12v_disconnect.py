"""
Find the 12V battery disconnect/reconnect gap in a partstruck testdrive log,
then extract OBD bus traffic (0x7DF, 0x7E0-0x7E7, 0x7E8-0x7EF) in the window
immediately after reconnect to look for any Mode 22 or non-standard startup reads.
Also tracks 0x649 B0 value at key-on after reconnect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

OBD_REQ_IDS  = set(range(0x7DF, 0x7E8))
OBD_RESP_IDS = set(range(0x7E8, 0x7F0))
OBD_ALL = OBD_REQ_IDS | OBD_RESP_IDS

GAP_THRESHOLD_S = 3.0
POST_RECONNECT_WINDOW_S = 30.0

LOG_FILES = [
    r"projects\vtrux\logs\vtrux_partstruck_testdrive.log",
    r"projects\vtrux\logs\vtrux_partstruck_testdrive_part2.log",
]

def find_bus_ids(frames):
    from collections import Counter
    bus_ids = {}
    for f in frames:
        bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
    return bus_ids

def identify_obd_bus(bus_ids):
    obd_anchor = set(range(0x040, 0x045))
    for bus, ids in bus_ids.items():
        if ids & obd_anchor:
            return bus
    return None

def find_12v_gaps(frames, threshold=GAP_THRESHOLD_S):
    gaps = []
    prev_t = None
    for f in frames:
        if prev_t is not None:
            gap = f.timestamp - prev_t
            if gap > threshold:
                gaps.append((prev_t, f.timestamp, gap))
        prev_t = f.timestamp
    return gaps

def decode_obd_svc(data):
    if not data:
        return "empty"
    svc = data[0]
    if svc == 0x7F:
        return f"NegResp(svc=0x{data[1]:02X} nrc=0x{data[2]:02X})" if len(data) >= 3 else "NegResp"
    mode = svc & 0x3F
    names = {0x01:"Mode01", 0x02:"Mode02", 0x03:"Mode03", 0x04:"Mode04",
             0x07:"Mode07", 0x09:"Mode09", 0x0A:"Mode0A",
             0x21:"Mode01(resp)", 0x22:"Mode22(readDBI)", 0x41:"Mode01(resp)",
             0x42:"Mode02(resp)", 0x43:"Mode03(resp)", 0x47:"Mode07(resp)",
             0x49:"Mode09(resp)", 0x4A:"Mode0A(resp)", 0x62:"Mode22(resp)"}
    name = names.get(svc, f"svc=0x{svc:02X}")
    if svc in (0x01, 0x21, 0x41) and len(data) >= 2:
        name += f" pid=0x{data[1]:02X}"
    elif svc in (0x22, 0x62) and len(data) >= 3:
        name += f" did=0x{data[1]:02X}{data[2]:02X}"
    elif svc in (0x03, 0x43, 0x07, 0x47, 0x0A, 0x4A):
        pass
    return name

for log_path in LOG_FILES:
    p = Path(log_path)
    if not p.exists():
        print(f"\n=== {p.name}: NOT FOUND ===")
        continue

    print(f"\n{'='*60}")
    print(f"Log: {p.name}  ({p.stat().st_size // 1024 // 1024} MB)")
    print(f"{'='*60}")

    frames = list(parse_file(str(p)))
    if not frames:
        print("  No frames parsed.")
        continue

    print(f"  Total frames: {len(frames):,}  span: {frames[0].timestamp:.1f}s - {frames[-1].timestamp:.1f}s")

    bus_map = find_bus_ids(frames)
    obd_bus = identify_obd_bus(bus_map)
    print(f"  OBD bus: {obd_bus}  (anchor IDs 0x040-0x044 present)" if obd_bus is not None else "  OBD bus: not identified")

    gaps = find_12v_gaps(frames, GAP_THRESHOLD_S)
    if not gaps:
        print("  No 12V gaps found (no gap > 3s).")
        continue

    print(f"\n  Traffic gaps > {GAP_THRESHOLD_S}s:")
    for gap_start, gap_end, duration in gaps:
        print(f"    {gap_start:.3f}s -> {gap_end:.3f}s  ({duration:.1f}s gap)")

    PROP_RESP_IDS = {0x5E8, 0x5E9, 0x5EA, 0x5EB}
    DIAG_ALL = OBD_ALL | set(range(0x7E0, 0x7E8)) | PROP_RESP_IDS

    for gap_idx, (gap_start, gap_end, gap_dur) in enumerate(gaps):
        reconnect_t = gap_end
        window_end = reconnect_t + POST_RECONNECT_WINDOW_S
        print(f"\n  --- Gap {gap_idx+1}: {gap_start:.3f}s -> {gap_end:.3f}s ({gap_dur:.1f}s) ---")
        print(f"  Analyzing window after reconnect: {reconnect_t:.3f}s - {window_end:.3f}s")

        window_frames = [f for f in frames if reconnect_t <= f.timestamp <= window_end]
        print(f"  Frames in window: {len(window_frames):,}")

        print(f"  0x649 B0 value at reconnect (first 5 unique values):")
        seen_b0 = []
        for f in window_frames:
            if f.arbitration_id == 0x649 and len(f.data) >= 1:
                b0 = f.data[0]
                if not seen_b0 or b0 != seen_b0[-1][1]:
                    seen_b0.append((f.timestamp - reconnect_t, b0))
                if len(seen_b0) >= 5:
                    break
        for rel_t, b0 in seen_b0:
            print(f"    +{rel_t:.3f}s  B0=0x{b0:02X}  bit7={'SET' if b0 & 0x80 else 'clear'}")
        if not seen_b0:
            print("    (none)")

        all_buses = set(f.bus for f in window_frames)
        for bus in sorted(all_buses):
            diag_frames = [f for f in window_frames
                           if f.bus == bus and f.arbitration_id in DIAG_ALL]
            if not diag_frames:
                continue
            print(f"\n  Diagnostic traffic bus{bus} in window ({len(diag_frames)} frames, first 80):")
            shown = 0
            for f in diag_frames:
                rel_t = f.timestamp - reconnect_t
                data_hex = " ".join(f"{b:02X}" for b in f.data)
                svc_label = decode_obd_svc(f.data) if f.data else ""
                prop = " [GM-PROP]" if f.arbitration_id in PROP_RESP_IDS else ""
                print(f"    +{rel_t:6.3f}s  bus{f.bus}  id=0x{f.arbitration_id:04X}{prop}  [{data_hex}]  {svc_label}")
                shown += 1
                if shown >= 80:
                    remaining = len(diag_frames) - shown
                    print(f"    ... ({remaining} more)")
                    break

            seen_svcs = set()
            for f in diag_frames:
                if f.data:
                    seen_svcs.add(f.data[0])
            print(f"  Service bytes on bus{bus}: {sorted(f'0x{s:02X}' for s in seen_svcs)}")

            mode22 = [f for f in diag_frames if f.data and f.data[0] in (0x22, 0x62)]
            if mode22:
                print(f"  *** Mode 22 frames: {len(mode22)}")
            prop_seen = [f for f in diag_frames if f.arbitration_id in PROP_RESP_IDS]
            if prop_seen:
                print(f"  *** GM proprietary responses (0x5E8 etc): {len(prop_seen)}")
