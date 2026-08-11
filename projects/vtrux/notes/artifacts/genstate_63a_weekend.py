"""0x63A B7 bits[5:4] vs generator power vs evap -- weekend trip (2026-07-24..26).

Goal: break the confound left open by evap-cycle-analysis.md Phase 6. That phase
retracted `vcm_evap_purging` (0x63A B7 bit4) and left this open:

    bits[5:4] separates at ~40 kW vs 0.4-4.6 kW gen_power, but every session
    examined so far had evap activity overlapping the high-generator windows,
    so "bits[5:4] tracks the generator" and "bits[5:4] tracks evap" were not
    yet separable.

The weekend trip is the candidate discriminator: the evap purge happened at the
start, then the generator ran heavily for the rest of the weekend with (per the
user) no further evap activity. If bits[5:4] follows the generator it must take
its bit4-set values during those later windows with evap inactive.

Signals
    0x63A B7            bits[7:6] = HV/VCM up, bits[5:4] = the unassigned field
                        (0x63A has no SG_ entries -- BO_ stub -- so B7 is read
                        by hand, which is the sanctioned case for hand-rolling)
    0x649               vcm_evap_active, vcm_evap_counter   (via cantools/DBC)
    0x598               gen_power, kW                        (via cantools/DBC)

BUS NUMBERING
    The Android logger was unplugged and replugged during this trip, so channel
    numbers are NOT stable across chunks -- phase 0 measured the VCU bus landing
    on channels 29, 2, 20 and 26 within Saturday alone. Nothing here keys off a
    channel number; frames are accepted on any channel and buses are identified
    by message content, per AGENTS.md. Each chunk still records its ID->channel
    map so a renumber is never misread as a dropout, and so a genuine concurrent
    duplicate (same ID live on two channels at once, which would double-count)
    is detected rather than silently folded in.

TIME BASE
    Each chunk's timestamps are relative to its own header. Absolute wall-clock
    comes from the header "START DATE AND TIME DD:MM:YYYY HH:MM:SS:mmm" line, so
    gaps sit on a real timeline and a replug does not read as a gap.

PERFORMANCE
    The logs live on SeaDrive and stream at ~3.6 MB/s, essentially all I/O wait,
    so 11.4 GB serial would be ~50 min. Chunks are processed in a worker pool and
    everything phase 2 needs is extracted in ONE pass; phase 2 then runs off the
    cached CSV/JSON without touching the network again.

Phases (toggle in PHASES):
    1  single full pass: per-chunk channel map, pooled bits[5:4] x evap
       contingency with gen_power histograms, and a 1 Hz joint timeseries
    2  analysis on the cached timeseries: sustained high-generator episodes and
       the evap state during each -- the actual confound-breaking test

Usage:  py -3.11 projects/vtrux/notes/artifacts/genstate_63a_weekend.py
        py -3.11 ... .py 20260725          # restrict to one day (smoke test)
"""

import sys
import os
import re
import csv
import glob
import json
import subprocess
import multiprocessing as mp
from collections import defaultdict

sys.path.insert(0, ".")

PHASES = {1, 2}

LOGDIR = "../../CANLogs/VtruxLogs"
OUTDIR = "projects/vtrux/notes/artifacts"
DBC = "projects/vtrux/vtrux-powertrain-experimental.dbc"

TS_CSV = os.path.join(OUTDIR, "genstate_63a_weekend_timeseries.csv")
STATS_JSON = os.path.join(OUTDIR, "genstate_63a_weekend_stats.json")
REPORT_TXT = os.path.join(OUTDIR, "genstate_63a_weekend_report.txt")

DAYS = ("20260724", "20260725", "20260726")

ID_63A = 0x63A
ID_649 = 0x649
ID_598 = 0x598
TARGETS = (ID_63A, ID_649, ID_598)
GREP_RE = r" 0x(63A|649|598) "

HDR = re.compile(
    r"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+):(\d+)")

# gen_power threshold for "generator working hard", kW. Phase 6 medians were
# 0.37 / 4.55 kW for the bit4-clear states and ~40 kW for the bit4-set states.
GEN_HIGH_KW = 20.0
EPISODE_MIN_S = 20.0      # shortest high-generator episode worth reporting
EPISODE_GAP_S = 10.0      # break an episode across a data gap this long

