"""AC source resistance at the second (working) ChargePoint, 2026-09-25, using
the estimators of artifacts/ac-voltage/ac_voltage_source_resistance.py
(step_estimates = the drift-immune one quoted in notes/ac-resistance.md;
level_fit = whole-session ladder fit; load_dump_anchor = measured Voc).
Input: vtrux_20260925_155857 T0-T*, merged, PT bus via canre.utils.buses.
Usage: python3.13 <this>
"""
import glob
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/vtrux/notes/artifacts/ac-voltage")

import cantools
from canre.utils.buses import describe, resolve_files
from canre.utils.merge import merge_files
import ac_voltage_source_resistance as acr

ANCH = [("powertrain", {0x051, 0x18FFD4C0}), ("vehicle", {0x1E5, 0x500}),
        ("obd", {0x040, 0x041, 0x042, 0x043, 0x044})]
paths = sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260925_155857_T*.log"))
bus_map = resolve_files(paths, ANCH)
db = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc", strict=False)
m = db.get_message_by_name("BELINV_hvBatteryAndCharger")
series, loaded = [], []
for fr in merge_files(paths, bus_map=bus_map):
    if fr.bus != "powertrain" or fr.arbitration_id != 0x18FFD7C0 or fr.timestamp < 280:
        continue
    d = m.decode(bytes(fr.data))
    v, i = d["BELINV_chargerInputVoltage"], d["BELINV_chargerInputCurrent"]
    if not acr.valid(v, i):
        continue
    series.append((fr.timestamp, v, i))
    if i >= acr.MIN_FIT_CURRENT_A:
        loaded.append((v, i, d["BELINV_hvBatteryVoltage"], d["BELINV_hvBatteryCurrent"]))
print(f"{len(series)} samples from t={series[0][0]:.0f} to {series[-1][0]:.0f} s")
vs = sorted(v for _, v, i in series if i >= 2)
is_ = sorted(i for _, v, i in series if i >= 2)
print(f"loaded: Vmed={acr.pct(vs, .5):.1f} V  Imed={acr.pct(is_, .5):.1f} A  Imax={is_[-1]:.1f} A")
steps = acr.step_estimates(series)
print("steps (R ohm, dI A, t):", [(round(r, 3), round(di, 1), round(t)) for r, di, t in steps])
if steps:
    print(f"R steps median = {acr.pct(sorted(r for r, _, _ in steps), .5):.3f} ohm over {len(steps)} steps")
lr, lvoc, lcorr, levels = acr.level_fit(loaded)
print(f"ladder fit: R={lr} Voc={lvoc} corr={lcorr} levels={[(round(a,1), round(b,1), n) for a, b, n in levels]}")
print("load-dump Voc:", acr.load_dump_anchor(series))

# Phase 2: intermittency -- samples at steady load (I within 1 A of the
# rolling 5 s median) whose V falls > 3 V below the rolling 5 s median V.
from collections import deque
win = deque()
dips, steady = [], 0
for t, v, i in series:
    win.append((t, v, i))
    while win and win[0][0] < t - 5:
        win.popleft()
    if len(win) < 20:
        continue
    mv = sorted(x[1] for x in win)[len(win) // 2]
    mi = sorted(x[2] for x in win)[len(win) // 2]
    if mi < 5 or abs(i - mi) > 1.0:
        continue
    steady += 1
    if v < mv - 3:
        dips.append((round(t, 1), round(v, 1), round(mv, 1), round(i, 1)))
print(f"\nsteady-load samples: {steady}, V dips > 3 V below 5 s median: {len(dips)}")
print(dips[:30])
