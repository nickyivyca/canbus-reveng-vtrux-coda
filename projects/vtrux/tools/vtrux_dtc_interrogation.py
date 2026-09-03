#!/usr/bin/env python3
"""DTC interrogation tool for Vtrux.

Connects to all available CAN hardware, identifies each bus using anchor IDs,
sends DTC requests using multiple protocols, and logs all traffic to a BUSMASTER
file for the duration of the session.

Protocols attempted on every bus:
  - OBD-II Mode 03/07/0A  at 0x7DF (functional) and 0x7E0 (physical)
  - UDS 0x19/02            at 0x7DF and 0x7E0
  - KWP2000 0x18           at 0x7DF and 0x7E0

PT bus only (additional):
  - Physical address sweep 0x700-0x7EF with TesterPresent (discovery)
  - Detailed sweep 0x7E0-0x7EF with Mode 03 + UDS 0x19 (confirmed diagnostic range)
  - J1939 DM1/DM2 requests to DCDC (SA=0xB3), charger (SA=0xC0), global broadcast
    -- DCDC confirmed to speak J1939 DM protocol (DM1 broadcasts seen 2026-03-30)

Decoded in real time:
  - 0x700-0x7FF  OBD-II Mode 43/47/4A responses (any module in diagnostic range)
  - 0x700-0x7FF  UDS 0x59 responses (ReadDTCInformation)
  - 0x700-0x7FF  KWP2000 0x58 responses (ReadDTCByStatus)
  - Extended ID   J1939 DM1 (0xFECA) and DM2 (0xFECB) from any SA
  - 0x065B        HCU proprietary DTC code (PT bus, 29-entry lookup table)
  - 0x7F xx xx    Negative response codes (any protocol)

Note: diagnostic activity during testing has triggered a power steering disable / 4WD
warning on the dash. Root cause bus not yet confirmed. Acceptable during stationary
testing; do not run while driving.

Log output goes to projects/vtrux/notes/artifacts/ by default.

Usage:
    py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py
    py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --log-time 30
    py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --output dtc_session.log
    py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --brands ixxat
"""

import argparse
import datetime
import logging
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

import can

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "can-tools"))
from canbench.live.receiver import CANBusLogger, detect_all_can_interfaces

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)
logging.getLogger("can").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# DTC lookup table (29 entries, from epri-decompile.md, 0x065B section)
# Encoded as standard SAE J2012 / GMLAN DTC codes.
# 0x065B frame: DTC code = (B6 << 8) | B7
# ---------------------------------------------------------------------------

DTC_TABLE = {
    0x0D67: "P0D67 - charger platform DTC",
    0x1A20: "P1A20 - BECM fault A",
    0x0A7B: "P0A7B - BECM MIL-on request (battery SOC too low)",
    0x1A21: "P1A21 - BECM critical fault A",
    0x1A81: "P1A81 - HVIL performance, generator",
    0x1A82: "P1A82 - HVIL performance, traction",
    0x1A80: "P1A80 - HVIL performance, DCDC",
    0x0AA6: "P0AA6 - HV isolation fault",
    0x1AA0: "P1AA0 - charger shutdown",
    0x0A0B: "P0A0B - ESS HVIL performance",
    0x0A1F: "P0A1F - ESS fault",
    0xD300: "U1300 - HCU: app interrupt task",
    0xD301: "U1301 - HCU: low mem task 2",
    0xD302: "U1302 - HCU: low mem task 1",
    0xD303: "U1303 - HCU: low mem idle task",
    0xD304: "U1304 - HCU: low mem interrupt",
    0xD305: "U1305 - HCU: low mem kernel",
    0xD306: "U1306 - HCU: shutdown task",
    0xD307: "U1307 - HCU: low mem heap",
    0xD311: "U1311 - HCU: high CPU task 2",
    0xD310: "U1310 - HCU: high CPU app interrupt task",
    0xD312: "U1312 - HCU: high CPU task 1",
    0xD313: "U1313 - HCU: high CPU shutdown task",
    0xD314: "U1314 - HCU: CPU idle app",
    0xC129: "U0129 - CAN lost Rx: EBCM",
    0xC100: "U0100 - CAN lost Rx: ECM",
    0xC16B: "U016B - CAN lost Rx: ACCM",
    0xC111: "U0111 - CAN lost Rx: BECM",
    0xC296: "U0296 - CAN lost Rx: BDC",
}

# ---------------------------------------------------------------------------
# Bus identification anchor IDs (from projects/vtrux/README.md)
# ---------------------------------------------------------------------------

