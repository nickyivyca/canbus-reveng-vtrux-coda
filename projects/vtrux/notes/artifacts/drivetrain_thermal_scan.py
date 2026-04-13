"""
Drivetrain motor temperature correlation scan -- full bus, 3-method strategy.

Reference: 0x06000002 decoded motor winding temp = (B6<<2)|(B5>>6), 2.0 deg C/count.
Log: vtruxdrivetrainoverheattest.log, PT bus, whole log.

Three correlation passes per candidate:
  full    -- full-window Pearson r on bucket medians
  bestwin -- best r in any 200s sliding window (catches 16-bit signals where MSB
             occasionally steps by +/-1, collapsing full-log r to near zero)
  delta   -- r on consecutive bucket differences (immune to all offset/wrap artifacts)

Single-byte candidates also get:
  unwrap  -- full-window r after overflow-unwrapping the byte series (handles signals
             that roll past 255 back to 0, e.g. slow monotone signals with limited range)

r_best = max(|r|) across all applicable passes. Results sorted by r_best descending.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/drivetrain_thermal_scan.py > projects/vtrux/notes/artifacts/drivetrain_thermal_scan.txt 2>&1
"""

import sys, collections, math
sys.path.insert(0, ".")

from canre.parsers import parse_file

LOG     = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS  = 3
REF_ID  = 0x06000002
T_START = 1500     # arc window: motor temp has meaningful rise->cutback->cooldown shape
T_END   = 99999    # to end of log
BUCKET  = 10       # seconds per median bucket
MIN_RANGE = 3      # minimum candidate value range (in raw units) to bother correlating
WIN_LEN   = 200    # sliding window length (seconds)
WIN_STEP  = 60     # sliding window step (seconds)
TOP_N     = 80     # rows to print


def decode_ref(data):
    """Decode confirmed motor winding temperature from 0x06000002."""
    if len(data) < 7:
        return None
    return (data[6] << 2) | (data[5] >> 6)