# 0x63A and 0x649 are 100 Hz; every 5th frame is 20 Hz for the contingency
# counts, and 0x649 is decoded through cantools every 10th frame (10 Hz), both
# far finer than any state change of interest.
DEC_63A = 5
DEC_649 = 10

# gen_power histogram: 1 kW bins over [-60, 120)
HIST_LO, HIST_HI = -60, 120

NWORKERS = 12


# ---------------------------------------------------------------- helpers

def chunks_for_days(days):
    """(session, [paths in real time order]) for every session in `days`."""
    out = defaultdict(list)
    for day in days:
        for p in glob.glob(os.path.join(LOGDIR, "vtrux_%s_*_T*.log" % day)):
            m = re.match(r"^(vtrux_\d{8}_\d{6})_T(\d+)\.log$",
                         os.path.basename(p))
            if m:
                out[m.group(1)].append((int(m.group(2)), p))
    return {k: [p for _, p in sorted(v)] for k, v in sorted(out.items())}


def header_start(path):
    """Absolute chunk start on a within-trip timeline, in seconds.

    The trip sits inside one month, so day-of-month*86400 + time-of-day is
    monotonic across it and avoids any calendar dependency.
    """
    with open(path, "r", errors="replace") as f:
        for _ in range(80):
            line = f.readline()
            if not line:
                break
            m = HDR.search(line)
            if m:
                dd, mo, yy, hh, mm, ss, ms = (int(x) for x in m.groups())
                return (dd * 86400 + hh * 3600 + mm * 60 + ss + ms / 1000.0,
                        (yy, mo, dd, hh, mm, ss))
    return None, None


