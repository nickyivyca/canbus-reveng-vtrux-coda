"""
For each Bel Inverter charging session, find the last moment where
the charger is still actively pushing current (abs(I) > 0.5A) and
record both the charger's hvBatteryVoltage and 0x420 pack voltage.

Charger ground truth (0x18FFD7C0):
  hvBatteryVoltage: B0-B1 LE signed16 * 0.05 -> Volts
  hvBatteryCurrent: B2-B3 LE signed16 * 0.05 -> Amps (negative = charging)

0x420 candidate:
  PackVoltage: B0-B1 BE / 100 -> Volts
"""

import re
import struct
import os

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)
CHARGER_ID = 0x18FFD7C0
VEHICLE_ID = 0x420
MIN_CURRENT_A = 0.5   # abs amps threshold for "charging active"


def parse_ts(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


def scan_file(path):
    """
    Returns (last_active_charger_v, last_active_420_v, last_active_t)
    at the last moment where abs(charger current) > MIN_CURRENT_A.
    Returns None if the file has no charger data or never shows active charging.
    """
    charger_v = None
    charger_i = None
    v420 = None
    last_charger_v = None
    last_420_v = None
    last_active_t = None
    t0 = None

    try:
        with open(path, errors='replace') as f:
            for line in f:
                m = BUSMASTER_RE.match(line.strip())
                if not m:
                    continue
                ts_str, _, id_str, _, data_str = m.groups()
                mid = int(id_str, 16)
                ts = parse_ts(ts_str)
                if t0 is None:
                    t0 = ts
                rel = ts - t0
                data = [int(b, 16) for b in data_str.strip().split()]

                if mid == CHARGER_ID and len(data) >= 4:
                    raw_v = struct.unpack_from('<h', bytes(data[:2]))[0]
                    raw_i = struct.unpack_from('<h', bytes(data[2:4]))[0]
                    charger_v = raw_v * 0.05
                    charger_i = raw_i * 0.05

                elif mid == VEHICLE_ID and len(data) >= 2:
                    v420 = ((data[0] << 8) | data[1]) / 100.0

                # Record snapshot whenever charging is active
                if charger_i is not None and abs(charger_i) > MIN_CURRENT_A:
                    last_charger_v = charger_v
                    last_420_v = v420
                    last_active_t = rel

    except FileNotFoundError:
        return None

    if last_active_t is None:
        return None
    return last_charger_v, last_420_v, last_active_t


BASE = r"projects/vtrux/Bel Inverter"

# Sessions: (label, filepath)
sessions = [
    # Root-level single-file sessions
    ("root/M0",           f"{BASE}/truklog_M0_T0.log"),
    ("root/M1",           f"{BASE}/truklog_M1_T0.log"),
    ("root/M2",           f"{BASE}/truklog_M2_T0.log"),

    # other-logs — last file of each session
    ("other/trukM0",      f"{BASE}/other-logs/truklog_M0_T24.log"),
    ("other/TRUKM1",      f"{BASE}/other-logs/TRUKLOG_M1_T0.log"),
    ("other/trukM1",      f"{BASE}/other-logs/truklog_M1_T14.log"),
    ("other/TRUKM2",      f"{BASE}/other-logs/TRUKLOG_M2_T7.log"),
    ("other/trukM2",      f"{BASE}/other-logs/truklog_M2_T21.log"),
    ("other/trukM3",      f"{BASE}/other-logs/truklog_M3_T22.log"),
    ("other/212M0",       f"{BASE}/other-logs/212charge_M0_T0.log"),
    ("other/212M1",       f"{BASE}/other-logs/212charge_M1_T9.log"),
    ("other/belre",       f"{BASE}/other-logs/belre.log"),
    ("other/charge2M0",   f"{BASE}/other-logs/charge2_M0.log"),
    ("other/charge2M1",   f"{BASE}/other-logs/charge2_M1.log"),
    ("other/charge2M2",   f"{BASE}/other-logs/charge2_M2.log"),
    ("other/charge3M0",   f"{BASE}/other-logs/charge3_M0.log"),
    ("other/charge4M0",   f"{BASE}/other-logs/charge4_M0_T2.log"),
    ("other/chargeM0",    f"{BASE}/other-logs/chargelog_M0.log"),
    ("other/chargeM1",    f"{BASE}/other-logs/chargelog_M1.log"),
    ("other/chargeM2",    f"{BASE}/other-logs/chargelog_M2.log"),
    ("other/chargeM3",    f"{BASE}/other-logs/chargelog_M3.log"),
    ("other/chargeM4",    f"{BASE}/other-logs/chargelog_M4.log"),
    ("other/chargeM5",    f"{BASE}/other-logs/chargelog_M5.log"),
    ("other/chargeM6",    f"{BASE}/other-logs/chargelog_M6.log"),
    ("other/chargeM7",    f"{BASE}/other-logs/chargelog_M7.log"),

    # actual-failed-charges — last file of each session
    ("fail/trukM0",       f"{BASE}/actual-failed-charges/truklog_M0_T10.log"),
    ("fail/trukM0(2)",    f"{BASE}/actual-failed-charges/truklog_M0_T5 (2).log"),
    ("fail/trukM1",       f"{BASE}/actual-failed-charges/truklog_M1_T14.log"),
    ("fail/trukM2",       f"{BASE}/actual-failed-charges/truklog_M2_T8.log"),
    ("fail/trukM3",       f"{BASE}/actual-failed-charges/truklog_M3_T21.log"),
    ("fail/trukM4",       f"{BASE}/actual-failed-charges/truklog_M4_T21.log"),
]

print(f"{'Session':<20}  {'Charger V':>10}  {'0x420 V':>10}  {'Delta':>8}  {'Active t':>9}")
print("-" * 68)

for label, path in sessions:
    result = scan_file(path)
    if result is None:
        print(f"{label:<20}  {'no active charge data':>10}")
        continue
    cv, v420, t = result
    if cv is None:
        print(f"{label:<20}  {'charger V missing':>10}")
        continue
    v420_str = f"{v420:10.2f}V" if v420 is not None else "    no 0x420"
    delta_str = f"{v420 - cv:+8.2f}V" if v420 is not None else "        —"
    print(f"{label:<20}  {cv:10.2f}V  {v420_str}  {delta_str}  {t:9.1f}s")
