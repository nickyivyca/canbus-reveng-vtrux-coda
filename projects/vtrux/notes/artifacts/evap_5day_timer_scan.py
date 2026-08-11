"""
Scan for a 5-day evap countdown timer signal.

Logs:
  post_a:   vtruxcurrentlimitingtest.log  (+1d after evap completion, 2026-02-26)
  post_b:   vtruxstartingat20.log         (+1d same day)
  pre_next: vtruxanotherevaplogpart1.log  (+7d, just before next evap fires)

Signal widths (per CLAUDE.md methodology):
  8-bit, 16-bit LE/BE, 12-bit byte-aligned Moto/Intel, 12-bit nibble-split A/B

Performance: direct BUSMASTER line parser (no CANFrame objects) + 5s-window
downsampling per ID. 650MB file should scan in <60s.

Phase 1: within-log monotonicity (post_a and pre_next)
Phase 2: cross-log stable-value comparison (all 3 logs)
"""

import sys
sys.path.insert(0, ".")

from pathlib import Path

LOGS_DIR       = Path(r"projects\vtrux\logs")
OUT_PATH       = Path(r"projects\vtrux\notes\artifacts\evap_5day_timer_results.txt")

LOGS = {
    "post_a":   LOGS_DIR / "vtruxcurrentlimitingtest.log",
    "post_b":   LOGS_DIR / "vtruxstartingat20.log",
    "pre_next": LOGS_DIR / "vtruxanotherevaplogpart1.log",
}

MONO_THRESH     = 0.88
STABLE_UQ       = 4
MIN_SAMPLES     = 20
CROSS_MIN_DELTA = 2
TIME_WINDOW_S   = 5.0

lines_out = []

def emit(s=""):
    lines_out.append(str(s))
    print(s, flush=True)


def sig_label(sk):
    t = sk[0]
    if t == "B":           return f"B{sk[1]}"
    if t == "16LE":        return f"B{sk[1]}-B{sk[2]}_16LE"
    if t == "16BE":        return f"B{sk[1]}-B{sk[2]}_16BE"
    if t == "12BA_moto":   return f"B{sk[1]}-B{sk[2]}_12BA_Moto"
    if t == "12BA_intel":  return f"B{sk[1]}-B{sk[2]}_12BA_Intel"
    if t == "12NS_a":      return f"B{sk[1]}-B{sk[2]}-B{sk[3]}_12NSA"
    if t == "12NS_b":      return f"B{sk[1]}-B{sk[2]}-B{sk[3]}_12NSB"
    return str(sk)


def parse_busmaster_line(line):
    """Return (timestamp_s, arb_id, data_bytes) or None.
    Handles two BUSMASTER column orders:
      Old: <Time> <Channel> <CAN_ID> <Rx/Tx> <DLC> <Data...>
      New: <Time> <Rx/Tx> <Channel> <CAN_ID> <Type> <DLC> <Data...>
    Detected by whether parts[1] is Rx/Tx (new) or a channel number (old).
    """
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        ts = parts[0]
        hms, ticks = ts.rsplit(":", 1)
        h, m, s = hms.split(":")
        t = int(h)*3600 + int(m)*60 + int(s) + int(ticks)*0.0001
        if parts[1].lower() in ("rx", "tx"):
            id_str = parts[3]
            dlc    = int(parts[5])
            data   = [int(x, 16) for x in parts[6:6+dlc]]
        else:
            id_str = parts[2]
            dlc    = int(parts[4])
            data   = [int(x, 16) for x in parts[5:5+dlc]]
        aid = int(id_str, 16)
        if len(data) != dlc or dlc == 0:
            return None
        return t, aid, data
    except Exception:
        return None


