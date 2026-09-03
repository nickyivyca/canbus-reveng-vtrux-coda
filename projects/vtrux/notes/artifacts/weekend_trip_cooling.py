"""Did battery thermal conditioning engage during the 2026-07-24/26 weekend trip?

Question: cell tmax appeared to cross the ~40 C conditioning threshold on the
trip. Confirm it actually crossed, and determine whether the cooling package
actually engaged and ran.

The cooling-active signal (0x506 B0 bit5, corroborated by 0x508 presence) is
raw bytes not present in any DBC, so it is NOT in InfluxDB -- this must be done
against the raw Android logs. Cell temps ARE in InfluxDB but are read here too
so both sides share one clock.

Threshold model under test (from notes/battery-thermals.md):
  HV path active (charging or driving) AND cell tmax crossing ~40 C ON,
  dropping out around ~36.5 C OFF (thermostat with hysteresis).
  Driving edges run lower (~37-38 C) on the hysteresis tail.

Signals (epri-pt-bus.dbc): 0x410 bcm_ibat/bcm_soc, 0x430 bcm_cell_tmax/tmin,
0x506 B0 bit5 cooling state, 0x508 presence, 0x18FFD6B3 DCDC_LV_Curr (12V load,
the independent corroborator -- ~+95 A step when the package energizes).

Phase A: parse sessions (grep-prefiltered), sample ~1 Hz on the 0x430 clock,
         cache to CSV.
Phase B: per-session summary -- pack presence check, peak tmax, cooling windows,
         tmax at each edge, 12V load by state.
"""
import sys
sys.path.insert(0, ".")

import os
import csv
import glob
import subprocess
from datetime import datetime, timedelta

import cantools

LOG_DIR = "../../CANLogs/VtruxLogs"
ART = "projects/vtrux/notes/artifacts"
CACHE = os.path.join(ART, "weekend_trip_cooling_samples.csv")

RUN_PARSE = False   # Phase A cached in weekend_trip_cooling_samples.csv; set True to re-parse

SESSIONS = [
    "20260724_160330",
    "20260724_162517",
    "20260724_172621",
    "20260724_211556",
    "20260725_102722",
    "20260725_170050",
    "20260726_124205",
    "20260726_142628",
    "20260726_160923",
    "20260726_191901",
]

db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = db.get_message_by_frame_id(0x410)
M430 = db.get_message_by_frame_id(0x430)
MDCDC = db.get_message_by_frame_id(0x18FFD6B3)


def parse_header_time(path):
    with open(path, "r", errors="replace") as f:
        for _ in range(20):
            line = f.readline()
            if "START DATE AND TIME" in line:
                part = line.split("START DATE AND TIME", 1)[1].strip()
                date_s, time_s = part.split(" ", 1)
                dd, mm, yyyy = date_s.split(":")
                hh, mi, ss, ms = time_s.split(":")
                ms = "".join(c for c in ms if c.isdigit())
                return datetime(int(yyyy), int(mm), int(dd),
                                int(hh), int(mi), int(ss), int(ms) * 1000)
    return None


def rel_seconds(tok):
    hh, mm, ss, ticks = tok.split(":")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ticks) * 0.0001


def decode_line(line, base_dt):
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        t = base_dt + timedelta(seconds=rel_seconds(parts[0]))
    except Exception:
        return None
    idx = None
    for i, p in enumerate(parts):
        if p.startswith("0x"):
            idx = i
            break
    if idx is None:
        return None
    try:
        arb = int(parts[idx], 16)
    except ValueError:
        return None
    try:
        dlc = int(parts[idx + 2])
        data = bytes(int(b, 16) for b in parts[idx + 3:idx + 3 + dlc])
    except (ValueError, IndexError):
        return None
    return t, arb, data


def chunk_files(session):
    files = glob.glob(os.path.join(LOG_DIR, "vtrux_%s_T*.log" % session))
    return sorted(files, key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))


