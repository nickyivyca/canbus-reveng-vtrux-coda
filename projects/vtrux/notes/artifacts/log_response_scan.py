#!/usr/bin/env python3
"""Scan existing DTC interrogation logs for unrecognized response patterns.

Looks for frames that were captured in the logs but may not have been decoded
in real-time during the session:

  1. Any Rx frame in 0x700-0x7FF CAN ID range (diagnostic range)
     - flags frames with positive-response SIDs: 0x43/47/4A/58/59/50/62/7E
     - flags NRC frames (0x7F) and response-pending (0x78)
     - reports all unique patterns, not just known ones
  2. CAN IDs seen in 0x700-0x7FF that are OUTSIDE the expected 0x7DF-0x7EF range
     (would indicate a module we didn't know was there)
  3. J1939 extended-ID DM1 (PGN 0xFECA) or DM2 (PGN 0xFECB) frames from any SA
  4. 0x065B frames with non-zero DTC code in B6:B7
  5. All unique Tx frames in the diagnostic range (what was sent)
"""
import sys
from pathlib import Path
from collections import defaultdict

LOG_DIR = Path(__file__).parent
LOGS = sorted(LOG_DIR.glob("dtc_interrogation_*.log"))

if not LOGS:
    print("No dtc_interrogation_*.log files found in", LOG_DIR)
    sys.exit(1)

DIAG_RANGE = set(range(0x700, 0x800))

# 0x7DF-0x7EF: addresses the existing tool explicitly used or listened to
EXPECTED_DIAG = set(range(0x7DF, 0x7F0))

# Positive UDS/OBD/KWP response SIDs (in data[1] for SF, data[2] for FF)
POS_SIDS = {
    0x43: "OBD Mode43 stored DTC+",
    0x47: "OBD Mode47 pending DTC+",
    0x4A: "OBD Mode4A permanent DTC+",
    0x58: "KWP 0x58 ReadDTCByStatus+",
    0x59: "UDS 0x59 ReadDTCInfo+",
    0x50: "UDS 0x50 DSC+",
    0x62: "UDS 0x62 RDBI+",
    0x7E: "UDS 0x7E TesterPresent+",
}

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFnNotSupported",
    0x13: "badLength",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x78: "responsePending",
    0x80: "0x80 (non-standard, legacy echo?)",
}


def parse_line(line):
    """Parse a BUSMASTER log line. Returns (direction, arb_id, is_ext, dlc, data) or None."""
    parts = line.split()
    if len(parts) < 7 or parts[1] not in ("Rx", "Tx"):
        return None
    try:
        arb_id = int(parts[3], 16)
    except ValueError:
        return None
    direction = parts[1]
    is_ext = parts[4] == "x"
    try:
        dlc = int(parts[5])
    except ValueError:
        return None
    data = []
    for b in parts[6:6 + dlc]:
        try:
            data.append(int(b, 16))
        except ValueError:
            pass
    return direction, arb_id, is_ext, dlc, data


def describe_diag_rx(data):
    """Short description of a diagnostic Rx frame based on content."""
    if len(data) < 2:
        return f"short({len(data)}b)"
    pci_hi = (data[0] >> 4) & 0xF
    if pci_hi == 0:
        length = data[0] & 0xF
        sid = data[1] if len(data) > 1 else None
    elif pci_hi == 1:
        length = ((data[0] & 0xF) << 8) | (data[1] if len(data) > 1 else 0)
        sid = data[2] if len(data) > 2 else None
        return f"FF(len={length}) SID=0x{sid:02X}" if sid is not None else "FF(short)"
    elif pci_hi == 2:
        return f"CF(SN={data[0]&0xF})"
    elif pci_hi == 3:
        bs = data[1] if len(data) > 1 else "?"
        return f"FC(blocksize={bs})"
    else:
        return "raw: " + " ".join(f"{b:02X}" for b in data)

    if sid is None:
        return "SF(empty)"
    if sid == 0x7F:
        req_sid = data[2] if len(data) > 2 else 0
        nrc = data[3] if len(data) > 3 else 0
        nrc_name = NRC_NAMES.get(nrc, f"0x{nrc:02X}")
        return f"NRC(req=0x{req_sid:02X}, nrc={nrc_name})"
    label = POS_SIDS.get(sid)
    if label:
        extra = " ".join(f"{b:02X}" for b in data[2:])
        return f"{label} data=[{extra}]"
    return f"SF SID=0x{sid:02X}: " + " ".join(f"{b:02X}" for b in data)


# Aggregation structures
# diag_rx_patterns[(arb_id, data_hex)] = {"logs": set, "count": int}
diag_rx_patterns = defaultdict(lambda: {"logs": set(), "count": 0})
diag_tx_addrs = defaultdict(set)   # addr -> set of log names that sent to it
unexpected_ids = set()             # any 0x700-0x7FF ID outside expected range
j1939_dm_frames = []
dtc065b_frames = []
total_lines = 0