def fmt_t(t):
    """Format a within-trip timeline value as 'Jul-DD HH:MM:SS'."""
    d = int(t // 86400)
    r = t % 86400
    return "Jul-%02d %02d:%02d:%02d" % (d, r // 3600, (r % 3600) // 60, r % 60)


def hist_bin(kw):
    b = int(kw) - HIST_LO
    return min(max(b, 0), HIST_HI - HIST_LO - 1)


def hist_median(hist):
    tot = sum(hist.values())
    if not tot:
        return None
    half, run = tot / 2.0, 0
    for b in sorted(hist):
        run += hist[b]
        if run >= half:
            return b + HIST_LO + 0.5
    return None


# ---------------------------------------------------------------- worker

_DB = None


def _db():
    """Lazily load the DBC once per worker process."""
    global _DB
    if _DB is None:
        import cantools
        _DB = cantools.db.load_file(DBC)
    return _DB


def scan_chunk(path):
    """Extract everything phase 2 needs from one chunk. Runs in a worker."""
    base, raw = header_start(path)
    if base is None:
        return {"chunk": os.path.basename(path), "error": "no header timestamp"}

    db = _db()
    msg_649 = db.get_message_by_frame_id(ID_649)
    msg_598 = db.get_message_by_frame_id(ID_598)

    chan = defaultdict(lambda: [0, None, None])   # (id, ch) -> [n, t0, t1]
    cont = defaultdict(int)                       # (state, evap) -> frames
    hist = defaultdict(lambda: defaultdict(int))  # state -> {bin: n}
    series = {}                                   # int second -> row
    n63a = n649 = 0
    gen = evap = cnt = None
    cnt_first = cnt_last = None

    p = subprocess.Popen(["grep", "-E", GREP_RE, path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                 + int(ts[2]) + int(ts[3]) / 10000.0)
            ch = int(f[2])
            cid = int(f[3], 16)
        except (ValueError, IndexError):
            continue
        if cid not in TARGETS:
            continue

        e = chan[(cid, ch)]
        e[0] += 1
        if e[1] is None:
            e[1] = t
        e[2] = t

        try:
            data = bytes(int(x, 16) for x in f[6:])
        except ValueError:
            continue

        if cid == ID_598:
            if len(data) >= msg_598.length:
                try:
                    gen = db.decode_message(ID_598, data,
                                            decode_choices=False)["gen_power"]
                except Exception:
                    pass

        elif cid == ID_649:
            n649 += 1
            if n649 % DEC_649 or len(data) < msg_649.length:
                continue
            # decode_choices=False: vcm_evap_active carries a VAL_ table and
            # would otherwise come back as a NamedSignalValue, not an int
            try:
                d = db.decode_message(ID_649, data, decode_choices=False)
            except Exception:
                continue
            evap = int(d["vcm_evap_active"])
            cnt = int(d["vcm_evap_counter"])
            if cnt_first is None:
                cnt_first = cnt
            cnt_last = cnt

        elif cid == ID_63A:
            n63a += 1
            if n63a % DEC_63A or len(data) < 8:
                continue
            b7 = data[7]
            hv = (b7 >> 6) & 0x3
            # HV/VCM down is its own bucket -- bits[5:4] is not meaningful there
            state = "hv_down" if hv != 0x3 else str((b7 >> 4) & 0x3)
            ev = -1 if evap is None else evap
            cont[(state, ev)] += 1
            if gen is not None:
                hist[state][hist_bin(gen)] += 1
            series[int(t)] = (round(t, 1),
                              None if gen is None else round(gen, 2),
                              ev,
                              -1 if cnt is None else cnt,
                              b7, state)
    p.stdout.close()
    p.wait()

    spans = defaultdict(list)
    for (cid, ch), v in chan.items():
        spans[cid].append((v[1], v[2], ch))
    overlaps = []
    for cid, sp in spans.items():
        sp.sort()
        for i in range(1, len(sp)):
            if sp[i][0] < sp[i - 1][1] - 1.0:
                overlaps.append("0x%03X ch%d/ch%d concurrent"
                                % (cid, sp[i - 1][2], sp[i][2]))

    return {
        "chunk": os.path.basename(path),
        "start": raw,
        "base": base,
        "chan": {"0x%03X" % cid: sorted({ch for (c, ch) in chan if c == cid})
                 for cid in TARGETS},
        "overlaps": overlaps,
        "n63a": n63a, "n649": n649,
        "cont": {"%s|%d" % k: v for k, v in cont.items()},
        "hist": {s: dict(h) for s, h in hist.items()},
        "counter": [cnt_first, cnt_last],
        "series": sorted(series.values()),
    }


# ---------------------------------------------------------------- phase 1

def phase1(days):
    sessions = chunks_for_days(days)
    paths = [p for ps in sessions.values() for p in ps]
    print("phase 1: %d sessions, %d chunks, %.1f GB"
          % (len(sessions), len(paths),
             sum(os.path.getsize(p) for p in paths) / 2**30))

    with mp.Pool(NWORKERS) as pool:
        results = []
        for i, r in enumerate(pool.imap_unordered(scan_chunk, paths), 1):
            results.append(r)
            print("  [%3d/%3d] %-38s %s"
                  % (i, len(paths), r["chunk"],
                     r.get("error", "63A=%d 649=%d ch=%s"
                           % (r["n63a"], r["n649"],
                              r["chan"]["0x63A"]))), flush=True)

    good = [r for r in results if "error" not in r]
    cont = defaultdict(int)
    hist = defaultdict(lambda: defaultdict(int))
    rows, overlaps, chanmap = [], [], {}
    for r in good:
        for k, v in r["cont"].items():
            s, e = k.rsplit("|", 1)
            cont[(s, int(e))] += v
        for s, h in r["hist"].items():
            for b, v in h.items():
                hist[s][int(b)] += v
        rows.extend(r["series"])
        overlaps.extend("%s: %s" % (r["chunk"], o) for o in r["overlaps"])
        chanmap[r["chunk"]] = r["chan"]
    rows.sort()

    with open(TS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "gen_power_kw", "evap_active", "evap_counter",
                    "b7", "state"])
        w.writerows(rows)

    stats = {
        "days": list(days),
        "sessions": {k: len(v) for k, v in sessions.items()},
        "chanmap": chanmap,
        "overlaps": overlaps,
        "contingency": {"%s|%d" % k: v for k, v in sorted(cont.items())},
        "hist": {s: dict(h) for s, h in hist.items()},
        "rows": len(rows),
    }
    with open(STATS_JSON, "w") as f:
        json.dump(stats, f, indent=1)

    print("\nwrote %s (%d rows)" % (os.path.basename(TS_CSV), len(rows)))
    print("wrote %s" % os.path.basename(STATS_JSON))
    if overlaps:
        print("\n*** CONCURRENT DUPLICATE CHANNELS (would double-count):")
        for o in overlaps:
            print("   ", o)
    else:
        print("no concurrent duplicate channels -- channel renumbering only")


# ---------------------------------------------------------------- phase 2

def phase2():
    with open(STATS_JSON) as f:
        stats = json.load(f)
    rows = []
    with open(TS_CSV) as f:
        for d in csv.DictReader(f):
            rows.append((float(d["t"]),
                         None if d["gen_power_kw"] == "" else float(d["gen_power_kw"]),
                         int(d["evap_active"]),
                         int(d["evap_counter"]),
                         int(d["b7"]),
                         d["state"]))
    rows.sort()

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("0x63A B7 bits[5:4] vs gen_power vs evap -- weekend 2026-07-24..26")
    emit("=" * 78)

    emit("\nBus channels carrying the VCU cluster (renumbering, not dropouts):")
    seen = []
    for ch, m in stats["chanmap"].items():
        c = tuple(m["0x63A"])
        if c and (not seen or seen[-1][1] != c):
            seen.append((ch, c))
    for ch, c in seen:
        emit("   %-38s channel %s" % (ch, ",".join(str(x) for x in c)))
    emit("   concurrent duplicates: %s"
         % (stats["overlaps"] if stats["overlaps"] else "none"))

    emit("\n--- Pooled contingency: bits[5:4] state x evap_active ---")
    emit("%-9s %12s %12s %10s %14s"
         % ("state", "evap=0 fr", "evap=1 fr", "total", "gen_med kW"))
    cont = defaultdict(int)
    for k, v in stats["contingency"].items():
        s, e = k.rsplit("|", 1)
        cont[(s, int(e))] += v
    # "hv_down" is the stored key from phase 1, kept stable so cached runs stay
    # readable, but the label is wrong: Saturday 2026-07-25 had bits[7:6] clear
    # for 100% of samples while ess_power hit 22.4 kW and trac_power 20.1 kW,
    # so bits[7:6] clear does NOT mean the HV bus is down. Displayed neutrally.
    order = ["hv_down", "0", "1", "2", "3"]
    label = {"hv_down": "b76!=3"}
    for s in order:
        n0, n1 = cont.get((s, 0), 0), cont.get((s, 1), 0)
        if not (n0 or n1 or cont.get((s, -1), 0)):
            continue
        med = hist_median({int(b): v for b, v in stats["hist"].get(s, {}).items()})
        emit("%-9s %12d %12d %10d %14s"
             % (label.get(s, s), n0, n1, n0 + n1 + cont.get((s, -1), 0),
                "n/a" if med is None else "%.1f" % med))

    # ---- per-day breakdown, in seconds of the 1 Hz timeseries
    #
    # Pooling all three days would hide the point: Friday is the data the
    # retracted claim was built on (purge and heavy generator in the same
    # window), Sunday is the drive home that is supposed to have heavy
    # generator use with no evap. They have to be read separately.
    emit("\n--- Per-day: seconds in each bits[5:4] state x evap_active ---")
    emit("%-7s %-9s %8s %8s %10s %10s"
         % ("day", "state", "evap=0 s", "evap=1 s", "gen_med", "gen_max"))
    perday = defaultdict(lambda: defaultdict(list))
    for t, gen, evap, cnt, b7, state in rows:
        perday[int(t // 86400)][(state, evap)].append(gen)
    for day in sorted(perday):
        for s in order:
            g0 = [g for g in perday[day].get((s, 0), []) if g is not None]
            g1 = [g for g in perday[day].get((s, 1), []) if g is not None]
            n0 = len(perday[day].get((s, 0), []))
            n1 = len(perday[day].get((s, 1), []))
            if not (n0 or n1):
                continue
            allg = sorted(g0 + g1)
            med = allg[len(allg) // 2] if allg else None
            emit("Jul-%02d %-9s %8d %8d %10s %10s"
                 % (day, label.get(s, s), n0, n1,
                    "n/a" if med is None else "%.1f" % med,
                    "n/a" if not allg else "%.1f" % allg[-1]))
        emit("")

    # ---- the confound-breaking cell: bit4 set while evap inactive
    emit("\n--- THE TEST: bits[5:4] with bit4 SET (states 1,3) and evap INACTIVE ---")
    n_bit4_evap0 = sum(cont.get((s, 0), 0) for s in ("1", "3"))
    n_bit4_evap1 = sum(cont.get((s, 1), 0) for s in ("1", "3"))
    emit("   bit4 set & evap active   : %d frames" % n_bit4_evap1)
    emit("   bit4 set & evap INACTIVE : %d frames" % n_bit4_evap0)
    if n_bit4_evap0 == 0:
        emit("   -> bit4 never sets without evap active. Confound NOT broken;")
        emit("      an evap-linked reading remains viable.")
    else:
        frac = 100.0 * n_bit4_evap0 / max(1, n_bit4_evap0 + n_bit4_evap1)
        emit("   -> bit4 DOES set with evap inactive (%.1f%% of its frames)."
             % frac)
        emit("      That falsifies any evap-linked reading of bits[5:4].")

    # ---- sustained high-generator episodes and their evap state
    emit("\n--- High-generator episodes (gen_power > %.0f kW, >= %.0f s) ---"
         % (GEN_HIGH_KW, EPISODE_MIN_S))
    eps, cur = [], None
    prev_t = None
    for t, gen, evap, cnt, b7, state in rows:
        gap = prev_t is not None and (t - prev_t) > EPISODE_GAP_S
        hi = gen is not None and gen > GEN_HIGH_KW
        if hi and not gap:
            if cur is None:
                cur = {"t0": t, "t1": t, "n": 0, "evap1": 0,
                       "st": defaultdict(int), "gmax": gen,
                       "c0": cnt, "c1": cnt}
            cur["t1"] = t
            cur["n"] += 1
            cur["evap1"] += 1 if evap == 1 else 0
            cur["st"][state] += 1
            cur["gmax"] = max(cur["gmax"], gen)
            if cnt >= 0:
                cur["c1"] = cnt
        else:
            if cur and (cur["t1"] - cur["t0"]) >= EPISODE_MIN_S:
                eps.append(cur)
            cur = None
        prev_t = t
    if cur and (cur["t1"] - cur["t0"]) >= EPISODE_MIN_S:
        eps.append(cur)

    emit("%-16s %7s %8s %7s %8s  %s"
         % ("start", "dur_s", "gen_max", "evap%", "cnt_adv", "bits[5:4] mix"))
    clean = []
    for e in eps:
        dur = e["t1"] - e["t0"]
        evp = 100.0 * e["evap1"] / max(1, e["n"])
        adv = (e["c1"] - e["c0"]) if (e["c0"] >= 0 and e["c1"] >= 0) else -1
        mix = " ".join("%s:%d%%" % (k, round(100.0 * v / e["n"]))
                       for k, v in sorted(e["st"].items(),
                                          key=lambda kv: -kv[1]))
        emit("%-16s %7.0f %8.1f %7.1f %8d  %s"
             % (fmt_t(e["t0"]), dur, e["gmax"], evp, adv, mix))
        if evp < 1.0:
            clean.append(e)

    emit("\n%d high-generator episodes; %d of them with evap inactive throughout"
         % (len(eps), len(clean)))
    if clean:
        agg = defaultdict(int)
        for e in clean:
            for k, v in e["st"].items():
                agg[k] += v
        tot = sum(agg.values())
        emit("bits[5:4] during evap-inactive high-generator time:")
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1]):
            emit("   state %-8s %8d samples  %5.1f%%" % (k, v, 100.0 * v / tot))

    with open(REPORT_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(REPORT_TXT))


# ---------------------------------------------------------------- phase 3

def scan_chunk_hv(path):
    """Per-chunk 0x63A B7 histogram against all three 0x598 power channels.

    Independent of any 0x63A interpretation: ess_power/trac_power come straight
    from the DBC and are nonzero only when the HV bus is actually live, so they
    test 'HV up' without reference to B7.
    """
    base, raw = header_start(path)
    if base is None:
        return None
    db = _db()
    b7hist = defaultdict(int)
    b7pow = defaultdict(lambda: {"ess": [], "gen": [], "trac": []})
    tl = {}
    ess = gen = trac = evap = None
    n63a = n649 = 0

    p = subprocess.Popen(["grep", "-E", r" 0x(63A|649|598) ", path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                 + int(ts[2]) + int(ts[3]) / 10000.0)
            cid = int(f[3], 16)
            data = bytes(int(x, 16) for x in f[6:])
        except (ValueError, IndexError):
            continue

        if cid == ID_598 and len(data) >= 8:
            try:
                d = db.decode_message(ID_598, data, decode_choices=False)
                ess, gen, trac = d["ess_power"], d["gen_power"], d["trac_power"]
            except Exception:
                pass
        elif cid == ID_649:
            n649 += 1
            if n649 % DEC_649 == 0 and len(data) >= 8:
                try:
                    evap = int(db.decode_message(
                        ID_649, data, decode_choices=False)["vcm_evap_active"])
                except Exception:
                    pass
        elif cid == ID_63A:
            n63a += 1
            if n63a % DEC_63A or len(data) < 8:
                continue
            b7 = data[7]
            b7hist[b7] += 1
            if ess is not None:
                r = b7pow[b7]
                r["ess"].append(ess)
                r["gen"].append(gen)
                r["trac"].append(trac)
            tl[int(t // 60)] = (t, b7, ess, gen, trac, evap)
    p.stdout.close()
    p.wait()
    return {"b7hist": dict(b7hist),
            "b7pow": {k: {kk: (len(vv), min(vv), max(vv),
                               sorted(vv)[len(vv) // 2])
                          for kk, vv in v.items() if vv}
                      for k, v in b7pow.items()},
            "tl": sorted(tl.values())}


def phase3(days):
    """Cross-check: was the HV bus live while 0x63A B7 bits[7:6] were clear?"""
    paths = [p for ps in chunks_for_days(days).values() for p in ps]
    print("phase 3: HV cross-check over %d chunks (%s)"
          % (len(paths), ",".join(days)))
    with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
        res = [r for r in pool.map(scan_chunk_hv, paths) if r]

    b7hist = defaultdict(int)
    pooled = defaultdict(lambda: {"ess": [], "gen": [], "trac": []})
    tl = []
    for r in res:
        for b7, n in r["b7hist"].items():
            b7hist[int(b7)] += n
        for b7, v in r["b7pow"].items():
            for kk, (n, lo, hi, med) in v.items():
                pooled[int(b7)][kk].extend([lo, med, hi])
        tl.extend(r["tl"])
    tl.sort()

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("Saturday HV cross-check: 0x63A B7 vs ess/gen/trac power (%s)"
         % ",".join(days))
    emit("=" * 78)
    emit("\nB7 value distribution (%d samples):" % sum(b7hist.values()))
    tot = sum(b7hist.values())
    for b7 in sorted(b7hist):
        emit("   0x%02X  bits[7:6]=%d  bits[5:4]=%d   %8d  %5.1f%%"
             % (b7, (b7 >> 6) & 3, (b7 >> 4) & 3, b7hist[b7],
                100.0 * b7hist[b7] / tot))

    emit("\nPower channels by B7 value (kW, min/median/max across chunks):")
    emit("%-6s %22s %22s %22s" % ("B7", "ess_power", "gen_power", "trac_power"))
    for b7 in sorted(pooled):
        cells = []
        for kk in ("ess", "gen", "trac"):
            v = sorted(pooled[b7][kk])
            cells.append("n/a" if not v else "%7.1f %7.1f %7.1f"
                         % (v[0], v[len(v) // 2], v[-1]))
        emit("0x%02X   %22s %22s %22s" % (b7, cells[0], cells[1], cells[2]))

    emit("\nTimeline (1 sample/min, non-idle rows only):")
    emit("%-16s %5s %9s %9s %9s %6s"
         % ("time", "B7", "ess_kW", "gen_kW", "trac_kW", "evap"))
    for t, b7, ess, gen, trac, evap in tl:
        if ess is None:
            continue
        if abs(ess) < 0.5 and abs(gen or 0) < 0.5 and abs(trac or 0) < 0.5:
            continue
        emit("%-16s  0x%02X %9.2f %9.2f %9.2f %6s"
             % (fmt_t(t), b7, ess, gen, trac,
                "-" if evap is None else evap))

    path = os.path.join(OUTDIR, "genstate_63a_saturday_hv_check.txt")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(path))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phases" in argv:
        i = argv.index("--phases")
        PHASES = {int(x) for x in argv[i + 1].split(",")}
        del argv[i:i + 2]
    if argv:
        DAYS = tuple(a for a in argv if a.isdigit())
    if 1 in PHASES:
        phase1(DAYS)
    if 2 in PHASES:
        phase2()
    if 3 in PHASES:
        phase3(DAYS)
