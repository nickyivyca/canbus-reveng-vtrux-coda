"""Investigate the 2026-07-19 drive where the Android display showed EVAP=COMPLETE
but an evap cycle started once SoC fell to 80%.

Phase 1: extract the evap state bytes (0x649 B0/B2/B3/B4), the VCM evap-pending
byte (0x640 B0), the generator flag (0x600 B0) and SoC (0x596 B6) across the
whole session. Flag bytes print every transition; the evap counter is sampled
periodically so it does not flood the output.
"""

import sys
sys.path.insert(0, ".")

import glob
import re
from canre.parsers import parse_file

LOGDIR = "../../CANLogs/VtruxLogs"
PREFIX = "vtrux_20260719_164520_T"

# Bytes where every transition matters (flags / state).
FLAG_BYTES = {
    0x649: [0, 4],
    0x640: [0],
    0x600: [0],
}
SOC_ID = 0x596
SOC_BYTE = 6
SNAPSHOT_INTERVAL = 60.0


def chunk_files():
    files = glob.glob(f"{LOGDIR}/{PREFIX}*.log")
    def idx(p):
        return int(re.search(r"_T(\d+)\.log$", p).group(1))
    return sorted(files, key=idx)


def main():
    last = {}
    state = {"soc": None, "ec": None, "b3": None, "b2lo": None}
    t_base = 0.0
    t_last = 0.0
    next_snap = 0.0

    for path in chunk_files():
        name = path.split("/")[-1]
        print(f"### {name} (t_base={t_base:.1f}s)", flush=True)
        for f in parse_file(path):
            t = t_base + f.timestamp
            t_last = t
            d = f.data

            if f.arbitration_id == 0x649 and len(d) >= 4:
                state["b2lo"] = d[2] & 0x0F
                state["b3"] = d[3]
                state["ec"] = (state["b2lo"] << 8) | d[3]

            if f.arbitration_id in FLAG_BYTES:
                for b in FLAG_BYTES[f.arbitration_id]:
                    if b >= len(d):
                        continue
                    key = (f.arbitration_id, b)
                    if last.get(key) != d[b]:
                        old = last.get(key)
                        olds = "--" if old is None else f"0x{old:02X}"
                        print(f"  t={t:9.3f}  0x{f.arbitration_id:03X} B{b}: {olds} -> 0x{d[b]:02X}"
                              f"   soc={state['soc']} ec=0x{(state['ec'] or 0):03X}",
                              flush=True)
                        last[key] = d[b]
            elif f.arbitration_id == SOC_ID and len(d) > SOC_BYTE:
                if d[SOC_BYTE] != state["soc"]:
                    print(f"  t={t:9.3f}  SoC: {state['soc']} -> {d[SOC_BYTE]}%"
                          f"   ec=0x{(state['ec'] or 0):03X}", flush=True)
                    state["soc"] = d[SOC_BYTE]

            if t >= next_snap:
                next_snap = t + SNAPSHOT_INTERVAL
                b0 = last.get((0x649, 0))
                b4 = last.get((0x649, 4))
                print(f"  t={t:9.3f}  [snap] 0x649 B0="
                      f"{'--' if b0 is None else f'0x{b0:02X}'}"
                      f" B4={'--' if b4 is None else f'0x{b4:02X}'}"
                      f" ec=0x{(state['ec'] or 0):03X} soc={state['soc']}", flush=True)

        t_base = t_last


if __name__ == "__main__":
    main()