def parse_session(session):
    """~1 Hz samples on the 0x430 clock, plus raw ID presence counts."""
    files = chunk_files(session)
    last_ibat = last_soc = last_lv = None
    last_cool = 0
    last_508 = None
    last_emit = None
    samples = []
    counts = {0x410: 0, 0x430: 0, 0x506: 0, 0x508: 0, 0x18FFD6B3: 0}

    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(
            ["grep", "-hE", " 0x(410|430|506|508|18FFD6B3) ", path],
            capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb in counts:
                counts[arb] += 1
            if arb == 0x410:
                try:
                    s = M410.decode(data, allow_truncated=True)
                    last_ibat = s.get("bcm_ibat")
                    last_soc = s.get("bcm_soc")
                except Exception:
                    pass
            elif arb == 0x506 and len(data) >= 1:
                last_cool = (data[0] >> 5) & 1
            elif arb == 0x508:
                last_508 = t
            elif arb == 0x18FFD6B3:
                try:
                    last_lv = MDCDC.decode(data, allow_truncated=True).get("DCDC_LV_Curr")
                except Exception:
                    pass
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax")
                    tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                # 87.0 C == raw 0xFE sentinel; real cells never go there
                if tmax is None or tmax < -30 or tmax > 60:
                    continue
                ep = t.timestamp()
                if last_emit is not None and ep - last_emit < 1.0:
                    continue
                last_emit = ep
                p508 = 1 if (last_508 is not None
                             and (t - last_508).total_seconds() < 3) else 0
                samples.append((round(ep, 1), tmax, tmin, last_ibat, last_soc,
                                last_cool, p508, last_lv))
    return samples, counts, len(files)


def phase_parse(only=None, append=False):
    """Parse sessions to CACHE. `only` limits to a subset; `append` keeps
    existing rows (used to repair a partial cache without re-reading 11 GB)."""
    todo = only if only else SESSIONS
    print("Phase A: parsing %d sessions from %s%s"
          % (len(todo), LOG_DIR, " (append)" if append else ""))
    with open(CACHE, "a" if append else "w", newline="") as f:
        w = csv.writer(f)
        if not append:
            w.writerow(["session", "t", "tmax", "tmin", "ibat", "soc",
                        "cool", "p508", "lv"])
        for i, sess in enumerate(todo):
            samples, counts, nfiles = parse_session(sess)
            for s in samples:
                w.writerow([sess, *s])
            f.flush()
            print("  [%d/%d] %-18s %2d chunks  %5d samples   "
                  "0x430=%-7d 0x506=%-7d 0x508=%-6d"
                  % (i + 1, len(todo), sess, nfiles, len(samples),
                     counts[0x430], counts[0x506], counts[0x508]))
    print("Phase A done ->", CACHE)


def fnum(x):
    return float(x) if x not in (None, "", "None") else None


def phase_analyze():
    from collections import defaultdict, OrderedDict
    rows = defaultdict(list)
    with open(CACHE) as f:
        for r in csv.DictReader(f):
            rows[r["session"]].append(r)

    print()
    print("=" * 92)
    print("PHASE B -- per-session cooling summary")
    print("=" * 92)
    # NB: the last column is "did cooling ever activate", NOT "is 0x506 present".
    # 0x506 is broadcast in every session on this pack; see the Phase A counts.
    print("%-18s %7s %7s %7s %7s %9s %9s"
          % ("session", "peak C", ">=38 s", ">=40 s", "cool s", "cool ON",
             "cooled?"))
    grand = []
    for sess in SESSIONS:
        rs = rows.get(sess, [])
        if not rs:
            print("%-18s   (no samples)" % sess)
            continue
        temps = [fnum(r["tmax"]) for r in rs]
        temps = [t for t in temps if t is not None]
        cool = [int(r["cool"]) for r in rs]
        has506 = any(int(r["p508"]) for r in rs) or any(cool)
        n38 = sum(1 for t in temps if t >= 38.0)
        n40 = sum(1 for t in temps if t >= 40.0)
        ncool = sum(cool)
        edges = sum(1 for a, b in zip(cool, cool[1:]) if b and not a)
        if cool and cool[0]:
            edges += 1
        print("%-18s %7.1f %7d %7d %7d %9d %9s"
              % (sess, max(temps) if temps else -99, n38, n40, ncool, edges,
                 "yes" if has506 else "NO"))
        grand.append((sess, rs))

    print()
    print("=" * 92)
    print("PHASE B2 -- cooling ON/OFF edges with cell temp at each edge")
    print("=" * 92)
    for sess, rs in grand:
        cool = [int(r["cool"]) for r in rs]
        if not any(cool):
            continue
        print("\n%s" % sess)
        print("  %-10s %-6s %8s %8s %9s %9s"
              % ("time", "edge", "tmax", "tmin", "ibat A", "12V A"))
        prev = 0
        for i, r in enumerate(rs):
            c = int(r["cool"])
            if c == prev:
                continue
            prev = c
            ts = datetime.fromtimestamp(float(r["t"])).strftime("%H:%M:%S")
            lv = fnum(r["lv"])
            ib = fnum(r["ibat"])
            print("  %-10s %-6s %8.1f %8.1f %9s %9s"
                  % (ts, "ON" if c else "OFF", fnum(r["tmax"]), fnum(r["tmin"]),
                     ("%.0f" % ib) if ib is not None else "-",
                     ("%.0f" % lv) if lv is not None else "-"))

    print()
    print("=" * 92)
    print("PHASE B3 -- 12V load by cooling state (independent corroboration)")
    print("=" * 92)
    for sess, rs in grand:
        on = [fnum(r["lv"]) for r in rs if int(r["cool"]) and fnum(r["lv"]) is not None]
        off = [fnum(r["lv"]) for r in rs if not int(r["cool"]) and fnum(r["lv"]) is not None]
        if not on and not off:
            continue
        med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
        print("  %-18s  OFF n=%-6d median %6.1f A   |  ON n=%-6d median %6.1f A"
              % (sess, len(off), med(off), len(on), med(on)))

    print()
    print("=" * 92)
    print("PHASE B4 -- P(cooling | tmax), HV active, whole trip")
    print("=" * 92)
    bins = defaultdict(lambda: [0, 0])
    for sess, rs in grand:
        for r in rs:
            tmax = fnum(r["tmax"]); ibat = fnum(r["ibat"])
            if tmax is None or ibat is None or abs(ibat) <= 3:
                continue
            tb = round(tmax * 2) / 2
            b = bins[tb]
            b[1] += 1
            b[0] += int(r["cool"])
    print("  %6s %7s %7s %6s" % ("tmax", "cool", "total", "P"))
    for tb in sorted(bins):
        c, t = bins[tb]
        if t < 10:
            continue
        print("  %6.1f %7d %7d %5.0f%%" % (tb, c, t, 100.0 * c / t))


def phase_envelope():
    """Is the ON/OFF chatter real, or aliasing of a toggling 0x506 bit?

    0x508 is broadcast only while cooling is active (~8.7 Hz beacon), so its
    presence gives an independent envelope. Compare the two, and rebuild
    cooling runs from 0x508 with a gap tolerance.
    """
    import csv as _csv
    from collections import defaultdict
    rows = defaultdict(list)
    with open(CACHE) as f:
        for r in _csv.DictReader(f):
            rows[r["session"]].append(r)

    print()
    print("=" * 92)
    print("PHASE C -- 0x506-bit5 vs 0x508-presence, and merged cooling runs")
    print("=" * 92)
    for sess in SESSIONS:
        rs = rows.get(sess, [])
        if not rs or not any(int(r["cool"]) or int(r["p508"]) for r in rs):
            continue
        agree = sum(1 for r in rs if int(r["cool"]) == int(r["p508"]))
        n506 = sum(int(r["cool"]) for r in rs)
        n508 = sum(int(r["p508"]) for r in rs)
        print("\n%s" % sess)
        print("  samples=%d  0x506-on=%d  0x508-on=%d  agreement=%.1f%%"
              % (len(rs), n506, n508, 100.0 * agree / len(rs)))

        # merge runs from 0x508 presence, tolerating gaps up to GAP seconds
        for GAP in (0, 5, 30):
            runs = []
            start = last = None
            for r in rs:
                t = float(r["t"])
                if int(r["p508"]):
                    if start is None:
                        start = t
                    last = t
                else:
                    if start is not None and t - last > GAP:
                        runs.append((start, last))
                        start = last = None
            if start is not None:
                runs.append((start, last))
            runs = [(a, b) for a, b in runs if b - a >= 1]
            total = sum(b - a for a, b in runs)
            print("    gap<=%-3ds : %3d runs, %5.0f s total, longest %5.0f s"
                  % (GAP, len(runs), total,
                     max((b - a for a, b in runs), default=0)))

        # print the merged runs at 30 s tolerance with temps
        runs = []
        start = last = None
        for r in rs:
            t = float(r["t"])
            if int(r["p508"]):
                if start is None:
                    start = t
                last = t
            else:
                if start is not None and t - last > 30:
                    runs.append((start, last))
                    start = last = None
        if start is not None:
            runs.append((start, last))
        runs = [(a, b) for a, b in runs if b - a >= 30]
        if runs:
            print("    merged runs (>=30 s, 30 s gap tolerance):")
            for a, b in runs:
                seg = [float(r["tmax"]) for r in rs
                       if a <= float(r["t"]) <= b and r["tmax"] not in ("", "None")]
                print("      %s -> %s  (%4.0f s)  tmax %.1f-%.1f C"
                      % (datetime.fromtimestamp(a).strftime("%H:%M:%S"),
                         datetime.fromtimestamp(b).strftime("%H:%M:%S"),
                         b - a, min(seg), max(seg)))


if __name__ == "__main__":
    if "--repair" in sys.argv:
        # re-parse only the sessions missing from the cache, appending.
        # Use after an interrupted parse -- avoids re-reading the full 11 GB.
        have = set()
        try:
            with open(CACHE) as f:
                for r in csv.DictReader(f):
                    have.add(r["session"])
        except FileNotFoundError:
            pass
        missing = [s for s in SESSIONS if s not in have]
        print("cache has %d sessions; missing %d: %s"
              % (len(have), len(missing), ", ".join(missing) or "none"))
        if missing:
            phase_parse(only=missing, append=bool(have))
    elif RUN_PARSE:
        phase_parse()
    phase_analyze()
    phase_envelope()
