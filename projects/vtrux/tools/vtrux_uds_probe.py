#!/usr/bin/env python3
"""UDS module probe for Vtrux PT bus.

Targets the two PT bus modules discovered during DTC interrogation (2026-03-30)
that respond to UDS at physical addresses 0x7E5 and 0x7E7 (response addresses
0x7ED and 0x7EF respectively).

Probe sequence per module:
  1. TesterPresent (0x3E)         -- confirm alive
  2. DiagnosticSessionControl default (0x10/01)
  3. DiagnosticSessionControl extended (0x10/03)  -- unlock services
  4. ReadDataByIdentifier (0x22):
       F190 VIN, F18C serial, F189 SW version, F187 parts number,
       F18A supplier ID, F186 active session
  5. ReadDTCInformation (0x19/01, 0x19/02, 0x19/0A) -- multiple subfunctions
  6. KWP2000 0x18 Continental-style variants (Coda ABS/Airbag encoding)

Additional modes (via flags):
  --sweep-broad  Sweep 0x700-0x7DF with TesterPresent, checking +1/+8/+0x10
                 response offsets. Finds modules outside the 0x7E0-0x7EF range.
  --j1939        Send J1939 DM1/DM2 requests to DCDC (SA=0xB3) and charger (SA=0xC0).
                 DCDC confirmed to broadcast DM1 spontaneously (2026-03-30 logs).

Response-pending (NRC 0x78) handling: collect_response now transparently discards
0x78 pending frames and keeps waiting for the real response within the timeout.

Handles ISO 15765-2 multi-frame responses (first frame + flow control +
consecutive frame reassembly).

Usage:
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --brands ixxat
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --targets 0x7E5
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --sweep-broad
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --j1939
    py -3.12 projects/vtrux/tools/vtrux_uds_probe.py --sweep-broad --j1939 --targets 0x7E5 0x7E7
"""

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path
from queue import Empty, Queue
import threading

import can

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "can-tools"))
from canbench.live.receiver import CANBusLogger, detect_all_can_interfaces

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("can").setLevel(logging.WARNING)

BITRATE = 500_000
PT_ANCHORS = frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639})

DEFAULT_TARGETS = [0x7E5, 0x7E7]   # discovered on PT bus 2026-03-30

SWEEP_RANGE = list(range(0x7E0, 0x7F0))       # 0x7E0-0x7EF (original, detail sweep)
BROAD_SWEEP_RANGE = list(range(0x700, 0x7E0)) # 0x700-0x7DF (never queried yet)

# Response offsets to check during broad sweep.
# Standard UDS uses +8. Coda reveals non-standard cases: ABS = +1, EPS = +0x10.
RESP_OFFSETS = [8, 1, 0x10, 0x18]