PT_BUS_ANCHORS  = frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639})
OBD_BUS_ANCHORS = frozenset({0x040, 0x041, 0x042, 0x043, 0x044, 0x441, 0x44A})
VEH_BUS_ANCHORS = frozenset({0x1E5, 0x500, 0x514, 0x52A, 0x778, 0x780})

# ---------------------------------------------------------------------------
# ISO 15765-4 / OBD-II addresses and requests
# ---------------------------------------------------------------------------

FUNC_ADDR    = 0x7DF   # functional broadcast (all modules respond)
VCM_PHYS     = 0x7E0   # VCM / HCU physical diagnostic address

# Real-time response decoder covers the full diagnostic address range 0x700-0x7FF.
# The existing tool monitored only 0x7E8-0x7EF; extending to catch any module
# in the broader range (e.g. ABS at +1 offset, EPS at +0x10, etc.).
DIAG_RESP_MIN = 0x700
DIAG_RESP_MAX = 0x7FF

HCU_DTC_ID   = 0x065B  # PT bus proprietary DTC broadcast

# OBD-II service IDs (single-frame: PCI=0x01, SID, 6x padding)
DTC_SERVICE_IDS = [
    (0x03, "stored DTCs"),
    (0x07, "pending DTCs"),
    (0x0A, "permanent DTCs"),
]

# UDS ReadDTCInformation (ISO 14229 service 0x19)
#   0x19 0x02 0xFF = reportDTCByStatusMask, all status bits
#   0x19 0x0A 0xFF = reportSupportedDTC (what DTCs the module can report)
# Single frame: PCI=0x03 (3 data bytes)
UDS_DTC_REQUESTS = [
    (bytes([0x03, 0x19, 0x02, 0xFF, 0x00, 0x00, 0x00, 0x00]),
     "UDS 0x19/02 reportDTCByStatusMask(0xFF)"),
    (bytes([0x02, 0x19, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00]),
     "UDS 0x19/0A reportSupportedDTC"),
]

# KWP2000 ReadDTCByStatus (ISO 14230 service 0x18)
# Three variants:
#   ISO 14230-3 group-based: 18 group_hi group_lo status_mask
#   Continental/Bel style (subfn-based): 18 subfn mask 00  (Coda ABS=subfn0x00, Airbag=subfn0x02)
# Single frame: PCI=0x04 (4 data bytes)
KWP_DTC_REQUESTS = [
    (bytes([0x04, 0x18, 0xFF, 0x00, 0xFF, 0x00, 0x00, 0x00]),
     "KWP2000 0x18 ReadDTCByStatus(group=0xFF00, mask=0xFF)"),
    (bytes([0x04, 0x18, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]),
     "KWP2000 0x18 ReadDTCByStatus(group=0x0000 all, mask=0xFF)"),
    (bytes([0x04, 0x18, 0x00, 0xFF, 0x00, 0x00, 0x00, 0x00]),
     "KWP2000 0x18 Continental-style(subfn=0x00, mask=0xFF)"),
    (bytes([0x04, 0x18, 0x02, 0xFF, 0x00, 0x00, 0x00, 0x00]),
     "KWP2000 0x18 Continental-style(subfn=0x02, mask=0xFF)"),
]

# Negative response code service ID
NRC_SID = 0x7F

# J1939 diagnostic requests (PT bus only).
# DCDC (SA=0xB3) confirmed to broadcast DM1 (PGN 0xFECA) spontaneously — 2026-03-30 logs.
# Requesting DM2 (PGN 0xFECB = previously active faults) should return stored fault history.
# Our tool SA = 0xF9 (unoccupied address on PT bus).
J1939_TOOL_SA = 0xF9

# J1939 destination addresses to poll
J1939_TARGETS = [
    (0xB3, "DCDC"),
    (0xC0, "Charger"),
    (0xFF, "Global broadcast"),
]

# J1939 PGNs to request (3 bytes, little-endian in request payload)
J1939_PGNS = [
    (0xFECA, bytes([0xCA, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), "DM1 active faults"),
    (0xFECB, bytes([0xCB, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]), "DM2 previously active faults"),
]


def make_j1939_request_id(dest_sa, src_sa=J1939_TOOL_SA):
    """Build a 29-bit J1939 Request PGN (0xEA00) CAN ID.
    Priority=6, DP=0, PF=0xEA (Request PGN service), PS=dest_sa, SA=src_sa.
    """
    return (6 << 26) | (0xEA << 16) | (dest_sa << 8) | src_sa


# Physical address sweep ranges for PT bus.
# Broad discovery sweep (0x700-0x7EF): TesterPresent only — lightweight, covers full range.
# Detail sweep (0x7E0-0x7EF): Mode03 + UDS 0x19 — known diagnostic range with confirmed modules.
PT_BROAD_SWEEP  = list(range(0x700, 0x7E0))   # 0x700-0x7DF (223 addresses, never queried)
PT_DETAIL_SWEEP = list(range(0x7E0, 0x7F0))   # 0x7E0-0x7EF (already known range)

# Default log destination
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "notes" / "artifacts"
)