for log_path in LOGS:
    log_name = log_path.name
    print(f"Reading {log_name} ...", end="", flush=True)
    line_count = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parsed = parse_line(line)
            if parsed is None:
                continue
            direction, arb_id, is_ext, dlc, data = parsed
            line_count += 1

            # --- J1939 DM1/DM2 extended-ID frames ---
            if is_ext and direction == "Rx":
                pgn = (arb_id >> 8) & 0xFFFF
                if pgn in (0xFECA, 0xFECB):
                    sa = arb_id & 0xFF
                    dm_name = "DM1(active)" if pgn == 0xFECA else "DM2(prev-active)"
                    j1939_dm_frames.append((log_name, arb_id, sa, dm_name, list(data)))

            if is_ext:
                continue  # rest of checks are standard-ID only

            # --- 0x065B HCU DTC frames ---
            if arb_id == 0x065B and direction == "Rx":
                if len(data) >= 8:
                    dtc_raw = (data[6] << 8) | data[7]
                    if dtc_raw != 0:
                        dtc065b_frames.append((log_name, dtc_raw, list(data)))

            # --- 0x700-0x7FF diagnostic range ---
            if arb_id not in DIAG_RANGE:
                continue

            if arb_id not in EXPECTED_DIAG:
                unexpected_ids.add(arb_id)

            if direction == "Tx":
                diag_tx_addrs[arb_id].add(log_name)
            else:  # Rx
                data_hex = " ".join(f"{b:02X}" for b in data)
                key = (arb_id, data_hex)
                diag_rx_patterns[key]["logs"].add(log_name)
                diag_rx_patterns[key]["count"] += 1

    total_lines += line_count
    print(f" {line_count:,} frames")

print(f"\nTotal frames scanned across {len(LOGS)} logs: {total_lines:,}")
print()

# ---------------------------------------------------------------------------
# Report 1: Unexpected CAN IDs in diagnostic range
# ---------------------------------------------------------------------------
print("=" * 70)
print("1. UNEXPECTED IDs IN 0x700-0x7FF (outside 0x7DF-0x7EF)")
print("=" * 70)
if unexpected_ids:
    for aid in sorted(unexpected_ids):
        in_rx = [(hex_data, info) for (a, hex_data), info in diag_rx_patterns.items() if a == aid]
        in_tx = diag_tx_addrs.get(aid, set())
        print(f"  0x{aid:03X}  Tx-in: {sorted(in_tx) if in_tx else '(none)'}  "
              f"Rx-patterns: {len(in_rx)}")
        for hex_data, info in sorted(in_rx, key=lambda x: -x[1]["count"])[:5]:
            d = [int(b, 16) for b in hex_data.split()] if hex_data else []
            desc = describe_diag_rx(d)
            print(f"    x{info['count']:3d} [{', '.join(sorted(info['logs']))}]: "
                  f"{hex_data}  -- {desc}")
else:
    print("  None. Only 0x7DF-0x7EF IDs seen in diagnostic range.")
print()

# ---------------------------------------------------------------------------
# Report 2: Positive response and interesting frames at 0x7E8-0x7EF
# ---------------------------------------------------------------------------
print("=" * 70)
print("2. ALL UNIQUE Rx PATTERNS AT 0x7E8-0x7EF (deduplicated)")
print("=" * 70)
by_addr = defaultdict(list)
for (aid, hex_data), info in diag_rx_patterns.items():
    if 0x7E8 <= aid <= 0x7EF:
        by_addr[aid].append((hex_data, info))

for aid in sorted(by_addr.keys()):
    patterns = sorted(by_addr[aid], key=lambda x: -x[1]["count"])
    print(f"\n  0x{aid:03X}  ({len(patterns)} unique patterns):")
    for hex_data, info in patterns:
        d = [int(b, 16) for b in hex_data.split()] if hex_data else []
        desc = describe_diag_rx(d)
        # Flag positive responses specifically
        flag = ""
        if len(d) >= 2:
            pci_hi = (d[0] >> 4) & 0xF
            sid = d[1] if pci_hi == 0 else (d[2] if pci_hi == 1 and len(d) > 2 else None)
            if sid is not None and sid in POS_SIDS:
                flag = " <<< POSITIVE RESPONSE"
            elif sid is not None and sid == 0x7F and len(d) > 3 and d[3] == 0x78:
                flag = " <<< RESPONSE PENDING (0x78)"
        print(f"    x{info['count']:3d} [{', '.join(sorted(info['logs']))}]: "
              f"{hex_data}  -- {desc}{flag}")

# ---------------------------------------------------------------------------
# Report 3: J1939 DM1/DM2 frames
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("3. J1939 DM1/DM2 FRAMES (PGN 0xFECA/0xFECB, any SA)")
print("=" * 70)
if j1939_dm_frames:
    for log_name, arb_id, sa, dm_name, data in j1939_dm_frames:
        print(f"  [{log_name}] 0x{arb_id:08X}  SA=0x{sa:02X}  {dm_name}: "
              + " ".join(f"{b:02X}" for b in data))
else:
    print("  None found. No spontaneous DM1/DM2 broadcasts during interrogation sessions.")
print()

# ---------------------------------------------------------------------------
# Report 4: 0x065B non-zero DTC frames
# ---------------------------------------------------------------------------
print("=" * 70)
print("4. 0x065B HCU DTC FRAMES (non-zero DTC code)")
print("=" * 70)
if dtc065b_frames:
    for log_name, dtc_raw, data in dtc065b_frames:
        print(f"  [{log_name}] DTC=0x{dtc_raw:04X}: " + " ".join(f"{b:02X}" for b in data))
else:
    print("  None found.")
print()

# ---------------------------------------------------------------------------
# Report 5: Summary of what was sent (Tx) to each diag address
# ---------------------------------------------------------------------------
print("=" * 70)
print("5. Tx ADDRESSES USED (diagnostic range) -- coverage summary")
print("=" * 70)
sent_addrs = sorted(diag_tx_addrs.keys())
print(f"  Addresses TX'd to: {[f'0x{a:03X}' for a in sent_addrs]}")
print(f"  Range covered: 0x{min(sent_addrs):03X} - 0x{max(sent_addrs):03X}" if sent_addrs else "  (none)")
not_covered = sorted(a for a in range(0x700, 0x7F0) if a not in diag_tx_addrs)
if not_covered:
    print(f"  Not yet TX'd: 0x{not_covered[0]:03X} to 0x{not_covered[-1]:03X} "
          f"({len(not_covered)} addresses)")
print()