# J1939 diagnostic targets (PT bus)
J1939_TOOL_SA = 0xF9   # source address for our tester (unoccupied on PT bus)
J1939_TARGETS = [
    (0xB3, "DCDC"),
    (0xC0, "Charger"),
]
J1939_PGNS = [
    # (pgn, request_data, label, listen_seconds)
    # DM1: DCDC broadcasts spontaneously every ~1s, responds immediately.
    # DM2: previously-active fault history, no spontaneous broadcast -- needs longer wait.
    (0xFECA, bytes([0xCA, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), "DM1 active faults",      2.0),
    (0xFECB, bytes([0xCB, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), "DM2 prev-active faults", 5.0),
]

# Extended DID candidates for modules that support RDBI (0x22) but reject standard F1xx DIDs.
# Covers common GM/Via proprietary ranges. Only positive responses are printed.
# 0x7E7 on PT bus: supports DSC, accepts RDBI service, rejects all F1xx -- try these next.
# 0x716 on PT bus: also confirmed to support RDBI (returns requestOutOfRange, not serviceNotSupported) -- also a candidate.
DID_SCAN_RANGES = [
    range(0x0100, 0x0200),   # GM calibration / config DIDs (extended to full 0x01xx block)
    range(0x0200, 0x0220),   # GM extended config
    range(0x4000, 0x4040),   # GM enhanced data
    range(0xF400, 0xF440),   # Manufacturer-specific (SAE J2012 F4xx block)
]


def make_j1939_request_id(dest_sa, src_sa=J1939_TOOL_SA):
    """29-bit J1939 Request PGN (0xEA00) CAN ID. Priority=6, DP=0, PF=0xEA."""
    return (6 << 26) | (0xEA << 16) | (dest_sa << 8) | src_sa


# Response address = request address + 8 (standard UDS)
def resp_addr(req_addr):
    return req_addr + 8

# ---------------------------------------------------------------------------
# ISO 15765-2 multi-frame helpers
# ---------------------------------------------------------------------------

def pci_type(byte):
    return (byte >> 4) & 0x0F   # 0=SF, 1=FF, 2=CF, 3=FC

def make_flow_control():
    """ContinueToSend, blockSize=0 (unlimited), STmin=0."""
    return bytes([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

def make_request(payload):
    """Wrap payload bytes in an ISO 15765-2 single frame (max 7 payload bytes)."""
    assert len(payload) <= 7, f"payload too long for single frame: {len(payload)}"
    pci = len(payload)
    return bytes([pci] + list(payload) + [0x00] * (7 - len(payload)))

# Common UDS requests
PROBES = [
    # (label, payload_bytes)
    ("TesterPresent",                   bytes([0x3E, 0x00])),
    ("DSC defaultSession",              bytes([0x10, 0x01])),
    ("DSC extendedSession",             bytes([0x10, 0x03])),
    ("RDBI F190 VIN",                   bytes([0x22, 0xF1, 0x90])),
    ("RDBI F18C ECU serial",            bytes([0x22, 0xF1, 0x8C])),
    ("RDBI F189 SW version",            bytes([0x22, 0xF1, 0x89])),
    ("RDBI F187 parts number",          bytes([0x22, 0xF1, 0x87])),
    ("RDBI F18A supplier ID",           bytes([0x22, 0xF1, 0x8A])),
    ("RDBI F186 active session",        bytes([0x22, 0xF1, 0x86])),
    ("ReadDTC 0x19/01 statusMask",      bytes([0x19, 0x01, 0xFF])),
    ("ReadDTC 0x19/02 byStatus(0xFF)",  bytes([0x19, 0x02, 0xFF])),
    ("ReadDTC 0x19/0A supported",       bytes([0x19, 0x0A])),
    # KWP2000 0x18 Continental-style variants (from Coda ABS=subfn0x00, Airbag=subfn0x02).
    # These use a different byte layout than ISO 14230-3 group-based encoding.
    # Format: 18 subfn mask 00
    ("KWP 0x18 Continental(subfn=0x00, mask=0xFF)",  bytes([0x18, 0x00, 0xFF, 0x00])),
    ("KWP 0x18 Continental(subfn=0x02, mask=0xFF)",  bytes([0x18, 0x02, 0xFF, 0x00])),
]

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x78: "responsePending",
}

# ---------------------------------------------------------------------------
# Response receiver
# ---------------------------------------------------------------------------

class UDSReceiver:
    """Listens on a bus and collects responses for a specific source address."""

    def __init__(self, bus, resp_arb_id, timeout=1.0):
        self.bus = bus
        self.resp_arb_id = resp_arb_id
        self.timeout = timeout
        self._queue = Queue()
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self):
        while self._running:
            msg = self.bus.recv(timeout=0.05)
            if msg and not msg.is_extended_id and msg.arbitration_id == self.resp_arb_id:
                self._queue.put(list(msg.data))

    def recv_frame(self, timeout=None):
        """Get next matching frame within timeout seconds, or None."""
        try:
            return self._queue.get(timeout=timeout or self.timeout)
        except Empty:
            return None

    def flush(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break


def collect_response(bus, recv, req_arb_id, req_data, label, timeout=1.0):
    """Send a request and collect/reassemble the full UDS response payload.

    Returns (success, payload_bytes, description_string).
    Handles:
    - Single-frame responses
    - First-frame + consecutive-frame multi-frame reassembly
    - NRC 0x78 (requestCorrectlyReceivedResponsePending): discards and keeps waiting.
      Some modules (e.g. Coda airbag, any slow processor) send 0x78 before the real
      response. The prior implementation returned 0x78 as the final answer, which caused
      the real response to be missed. Fixed: loop within the timeout.
    """
    recv.flush()

    req_msg = can.Message(arbitration_id=req_arb_id, data=req_data, is_extended_id=False)
    try:
        bus.send(req_msg)
    except Exception as e:
        return False, b"", f"send error: {e}"

    deadline = time.time() + timeout

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return False, b"", "no response (timeout)"

        frame = recv.recv_frame(timeout=remaining)
        if frame is None:
            return False, b"", "no response (timeout)"

        pt = pci_type(frame[0])

        if pt == 0:
            # Single frame
            length = frame[0] & 0x0F
            payload = bytes(frame[1:1 + length])
            # Discard response-pending (NRC 0x78) and keep waiting for the real response
            if (len(payload) >= 3
                    and payload[0] == 0x7F
                    and payload[2] == 0x78):
                log.debug("0x78 responsePending from 0x%03X, continuing...", req_arb_id + 8)
                continue
            return True, payload, _describe_payload(payload)

        elif pt == 1:
            # First frame — send flow control, collect consecutive frames
            total_len = ((frame[0] & 0x0F) << 8) | frame[1]
            payload = bytearray(frame[2:])

            fc = can.Message(arbitration_id=req_arb_id, data=make_flow_control(),
                             is_extended_id=False)
            try:
                bus.send(fc)
            except Exception as e:
                return False, b"", f"flow control send error: {e}"

            sn_expected = 1
            while len(payload) < total_len:
                cf = recv.recv_frame(timeout=min(timeout, deadline - time.time()))
                if cf is None:
                    break
                if pci_type(cf[0]) != 2:
                    break
                sn = cf[0] & 0x0F
                if sn != sn_expected % 16:
                    break
                payload.extend(cf[1:])
                sn_expected += 1

            payload = bytes(payload[:total_len])
            return True, payload, _describe_payload(payload)

        else:
            raw = " ".join(f"{b:02X}" for b in frame)
            return False, bytes(frame), f"unexpected PCI type {pt}: {raw}"


def _describe_payload(payload):
    """Best-effort human description of a UDS response payload."""
    if not payload:
        return "(empty)"
    sid = payload[0]

    if sid == 0x7F:
        req_sid = payload[1] if len(payload) > 1 else 0
        nrc     = payload[2] if len(payload) > 2 else 0
        return f"NRC for 0x{req_sid:02X}: {NRC_NAMES.get(nrc, f'0x{nrc:02X}')}"

    if sid == 0x7E:
        return "TesterPresent OK"

    if sid == 0x50:
        subfn = payload[1] if len(payload) > 1 else 0
        session_names = {0x01: "default", 0x02: "programming", 0x03: "extended"}
        return f"DSC OK: {session_names.get(subfn, f'subfn=0x{subfn:02X}')}"

    if sid == 0x62:
        did_high = payload[1] if len(payload) > 1 else 0
        did_low  = payload[2] if len(payload) > 2 else 0
        data     = payload[3:]
        printable = _try_ascii(data)
        hex_str  = " ".join(f"{b:02X}" for b in data)
        return f"RDBI 0x{did_high:02X}{did_low:02X}: {printable}  [{hex_str}]"

    if sid == 0x59:
        subfn = payload[1] if len(payload) > 1 else 0
        if subfn == 0x01:
            count = ((payload[3] << 8) | payload[4]) if len(payload) >= 5 else 0
            return f"ReadDTC 0x59/01: {count} DTCs (statusMask=0x{payload[2]:02X} if len>2 else ?)"
        if subfn == 0x02:
            avail_mask = payload[2] if len(payload) > 2 else 0
            records = []
            idx = 3
            while idx < len(payload):
                # Skip 0xAA bytes used as group separators by some modules (e.g. Bel charger)
                if payload[idx] == 0xAA:
                    idx += 1
                    continue
                if idx + 4 > len(payload):
                    break
                h, m, l, st = payload[idx], payload[idx+1], payload[idx+2], payload[idx+3]
                records.append(f"0x{h:02X}{m:02X}{l:02X}(st=0x{st:02X})")
                idx += 4
            if records:
                return f"ReadDTC 0x59/02 mask=0x{avail_mask:02X}: " + ", ".join(records)
            return f"ReadDTC 0x59/02: no DTCs (mask=0x{avail_mask:02X})"
        return f"ReadDTC 0x59/subfn=0x{subfn:02X}: " + " ".join(f"{b:02X}" for b in payload[2:])

    return " ".join(f"{b:02X}" for b in payload)


def _try_ascii(data):
    """Return ASCII string if data is printable, else hex."""
    try:
        s = data.decode("ascii")
        if all(0x20 <= ord(c) < 0x7F for c in s):
            return repr(s)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# J1939 DM1/DM2 decoder
# ---------------------------------------------------------------------------

def decode_j1939_dm(data, label):
    """Decode a J1939 DM1 or DM2 payload (SAE J1939-73 format).

    Bytes 0-1: lamp status (B0: MIL/RSL/AWL/PL; B1: flash rates)
    Bytes 2+:  4-byte DTC entries (SPN:19bits, FMI:5bits, OC:7bits, CM:1bit)
    All-0xFF = no faults / padding.
    """
    if not data:
        return "(empty)"
    if len(data) < 2:
        return "raw: " + " ".join(f"{b:02X}" for b in data)

    lamp_byte = data[0]
    lamps = []
    if lamp_byte & 0x80: lamps.append("MIL")
    if lamp_byte & 0x20: lamps.append("RSL")
    if lamp_byte & 0x08: lamps.append("AWL")
    if lamp_byte & 0x02: lamps.append("PL")
    lamp_str = "+".join(lamps) if lamps else "no-lamps"

    dtcs = []
    i = 2
    while i + 3 < len(data):
        b0, b1, b2, b3 = data[i], data[i+1], data[i+2], data[i+3]
        if b0 == 0xFF and b1 == 0xFF and b2 == 0xFF and b3 == 0xFF:
            break
        spn = b0 | (b1 << 8) | ((b2 & 0x07) << 16)
        fmi = (b2 >> 3) & 0x1F
        oc  = (b3 >> 1) & 0x7F
        dtcs.append(f"SPN{spn}/FMI{fmi}(OC={oc})")
        i += 4

    if not dtcs:
        return f"{label} lamps={lamp_str}: no active SPNs"
    return f"{label} lamps={lamp_str}: " + ", ".join(dtcs)


# ---------------------------------------------------------------------------
# Broad address sweep (0x700-0x7DF, multiple response offsets)
# ---------------------------------------------------------------------------

def probe_broad_sweep(bus):
    """Sweep 0x700-0x7DF with TesterPresent, checking +1, +8, +0x10, +0x18 offsets.

    The existing sweep covered only 0x7E0-0x7EF. This covers the range that Coda
    modules occupy (0x710, 0x722, 0x724, 0x750, 0x784, 0x7C4, 0x7C7) and any
    modules the Vtrux may have at similar addresses.

    Returns list of (req_addr, resp_offset, description) for responding modules.
    """
    print(f"\n{'='*60}")
    print(f"  Broad sweep: 0x700-0x7DF with TesterPresent")
    print(f"  Checking response offsets: {[f'+{o}' for o in RESP_OFFSETS]}")
    print(f"{'='*60}")

    tp_payload = make_request(bytes([0x3E, 0x00]))
    found = []

    for req_addr in BROAD_SWEEP_RANGE:
        for offset in RESP_OFFSETS:
            r_addr = req_addr + offset
            if r_addr > 0x7FF:
                continue
            recv = UDSReceiver(bus, r_addr, timeout=0.15)
            recv.start()
            ok, payload, description = collect_response(
                bus, recv, req_addr, tp_payload, "TesterPresent", timeout=0.15)
            recv.stop()
            if ok:
                print(f"  FOUND: 0x{req_addr:03X} -> 0x{r_addr:03X} (offset +{offset}): {description}")
                found.append((req_addr, offset, description))
            time.sleep(0.02)

    print()
    if found:
        print(f"Broad sweep found {len(found)} responding module(s):")
        for req_addr, offset, desc in found:
            print(f"  0x{req_addr:03X} -> 0x{req_addr+offset:03X} (+{offset}): {desc}")
    else:
        print("Broad sweep: no modules found in 0x700-0x7DF range.")
    return found


# ---------------------------------------------------------------------------
# J1939 DM1/DM2 probe
# ---------------------------------------------------------------------------

def probe_j1939_dm(bus):
    """Send J1939 DM1/DM2 requests and listen for responses.

    DCDC (SA=0xB3) confirmed to broadcast DM1 spontaneously (2026-03-30 logs,
    data 00 FF 00 00 00 00 = no active faults). This function actively requests
    DM2 (previously active fault history) from both DCDC and charger.

    Responses come at extended-ID 0x18FECA_SA (DM1) or 0x18FECB_SA (DM2).
    If multipacket, TP frames arrive at 0x1CEB_FF_SA / 0x1CEC_FF_SA.
    """
    print(f"\n{'='*60}")
    print(f"  J1939 DM1/DM2 probe")
    print(f"  Targets: {[(f'SA=0x{sa:02X}({name})') for sa, name in J1939_TARGETS]}")
    print(f"{'='*60}")

    for dest_sa, dest_name in J1939_TARGETS:
        req_id = make_j1939_request_id(dest_sa)
        for pgn, pgn_data, pgn_label, listen_secs in J1939_PGNS:
            resp_pgn_id = (6 << 26) | (pgn << 8) | dest_sa

            print(f"\n  Requesting {pgn_label} from {dest_name} (SA=0x{dest_sa:02X})...")
            print(f"    Request ID: 0x{req_id:08X}x")
            print(f"    Expected response ID: 0x{resp_pgn_id:08X}x")

            # Listen for both the direct PGN response and J1939 TP frames
            # 0x1CEB_FF_SA = TP.DT from dest_sa  0x1CEC_FF_SA = TP.CM from dest_sa
            tp_dt_id = (7 << 26) | (0xEB << 16) | (0xFF << 8) | dest_sa
            tp_cm_id = (7 << 26) | (0xEC << 16) | (0xFF << 8) | dest_sa

            req_msg = can.Message(arbitration_id=req_id, data=pgn_data, is_extended_id=True)
            try:
                bus.send(req_msg)
            except Exception as e:
                print(f"    Send failed: {e}")
                continue

            # Collect responses (DM1=2s, DM2=5s)
            deadline = time.time() + listen_secs
            responses = []
            while time.time() < deadline:
                msg = bus.recv(timeout=0.1)
                if msg is None or not msg.is_extended_id:
                    continue
                arb = msg.arbitration_id
                if arb in (resp_pgn_id, tp_dt_id, tp_cm_id):
                    responses.append((arb, list(msg.data)))

            if responses:
                for arb, data in responses:
                    if arb == resp_pgn_id:
                        desc = decode_j1939_dm(data, pgn_label)
                        print(f"    RESPONSE 0x{arb:08X}: {desc}")
                    elif arb == tp_cm_id:
                        print(f"    TP.CM 0x{arb:08X}: " + " ".join(f"{b:02X}" for b in data))
                    else:
                        print(f"    TP.DT 0x{arb:08X}: " + " ".join(f"{b:02X}" for b in data))
            else:
                print(f"    No response within {listen_secs:.0f}s.")

            time.sleep(0.2)

    print()


# ---------------------------------------------------------------------------
# Extended DID scan
# ---------------------------------------------------------------------------

def probe_did_scan(bus, target_addr):
    """Sweep GM/Via-specific DID ranges on a module that supports RDBI but rejects F1xx.

    Only prints DIDs that return a positive response (0x62). Silently skips NRCs.
    Covers 0x0100-0x013F, 0x0200-0x021F, 0x4000-0x403F, 0xF400-0xF43F (~192 DIDs).
    """
    r_addr = resp_addr(target_addr)
    recv = UDSReceiver(bus, r_addr, timeout=0.5)
    recv.start()

    print(f"\n{'='*60}")
    print(f"  Extended DID scan on 0x{target_addr:03X} (GM/Via ranges)")
    print(f"{'='*60}")

    hits = 0
    for did_range in DID_SCAN_RANGES:
        for did in did_range:
            payload = bytes([0x22, (did >> 8) & 0xFF, did & 0xFF])
            req_data = make_request(payload)
            ok, resp_payload, desc = collect_response(
                bus, recv, target_addr, req_data,
                f"RDBI 0x{did:04X}", timeout=0.4)
            if ok and resp_payload and resp_payload[0] == 0x62:
                print(f"  HIT  RDBI 0x{did:04X}: {desc}")
                hits += 1
            time.sleep(0.05)

    recv.stop()
    if hits == 0:
        print("  No positive responses in any scanned DID range.")
    print()


# ---------------------------------------------------------------------------
# Main probe session
# ---------------------------------------------------------------------------

def probe_module(bus, target_addr, bus_id_label):
    r_addr = resp_addr(target_addr)
    recv   = UDSReceiver(bus, r_addr, timeout=1.0)
    recv.start()

    print(f"\n{'='*60}")
    print(f"  Probing 0x{target_addr:03X} (expecting responses at 0x{r_addr:03X})")
    print(f"{'='*60}")

    in_extended = False

    for label, payload in PROBES:
        req_data = make_request(payload)
        ok, resp_payload, desc = collect_response(bus, recv, target_addr, req_data, label)

        status = "OK  " if ok else "----"
        print(f"  {status}  {label:<35}  {desc}")

        # Track session state
        if ok and resp_payload and resp_payload[0] == 0x50 and len(resp_payload) > 1:
            if resp_payload[1] == 0x03:
                in_extended = True

        time.sleep(0.15)

    recv.stop()


def run(args):
    targets = []
    for t in args.targets:
        try:
            targets.append(int(t, 16) if t.startswith("0x") or t.startswith("0X") else int(t, 16))
        except ValueError:
            print(f"Invalid target address: {t}")
            sys.exit(1)

    brands = set(args.brands.split(",")) if args.brands else None
    interfaces = detect_all_can_interfaces(BITRATE, brands=brands)
    if not interfaces:
        print("ERROR: No CAN interfaces detected.")
        sys.exit(1)

    # Find PT bus
    print("Identifying buses (3s listen)...")
    pt_bus_obj = None
    pt_bus_idx = None

    opened = []
    for iface, ch_spec, desc in interfaces:
        try:
            if isinstance(ch_spec, dict):
                bus = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
            else:
                bus = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
            opened.append((bus, desc))
        except Exception as e:
            log.error("Failed to open %s: %s", desc, e)

    if not opened:
        print("ERROR: Could not open any bus.")
        sys.exit(1)

    deadline = time.time() + 3.0
    seen = [set() for _ in opened]
    sniffers = []
    queues   = []
    for i, ((iface, ch_spec, _desc), (bus, desc)) in enumerate(zip(interfaces, opened)):
        q = Queue()
        queues.append(q)
        if isinstance(ch_spec, dict):
            ch_for_logger = ch_spec
        else:
            ch_for_logger = ch_spec
        bl = CANBusLogger(i, bus, q, iface, ch_for_logger, BITRATE)
        bl.start()
        sniffers.append(bl)

    while time.time() < deadline:
        for i, q in enumerate(queues):
            try:
                ts, bus_id, msg, direction = q.get_nowait()
                if not msg.is_extended_id:
                    seen[i].add(msg.arbitration_id)
            except Empty:
                pass
        time.sleep(0.01)

    for bl in sniffers:
        bl.stop()

    for i, (bus, desc) in enumerate(opened):
        hits = len(seen[i] & PT_ANCHORS)
        print(f"  Bus {i} ({desc}): {hits} PT anchors, {len(seen[i])} unique IDs")
        if hits >= 3 and pt_bus_obj is None:
            pt_bus_obj = bus
            pt_bus_idx = i

    if pt_bus_obj is None:
        print("ERROR: Could not identify PT bus. Check connections.")
        for bus, _ in opened:
            try: bus.shutdown()
            except Exception: pass
        sys.exit(1)

    print(f"\nUsing Bus {pt_bus_idx} as PT bus.")

    # Re-open just the PT bus cleanly (sniffer threads closed it)
    iface, ch_spec, desc = interfaces[pt_bus_idx]
    try:
        if isinstance(ch_spec, dict):
            pt_bus = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
        else:
            pt_bus = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
    except Exception as e:
        print(f"ERROR: Could not reopen PT bus: {e}")
        sys.exit(1)

    if args.sweep_all:
        # Discover responding addresses on every bus before doing the deep probe
        print("\n--- Address sweep (TesterPresent 0x7E0-0x7EF) on all buses ---")
        all_buses = []
        for i, (iface, ch_spec, desc) in enumerate(interfaces):
            try:
                if isinstance(ch_spec, dict):
                    b = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
                else:
                    b = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
                all_buses.append((i, b, desc))
            except Exception as e:
                log.error("Could not open %s: %s", desc, e)

        tp_payload = make_request(bytes([0x3E, 0x00]))
        for bus_idx, sweep_bus, desc in all_buses:
            responding = []
            for addr in SWEEP_RANGE:
                recv = UDSReceiver(sweep_bus, resp_addr(addr), timeout=0.3)
                recv.start()
                ok, payload, description = collect_response(
                    sweep_bus, recv, addr, tp_payload, "TesterPresent", timeout=0.3)
                recv.stop()
                if ok:
                    responding.append((addr, description))
                time.sleep(0.05)
            print(f"\nBus {bus_idx} ({desc}) responding addresses:")
            if responding:
                for addr, desc_str in responding:
                    print(f"  0x{addr:03X} -> 0x{resp_addr(addr):03X}  {desc_str}")
            else:
                print("  (none)")
            sweep_bus.shutdown()
        print()

    # Broad sweep (0x700-0x7DF, multiple response offsets)
    if args.sweep_broad:
        broad_found = probe_broad_sweep(pt_bus)
        # Add any newly found modules to targets if not already there
        new_targets = [req for req, offset, _ in broad_found
                       if req not in targets and req + offset not in [t + 8 for t in targets]]
        if new_targets:
            print(f"\nAdding {len(new_targets)} newly discovered module(s) to probe targets:")
            for a in new_targets:
                print(f"  0x{a:03X}")
            targets.extend(new_targets)

    # J1939 DM1/DM2 probe
    if args.j1939:
        probe_j1939_dm(pt_bus)

    # UDS deep probe of specified targets
    for target in targets:
        probe_module(pt_bus, target, f"PT Bus {pt_bus_idx}")
        if args.did_scan:
            probe_did_scan(pt_bus, target)

    pt_bus.shutdown()
    print()


def main():
    parser = argparse.ArgumentParser(
        description="UDS module probe for Vtrux PT bus modules at 0x7E5 and 0x7E7"
    )
    parser.add_argument(
        "--targets", nargs="+",
        default=[f"0x{a:03X}" for a in DEFAULT_TARGETS],
        help="Hex addresses to probe (default: 0x7E5 0x7E7)",
    )
    parser.add_argument(
        "--brands", default=None,
        help="Comma-separated dongle brands (e.g. ixxat). Default: all.",
    )
    parser.add_argument(
        "--sweep-all", action="store_true",
        help="Before probing targets, sweep 0x7E0-0x7EF with TesterPresent on ALL buses.",
    )
    parser.add_argument(
        "--sweep-broad", action="store_true",
        help="Sweep 0x700-0x7DF with TesterPresent, checking +1/+8/+0x10/+0x18 offsets. "
             "Covers address range not yet queried (0x700-0x7DF never tried).",
    )
    parser.add_argument(
        "--j1939", action="store_true",
        help="Send J1939 DM1/DM2 requests to DCDC (SA=0xB3) and charger (SA=0xC0). "
             "DCDC confirmed to support J1939 DM protocol (DM1 seen in 2026-03-30 logs).",
    )
    parser.add_argument(
        "--did-scan", action="store_true",
        help="After each target probe, sweep GM/Via-specific DID ranges "
             "(0x0100-0x013F, 0x0200-0x021F, 0x4000-0x403F, 0xF400-0xF43F). "
             "Use when a module accepts RDBI service but rejects all standard F1xx DIDs "
             "(e.g. 0x7E7 on PT bus).",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
