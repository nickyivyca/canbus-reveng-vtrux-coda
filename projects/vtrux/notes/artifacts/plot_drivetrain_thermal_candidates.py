"""
Plot top drivetrain thermal correlation candidates against confirmed motor temp.

Each subplot: motor temp (orange) + candidate (blue), both min-max normalised
to [0,1] so shape comparison is direct regardless of raw units.

Event markers on every panel:
  t=393s  -- drivetrain oil pump unplugged
  t=1953s -- torque cutback onset
  t=2253s -- pump reconnected

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/plot_drivetrain_thermal_candidates.py
"""

import sys, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, ".")
from canre.parsers import parse_file

LOG     = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS  = 3
BUCKET  = 10    # seconds
T_START = 0     # whole log
T_END   = 99999

# Events to mark on every panel
EVENTS = [
    (393,  "pump\nunplug",  "red"),
    (1953, "cutback\nonset", "darkorange"),
    (2253, "pump\nrecon.",  "green"),
]

# Reference: decoded motor winding temp
REF_ID = 0x06000002
def decode_ref(data):
    if len(data) < 7:
        return None
    return (data[6] << 2) | (data[5] >> 6)

# Candidates: (label, id, lo_byte, hi_byte_or_None, encoding_note)
# hi_byte=None means single byte; otherwise LE uint16 = lo + 256*hi
CANDIDATES = [
    ("0x63F B3\n(r_full=0.950, r_delt=0.690)",         0x0000063F, 3, None),
    ("0x18FFD6B3 B3\n(r_full=0.889, r_delt=0.331)",    0x18FFD6B3, 3, None),
    ("0x600 B2\n(r_full=0.710, r_delt=0.075)",         0x00000600, 2, None),
    ("0x599 B0\n(r_full=0.684, r_delt=0.052)",         0x00000599, 0, None),
    ("0x0870A047 B1\n(r_full=0.604, r_delt=0.003)",    0x0870A047, 1, None),
    ("0x483 B6:7 LE\n(r_full=0.594, r_delt=0.368)",    0x00000483, 6, 7),
    ("0x484 B0\n(r_full=0.565, r_delt=0.555)",         0x00000484, 0, None),
    ("0x06000002 B3\n(r_full=-0.518, same msg)",        0x06000002, 3, None),
]

# -----------------------------------------------------------------------
# Load frames
# -----------------------------------------------------------------------
print("Reading log...", flush=True)

ids_needed = {REF_ID} | {cid for _, cid, _, _ in CANDIDATES}
ref_bucks  = collections.defaultdict(list)
# collect every needed byte index per id
byte_needs = collections.defaultdict(set)
for _, cid, lo, hi in CANDIDATES:
    byte_needs[cid].add(lo)
    if hi is not None:
        byte_needs[cid].add(hi)
cand_bucks = {(cid, bi): collections.defaultdict(list)
              for cid, bis in byte_needs.items() for bi in bis}

n = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    if not (T_START <= t < T_END):
        continue
    aid  = frame.arbitration_id
    if aid not in ids_needed:
        continue
    bk = int(t // BUCKET) * BUCKET
    d  = frame.data

    if aid == REF_ID:
        v = decode_ref(d)
        if v is not None:
            ref_bucks[bk].append(v)

    for bi in byte_needs.get(aid, ()):
        if bi < len(d):
            cand_bucks[(aid, bi)][bk].append(d[bi])

    n += 1
    if n % 1_000_000 == 0:
        print(f"  {n//1_000_000}M frames...", flush=True)

print(f"Loaded {n} frames.", flush=True)

def median(lst):
    s = sorted(lst)
    return s[len(s)//2]

def to_series(bk_dict):
    items = sorted((bk, median(vs)) for bk, vs in bk_dict.items() if vs)
    if not items:
        return [], []
    ts, vs = zip(*items)
    return list(ts), list(vs)

def normalise(vs):
    lo, hi = min(vs), max(vs)
    if hi == lo:
        return [0.5] * len(vs)
    return [(v - lo) / (hi - lo) for v in vs]

ref_t, ref_v = to_series(ref_bucks)
ref_vn = normalise(ref_v)

# -----------------------------------------------------------------------
# Plot
# -----------------------------------------------------------------------
NCOLS = 2
NROWS = (len(CANDIDATES) + 1) // 2   # 4 rows for 8 candidates

fig, axes = plt.subplots(NROWS, NCOLS, figsize=(14, NROWS * 3.2), sharex=True)
fig.suptitle("Drivetrain thermal candidates vs confirmed motor winding temp\n"
             "Both signals min-max normalised -- shape comparison only",
             fontsize=11, y=0.995)

ax_flat = axes.flatten()

for idx, (label, cid, lo, hi) in enumerate(CANDIDATES):
    ax = ax_flat[idx]

    # Reference
    ax.plot(ref_t, ref_vn, color="darkorange", lw=1.5, alpha=0.85,
            label="Motor temp (ref)")

    # Build candidate series
    if hi is None:
        ct, cv = to_series(cand_bucks[(cid, lo)])
    else:
        blo = cand_bucks[(cid, lo)]
        bhi = cand_bucks[(cid, hi)]
        common = sorted(set(blo) & set(bhi))
        ct = common
        cv = [median(blo[bk]) + 256 * median(bhi[bk]) for bk in common]

    if cv:
        cvn = normalise(cv)
        # Show direction: flip if negatively correlated (r_best negative)
        # so the shape comparison makes sense visually.
        # Detect: if first third vs last third moves opposite to ref, flip.
        n3 = max(1, len(cvn) // 3)
        ref_dir = ref_vn[-1] - ref_vn[0]
        cand_dir = cvn[-1] - cvn[0]
        flipped = False
        if ref_dir * cand_dir < 0:
            cvn = [1 - v for v in cvn]
            flipped = True
        flip_str = " [inv]" if flipped else ""
        ax.plot(ct, cvn, color="steelblue", lw=1.2, alpha=0.85,
                label=f"Candidate{flip_str}")
    else:
        ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center")

    # Event markers
    for ev_t, ev_lbl, ev_col in EVENTS:
        ax.axvline(ev_t, color=ev_col, lw=0.8, ls="--", alpha=0.7)
        ax.text(ev_t + 20, 0.02, ev_lbl, color=ev_col, fontsize=6.5,
                va="bottom", alpha=0.85)

    ax.set_title(label, fontsize=8, pad=3)
    ax.set_ylim(-0.05, 1.1)
    ax.set_ylabel("Normalised", fontsize=7)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=6.5, loc="upper left")

# x-axis label on bottom row
for ax in ax_flat[-NCOLS:]:
    ax.set_xlabel("Time (s)", fontsize=8)

# Hide any unused axes
for ax in ax_flat[len(CANDIDATES):]:
    ax.set_visible(False)

plt.tight_layout(rect=[0, 0, 1, 0.99])

OUT = "projects/vtrux/notes/artifacts/drivetrain_thermal_candidates.png"
plt.savefig(OUT, dpi=130, bbox_inches="tight")
print(f"Saved {OUT}")