BITRATE = 500_000


# ---------------------------------------------------------------------------
# BUSMASTER log writer
# ---------------------------------------------------------------------------

class BUSMASTERWriter:
    """Writes CAN messages to BUSMASTER log format."""

    HEADER = (
        "***BUSMASTER Ver 3.2.2***\n"
        "***PROTOCOL CAN***\n"
        "***NOTE: PLEASE DO NOT EDIT THIS DOCUMENT***\n"
        "***[START LOGGING SESSION]***\n"
        "***START DATE AND TIME {datetime}***\n"
        "***HEX***\n"
        "***SYSTEM MODE***\n"
        "***START CHANNEL BAUD RATE***\n"
        "{channel_info}\n"
        "***END CHANNEL BAUD RATE***\n"
        "***START DATABASE FILES***\n"
        "***END DATABASE FILES***\n"
        "***<Time><Tx/Rx><Channel><CAN ID><Type><DLC><DataBytes>***\n"
    )

    def __init__(self, filepath, num_buses, bitrate):
        self.filepath = Path(filepath)
        self.num_buses = num_buses
        self.bitrate = bitrate
        self.file = None
        self.message_count = 0

    def __enter__(self):
        self.file = open(self.filepath, "w", encoding="utf-8")
        self._write_header()
        return self

    def __exit__(self, *_):
        if self.file:
            self._write_footer()
            self.file.close()
            log.info("Wrote %d messages to %s", self.message_count, self.filepath)

    def _write_header(self):
        now = datetime.datetime.now()
        dt_str = now.strftime("%d:%m:%Y %H:%M:%S:%f")[:-3]
        channel_lines = "\n".join(
            f"***CHANNEL {i} - CAN - {self.bitrate} bps***"
            for i in range(1, self.num_buses + 1)
        )
        self.file.write(self.HEADER.format(datetime=dt_str, channel_info=channel_lines))
        self.file.flush()

    def _write_footer(self):
        now = datetime.datetime.now()
        dt_str = now.strftime("%d:%m:%Y %H:%M:%S:%f")[:-3]
        self.file.write(f"***END DATE AND TIME {dt_str}***\n")
        self.file.write("***[STOP LOGGING SESSION]***\n")

    def write_message(self, timestamp, bus_id, msg, direction="Rx"):
        hours  = int(timestamp // 3600)
        mins   = int((timestamp % 3600) // 60)
        secs   = int(timestamp % 60)
        ticks  = int((timestamp % 1.0) * 10000)  # 10 kHz ticks (0.1 ms)
        time_str  = f"{hours:02d}:{mins:02d}:{secs:02d}:{ticks:04d}"
        channel   = bus_id + 1
        can_id    = f"0x{msg.arbitration_id:X}"
        msg_type  = "x" if msg.is_extended_id else "s"
        data_str  = " ".join(f"{b:02X}" for b in msg.data)
        self.file.write(
            f"{time_str} {direction} {channel} {can_id} {msg_type} {msg.dlc} {data_str}\n"
        )
        self.message_count += 1
        if self.message_count % 500 == 0:
            self.file.flush()


# ---------------------------------------------------------------------------
# Response decoders
# ---------------------------------------------------------------------------

def decode_obd_mode43(data):
    """Parse a Mode 43 response frame and return list of (raw_code, text) tuples.

    ISO 15765-4 single-frame layout:
      B0: PCI  (0x0N where N = byte count)
      B1: 0x43 (response to Mode 03)
      B2: number of DTC pairs to follow
      B3-B4: DTC pair 1
      B5-B6: DTC pair 2 (if present)
      ...
    """
    if len(data) < 3 or data[1] != 0x43:
        return []
    num_dtcs = data[2]
    if num_dtcs == 0:
        return [("(none)", "No stored DTCs reported")]
    dtcs = []
    for i in range(num_dtcs):
        idx = 3 + i * 2
        if idx + 1 >= len(data):
            break
        high, low = data[idx], data[idx + 1]
        raw = (high << 8) | low
        if raw == 0x0000:
            continue
        # Decode upper 2 bits: 00=P, 01=C, 10=B, 11=U
        prefix_bits = (high >> 6) & 0x03
        prefix = ["P", "C", "B", "U"][prefix_bits]
        code_num = ((high & 0x3F) << 8) | low
        code_str = f"{prefix}{code_num:04X}"
        dtcs.append((code_str, _lookup_dtc(raw)))
    return dtcs


def decode_0x065b(data):
    """Decode a 0x065B HCU DTC frame.

    The EPRI app reads B6:B7 (bytes at index 6 and 7, i.e. B6 = pbVar15[8])
    as a big-endian uint16 DTC code. B0-B5 are not decoded by the app.
    Returns (code_hex, description) or None if code is 0x0000.
    """
    if len(data) < 8:
        return None
    raw = (data[6] << 8) | data[7]
    if raw == 0x0000:
        return None
    return (f"0x{raw:04X}", _lookup_dtc(raw))


def _lookup_dtc(raw_code):
    """Look up a 16-bit DTC code in the known table, return a description string."""
    if raw_code in DTC_TABLE:
        return DTC_TABLE[raw_code]
    # Format as standard OBD code even if not in table
    prefix_bits = (raw_code >> 14) & 0x03
    prefix = ["P", "C", "B", "U"][prefix_bits]
    code_num = raw_code & 0x3FFF
    return f"{prefix}{code_num:04X} (unknown code)"


def decode_uds_0x59(data):
    """Decode a UDS 0x59 (ReadDTCInformation positive response) frame.

    Layout for subfunction 0x02 (reportDTCByStatusMask):
      B0: PCI
      B1: 0x59
      B2: subfunction (0x02)
      B3: DTCStatusAvailabilityMask
      B4-B6: DTC record 1 (3 bytes: high, mid, low)
      B7:    status byte for record 1
      ... repeating 4-byte groups
    Returns list of (code_str, desc) tuples.
    """
    if len(data) < 4 or data[1] != 0x59:
        return None
    subfn = data[2]
    if subfn != 0x02:
        return [(f"UDS 0x59 subfn=0x{subfn:02X}", "unhandled subfunction — raw: " +
                 " ".join(f"{b:02X}" for b in data))]
    if len(data) < 5:
        return [("(none)", "UDS 0x59: no DTCs in response")]
    dtcs = []
    idx = 4
    while idx + 3 <= len(data):
        high, mid, low, status = data[idx], data[idx+1], data[idx+2], data[idx+3]
        raw16 = (high << 8) | mid   # upper 2 bytes map to the 16-bit OBD DTC code
        if raw16 != 0x0000:
            prefix_bits = (high >> 6) & 0x03
            prefix = ["P", "C", "B", "U"][prefix_bits]
            code_num = ((high & 0x3F) << 8) | mid
            code_str = f"{prefix}{code_num:04X} (status=0x{status:02X})"
            dtcs.append((code_str, _lookup_dtc(raw16)))
        idx += 4
    return dtcs if dtcs else [("(none)", "UDS 0x59: no DTCs reported")]


def decode_kwp_0x58(data):
    """Decode a KWP2000 0x58 (ReadDTCByStatus positive response) frame.

    Layout:
      B0: PCI
      B1: 0x58
      B2: number of DTC/status pairs
      B3-B4: DTC bytes (high, low)
      B5:    status byte
      ... repeating 3-byte groups
    Returns list of (code_str, desc) tuples.
    """
    if len(data) < 3 or data[1] != 0x58:
        return None
    num_dtcs = data[2]
    if num_dtcs == 0:
        return [("(none)", "KWP2000 0x58: no DTCs reported")]
    dtcs = []
    for i in range(num_dtcs):
        idx = 3 + i * 3
        if idx + 2 >= len(data):
            break
        high, low, status = data[idx], data[idx+1], data[idx+2]
        raw = (high << 8) | low
        prefix_bits = (high >> 6) & 0x03
        prefix = ["P", "C", "B", "U"][prefix_bits]
        code_num = ((high & 0x3F) << 8) | low
        code_str = f"{prefix}{code_num:04X} (status=0x{status:02X})"
        dtcs.append((code_str, _lookup_dtc(raw)))
    return dtcs if dtcs else [("(none)", "KWP2000 0x58: no DTCs reported")]


def _decode_j1939_dm(data, label):
    """Decode a J1939 DM1 or DM2 payload.

    J1939 DM1/DM2 format (SAE J1939-73):
      B0: MIL/lamp status byte (bit7=MIL, bit5=RSL, bit3=AWL, bit1=PL)
      B1: Flash lamp status byte
      B2-B5: First SPN/FMI DTC entry (if any; all-0xFF padding = no faults)
      B6-B9: Second DTC (etc.)

    Each 4-byte DTC entry:
      bits [31..13] = SPN (19 bits, little-endian across bytes 0-2)
      bits [12..8]  = FMI (5 bits)
      bits [7..1]   = OC (7-bit occurrence count)
      bit  [0]      = CM (conversion method)

    Returns human-readable string.
    """
    if not data:
        return "(empty)"
    if len(data) < 2:
        return f"raw: {' '.join(f'{b:02X}' for b in data)}"

    lamp_byte = data[0]
    mil  = bool(lamp_byte & 0x80)
    rsl  = bool(lamp_byte & 0x20)
    awl  = bool(lamp_byte & 0x08)
    pl   = bool(lamp_byte & 0x02)
    lamps = []
    if mil: lamps.append("MIL")
    if rsl: lamps.append("RSL")
    if awl: lamps.append("AWL")
    if pl:  lamps.append("PL")
    lamp_str = "+".join(lamps) if lamps else "no-lamps"

    # Extract DTC entries (4 bytes each, starting at byte 2)
    dtcs = []
    i = 2
    while i + 3 < len(data):
        b0, b1, b2, b3 = data[i], data[i+1], data[i+2], data[i+3]
        if b0 == 0xFF and b1 == 0xFF and b2 == 0xFF and b3 == 0xFF:
            break   # padding / no more entries
        # SPN: bits 0-7 of b0, bits 0-7 of b1, bits 0-2 of b2 (J1939 bit ordering)
        spn = b0 | (b1 << 8) | ((b2 & 0x07) << 16)
        fmi = (b2 >> 3) & 0x1F
        oc  = (b3 >> 1) & 0x7F
        dtcs.append(f"SPN{spn}/FMI{fmi}(OC={oc})")
        i += 4

    if not dtcs:
        return f"{label} {lamp_str}: no active SPNs"
    return f"{label} {lamp_str}: " + ", ".join(dtcs)


def decode_nrc(data):
    """Detect and describe a negative response code frame.

    Format: [pci] [0x7F] [requested_sid] [nrc_byte]
    """
    if len(data) < 4 or data[1] != 0x7F:
        return None
    req_sid = data[2]
    nrc     = data[3]
    nrc_names = {
        0x10: "generalReject",
        0x11: "serviceNotSupported",
        0x12: "subFunctionNotSupported",
        0x13: "incorrectMessageLengthOrInvalidFormat",
        0x22: "conditionsNotCorrect",
        0x31: "requestOutOfRange",
        0x33: "securityAccessDenied",
        0x35: "invalidKey",
        0x78: "requestCorrectlyReceivedResponsePending",
    }
    nrc_str = nrc_names.get(nrc, f"0x{nrc:02X}")
    return f"NRC for SID 0x{req_sid:02X}: {nrc_str}"


# ---------------------------------------------------------------------------
# Bus identification helper
# ---------------------------------------------------------------------------

def identify_bus(seen_ids):
    """Return 'PT', 'OBD', 'Vehicle', or 'unknown' based on seen CAN IDs."""
    pt_hits  = len(seen_ids & PT_BUS_ANCHORS)
    obd_hits = len(seen_ids & OBD_BUS_ANCHORS)
    veh_hits = len(seen_ids & VEH_BUS_ANCHORS)
    if pt_hits == 0 and obd_hits == 0 and veh_hits == 0:
        return "unknown"
    scores = {"PT": pt_hits, "OBD": obd_hits, "Vehicle": veh_hits}
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------

def make_obd_request(service_id):
    """Build an 8-byte ISO 15765-4 single-frame OBD-II request.

    PCI = 0x01 (single frame, 1 data byte), then service ID, then padding.
    """
    return bytes([0x01, service_id, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def run_session(args):
    ident_secs = args.ident_time
    log_secs   = args.log_time
    output_path = resolve_output_path(args.output)

    print(f"\nDTC Interrogation Session")
    print(f"  Bitrate       : {BITRATE} bps")
    print(f"  Ident phase   : {ident_secs}s (listen only, identify buses)")
    print(f"  Log duration  : {log_secs}s after sending requests")
    print(f"  Output log    : {output_path}")
    print()

    # Detect hardware
    brands = set(args.brands.split(",")) if args.brands else None
    interfaces = detect_all_can_interfaces(BITRATE, brands=brands)
    if not interfaces:
        print("ERROR: No CAN interfaces detected. Check connections and drivers.")
        sys.exit(1)

    print(f"Detected {len(interfaces)} CAN interface(s):")
    for i, (iface, ch, desc) in enumerate(interfaces):
        print(f"  Bus {i}: {desc}")
    print()

    # Open all buses
    buses = []
    for iface, ch_spec, desc in interfaces:
        try:
            if isinstance(ch_spec, dict):
                bus = can.interface.Bus(interface=iface, bitrate=BITRATE, **ch_spec)
            else:
                bus = can.interface.Bus(interface=iface, channel=ch_spec, bitrate=BITRATE)
            buses.append((bus, iface, ch_spec, desc))
            log.info("Opened: %s", desc)
        except Exception as e:
            log.error("Failed to open %s: %s", desc, e)

    if not buses:
        print("ERROR: Failed to open any CAN bus.")
        sys.exit(1)

    num_buses = len(buses)
    msg_queue = Queue()
    session_start = time.time()

    # Start receive threads via CANBusLogger
    loggers = []
    for bus_id, (bus, iface, ch_spec, desc) in enumerate(buses):
        bl = CANBusLogger(bus_id, bus, msg_queue, iface, ch_spec, BITRATE)
        bl.start()
        loggers.append(bl)

    # Track anchor-ID hits per bus for identification
    seen_ids = [set() for _ in range(num_buses)]
    # Track decoded DTC results for summary
    dtc_findings = []

    def drain_queue_to_writer(writer, until_time, phase_label):
        """Drain msg_queue into writer until until_time, decoding and printing responses."""
        printed_header = False
        while time.time() < until_time:
            try:
                ts, bus_id, msg, direction = msg_queue.get(timeout=0.05)
            except Empty:
                continue

            # Record anchor IDs during ident phase
            if not msg.is_extended_id:
                seen_ids[bus_id].add(msg.arbitration_id)

            writer.write_message(ts, bus_id, msg, direction)

            # Only decode Rx frames -- Tx echoes are not responses
            if direction != "Rx":
                continue

            # Real-time decode of interesting responses
            data = list(msg.data)
            arb  = msg.arbitration_id

            if arb == HCU_DTC_ID and not msg.is_extended_id:
                result = decode_0x065b(data)
                if result:
                    code, desc_str = result
                    _print_finding(f"[0x065B] PT bus HCU DTC: {code} = {desc_str}")
                    dtc_findings.append(("0x065B HCU", code, desc_str))
                else:
                    _print_finding("[0x065B] PT bus HCU DTC: code 0x0000 (no fault stored)")

            elif msg.is_extended_id:
                # J1939 DM1/DM2 response detection (extended ID frames)
                pgn = (arb >> 8) & 0xFFFF
                sa  = arb & 0xFF
                if pgn == 0xFECA:
                    dm1_desc = _decode_j1939_dm(data, "DM1")
                    _print_finding(
                        f"[J1939 DM1 from SA=0x{sa:02X}] active faults: {dm1_desc}")
                    dtc_findings.append((f"J1939_DM1 SA=0x{sa:02X}", dm1_desc, ""))
                elif pgn == 0xFECB:
                    dm2_desc = _decode_j1939_dm(data, "DM2")
                    _print_finding(
                        f"[J1939 DM2 from SA=0x{sa:02X}] prev-active faults: {dm2_desc}")
                    dtc_findings.append((f"J1939_DM2 SA=0x{sa:02X}", dm2_desc, ""))

            elif DIAG_RESP_MIN <= arb <= DIAG_RESP_MAX and not msg.is_extended_id:
                # Standard-ID frames in diagnostic address range 0x700-0x7FF.
                # Extended from original 0x7E8-0x7EF to catch non-standard response offsets
                # (e.g. ABS at req+1, EPS at req+0x10) and any new modules found in sweep.
                # Skip frames that are not valid ISO-TP single frames (PCI length=0 means
                # a periodic broadcast that happens to fall in this range, not a response).
                if len(data) >= 2 and (data[0] & 0x0F) >= 1:
                    src = f"0x{arb:03X}"
                    sid = data[1]   # SID is at byte 1 for single frames (PCI byte 0)
                    if sid == 0x43:
                        dtcs = decode_obd_mode43(data)
                        for code, desc_str in dtcs:
                            _print_finding(f"[{src}] Mode 43 DTC: {code} = {desc_str}")
                            dtc_findings.append((f"Mode43 {src}", code, desc_str))
                    elif sid == 0x47:
                        _print_finding(f"[{src}] Mode 47 response (pending DTCs, empty)")
                    elif sid == 0x4A:
                        _print_finding(f"[{src}] Mode 4A response (permanent DTCs, empty)")
                    elif sid == 0x59:
                        dtcs = decode_uds_0x59(data)
                        if dtcs is not None:
                            for code, desc_str in dtcs:
                                _print_finding(f"[{src}] UDS 0x59 DTC: {code} = {desc_str}")
                                dtc_findings.append((f"UDS59 {src}", code, desc_str))
                    elif sid == 0x58:
                        dtcs = decode_kwp_0x58(data)
                        if dtcs is not None:
                            for code, desc_str in dtcs:
                                _print_finding(f"[{src}] KWP 0x58 DTC: {code} = {desc_str}")
                                dtc_findings.append((f"KWP58 {src}", code, desc_str))
                    elif sid == NRC_SID:
                        nrc_str = decode_nrc(data)
                        if nrc_str:
                            _print_finding(f"[{src}] {nrc_str}")
                    elif sid not in (0x00, 0x7E):
                        # Unexpected SID in diagnostic range -- log raw for review
                        raw = " ".join(f"{b:02X}" for b in data)
                        _print_finding(f"[{src}] UNKNOWN SID=0x{sid:02X}: {raw}")

    def _print_finding(msg_str):
        ts_rel = time.time() - session_start
        print(f"  [{ts_rel:6.2f}s] {msg_str}")

    # ------------------------------------------------------------------
    # Phase 1: Listen only (bus identification)
    # ------------------------------------------------------------------
    print(f"Phase 1: Listening for {ident_secs}s to identify buses...")
    ident_end = time.time() + ident_secs

    with BUSMASTERWriter(output_path, num_buses, BITRATE) as writer:

        drain_queue_to_writer(writer, ident_end, "ident")

        # Report bus identities
        bus_names = {}
        print()
        print("Bus identification results:")
        for bus_id in range(num_buses):
            name = identify_bus(seen_ids[bus_id])
            bus_names[bus_id] = name
            hit_count = len(seen_ids[bus_id])
            print(f"  Bus {bus_id} ({interfaces[bus_id][2]}): {name} ({hit_count} unique IDs seen)")
        print()

        # ------------------------------------------------------------------
        # Phase 2: Send requests and log for log_secs
        # ------------------------------------------------------------------
        print(f"Phase 2: Sending DTC requests, logging for {log_secs}s...")
        print()

        log_end = time.time() + log_secs

        def _send(bus, bus_id, bus_name, arb_id, data, label, delay=0.1):
            """Send one frame, log it to the queue, print it."""
            msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
            try:
                ts_rel = time.time() - session_start
                bus.send(msg)
                fake = can.Message(arbitration_id=arb_id, data=data,
                                   is_extended_id=False, timestamp=time.time())
                msg_queue.put((ts_rel, bus_id, fake, "Tx"))
                print(f"  [{ts_rel:6.2f}s] Tx Bus {bus_id} ({bus_name}): "
                      f"0x{arb_id:03X} {label}")
            except Exception as e:
                log.error("Bus %d send 0x%03X failed: %s", bus_id, arb_id, e)
            time.sleep(delay)

        for bus_id, (bus, iface, ch_spec, desc) in enumerate(buses):
            bus_name = bus_names.get(bus_id, "unknown")
            phys = bus_name in ("OBD", "PT", "unknown")

            # --- OBD-II Mode 03 / 07 / 0A ---
            for sid, sid_label in DTC_SERVICE_IDS:
                req = make_obd_request(sid)
                _send(bus, bus_id, bus_name, FUNC_ADDR, req,
                      f"OBD-II {sid_label} (SID 0x{sid:02X})")
                if phys:
                    _send(bus, bus_id, bus_name, VCM_PHYS, req,
                          f"OBD-II {sid_label} (SID 0x{sid:02X}, phys 0x7E0)")

            # --- UDS 0x19 ---
            for req, label in UDS_DTC_REQUESTS:
                _send(bus, bus_id, bus_name, FUNC_ADDR, req, label)
                if phys:
                    _send(bus, bus_id, bus_name, VCM_PHYS, req, label + " phys 0x7E0")

            # --- KWP2000 0x18 ---
            for req, label in KWP_DTC_REQUESTS:
                _send(bus, bus_id, bus_name, FUNC_ADDR, req, label)
                if phys:
                    _send(bus, bus_id, bus_name, VCM_PHYS, req, label + " phys 0x7E0")

            # --- PT bus only: address sweeps and J1939 DM requests ---
            if bus_name == "PT":
                # Broad discovery sweep: 0x700-0x7DF with TesterPresent only.
                # These 223 addresses have never been queried. Lightweight request to
                # find any module that responds. Response may come at req+1, req+8, req+0x10
                # (all captured in the log; real-time decode covers 0x700-0x7FF).
                print(f"  Broad sweep: 0x700-0x7DF with TesterPresent ({len(PT_BROAD_SWEEP)} addrs)...")
                tp_req = bytes([0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                for addr in PT_BROAD_SWEEP:
                    _send(bus, bus_id, bus_name, addr, tp_req,
                          f"TesterPresent sweep 0x{addr:03X}", delay=0.05)

                # Detail sweep: 0x7E0-0x7EF with Mode03 + UDS 0x19 (known diagnostic range)
                print(f"  Detail sweep: 0x7E1-0x7EF with Mode03 + UDS 0x19...")
                mode03 = make_obd_request(0x03)
                uds19  = bytes([0x03, 0x19, 0x02, 0xFF, 0x00, 0x00, 0x00, 0x00])
                for addr in PT_DETAIL_SWEEP[1:]:   # skip 0x7E0, already sent above
                    _send(bus, bus_id, bus_name, addr, mode03,
                          f"OBD-II Mode03 sweep addr 0x{addr:03X}")
                    _send(bus, bus_id, bus_name, addr, uds19,
                          f"UDS 0x19/02 sweep addr 0x{addr:03X}")

                # J1939 DM1/DM2 requests.
                # DCDC (SA=0xB3) confirmed to broadcast DM1 spontaneously (2026-03-30).
                # DM2 (PGN 0xFECB) requests stored/previously-active fault history.
                print(f"  J1939 DM1/DM2 requests to DCDC, Charger, global...")
                for dest_sa, dest_name in J1939_TARGETS:
                    req_id = make_j1939_request_id(dest_sa)
                    for pgn, pgn_data, pgn_label in J1939_PGNS:
                        j_msg = can.Message(
                            arbitration_id=req_id,
                            data=pgn_data,
                            is_extended_id=True,
                        )
                        try:
                            ts_rel = time.time() - session_start
                            bus.send(j_msg)
                            fake = can.Message(
                                arbitration_id=req_id,
                                data=pgn_data,
                                is_extended_id=True,
                                timestamp=time.time(),
                            )
                            msg_queue.put((ts_rel, bus_id, fake, "Tx"))
                            print(f"  [{ts_rel:6.2f}s] Tx Bus {bus_id} (PT): "
                                  f"0x{req_id:08X}x J1939 Request {pgn_label} "
                                  f"-> {dest_name}(0x{dest_sa:02X})")
                        except Exception as e:
                            log.error("J1939 send failed: %s", e)
                        time.sleep(0.2)   # longer wait: DM2 may trigger multipacket TP

            time.sleep(0.2)

        print()
        print(f"Logging responses for {log_secs:.0f}s...")
        drain_queue_to_writer(writer, log_end, "log")

    # ------------------------------------------------------------------
    # Stop receive threads
    # ------------------------------------------------------------------
    for bl in loggers:
        bl.stop()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SESSION SUMMARY")
    print("=" * 60)
    if dtc_findings:
        print(f"DTC codes received ({len(dtc_findings)} total):")
        for source, code, desc_str in dtc_findings:
            print(f"  [{source}] {code}: {desc_str}")
    else:
        print("No DTC response frames received.")
        print()
        print("Possible reasons:")
        print("  - Ignition/key must be ON for modules to respond")
        print("  - No stored DTCs present (normal if truck is healthy)")
        print("  - 0x065B may require a different request address on the PT bus")
        print("  - Check the log file for any unexpected responses near 0x7E8-0x7EF")
    print()
    print(f"Full log saved to: {output_path}")
    print()


def resolve_output_path(output_arg):
    """Resolve output file path, defaulting to artifacts/ with timestamp name."""
    if output_arg:
        p = Path(output_arg)
        if not p.is_absolute() and "/" not in output_arg and "\\" not in output_arg:
            p = DEFAULT_OUTPUT_DIR / p
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        p = DEFAULT_OUTPUT_DIR / f"dtc_interrogation_{ts}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Vtrux DTC interrogation: send OBD-II DTC requests and log responses"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=(
            "Output log file path. A bare filename goes into artifacts/. "
            "Default: artifacts/dtc_interrogation_<timestamp>.log"
        ),
    )
    parser.add_argument(
        "--ident-time",
        type=float,
        default=3.0,
        help="Seconds to listen before sending requests (bus identification phase). Default: 3",
    )
    parser.add_argument(
        "--log-time",
        type=float,
        default=30.0,
        help="Seconds to log after sending requests. Default: 30",
    )
    parser.add_argument(
        "--brands",
        default=None,
        help="Comma-separated CAN dongle brands to use (e.g. ixxat,kvaser). Default: all.",
    )
    args = parser.parse_args()
    run_session(args)


if __name__ == "__main__":
    main()