def median(lst):
    s = sorted(lst)
    return s[len(s) // 2]


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sdx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sdy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if sdx < 1e-9 or sdy < 1e-9:
        return None
    return num / (sdx * sdy)


def unwrap_list(vals, modulus):
    """Correct overflow wraps in a list of values.

    If a byte rolls over 255->0 (or a uint16 rolls over 65535->0), consecutive
    deltas crossing half the modulus are treated as wrap events and corrected by
    adding/subtracting the modulus. This makes slow monotone signals that happen
    to overflow visible to full-window correlation.
    """
    if not vals:
        return vals
    out = [vals[0]]
    offset = 0
    half = modulus / 2
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        if d > half:
            offset -= modulus
        elif d < -half:
            offset += modulus
        out.append(vals[i] + offset)
    return out


# ---------------------------------------------------------------------------
# Load all PT-bus frames
# ---------------------------------------------------------------------------
print("Reading log...", flush=True)

ref_bucks  = collections.defaultdict(list)          # bucket -> [decoded ref values]
# cand_raw[(aid, bi)][bucket] = [raw byte values]
cand_raw = collections.defaultdict(lambda: collections.defaultdict(list))

n_frames = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue

    t  = frame.timestamp
    if not (T_START <= t < T_END):
        continue
    bk = int(t // BUCKET) * BUCKET
    aid = frame.arbitration_id
    data = frame.data

    if aid == REF_ID:
        v = decode_ref(data)
        if v is not None:
            ref_bucks[bk].append(v)
        # still collect other bytes from this message as candidates
        # (B0/B3/B4 are unattributed and worth checking)

    for bi in range(len(data)):
        if aid == REF_ID and bi in (5, 6):
            continue   # skip the reference bytes themselves
        cand_raw[(aid, bi)][bk].append(data[bi])

    n_frames += 1
    if n_frames % 1_000_000 == 0:
        print(f"  {n_frames // 1_000_000}M frames...", flush=True)

print(f"Loaded {n_frames} PT-bus frames.", flush=True)

# Bucket medians
ref_med = {bk: median(vs) for bk, vs in ref_bucks.items() if vs}
ref_sorted = sorted(ref_med)

if not ref_sorted:
    print("ERROR: reference signal not found on this bus.")
    sys.exit(1)

print(f"Reference: {len(ref_sorted)} buckets, "
      f"range {min(ref_med.values()):.0f}-{max(ref_med.values()):.0f} raw", flush=True)

# Per-(id, byte) median series
cand_med = {}    # (aid, bi) -> {bucket: median}
for key, bk_data in cand_raw.items():
    cand_med[key] = {bk: median(vs) for bk, vs in bk_data.items() if vs}

# Index by aid for 16-bit pair construction
aid_to_bytes = collections.defaultdict(set)
for (aid, bi) in cand_med:
    aid_to_bytes[aid].add(bi)


# ---------------------------------------------------------------------------
# Correlation helpers
# ---------------------------------------------------------------------------

def corr_full(series):
    """Full-window r. Returns (r, range, min, max)."""
    common = sorted(set(ref_sorted) & set(series))
    if len(common) < 5:
        return None, 0, 0, 0
    xs = [ref_med[b] for b in common]
    ys = [series[b] for b in common]
    return pearson(xs, ys), max(ys) - min(ys), min(ys), max(ys)


def corr_unwrap(series, modulus):
    """Full-window r after overflow-unwrapping the candidate."""
    common = sorted(set(ref_sorted) & set(series))
    if len(common) < 5:
        return None
    ys = unwrap_list([series[b] for b in common], modulus)
    xs = [ref_med[b] for b in common]
    return pearson(xs, ys)


def corr_bestwin(series):
    """Best |r| in any WIN_LEN-second sliding window."""
    t0 = min(ref_sorted)
    t1 = max(ref_sorted)
    best = None
    w = t0
    while w <= t1:
        wend = w + WIN_LEN
        common = sorted(b for b in ref_sorted if w <= b < wend
                        if b in series)
        if len(common) >= 5:
            xs = [ref_med[b] for b in common]
            ys = [series[b]  for b in common]
            r = pearson(xs, ys)
            if r is not None and (best is None or abs(r) > abs(best)):
                best = r
        w += WIN_STEP
    return best


def corr_delta(series):
    """r on consecutive bucket-to-bucket differences."""
    common = sorted(set(ref_sorted) & set(series))
    if len(common) < 6:
        return None
    xd = [ref_med[common[i+1]] - ref_med[common[i]] for i in range(len(common)-1)]
    yd = [series[common[i+1]] - series[common[i]] for i in range(len(common)-1)]
    return pearson(xd, yd)


# ---------------------------------------------------------------------------
# Scan: per-byte candidates
# ---------------------------------------------------------------------------
print("Scanning per-byte candidates...", flush=True)

results = []

for (aid, bi), series in cand_med.items():
    r_f, rng, mn, mx = corr_full(series)
    if rng < MIN_RANGE:
        continue

    r_u = corr_unwrap(series, 256)
    r_w = corr_bestwin(series)
    r_d = corr_delta(series)

    candidates = [r for r in [r_f, r_u, r_w, r_d] if r is not None]
    if not candidates:
        continue
    r_best = max(candidates, key=abs)

    results.append(dict(
        r_best=r_best, aid=aid, enc="B", bi=bi,
        r_f=r_f, r_u=r_u, r_w=r_w, r_d=r_d,
        rng=rng, mn=mn, mx=mx,
    ))

print(f"  {len(results)} per-byte candidates.", flush=True)

# ---------------------------------------------------------------------------
# Scan: adjacent 16-bit pairs (LE and BE)
# ---------------------------------------------------------------------------
print("Scanning 16-bit pairs...", flush=True)

n_pairs_before = len(results)

for aid, byte_set in aid_to_bytes.items():
    max_bi = max(byte_set)
    for bi in range(max_bi):
        if bi not in byte_set or (bi + 1) not in byte_set:
            continue

        for label, lo, hi in [("LE", bi, bi+1), ("BE", bi+1, bi)]:
            slo = cand_med.get((aid, lo))
            shi = cand_med.get((aid, hi))
            if slo is None or shi is None:
                continue
            common = sorted(set(ref_sorted) & set(slo) & set(shi))
            if len(common) < 5:
                continue

            series16 = {bk: slo[bk] + 256 * shi[bk] for bk in common}
            r_f, rng, mn, mx = corr_full(series16)
            if rng < MIN_RANGE:
                continue

            # For 16-bit pairs: windowed and delta handle MSB-step artifacts;
            # unwrap is not useful here (MSB stepping != overflow).
            r_w = corr_bestwin(series16)
            r_d = corr_delta(series16)

            candidates = [r for r in [r_f, r_w, r_d] if r is not None]
            if not candidates:
                continue
            r_best = max(candidates, key=abs)

            results.append(dict(
                r_best=r_best, aid=aid, enc=label, bi=bi,
                r_f=r_f, r_u=None, r_w=r_w, r_d=r_d,
                rng=rng, mn=mn, mx=mx,
            ))

print(f"  {len(results) - n_pairs_before} pair candidates. Sorting...", flush=True)

results.sort(key=lambda x: -abs(x["r_f"]) if x["r_f"] is not None else 0)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def fv(r, w=7):
    return f"{r:{w}.4f}" if r is not None else " " * (w - 3) + "---"


hdr = (f"{'r_best':>7}  {'r_full':>7}  {'r_unwr':>7}  {'r_bwin':>7}  {'r_delt':>7}  "
       f"{'ID':>12}  {'enc':>5}  {'byte(s)':>7}  {'range':>8}  {'min':>8}  {'max':>8}")
sep = "-" * len(hdr)

print()
print("Drivetrain motor temperature correlation scan")
print(f"Ref: 0x{REF_ID:08X} (B6<<2)|(B5>>6) | t={T_START}s to end | {BUCKET}s buckets")
print(f"Sorted by |r_full| -- windowed and delta shown for reference")
print(f"Windowed: {WIN_LEN}s window / {WIN_STEP}s step | Delta: bucket-to-bucket diffs")
print(sep)
print(hdr)
print(sep)

shown = 0
for res in results:
    enc = res["enc"]
    bs  = str(res["bi"]) if enc == "B" else f"{res['bi']}:{res['bi']+1}"
    print(
        f"{fv(res['r_best'])}  {fv(res['r_f'])}  {fv(res['r_u'])}  "
        f"{fv(res['r_w'])}  {fv(res['r_d'])}  "
        f"0x{res['aid']:08X}  {enc:>5}  {bs:>7}  "
        f"{int(res['rng']):8d}  {int(res['mn']):8d}  {int(res['mx']):8d}"
    )
    shown += 1
    if shown >= TOP_N:
        break

print(sep)
print(f"({shown} of {len(results)} results shown, sorted by |r_best|)")