def extract_sigs(data):
    n = len(data)
    out = []
    for i in range(n):
        out.append((("B", i), data[i]))
    for i in range(n - 1):
        out.append((("16LE",       i, i+1), data[i] | (data[i+1] << 8)))
        out.append((("16BE",       i, i+1), (data[i] << 8) | data[i+1]))
        out.append((("12BA_moto",  i, i+1), ((data[i] & 0x0F) << 8) | data[i+1]))
        out.append((("12BA_intel", i, i+1), data[i] | ((data[i+1] & 0x0F) << 8)))
    for i in range(n - 2):
        out.append((("12NS_a", i, i+1, i+2), (data[i] << 4) | (data[i+1] >> 4)))
        out.append((("12NS_b", i, i+1, i+2), ((data[i+1] & 0x0F) << 8) | data[i+2]))
    return out


def scan_log(path):
    last_t  = {}
    samples = {}
    nf = nkept = 0
    t0 = t1 = None

    with open(path, encoding="latin-1", errors="replace") as fh:
        for line in fh:
            parsed = parse_busmaster_line(line)
            if parsed is None:
                continue
            t, aid, data = parsed
            nf += 1
            if t0 is None:
                t0 = t
            t1 = t

            if t - last_t.get(aid, -1e9) < TIME_WINDOW_S:
                continue
            last_t[aid] = t
            nkept += 1

            for sk, val in extract_sigs(data):
                key = (aid, sk)
                s = samples.get(key)
                if s is None:
                    samples[key] = {
                        "vals": [val],
                        "small_vals": {val: 1},
                    }
                    continue
                s["vals"].append(val)
                sv = s.get("small_vals")
                if sv is not None:
                    if val in sv:
                        sv[val] += 1
                    elif len(sv) < STABLE_UQ + 1:
                        sv[val] = 1
                    else:
                        s["small_vals"] = None

    return samples, nf, nkept, t0, t1


def mono_ratio(vals):
    ups = downs = 0
    for a, b in zip(vals, vals[1:]):
        if b > a:   ups   += 1
        elif b < a: downs += 1
    total = ups + downs
    if total == 0:
        return 0.0, 0
    return max(ups, downs) / total, (1 if ups >= downs else -1)


def uq(s):
    sv = s.get("small_vals")
    return STABLE_UQ + 2 if sv is None else len(sv)


def modal(s):
    sv = s.get("small_vals")
    if sv:
        return max(sv, key=sv.get)
    v = s["vals"]
    return v[-1] if v else 0


# -----------------------------------------------------------------------
emit("=== Evap 5-day timer scan ===")
emit(f"Downsample window: {TIME_WINDOW_S}s per ID")
emit()
emit("Scanning logs (direct BUSMASTER parser)...")

log_st = {}
for name, path in LOGS.items():
    if not path.exists():
        emit(f"  {name}: NOT FOUND")
        continue
    emit(f"  {name}: {path.name}...")
    st, nf, nk, t0, t1 = scan_log(path)
    log_st[name] = st
    n_ids = len(set(aid for (aid, _) in st))
    if t0 is None:
        emit(f"    WARNING: no valid frames parsed from {path.name}")
    else:
        emit(f"    {nf:,} raw frames -> {nk:,} kept, {n_ids} IDs, t={t0:.1f}-{t1:.1f}s")

emit()

# -----------------------------------------------------------------------
emit("=" * 60)
emit("PHASE 1: WITHIN-LOG SLOW-MONOTONIC SCAN")
emit(f"  mono > {MONO_THRESH}, uq > 3, samples >= {MIN_SAMPLES}")
emit("=" * 60)

scan_names = [n for n in ("post_a", "pre_next") if n in log_st]
hits = {}

for ln in scan_names:
    for key, s in log_st[ln].items():
        vals = s["vals"]
        if len(vals) < MIN_SAMPLES:
            continue
        uqv = uq(s)
        if uqv <= 3:
            continue
        mr, dirn = mono_ratio(vals)
        if mr >= MONO_THRESH:
            hits.setdefault(key, {})[ln] = {
                "mono": mr, "dir": dirn, "uq": uqv,
                "v0": vals[0], "v1": vals[-1],
                "net": vals[-1] - vals[0], "n": len(vals),
            }

emit(f"\nSignals passing in at least one log: {len(hits)}")

