"""
Step 3: Scan all buses for drivetrain motor temperature candidate.

Expected profile:
  - Slow rise from pump-off (~393s) to cutback (~1953s)
  - Plateau or inflection at cutback onset
  - Drop after pump reconnect (~2253s)

Outputs a ranked list of (bus, ID, byte, encoding) candidates.
"""

import sys, collections
sys.path.insert(0, ".")

from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"

PUMP_OFF = 393
CUTBACK  = 1953
PUMP_ON  = 2253

# Time windows for profile scoring
WINDOWS = {
    "baseline": (60,   PUMP_OFF),           # before pump disconnected
    "heat_mid": (PUMP_OFF + 300, PUMP_OFF + 900),  # mid-heating (~5-15 min after pump off)
    "heat_late": (CUTBACK - 120, CUTBACK),   # just before cutback
    "cutback":  (CUTBACK, CUTBACK + 120),    # during cutback
    "recovery": (PUMP_ON + 120, PUMP_ON + 480),    # well after pump reconnect
}

# PT bus = Bus 3 in this log (anchor: 0x051 present on Bus 3; Bus 2 = OBD)
PT_BUS = 3

# Collect per-(id,byte) bucket medians at 30s resolution
BUCKET = 30
# data[id][byte] = list of (bucket_start, value)
data = collections.defaultdict(
    lambda: collections.defaultdict(list)
)

print("Reading log...", flush=True)
n = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    aid = frame.arbitration_id
    b = frame.data
    bucket = int(t // BUCKET) * BUCKET
    for byte_idx in range(len(b)):
        data[aid][byte_idx].append((bucket, b[byte_idx]))
    n += 1
    if n % 1_000_000 == 0:
        print(f"  {n//1_000_000}M frames...", flush=True)

print(f"Done reading {n} frames. Scoring...", flush=True)


def window_median(samples, t0, t1):
    """Median value of samples whose timestamp falls in [t0, t1)."""
    vals = [v for t, v in samples if t0 <= t < t1]
    if not vals:
        return None
    return sorted(vals)[len(vals) // 2]


def score_thermal(samples):
    """
    Score a (bus,id,byte) timeseries for the expected thermal profile.
    Returns (score, details_dict) or None if insufficient data.

    Profile:
      baseline  < heat_late   (rose during heating)
      heat_late ~= cutback     (plateau at cutback)
      recovery  < heat_late    (dropped after pump reconnect)

    Score = rise_delta - recovery_penalty, higher is better.
    """
    wm = {k: window_median(samples, *v) for k, v in WINDOWS.items()}
    if any(v is None for v in wm.values()):
        return None

    rise    = wm["heat_late"] - wm["baseline"]      # want > 0
    drop    = wm["heat_late"] - wm["recovery"]      # want > 0
    plateau = abs(wm["cutback"] - wm["heat_late"])  # want small

    if rise <= 0 or drop <= 0:
        return None

    # Score: rise * drop, penalised by plateau magnitude
    score = rise * drop / (plateau + 1)
    return score, wm, rise, drop, plateau


results = []
for aid, aid_data in data.items():
    for byte_idx, samples in aid_data.items():
        r = score_thermal(samples)
        if r is None:
            continue
        score, wm, rise, drop, plateau = r
        results.append((score, aid, byte_idx, wm, rise, drop, plateau))

results.sort(reverse=True)

print()
print(f"Top 40 thermal profile candidates on PT bus (Bus {PT_BUS}):")
print(f"{'Score':>10}  {'ID':>12}  {'B':>2}  {'baseline':>8}  {'heat_late':>9}  {'cutback':>7}  {'recovery':>8}  {'rise':>5}  {'drop':>5}  {'plateau':>7}")
print("-" * 100)
for score, aid, byte_idx, wm, rise, drop, plateau in results[:40]:
    print(f"{score:10.1f}  0x{aid:08X}  {byte_idx:2d}"
          f"  {wm['baseline']:8.1f}  {wm['heat_late']:9.1f}  {wm['cutback']:7.1f}"
          f"  {wm['recovery']:8.1f}  {rise:5.1f}  {drop:5.1f}  {plateau:7.1f}")

# Also specifically check the flagged candidates from PE overheat test
print()
print("Flagged candidates from PE overheat investigation (0x483, 0x484):")
for aid in [0x483, 0x484]:
    if aid in data:
        for byte_idx in range(8):
            if byte_idx in data[aid]:
                samples = data[aid][byte_idx]
                if not samples:
                    continue
                wm = {k: window_median(samples, *v) for k, v in WINDOWS.items()}
                print(f"  0x{aid:03X} B{byte_idx}: "
                      + " ".join(f"{k}={v:.0f}" if v is not None else f"{k}=None"
                                 for k, v in wm.items()))
