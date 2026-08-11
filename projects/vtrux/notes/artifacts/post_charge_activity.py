"""
Check for activity after the charge failure in "full charge then fail.log".
Failure occurred at t~7243s. Log ends at t~7378s (~135s of post-failure data).
Looks for: drive mode attempts (0x440 mainc_stat), operation state (0x053),
motor RPM (0x5A2), ignition key / EVSE state (0x592), charger state (0x3FE),
and any 0x410 alarm changes.
"""

import re

LINE_RE = re.compile(
    r'^(\d+:\d+:\d+:\d+)\s+Rx\s+\d+\s+(0x[0-9A-Fa-f]+)\s+[sx]\s+\d+\s+(.+)$'
)

LOG = "projects/vtrux/logs/full charge then fail.log"

ALARM_STRINGS = ["NONE", "TYPE1", "TYPE2", "TYPE3", "Invalid"]
MAINC_STAT = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
CHGC_STAT = ["OPEN", "CLOSED", "HIGH", "LOW"]
OP_MODE  = ["Normal", "Error1", "Error2", "Error3"]
OP_STATE = ["Init", "Standby", "Start", "Run", "Stop", "Failure", "Fault", "Safe", "Reserved"]

T_START = 7200.0   # start a bit before the failure for context
T_END   = 9999.0   # all the way to end of log

t_zero = None

prev = {}

def changed(key, val):
    if prev.get(key) != val:
        prev[key] = val
        return True
    return False

with open(LOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        m = LINE_RE.match(line.rstrip())
        if not m:
            continue
        ts, cid, dp = m.group(1), m.group(2).upper(), m.group(3)
        parts = ts.split(":")
        abs_s = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/10000.0
        if t_zero is None:
            t_zero = abs_s
        t = abs_s - t_zero
        if t < T_START:
            continue
        try:
            data = [int(x, 16) for x in dp.split()]
        except ValueError:
            continue

        # 0x410 — BMS alarm / contactor / EPO
        if cid == "0X410" and len(data) >= 2:
            B0, B1 = data[0], data[1]
            alarm = ALARM_STRINGS[(B1 >> 6) & 3]
            chgc  = CHGC_STAT[(B0 >> 6) & 3]
            epo   = (B0 >> 4) & 1
            hvil  = (B0 >> 3) & 1
            ready = B0 & 1
            state = (alarm, chgc, epo, hvil, ready)
            if changed("0x410", state):
                print(f"t={t:8.2f}  0x410  alarm={alarm:<6} chgc={chgc:<6} epo={epo} hvil={hvil} ready={ready}  [B0={B0:02X} B1={B1:02X}]")

        # 0x440 — contactor sequence
        elif cid == "0X440" and len(data) >= 1:
            B0 = data[0]
            idx = (B0 >> 2) & 0xF
            mainc = MAINC_STAT[idx]
            if changed("0x440", mainc):
                print(f"t={t:8.2f}  0x440  mainc_stat={mainc}  [B0={B0:02X}]")

        # 0x053 — charger operation mode/state
        elif cid == "0X053" and len(data) >= 1:
            B0 = data[0]
            mode_idx = (B0 >> 4) & 0x7
            state_idx = B0 & 0xF
            mode  = OP_MODE[mode_idx]  if mode_idx  < len(OP_MODE)  else f"mode{mode_idx}"
            state = OP_STATE[state_idx] if state_idx < len(OP_STATE) else f"state{state_idx}"
            val = (mode, state)
            if changed("0x053", val):
                print(f"t={t:8.2f}  0x053  mode={mode} state={state}  [B0={B0:02X}]")

        # 0x592 — ignition key, EVSE switch, export power
        elif cid == "0X592" and len(data) >= 1:
            B0 = data[0]
            ign   = (B0 >> 4) & 1
            evse  = (B0 >> 1) & 1
            exprt = (B0 >> 2) & 1
            val = (ign, evse, exprt)
            if changed("0x592", val):
                print(f"t={t:8.2f}  0x592  ignition={ign} evse_sw={evse} export={exprt}  [B0={B0:02X}]")

        # 0x5A2 — motor RPM (B2-B3 LE, centered 32768)
        elif cid == "0X5A2" and len(data) >= 4:
            rpm_raw = data[2] | (data[3] << 8)
            rpm = rpm_raw - 32768
            # only print if RPM changes by more than 50 (noise filter)
            if abs(rpm - prev.get("rpm", 0)) > 50:
                prev["rpm"] = rpm
                print(f"t={t:8.2f}  0x5A2  motor_RPM={rpm:+d}")

        # 0x3FE — charger state
        elif cid == "0X3FE" and len(data) >= 1:
            state_val = data[0]
            if changed("0x3FE_state", state_val):
                print(f"t={t:8.2f}  0x3FE  charger_state={state_val}  [B0={state_val:02X}]")
