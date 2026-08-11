"""
Decode BMS alarm, contactor state, and cell voltages from post-failure logs.
Shows unique state transitions for 0x410, 0x440, 0x430 across each log.

Usage: py -3.12 tools/... (run from project root)
Logs analyzed: Sep 15/19/20 2025 (Bel-Inverter/other-logs), Oct 25 2025 (truk1log)
"""

import re

ALARM_STRINGS = ["NONE", "TYPE1", "TYPE2", "TYPE3", "Invalid"]
MAINC_STAT = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
CHGC_STAT = ["OPEN", "CLOSED", "HIGH", "LOW"]

LINE_RE = re.compile(
    r'^(\d+:\d+:\d+:\d+)\s+Rx\s+\d+\s+(0x[0-9A-Fa-f]+)\s+[sx]\s+\d+\s+(.+)$'
)

LOGS = [
    ("Sep15", "projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T1.log"),
    ("Sep19", "projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T0.log"),
    ("Sep20", "projects/vtrux/Bel-Inverter/other-logs/TRUKLOG_M1_T0.log"),
    ("Oct25-truk1log-M0", "projects/vtrux/logs/truk1log_M0_T0.log"),
]


def parse_elapsed(ts, t_zero_ref):
    parts = ts.split(":")
    abs_s = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/10000.0
    if t_zero_ref[0] is None:
        t_zero_ref[0] = abs_s
    return abs_s - t_zero_ref[0]


for label, path in LOGS:
    print(f"\n=== {label}: {path.split('/')[-1]} ===")
    t_zero_ref = [None]
    prev_410 = None
    prev_440 = None
    prev_vmax = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = LINE_RE.match(line.rstrip())
                if not m:
                    continue
                ts, cid, dp = m.group(1), m.group(2).upper(), m.group(3)
                t = parse_elapsed(ts, t_zero_ref)
                try:
                    data = [int(x, 16) for x in dp.split()]
                except ValueError:
                    continue

                if cid == "0X410" and len(data) >= 2:
                    B0, B1 = data[0], data[1]
                    alarm = ALARM_STRINGS[(B1 >> 6) & 3]
                    chgc = CHGC_STAT[(B0 >> 6) & 3]
                    epo = (B0 >> 4) & 1
                    hvil = (B0 >> 3) & 1
                    ready = B0 & 1
                    state = (alarm, chgc, epo, hvil, ready)
                    if state != prev_410:
                        print(f"  t={t:7.1f}  0x410  alarm={alarm:<6}  chgc={chgc:<6}  epo={epo}  hvil={hvil}  ready={ready}  [B0={B0:02X} B1={B1:02X}]")
                        prev_410 = state

                elif cid == "0X440" and len(data) >= 1:
                    B0 = data[0]
                    idx = (B0 >> 2) & 0xF
                    mainc = MAINC_STAT[idx]
                    if mainc != prev_440:
                        print(f"  t={t:7.1f}  0x440  mainc_stat={mainc}  [B0={B0:02X}]")
                        prev_440 = mainc

                elif cid == "0X430" and len(data) >= 4:
                    B0, B1, B2, B3 = data[0], data[1], data[2], data[3]
                    raw_vmax = ((B0 & 0x1F) << 8) | B1
                    raw_vmin = ((B2 & 0x1F) << 8) | B3
                    if raw_vmax == 0x1FFE or raw_vmin == 0x1FFE:
                        continue
                    vmax = raw_vmax * 0.001
                    vmin = raw_vmin * 0.001
                    # Print on first read or >= 5 mV change
                    if prev_vmax is None or abs(vmax - prev_vmax) >= 0.005:
                        spread = int((vmax - vmin) * 1000)
                        print(f"  t={t:7.1f}  0x430  vmax={vmax:.3f}V  vmin={vmin:.3f}V  spread={spread}mV")
                        prev_vmax = vmax

    except FileNotFoundError:
        print("  NOT FOUND")
