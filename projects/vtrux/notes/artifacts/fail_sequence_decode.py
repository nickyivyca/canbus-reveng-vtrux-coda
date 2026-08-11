"""
Decode fail sequence from "full charge then fail.log"
Extracts: bcm_mainc_stat (0x440), bcm_alarm (0x410), bcm_cell_vmax/vmin (0x430)
around the failure window.

Signal encodings from original-datalogging-investigation.md (Ghidra-confirmed):
  0x410 B0 bits[5:4]: bcm_mainc_stat index for chgc (charge contactor)
       B0 bits[7:6]: bcm_chgc_stat index (same 4-entry OPEN/CLOSED/HIGH/LOW array)
       B1 bits[7:6]: bcm_alarm index -> ["NONE","TYPE1","TYPE2","TYPE3"]
       B0 bit 4: bcm_epo
       B0 bit 3: bcm_hvil_mon
  0x440 B0 bits[5:2]: bcm_mainc_stat index (16-entry contactor sequence array)
  0x430 B0&0x1F, B1: bcm_cell_vmax = ((B0&0x1F)<<8|B1)*0.001 V
        B2&0x1F, B3: bcm_cell_vmin = ((B2&0x1F)<<8|B3)*0.001 V
"""

import sys
import re

LOG_PATH = "projects/vtrux/logs/full charge then fail.log"

# Time window: from chg_done (t~6694s) through final shutdown (t~7380s)
T_START = 6650.0
T_END   = 7400.0

# bcm_alarm strings (0x410 B1 bits[7:6])
ALARM_STRINGS = ["NONE", "TYPE1", "TYPE2", "TYPE3", "Invalid"]

# bcm_mainc_stat 16-entry array (0x440 B0 bits[5:2])
MAINC_STAT = [
    "ALL_OPEN",            # 0
    "FAILED_MAINP_OR_R_WELD",  # 1
    "CLOSE_MAINR",         # 2
    "FAILED_MAINR_OPEN",   # 3
    "FAILED_MAINN_WELD",   # 4
    "CLOSE_MAINN",         # 5
    "FAILED_MAINN_OPEN",   # 6
    "WAIT_PRECHARGE",      # 7
    "CLOSE_MAINP",         # 8
    "OPEN_MAINR",          # 9
    "FAILED_MAINP_OPEN",   # 10
    "MAIN_PN_CLOSED_DRIVE", # 11
    "MAIN_P_CLOSED_CHARGE", # 12
    "SHUTDOWN_REQUEST",    # 13
    "ALL_OPEN_SHUTDOWN",   # 14
    "(idx15-artifact)",    # 15
]

# bcm_chgc_stat / bcm_mainc_stat shared 4-entry array (0x410 B0)
CHGC_STAT = ["OPEN", "CLOSED", "HIGH", "LOW"]

t_zero = None  # set on first frame

def parse_time(ts):
    """Parse HH:MM:SS:TTTT BUSMASTER wall-clock timestamp to elapsed seconds."""
    global t_zero
    parts = ts.split(":")
    if len(parts) == 4:
        h, m, s, tk = parts
        abs_s = int(h)*3600 + int(m)*60 + int(s) + int(tk)/10000.0
        if t_zero is None:
            t_zero = abs_s
        return abs_s - t_zero
    return None

def parse_bytes(byte_strs):
    return [int(b, 16) for b in byte_strs]

# State tracking (print only on change)
prev = {
    "alarm": None,
    "mainc_stat": None,
    "chgc_stat": None,
    "epo": None,
    "hvil": None,
    "vmax": None,
    "vmin": None,
}

LINE_RE = re.compile(
    r'^(\d+:\d+:\d+:\d+)\s+Rx\s+\d+\s+(0x[0-9A-Fa-f]+)\s+[sx]\s+\d+\s+(.+)$'
)

print(f"{'Time':>10}  {'ID':>6}  Signal")
print("-" * 70)

with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.rstrip()
        m = LINE_RE.match(line)
        if not m:
            continue
        ts, can_id, data_part = m.group(1), m.group(2).upper(), m.group(3)
        t = parse_time(ts)
        if t is None or t < T_START or t > T_END:
            continue
        raw = data_part.split()
        try:
            data = parse_bytes(raw)
        except ValueError:
            continue

        if can_id == "0X410" and len(data) >= 2:
            B0, B1 = data[0], data[1]
            alarm_idx = (B1 >> 6) & 0x3
            alarm = ALARM_STRINGS[alarm_idx]
            chgc_idx = (B0 >> 6) & 0x3
            chgc = CHGC_STAT[chgc_idx]
            epo = 1 if (B0 & 0x10) else 0
            hvil = 1 if (B0 & 0x08) else 0

            changed = []
            if alarm != prev["alarm"]:
                changed.append(f"bcm_alarm: {prev['alarm']} -> {alarm}")
                prev["alarm"] = alarm
            if chgc != prev["chgc_stat"]:
                changed.append(f"bcm_chgc_stat: {prev['chgc_stat']} -> {chgc}")
                prev["chgc_stat"] = chgc
            if epo != prev["epo"]:
                changed.append(f"bcm_epo: {prev['epo']} -> {epo}")
                prev["epo"] = epo
            if hvil != prev["hvil"]:
                changed.append(f"bcm_hvil_mon: {prev['hvil']} -> {hvil}")
                prev["hvil"] = hvil
            for ch in changed:
                print(f"{t:10.2f}  0x0410  {ch}  [B0={B0:02X} B1={B1:02X}]")

        elif can_id == "0X440" and len(data) >= 1:
            B0 = data[0]
            idx = (B0 >> 2) & 0xF
            mainc = MAINC_STAT[idx] if idx < len(MAINC_STAT) else f"idx{idx}"
            if mainc != prev["mainc_stat"]:
                print(f"{t:10.2f}  0x0440  bcm_mainc_stat: {prev['mainc_stat']} -> {mainc}  [B0={B0:02X} idx={idx}]")
                prev["mainc_stat"] = mainc

        elif can_id == "0X430" and len(data) >= 4:
            B0, B1, B2, B3 = data[0], data[1], data[2], data[3]
            raw_vmax = ((B0 & 0x1F) << 8) | B1
            raw_vmin = ((B2 & 0x1F) << 8) | B3
            # sentinel check
            vmax = None if raw_vmax == 0x1FFE else raw_vmax * 0.001
            vmin = None if raw_vmin == 0x1FFE else raw_vmin * 0.001

            # Print every 30s or on significant change (>= 5mV)
            vmax_changed = (vmax is not None and prev["vmax"] is not None and
                            abs(vmax - prev["vmax"]) >= 0.005)
            vmin_changed = (vmin is not None and prev["vmin"] is not None and
                            abs(vmin - prev["vmin"]) >= 0.005)
            first_time = prev["vmax"] is None

            if first_time or vmax_changed or vmin_changed:
                print(f"{t:10.2f}  0x0430  cell_vmax={vmax:.3f}V  cell_vmin={vmin:.3f}V  spread={(vmax-vmin)*1000:.0f}mV")
                prev["vmax"] = vmax
                prev["vmin"] = vmin