both = [(key, by) for key, by in hits.items()
        if "post_a" in by and "pre_next" in by
        and by["post_a"]["dir"] == by["pre_next"]["dir"]]
both.sort(key=lambda x: -(x[1]["post_a"]["mono"] + x[1]["pre_next"]["mono"]) / 2)

emit(f"\nPassing in BOTH post_a and pre_next (same direction): {len(both)}")
for (aid, sk), by in both:
    avg = (by["post_a"]["mono"] + by["pre_next"]["mono"]) / 2
    dirstr = "up" if by["post_a"]["dir"] > 0 else "dn"
    emit(f"\n  0x{aid:X} {sig_label(sk)}  avg_mono={avg:.2f} {dirstr}")
    for ln in scan_names:
        if ln in by:
            s = by[ln]
            emit(f"    [{ln:10s}] mono={s['mono']:.2f} {'up' if s['dir']>0 else 'dn'}  "
                 f"uq={s['uq']:4d}  net={s['net']:+6d}  "
                 f"0x{s['v0']:x}->0x{s['v1']:x}  n={s['n']}")

emit()
post_only = sorted([(key, by) for key, by in hits.items()
                    if "post_a" in by and "pre_next" not in by],
                   key=lambda x: -x[1]["post_a"]["mono"])
emit(f"Passing in post_a only: {len(post_only)}")
for (aid, sk), by in post_only[:40]:
    s = by["post_a"]
    emit(f"  0x{aid:X} {sig_label(sk)}  mono={s['mono']:.2f} {'up' if s['dir']>0 else 'dn'}  "
         f"uq={s['uq']}  net={s['net']:+d}  0x{s['v0']:x}->0x{s['v1']:x}")

emit()
pre_only = sorted([(key, by) for key, by in hits.items()
                   if "pre_next" in by and "post_a" not in by],
                  key=lambda x: -x[1]["pre_next"]["mono"])
emit(f"Passing in pre_next only: {len(pre_only)}")
for (aid, sk), by in pre_only[:40]:
    s = by["pre_next"]
    emit(f"  0x{aid:X} {sig_label(sk)}  mono={s['mono']:.2f} {'up' if s['dir']>0 else 'dn'}  "
         f"uq={s['uq']}  net={s['net']:+d}  0x{s['v0']:x}->0x{s['v1']:x}")

# -----------------------------------------------------------------------
emit()
emit("=" * 60)
emit("PHASE 2: CROSS-LOG STABLE-VALUE COMPARISON")
emit(f"  Stable = uq <= {STABLE_UQ}. Report |delta| >= {CROSS_MIN_DELTA}.")
emit("=" * 60)

all_keys = set()
for n in ("post_a", "post_b", "pre_next"):
    if n in log_st:
        all_keys.update(log_st[n].keys())

cross = []
for key in all_keys:
    aid, sk = key
    stable = {}
    for n in ("post_a", "post_b", "pre_next"):
        s = log_st.get(n, {}).get(key)
        if s and len(s["vals"]) >= MIN_SAMPLES and uq(s) <= STABLE_UQ:
            stable[n] = modal(s)
    if "pre_next" not in stable:
        continue
    post_vals = [v for n, v in stable.items() if n in ("post_a", "post_b")]
    if not post_vals:
        continue
    avg_post = sum(post_vals) / len(post_vals)
    delta = stable["pre_next"] - avg_post
    if abs(delta) >= CROSS_MIN_DELTA:
        cross.append((abs(delta), delta, aid, sk, stable))

cross.sort(reverse=True)
emit(f"\n{len(cross)} cross-log candidates (|delta| >= {CROSS_MIN_DELTA}):")
for abs_d, delta, aid, sk, stable in cross:
    parts = [f"{n}=0x{v:x}" for n, v in stable.items()]
    emit(f"  0x{aid:X} {sig_label(sk)}  delta={delta:+.0f} {'up' if delta>0 else 'dn'}  [{', '.join(parts)}]")

emit()
emit("Done.")
OUT_PATH.write_text("\n".join(lines_out), encoding="utf-8")
print(f"Written to {OUT_PATH}", flush=True)
