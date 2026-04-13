#!/usr/bin/env python3
"""Extract and decode OBD-II and J1939 DM diagnostic reads from a CAN log file.

Finds all OBD-II request/response exchanges and J1939 DM1/DM2 broadcasts,
reassembles ISO-TP multi-frame responses, decodes stored/pending/permanent DTCs,
and prints a chronological report.

Covers:
  Standard 11-bit OBD-II (ISO 15765-4):
    Requests  0x7DF (broadcast), 0x7E0-0x7E7 (physical to ECU 0-7)
    Responses 0x7E8-0x7EF (from ECU 0-7)
  J1939 (SAE J1939-73):
    DM1  PGN 0xFECA  -- active DTCs broadcast
    DM2  PGN 0xFECB  -- previously active DTCs broadcast

OBD service modes decoded:
  01 / 0x41  Show current data     (PID 0x01: MIL on/off, stored DTC count)
  02 / 0x42  Show freeze frame
  03 / 0x43  Stored DTCs
  07 / 0x47  Pending DTCs
  09 / 0x49  Vehicle info          (VIN, calibration IDs)
  0A / 0x4A  Permanent DTCs
  0x7F       Negative response

Usage:
  py -3.12 projects/vtrux/tools/extract_obd.py LOG [LOG ...]
  py -3.12 projects/vtrux/tools/extract_obd.py LOG --bus 1
  py -3.12 projects/vtrux/tools/extract_obd.py LOG --j1939-only
  py -3.12 projects/vtrux/tools/extract_obd.py LOG --output report.txt
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from canre.parsers import parse_file
from canre.utils.merge import merge_files

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OBD_REQ_IDS  = set(range(0x7DF, 0x7E8))   # 0x7DF + 0x7E0-0x7E7
OBD_RESP_IDS = set(range(0x7E8, 0x7F0))   # 0x7E8-0x7EF

J1939_PGN_DM1 = 0xFECA
J1939_PGN_DM2 = 0xFECB

SVC_NAMES = {
    0x01: "Mode01(current)",
    0x02: "Mode02(freeze)",
    0x03: "Mode03(stored)",
    0x04: "Mode04(clear)",
    0x05: "Mode05(O2tests)",
    0x06: "Mode06(onboardtest)",
    0x07: "Mode07(pending)",
    0x08: "Mode08(control)",
    0x09: "Mode09(vehicleinfo)",
    0x0A: "Mode0A(permanent)",
}

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

# ---------------------------------------------------------------------------
# DTC decoding
# ---------------------------------------------------------------------------

DTC_TYPE = ["P", "C", "B", "U"]


def decode_dtc(hi: int, lo: int) -> str:
    """Decode a 2-byte OBD DTC into 'P0300' style string."""
    t = (hi >> 6) & 0x03
    prefix = DTC_TYPE[t]
    code = ((hi & 0x3F) << 8) | lo
    return f"{prefix}{code:04X}"


def decode_j1939_dtc(b0: int, b1: int, b2: int, b3: int) -> str:
    """Decode a 4-byte J1939 SPN/FMI DTC.

    J1939 DTC layout (SAE J1939-73 Table 5):
      Bytes 0-2 (bits 23-0): SPN bits 19-0 in B0[7:0]+B1[7:0]+B2[7:3]
                             SPN bits 25-20 in B3[7:2]  (if supported)
                             Actually standard short form:
      B0, B1      = SPN[7:0], SPN[15:8]
      B2[7:3]     = SPN[20:16]
      B2[2:0]     = FMI[4:2]   (high 3 bits of FMI)
      B3[7:5]     = FMI[2:0]   (low bits -- actually varies by implementation)
    Simple decode used here:
      SPN = B0 | (B1 << 8) | ((B2 >> 3) << 16)
      FMI = B2 & 0x1F
      OC  = B3 & 0x7F  (occurrence count)
    """
    spn = b0 | (b1 << 8) | ((b2 >> 3) << 16)
    fmi = b2 & 0x1F
    oc  = b3 & 0x7F
    return f"SPN={spn} FMI={fmi} OC={oc}"


# ---------------------------------------------------------------------------
# ISO-TP reassembly
# ---------------------------------------------------------------------------

class ISOTPReassembler:
    """Minimal ISO-TP (ISO 15765-2) reassembler.

    Tracks in-progress multi-frame transfers keyed by (bus, arbitration_id).
    Returns payload bytes when a complete PDU is received, None otherwise.
    """

    def __init__(self):
        self._pending = {}   # (bus, arbitration_id) -> {'expected_len': int, 'data': bytearray, 'sn': int}

    def feed(self, bus: int, arbitration_id: int, raw: bytes):
        """Feed one CAN frame. Returns complete payload bytes or None."""
        if not raw:
            return None
        frame_type = (raw[0] >> 4) & 0x0F

        if frame_type == 0x0:   # Single frame
            length = raw[0] & 0x0F
            if length == 0 or length > len(raw) - 1:
                return None
            self._pending.pop((bus, arbitration_id), None)
            return bytes(raw[1:1 + length])

        elif frame_type == 0x1:  # First frame
            if len(raw) < 2:
                return None
            length = ((raw[0] & 0x0F) << 8) | raw[1]
            data = bytearray(raw[2:])
            self._pending[(bus, arbitration_id)] = {
                'expected_len': length,
                'data': data,
                'sn': 1,
            }
            return None   # Wait for consecutive frames

        elif frame_type == 0x2:  # Consecutive frame
            key = (bus, arbitration_id)
            if key not in self._pending:
                return None
            sn = raw[0] & 0x0F
            state = self._pending[key]
            if sn != state['sn']:
                self._pending.pop(key, None)
                return None
            state['data'].extend(raw[1:])
            state['sn'] = (state['sn'] + 1) & 0x0F
            if len(state['data']) >= state['expected_len']:
                payload = bytes(state['data'][:state['expected_len']])
                self._pending.pop(key, None)
                return payload
            return None

        elif frame_type == 0x3:  # Flow control (from tester, ignore)
            return None

        return None


# ---------------------------------------------------------------------------
# OBD exchange tracking
# ---------------------------------------------------------------------------

class OBDExchange:
    """One request + zero or more responses."""

    def __init__(self, t: float, bus: int, req_id: int, payload: bytes):
        self.t_req    = t
        self.bus      = bus
        self.req_id   = req_id
        self.req_data = payload
        self.responses = []   # list of (t, resp_id, payload_bytes)

    def add_response(self, t: float, resp_id: int, payload: bytes):
        self.responses.append((t, resp_id, payload))


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------

def decode_response_payload(payload: bytes) -> str:
    """Decode an OBD response payload (after ISO-TP unwrap) to human-readable text."""
    if len(payload) < 2:
        return f"(too short: {payload.hex()})"

    svc = payload[0]

    if svc == 0x7F:
        req_svc   = payload[1] if len(payload) > 1 else 0
        nrc       = payload[2] if len(payload) > 2 else 0
        nrc_name  = NRC_NAMES.get(nrc, "unknown")
        svc_name  = SVC_NAMES.get(req_svc, hex(req_svc))
        return f"NegativeResponse svc={svc_name} NRC=0x{nrc:02X}({nrc_name})"

    resp_mode = svc - 0x40
    if resp_mode < 0:
        return f"(unexpected svc=0x{svc:02X} raw={payload.hex()})"

    if resp_mode == 0x01:
        if len(payload) < 3:
            return f"Mode01 PID=0x{payload[1]:02X} (no data)"
        pid = payload[1]
        data = payload[2:]
        if pid == 0x01 and len(data) >= 4:
            mil        = (data[0] >> 7) & 1
            dtc_count  = data[0] & 0x7F
            return f"Mode01/PID01 MIL={'ON' if mil else 'off'} stored_dtc_count={dtc_count}"
        if pid == 0x41 and len(data) >= 4:
            supported = int.from_bytes(data[:4], 'big')
            return f"Mode01/PID41 monitor_status=0x{supported:08X}"
        return f"Mode01 PID=0x{pid:02X} data={data.hex()}"

    if resp_mode in (0x03, 0x07, 0x0A):
        mode_label = {3: "stored", 7: "pending", 10: "permanent"}[resp_mode]
        if len(payload) < 2:
            return f"Mode{resp_mode:02X}({mode_label}) (empty)"
        n = payload[1]
        dtcs = []
        for i in range(n):
            base = 2 + i * 2
            if base + 1 < len(payload):
                dtcs.append(decode_dtc(payload[base], payload[base + 1]))
        if not dtcs and n > 0:
            return f"Mode{resp_mode:02X}({mode_label}) n={n} (incomplete payload, raw={payload.hex()})"
        if not dtcs:
            return f"Mode{resp_mode:02X}({mode_label}) no DTCs"
        return f"Mode{resp_mode:02X}({mode_label}) n={n} DTCs=[{', '.join(dtcs)}]"

    if resp_mode == 0x09:
        if len(payload) < 2:
            return "Mode09 (empty)"
        pid = payload[1]
        data = payload[2:]
        try:
            text = data.decode('ascii', errors='replace').rstrip('\x00')
        except Exception:
            text = data.hex()
        return f"Mode09 PID=0x{pid:02X} '{text}'"

    return f"Mode{resp_mode:02X} raw={payload.hex()}"


def decode_request_payload(payload: bytes) -> str:
    if len(payload) < 1:
        return "(empty)"
    svc = payload[0]
    name = SVC_NAMES.get(svc, f"svc=0x{svc:02X}")
    if len(payload) > 1:
        return f"{name} PID/sub=0x{payload[1]:02X}"
    return name


# ---------------------------------------------------------------------------
# J1939 DM parsing
# ---------------------------------------------------------------------------

def decode_j1939_dm(pgn: int, sa: int, data: bytes) -> str:
    label = "DM1(active)" if pgn == J1939_PGN_DM1 else "DM2(prev-active)"
    if len(data) < 2:
        return f"J1939 {label} SA=0x{sa:02X} (too short)"

    lamp_byte = data[0]
    protect  = (lamp_byte >> 6) & 0x03
    amber    = (lamp_byte >> 4) & 0x03
    red      = (lamp_byte >> 2) & 0x03
    malfunction = lamp_byte & 0x03

    lamp_str = []
    if protect  != 0x03: lamp_str.append(f"protect={'on' if protect==0 else 'off'}")
    if amber    != 0x03: lamp_str.append(f"amber={'on' if amber==0 else 'off'}")
    if red      != 0x03: lamp_str.append(f"red={'on' if red==0 else 'off'}")
    if malfunction != 0x03: lamp_str.append(f"mil={'on' if malfunction==0 else 'off'}")

    dtcs = []
    i = 2
    while i + 3 < len(data):
        dtcs.append(decode_j1939_dtc(data[i], data[i+1], data[i+2], data[i+3]))
        i += 4

    result = f"J1939 {label} SA=0x{sa:02X}"
    if lamp_str:
        result += f" lamps=[{', '.join(lamp_str)}]"
    if dtcs:
        result += f" DTCs=[{'; '.join(dtcs)}]"
    else:
        result += " no DTCs"
    return result


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse(frames, bus_filter=None, j1939_only=False, out=sys.stdout):
    reassembler = ISOTPReassembler()

    obd_frames    = []   # (t, bus, arbitration_id, payload)  -- fully reassembled
    j1939_events  = []   # (t, bus, arbitration_id, pgn, sa, data)

    for f in frames:
        if bus_filter is not None and f.bus != bus_filter:
            continue
        arbitration_id = f.arbitration_id
        data   = f.data

        # J1939 DM1 / DM2 -- extended ID, PGN in bits 17-0 of 29-bit ID
        if f.is_extended:
            pgn = (arbitration_id >> 8) & 0x1FFFF
            sa  = arbitration_id & 0xFF
            if pgn in (J1939_PGN_DM1, J1939_PGN_DM2):
                j1939_events.append((f.timestamp, f.bus, arbitration_id, pgn, sa, data))
            continue

        if j1939_only:
            continue

        if arbitration_id in OBD_REQ_IDS or arbitration_id in OBD_RESP_IDS:
            payload = reassembler.feed(f.bus, arbitration_id, data)
            if payload is not None:
                obd_frames.append((f.timestamp, f.bus, arbitration_id, payload))

    if not obd_frames and not j1939_events:
        print("No OBD or J1939 DM frames found.", file=out)
        return

    # -----------------------------------------------------------------------
    # Print OBD section
    # -----------------------------------------------------------------------

    if not j1939_only and obd_frames:
        print("=" * 68, file=out)
        print("OBD-II EXCHANGES", file=out)
        print("=" * 68, file=out)

        # Group into request+response pairs
        # Strategy: walk chronologically; each request on 0x7DF or 0x7E0-E7
        # is a new exchange; responses on 0x7E8-EF within 0.5s are attached.

        exchanges = []
        pending   = {}   # bus -> current exchange

        all_sorted = sorted(obd_frames, key=lambda x: x[0])
        for (t, bus, arbitration_id, payload) in all_sorted:
            if arbitration_id in OBD_REQ_IDS:
                exch = OBDExchange(t, bus, arbitration_id, payload)
                pending[bus] = exch
                exchanges.append(exch)
            elif arbitration_id in OBD_RESP_IDS:
                exch = pending.get(bus)
                if exch and (t - exch.t_req) < 0.5:
                    exch.add_response(t, arbitration_id, payload)
                else:
                    # Unsolicited / late response -- create orphan entry
                    orphan = OBDExchange(t, bus, arbitration_id, payload)
                    orphan.responses.append((t, arbitration_id, payload))
                    exchanges.append(orphan)

        # Collapse duplicate consecutive identical exchanges for readability
        printed = []
        for exch in exchanges:
            sig = (exch.bus, exch.req_id, exch.req_data,
                   tuple((r[1], r[2]) for r in exch.responses))
            if printed and printed[-1] == sig:
                continue
            printed.append(sig)

            # Print request
            t_str = f"t={exch.t_req:8.2f}s"
            src   = f"id=0x{exch.req_id:03X}"
            req_decoded = decode_request_payload(exch.req_data)
            print(f"{t_str}  Bus{exch.bus}  {src} (req)  {req_decoded}", file=out)

            # Print responses
            for (tr, resp_id, rpayload) in exch.responses:
                resp_decoded = decode_response_payload(rpayload)
                dt = tr - exch.t_req
                print(f"         +{dt*1000:5.1f}ms  Bus{exch.bus}  id=0x{resp_id:03X} (rsp)  {resp_decoded}", file=out)

        # Summary counts
        dtc_sets = defaultdict(set)   # mode -> set of DTC strings
        for exch in exchanges:
            for (_, _, rpayload) in exch.responses:
                svc = rpayload[0] if rpayload else 0
                if svc - 0x40 in (3, 7, 10):
                    mode = svc - 0x40
                    n = rpayload[1] if len(rpayload) > 1 else 0
                    for i in range(n):
                        base = 2 + i * 2
                        if base + 1 < len(rpayload):
                            dtc_sets[mode].add(decode_dtc(rpayload[base], rpayload[base + 1]))

        if any(dtc_sets.values()):
            print(file=out)
            print("--- DTC Summary ---", file=out)
            for mode, label in [(3, "Stored"), (7, "Pending"), (10, "Permanent")]:
                if dtc_sets[mode]:
                    print(f"  {label}: {', '.join(sorted(dtc_sets[mode]))}", file=out)

    # -----------------------------------------------------------------------
    # Print J1939 section
    # -----------------------------------------------------------------------

    if j1939_events:
        print(file=out)
        print("=" * 68, file=out)
        print("J1939 DM BROADCASTS", file=out)
        print("=" * 68, file=out)

        prev_sig = None
        repeat_count = 0
        for (t, bus, arbitration_id, pgn, sa, data) in sorted(j1939_events, key=lambda x: x[0]):
            decoded = decode_j1939_dm(pgn, sa, data)
            sig = (bus, arbitration_id, data.hex())
            if sig == prev_sig:
                repeat_count += 1
                continue
            if repeat_count:
                print(f"  ... repeated {repeat_count} more time(s) ...", file=out)
                repeat_count = 0
            print(f"t={t:8.2f}s  Bus{bus}  id=0x{arbitration_id:08X}  {decoded}", file=out)
            prev_sig = sig
        if repeat_count:
            print(f"  ... repeated {repeat_count} more time(s) ...", file=out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Extract and decode OBD-II and J1939 DM DTCs from a CAN log file."
    )
    p.add_argument("files", nargs="+", metavar="LOG", help="CAN log file(s)")
    p.add_argument("--bus", type=int, default=None,
                   help="Restrict to a single bus number (1-indexed)")
    p.add_argument("--j1939-only", action="store_true",
                   help="Show only J1939 DM1/DM2 broadcasts, skip OBD-II")
    p.add_argument("--output", "-o", default=None, metavar="FILE",
                   help="Write output to file instead of stdout")
    args = p.parse_args()

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            sys.exit(f"File not found: {p}")

    if len(paths) == 1:
        frames = list(parse_file(str(paths[0])))
    else:
        frames = list(merge_files([str(p) for p in paths]))

    out = sys.stdout
    fh  = None
    if args.output:
        fh = open(args.output, "w", encoding="utf-8")
        out = fh

    try:
        analyse(frames, bus_filter=args.bus, j1939_only=args.j1939_only, out=out)
    finally:
        if fh:
            fh.close()


if __name__ == "__main__":
    main()
