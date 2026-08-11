"""
Characterize the earliest post-swap DRIVING logs (winter 2026) to compare
battery internal resistance + imbalance against today's summer drive.
Swap date: 2025-12-09. First post-swap drive: movingaroundindriveway (2026-02-16).
"""
import sys, os
sys.path.insert(0, ".")
from battery_degradation_characterize import characterize

L = "projects/vtrux/logs"
SESSIONS = [
    ("movingaroundindriveway 2026-02-16", [f"{L}/movingaroundindriveway.log"]),
    ("vtruxevapdrivelog4 2026-02-25", [f"{L}/vtruxevapdrivelog4.log",
                                       f"{L}/vtruxevapdrivelog4part2.log"]),
    ("vtruxcurrentlimitingtest 2026-02-25", [f"{L}/vtruxcurrentlimitingtest.log"]),
    ("vtruxevapdrivelog 2026-02-25", [f"{L}/vtruxevapdrivelog.log"]),
]

results = []
for label, files in SESSIONS:
    if not all(os.path.exists(f) for f in files):
        print(f"MISSING: {label}")
        continue
    r = characterize(label, files)
    if r:
        results.append(r)
