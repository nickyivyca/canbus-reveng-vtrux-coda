"""Second, independent discriminator for the 0x598 encoding conflict.

epri-pt-bus.dbc says B0-B1 / B4-B5 are signed int16, offset 0.
vtrux.md + vtrux-powertrain-experimental.dbc say offset-binary (excess-32768).

The two hypotheses make *different* predictions for the known channel balance
    drivetrain = battery + generator
because the constant offsets do not cancel the same way:

  signed:   d_s == b_s + g_s          (raw values interpreted as int16)
  centered: (d-32768) == (b-32768) + (g-32768)  ->  d == b + g - 32768

Only one of these can hold. Also reports the worst frame-to-frame jump, since
under the signed reading every crossing of the 0x7FFF/0x8000 boundary would be
a ~655 kW discontinuity.
"""
import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file
from statistics import mean, pstdev

TARGET = 0x598
SCALE = 0.01


def s16(v):
    return v - 65536 if v >= 32768 else v


for path in sys.argv[1:]:
    raw = []
    for f in parse_file(path):
        if f.arbitration_id == TARGET and len(f.data) >= 6:
            d = f.data
            raw.append((d[0] | (d[1] << 8), d[2] | (d[3] << 8), d[4] | (d[5] << 8)))
    if not raw:
        print(f"{path}: no 0x598 frames")
        continue

    # Hypothesis A: offset-binary, excess-32768
    res_c = [(d - 32768) - ((b - 32768) + (g - 32768)) for b, g, d in raw]
    # Hypothesis B: plain signed int16, zero at 0
    res_s = [s16(d) - (s16(b) + s16(g)) for b, g, d in raw]

    # magnitude of the drivetrain channel under each reading, for a relative scale
    mag_c = mean(abs(d - 32768) for b, g, d in raw) or 1
    mag_s = mean(abs(s16(d)) for b, g, d in raw) or 1

    print(f"\n=== {path.split('/')[-1]}  ({len(raw)} frames) ===")
    print(f"  CENTERED  residual mean={mean(res_c)*SCALE:8.2f} kW  "
          f"sd={pstdev(res_c)*SCALE:7.2f} kW  "
          f"|residual|/|drivetrain| = {mean(abs(r) for r in res_c)/mag_c:6.1%}")
    print(f"  SIGNED    residual mean={mean(res_s)*SCALE:8.2f} kW  "
          f"sd={pstdev(res_s)*SCALE:7.2f} kW  "
          f"|residual|/|drivetrain| = {mean(abs(r) for r in res_s)/mag_s:6.1%}")

    # frame-to-frame jump on the drivetrain channel under each reading
    jump_c = max(abs((raw[i][2] - 32768) - (raw[i - 1][2] - 32768)) for i in range(1, len(raw)))
    jump_s = max(abs(s16(raw[i][2]) - s16(raw[i - 1][2])) for i in range(1, len(raw)))
    print(f"  max frame-to-frame step (drivetrain):  "
          f"centered={jump_c*SCALE:7.2f} kW   signed={jump_s*SCALE:7.2f} kW")

    # physical plausibility of the implied range
    lo_c = min(d for b, g, d in raw) - 32768
    hi_c = max(d for b, g, d in raw) - 32768
    lo_s = min(s16(d) for b, g, d in raw)
    hi_s = max(s16(d) for b, g, d in raw)
    print(f"  drivetrain range: centered=[{lo_c*SCALE:7.2f}, {hi_c*SCALE:7.2f}] kW   "
          f"signed=[{lo_s*SCALE:7.2f}, {hi_s*SCALE:7.2f}] kW")
