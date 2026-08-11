"""
soc_correlation.py

Correlate all BMS cluster bytes (0x400-0x507) and key adjacent IDs against SoC
in the window where SoC drops from its starting value (~93%) down to ~80%.

SoC reference: 0x596 B6 (1%/count).
Window: t=0 to first moment SoC <= 80.

Output: table sorted by |r| descending, so the strongest correlations appear
first. CCL candidate: strongly negative r (SoC down -> CCL up), few unique values.
"""

import sys
import bisect
import statistics
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"

SCAN_IDS = set(range(0x400, 0x508)) | {0x596, 0x598, 0x639}

# ---- collect ----------------------------------------------------------------
soc_trace = []  # [(t, v)]
raw = defaultdict(lambda: defaultdict(list))  # {aid: {byte_idx: [(t,v)]}}

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id

    if aid == 0x596 and len(d) >= 7:
        soc_trace.append((t, d[6]))

    if aid in SCAN_IDS:
        for i, b in enumerate(d):
            raw[aid][i].append((t, b))

if not soc_trace:
    print("ERROR: no 0x596 frames found -- check log path or ID")
    sys.exit(1)

soc_trace.sort()
soc_times = [t for t, _ in soc_trace]
soc_vals  = [v for _, v in soc_trace]

print(f"SoC samples  : {len(soc_trace)}")
print(f"SoC start    : {soc_vals[0]}%  at t={soc_times[0]:.1f}s")
print(f"SoC end      : {soc_vals[-1]}%  at t={soc_times[-1]:.1f}s")

# Window end: first time SoC <= 80
t_window_end = next((t for t, v in soc_trace if v <= 80), soc_times[-1])
print(f"Window       : t=0 to t={t_window_end:.1f}s  (SoC {soc_vals[0]}% -> 80%)")

# ---- helpers ----------------------------------------------------------------
def nearest_soc(t_query):
    i = bisect.bisect_left(soc_times, t_query)
    if i == 0:
        return soc_vals[0]
    if i >= len(soc_times):
        return soc_vals[-1]
    if abs(soc_times[i] - t_query) <= abs(soc_times[i - 1] - t_query):
        return soc_vals[i]
    return soc_vals[i - 1]


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return float('nan')
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return float('nan') if denom == 0 else num / denom


# ---- correlation scan -------------------------------------------------------
results = []
for aid in sorted(raw):
    for bi in sorted(raw[aid]):
        window_samples = [(t, v) for t, v in raw[aid][bi] if t <= t_window_end]
        if len(window_samples) < 10:
            continue

        bv  = [v for _, v in window_samples]
        soc = [nearest_soc(t) for t, _ in window_samples]

        n_u = len(set(bv))
        if n_u < 2:
            continue

        r = pearson(bv, soc)
        if r != r:  # nan guard
            continue

        results.append((r, aid, bi, n_u, min(bv), max(bv), len(window_samples)))

results.sort(key=lambda x: -abs(x[0]))

# ---- report -----------------------------------------------------------------
print(f"\n{'ID':<8} {'B':>2}  {'nu':>4}  {'range':<12}  {'r_SoC':>8}  {'n':>7}")
print("-" * 55)
for r, aid, bi, n_u, mn, mx, n in results[:50]:
    flag = ''
    if n_u <= 12 and abs(r) >= 0.7:
        flag = ' <<< LIMIT CANDIDATE'
    elif n_u <= 30 and abs(r) >= 0.85:
        flag = ' <<< strong analog'
    print(f"0x{aid:03X}   {bi:3d}  {n_u:4d}  {mn}-{mx:<8}  {r:+.4f}  {n:7d}{flag}")

# ---- also show all 0x440 bytes for reference --------------------------------
print("\n--- 0x440 all bytes (reference) ---")
for bi in sorted(raw.get(0x440, {})):
    window_samples = [(t, v) for t, v in raw[0x440][bi] if t <= t_window_end]
    if not window_samples:
        continue
    bv  = [v for _, v in window_samples]
    soc = [nearest_soc(t) for t, _ in window_samples]
    n_u = len(set(bv))
    r   = pearson(bv, soc) if n_u >= 2 else float('nan')
    print(f"  0x440 B{bi}: nu={n_u:3d}  range={min(bv)}-{max(bv)}  r_SoC={r:+.4f}")
