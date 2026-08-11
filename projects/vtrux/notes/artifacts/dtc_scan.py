"""
Scan for DTC codes in 0x065B across charge session logs.
Encoding (Ghidra-confirmed, original-datalogging-investigation.md):
  DTC code = (B6 << 8) | B7 (big-endian uint16)
  0x0000 = null (no DTC)
  Non-zero = lookup in 29-entry table

Logs scanned:
  - projects/vtrux/logs/full charge then fail.log
  - projects/vtrux/Bel-Inverter/actual-failed-charges/  (M0_b and M1_b sessions)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/dtc_scan.py
"""

import sys
sys.path.insert(0, ".")

from pathlib import Path
from canre.utils.sessions import list_session_files
from canre.utils.merge import merge_files
from canre.parsers.autodetect import parse_file

DTC_TABLE = {
    0x0D67: "aChgr_p0d67ChgrPfrm_dtc -- charger platform DTC",
    0x1A20: "sEss_p1a20BecmAFlt -- BECM fault A",
    0x0A7B: "sEss_p0a7bBecmMilOnReq -- BECM MIL-on request",
    0x1A21: "sEss_p1a21BecmACritFlt -- BECM critical fault A",
    0x1A81: "sEss_p1a81HvilPrfmGene -- HVIL performance, generator",
    0x1A82: "sEss_p1a82HvilPrfmTrac -- HVIL performance, traction",
    0x1A80: "sEss_p1a80HvilPrfmDcdc -- HVIL performance, DCDC",
    0x0AA6: "sEss_p0aa6HvIso -- HV isolation",
    0x1AA0: "sChgr_p1aa0ChgrShtdwn -- charger shutdown",
    0x0A0B: "cEss_p0a0bHvilPrfm -- ESS HVIL performance",
    0x0A1F: "cEss_p0a1fEss -- ESS fault",
    0xD300: "diagHcu_u1300AppIntrptTsk -- HCU: app interrupt task",
    0xD301: "diagHcu_u1301LowMemTsk2 -- HCU: low mem task 2",
    0xD302: "diagHcu_u1302LowMemTsk1 -- HCU: low mem task 1",
    0xD303: "diagHcu_u1303LowMemIdleTsk -- HCU: low mem idle task",
    0xD304: "diagHcu_u1304LowMemIntrpt -- HCU: low mem interrupt",
    0xD305: "diagHcu_u1305LowMemKernel -- HCU: low mem kernel",
    0xD306: "diagHcu_u1306ShtdwnTsk -- HCU: shutdown task",
    0xD307: "diagHcu_u1307LowMemHeap -- HCU: low mem heap",
    0xD311: "diagHcu_u1311HighCpuTsk2 -- HCU: high CPU task 2",
    0xD310: "diagHcu_u1310HighCpuAppIntrptTsk -- HCU: high CPU app interrupt task",
    0xD312: "diagHcu_u1312HighCpuTsk1 -- HCU: high CPU task 1",
    0xD313: "diagHcu_u1313HighCpuShtdwnTsk -- HCU: high CPU shutdown task",
    0xD314: "diagHcu_u1314CpuIdleApp -- HCU: CPU idle app",
    0xC129: "inAbstrCanEbcm_u0129LostRx -- CAN lost Rx: EBCM",
    0xC100: "inAbstrCanEcm_u0100LostRx -- CAN lost Rx: ECM",
    0xC16B: "inAbstrCanAccm_u016BLostRx -- CAN lost Rx: ACCM",
    0xC111: "inAbstrCanBecm_u0111LostRx -- CAN lost Rx: BECM",
    0xC296: "inAbstrCanBdc_u0296LostRx -- CAN lost Rx: BDC",
}


def scan_frames(frames, label):
    prev_code = None
    found_any = False
    for frame in frames:
        if frame.arbitration_id != 0x065B:
            continue
        if len(frame.data) < 8:
            continue
        code = (frame.data[6] << 8) | frame.data[7]
        if code == prev_code:
            continue
        prev_code = code
        t = frame.timestamp
        if code == 0x0000:
            name = "<null>"
        else:
            name = DTC_TABLE.get(code, f"UNKNOWN (0x{code:04X})")
        print(f"  t={t:9.2f}  DTC 0x{code:04X}  {name}")
        found_any = True
    if not found_any:
        print("  (no 0x065B frames found)")


# --- Full charge then fail ---
print("\n" + "="*70)
print("full charge then fail.log")
print("="*70)
log_path = Path("projects/vtrux/logs/full charge then fail.log")
scan_frames(parse_file(log_path), log_path.name)

# --- Actual failed charges (M0_b and M1_b only -- have PT bus data) ---
afc_dir = Path("projects/vtrux/Bel-Inverter/actual-failed-charges")
sessions, standalones = list_session_files(afc_dir)

for name in sorted(sessions.keys()):
    paths = sessions[name]
    print(f"\n{'='*70}")
    print(f"Session: {name}  ({len(paths)} file(s))")
    scan_frames(merge_files(paths), name)
