"""
Extract cell voltages (0x430 bcm_cell_vmax/vmin) from post-failure September logs.
Shows all unique readings to track whether the overvoltage cell is still present.

Signal encoding (Ghidra-confirmed from original-datalogging-investigation.md):
  bcm_cell_vmax = ((B0 & 0x1F) << 8 | B1) * 0.001 V
  bcm_cell_vmin = ((B2 & 0x1F) << 8 | B3) * 0.001 V
  Sentinel: raw == 0x1FFE -> invalid
"""

import re

LINE_RE = re.compile(
    r'^(\d+:\d+:\d+:\d+)\s+Rx\s+\d+\s+(0x[0-9A-Fa-f]+)\s+[sx]\s+\d+\s+(.+)$'
)

LOGS = [
    ("Sep15", "projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T1.log"),
    ("Sep19", "projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T0.log"),
    ("Sep20", "projects/vtrux/Bel-Inverter/other-logs/TRUKLOG_M1_T0.log"),
]

for label, path in LOGS:
    print(f"\n=== {label}: {path.split('/')[-1]} ===")
    t_zero = None
    prev = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = LINE_RE.match(line.rstrip())
                if not m:
                    continue
                ts, cid, dp = m.group(1), m.group(2).upper(), m.group(3)
                if cid != "0X430":
                    continue
                parts = ts.split(":")
                abs_s = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/10000.0
                if t_zero is None:
                    t_zero = abs_s
                t = abs_s - t_zero
                try:
                    data = [int(x, 16) for x in dp.split()]
                except ValueError:
                    continue
                if len(data) < 4:
                    continue
                B0, B1, B2, B3 = data[0], data[1], data[2], data[3]
                raw_vmax = ((B0 & 0x1F) << 8) | B1
                raw_vmin = ((B2 & 0x1F) << 8) | B3
                if raw_vmax == 0x1FFE or raw_vmin == 0x1FFE:
                    continue
                vmax = raw_vmax * 0.001
                vmin = raw_vmin * 0.001
                cur = (vmax, vmin)
                if prev is None or abs(vmax - (prev[0])) >= 0.005:
                    spread = int((vmax - vmin) * 1000)
                    print(f"  t={t:7.1f}  vmax={vmax:.3f}V  vmin={vmin:.3f}V  spread={spread}mV")
                    prev = cur
    except FileNotFoundError:
        print("  NOT FOUND")
