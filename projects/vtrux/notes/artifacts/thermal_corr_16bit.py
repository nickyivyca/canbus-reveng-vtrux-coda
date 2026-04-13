"""
Correlation scan for drivetrain motor temperature -- 16-bit pairs.

Reference: 0x06000002 B6 (confirmed motor temp, ~10C/count)
Window: t=1500-2550s (post-generator-shutdown, isolates pure motor thermal)
Bucket: 30s medians
Tests: per-byte AND adjacent LE/BE uint16 pairs on PT Bus (Bus 3)
Sorted by |r|, min range >= 3.
"""

import sys, collections, math
sys.path.insert(0, ".")

from canre.parsers import parse_file

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
T0, T1 = 1500, 2550
BUCKET = 5
REF_ID, REF_B = 0x06000002, 6
MIN_RANGE = 3

# data[id][(byte_idx, width, endian)] = {bucket: [values]}
# We store raw byte data and compute pairs post-hoc.
# Simpler: collect per-(id, byte_idx) bucket samples, reconstruct pairs after.

raw = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
# raw[id][byte_idx][bucket] = [val, ...]

print("Reading log...", flush=True)
n = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    if not (T0 <= t < T1):
        continue
    bucket = int(t // BUCKET) * BUCKET
    aid = frame.arbitration_id
    b = frame.data
    for bi in range(len(b)):
        raw[aid][bi][bucket].append(b[bi])
    n += 1
    if n % 500_000 == 0:
        print(f"  {n//1_000_000:.1f}M frames...", flush=True)

print(f"Read {n} frames in window. Computing medians...", flush=True)

def median(lst):
    s = sorted(lst)
    return s[len(s) // 2]

# Bucket medians per (id, byte)
bmed = {}  # bmed[(id, bi)] = {bucket: median_val}
for aid, bytes_data in raw.items():
    for bi, buckets in bytes_data.items():
        bmed[(aid, bi)] = {bk: median(vs) for bk, vs in buckets.items()}

# Reference series
ref_key = (REF_ID, REF_B)
if ref_key not in bmed:
    print("ERROR: reference signal not found in window")
    sys.exit(1)
ref_bmed = bmed[ref_key]
ref_buckets = sorted(ref_bmed)

def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs)/n
    my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)

def corr_vs_ref(series_bmed):
    """Given {bucket: value}, correlate against reference over shared buckets."""
    common = sorted(set(ref_buckets) & set(series_bmed))
    if len(common) < 5:
        return None, 0, 0, 0
    xs = [ref_bmed[b] for b in common]
    ys = [series_bmed[b] for b in common]
    r = pearson(xs, ys)
    rng = max(ys) - min(ys)
    return r, rng, min(ys), max(ys)

results = []

# 1. Per-byte signals
for (aid, bi), series in bmed.items():
    if aid == REF_ID and bi == REF_B:
        continue
    r, rng, mn, mx = corr_vs_ref(series)
    if r is None or rng < MIN_RANGE:
        continue
    results.append((r, aid, bi, "B", rng, mn, mx))

# 2. Adjacent 16-bit pairs (LE and BE)
for aid, bytes_data in raw.items():
    dlc = max(bytes_data.keys()) + 1
    for bi in range(dlc - 1):
        if bi not in bytes_data or (bi+1) not in bytes_data:
            continue
        b_lo = bmed.get((aid, bi))
        b_hi = bmed.get((aid, bi+1))
        if b_lo is None or b_hi is None:
            continue

        # LE: value = b_lo + 256*b_hi
        common = sorted(set(ref_buckets) & set(b_lo) & set(b_hi))
        if len(common) >= 5:
            for label, fn in [
                ("LE", lambda lo, hi: lo + 256*hi),
                ("BE", lambda lo, hi: hi + 256*lo),
            ]:
                series = {bk: fn(b_lo[bk], b_hi[bk]) for bk in common}
                r, rng, mn, mx = corr_vs_ref(series)
                if r is not None and rng >= MIN_RANGE:
                    # tag: bi is the lower byte index; pair = bi:(bi+1)
                    results.append((r, aid, bi, label, rng, mn, mx))

# Sort by |r| descending
results.sort(key=lambda x: -abs(x[0]))

print()
print(f"Correlation vs 0x{REF_ID:X} B{REF_B} -- 30s buckets, t={T0}-{T1}s (post-gen-shutdown)")
print(f"(Includes per-byte and adjacent LE/BE uint16 pairs. Min range={MIN_RANGE})")
print()
print(f"      r            ID  Enc  byte(s)  range    min    max")
print(f"------------------------------------------------------------")

# Reference row
rref_vals = list(ref_bmed.values())
print(f" 1.0000  0x{REF_ID:08X}   B     {REF_B}     {max(rref_vals)-min(rref_vals):3d}    {min(rref_vals):3d}    {max(rref_vals):3d} <-- REF")

shown = 0
for r, aid, bi, enc, rng, mn, mx in results:
    if enc == "B":
        byte_str = f"{bi:2d}"
    else:
        byte_str = f"{bi}:{bi+1}"
    print(f"{r:7.4f}  0x{aid:08X}  {enc:>3}  {byte_str:>7}    {rng:3d}    {mn:3d}    {mx:3d}")
    shown += 1
    if shown >= 60:
        break

print()
print(f"({shown} results shown, {len(results)} total)")
