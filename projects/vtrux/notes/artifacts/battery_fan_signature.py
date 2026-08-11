"""Battery-fan signature hunt across the 2026-07-14 contiguous Android session.

The user heard the battery cooling fan come on for the first time during the
*second* charge session on 2026-07-14. Goal: find any CAN signature.

Primary candidate: bcm_cool_req (0x410 B6 bit5) = A123 BMS cooling request.
Supporting context: bcm_ibat (charge/discharge), bcm_soc, bcm_on_plug,
bcm_chgc_stat (charge contactor), cell tmax/tmin (0x430), bcm_chga_ena.

Phase 1: stream every T-chunk (grep-prefiltered for 0x410/0x430), decode with
         cantools, build absolute-time series. Cache to CSV.
Phase 2: identify charge vs drive vs idle segments from ibat.
Phase 3: report every cool_req transition + context; correlate with charge segs.
"""
import sys
sys.path.insert(0, ".")

import os
import glob
import csv
import subprocess
from datetime import datetime, timedelta

import cantools

LOG_DIR = "<home>/Seafile/CANLogs/VtruxLogs"
SESSION = "20260714_161319"
DBC = "projects/vtrux/epri-pt-bus.dbc"
ART = "projects/vtrux/notes/artifacts"
CSV_410 = os.path.join(ART, "battery_fan_0410.csv")
CSV_430 = os.path.join(ART, "battery_fan_0430.csv")

RUN_PHASE1 = False
RUN_PHASE2 = False
RUN_PHASE3 = False
RUN_PHASE4 = False
RUN_PHASE5 = True

CSV_440 = os.path.join(ART, "battery_fan_0440.csv")

db = cantools.database.load_file(DBC)
MSG_410 = db.get_message_by_frame_id(0x410)
MSG_430 = db.get_message_by_frame_id(0x430)
MSG_440 = db.get_message_by_frame_id(0x440)


def chunk_files():
    files = glob.glob(os.path.join(LOG_DIR, f"vtrux_{SESSION}_T*.log"))
    def tnum(f):
        base = os.path.basename(f)
        return int(base.split("_T")[1].split(".")[0])
    return sorted(files, key=tnum)


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
    dlc = int(parts[idx + 2])
    data = bytes(int(b, 16) for b in parts[idx + 3:idx + 3 + dlc])
    return t, arb, data


def phase1():
    rows410, rows430, rows440 = [], [], []
    files = chunk_files()
    print(f"Phase1: {len(files)} chunks")
    for n, path in enumerate(files):
        base = parse_header_time(path)
        if base is None:
            print(f"  skip (no header): {os.path.basename(path)}")
            continue
        out = subprocess.run(["grep", "-hE", " 0x(410|430|440) ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            try:
                if arb == 0x410:
                    s = MSG_410.decode(data, decode_choices=False,
                                       allow_truncated=True)
                    rows410.append((t.isoformat(), s.get("bcm_ibat"),
                                    s.get("bcm_soc"), s.get("bcm_cool_req"),
                                    s.get("bcm_on_plug"), s.get("bcm_chgc_stat"),
                                    s.get("bcm_cpwr_cmd")))
                elif arb == 0x430:
                    s = MSG_430.decode(data, decode_choices=False,
                                       allow_truncated=True)
                    rows430.append((t.isoformat(), s.get("bcm_cell_tmax"),
                                    s.get("bcm_cell_tmin"), s.get("bcm_chga_ena")))
                elif arb == 0x440:
                    s = MSG_440.decode(data, decode_choices=False,
                                       allow_truncated=True)
                    rows440.append((t.isoformat(), s.get("bcm_balancing"),
                                    s.get("bcm_balancing_cnt"), s.get("bcm_fgd"),
                                    s.get("bcm_mainc_stat"), s.get("bcm_fault_mon")))
            except Exception:
                continue
        if n % 10 == 0:
            print(f"  chunk {n}: 410={len(rows410)} 430={len(rows430)} 440={len(rows440)}")
    with open(CSV_410, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "ibat", "soc", "cool_req", "on_plug", "chgc_stat", "cpwr_cmd"])
        w.writerows(rows410)
    with open(CSV_430, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "tmax", "tmin", "chga_ena"])
        w.writerows(rows430)
    with open(CSV_440, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "balancing", "balancing_cnt", "fgd", "mainc_stat", "fault_mon"])
        w.writerows(rows440)
    print(f"Phase1 done: {len(rows410)}/{len(rows430)}/{len(rows440)} rows")


def load_410():
    rows = []
    with open(CSV_410) as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["t"]),
                         float(r["ibat"]) if r["ibat"] else None,
                         float(r["soc"]) if r["soc"] else None,
                         int(float(r["cool_req"])) if r["cool_req"] else None,
                         int(float(r["on_plug"])) if r["on_plug"] else None,
                         int(float(r["chgc_stat"])) if r["chgc_stat"] else None,
                         int(float(r["cpwr_cmd"])) if r["cpwr_cmd"] else None))
    rows.sort(key=lambda x: x[0])
    return rows


def load_430():
    rows = []
    with open(CSV_430) as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["t"]),
                         float(r["tmax"]) if r["tmax"] else None,
                         float(r["tmin"]) if r["tmin"] else None,
                         int(float(r["chga_ena"])) if r["chga_ena"] else None))
    rows.sort(key=lambda x: x[0])
    return rows


def fmt(t, t0):
    return f"{t.strftime('%H:%M:%S')} (+{(t-t0).total_seconds()/60:6.1f}m)"


def phase2(rows):
    t0 = rows[0][0]
    print("\n=== Phase2: segment by pack current (charging = ibat>+5A) ===")
    segs = []
    cur = None
    for t, ibat, soc, *_ in rows:
        if ibat is None:
            continue
        state = "chg" if ibat > 5 else ("dis" if ibat < -5 else "idle")
        if cur is None or state != cur[0]:
            if cur:
                segs.append(cur)
            cur = [state, t, t, soc, soc]
        cur[2] = t
        cur[4] = soc
    if cur:
        segs.append(cur)
    merged = []
    for s in segs:
        dur = (s[2] - s[1]).total_seconds()
        if dur < 20 and merged:
            merged[-1][2] = s[2]
            merged[-1][4] = s[4]
            continue
        merged.append(s)
    print("  significant segments (>60s):")
    for state, ts, te, soc0, soc1 in merged:
        dur = (te - ts).total_seconds()
        if dur < 60:
            continue
        print(f"    {state:4s} {fmt(ts,t0)} -> {fmt(te,t0)}  dur={dur/60:5.1f}m  "
              f"soc {soc0}->{soc1}")
    return t0, merged


def phase3(rows, rows430, t0):
    print("\n=== Phase3: cool_req transitions ===")
    prev = None
    trans = []
    for t, ibat, soc, cool, plug, chgc, cpwr in rows:
        if cool is None:
            continue
        if prev is not None and cool != prev:
            trans.append((t, cool, ibat, soc, plug, chgc))
        prev = cool
    if not trans:
        print("  NO cool_req transitions in entire session.")
    for t, cool, ibat, soc, plug, chgc in trans:
        print(f"  {fmt(t,t0)}  cool_req -> {cool}  ibat={ibat:7.1f}A soc={soc} "
              f"plug={plug} chgc={chgc}")
    onpct = 100 * sum(1 for r in rows if r[3] == 1) / max(1, sum(1 for r in rows if r[3] is not None))
    print(f"  cool_req=1 fraction of session: {onpct:.1f}%")

    print("\n=== cell temperature range over session ===")
    temps = [(t, tmax, tmin) for t, tmax, tmin, _ in rows430 if tmax is not None]
    if temps:
        tmaxvals = [x[1] for x in temps]
        print(f"  tmax: {min(tmaxvals):.1f} -> {max(tmaxvals):.1f} degC")
        peak = max(temps, key=lambda x: x[1])
        print(f"  peak tmax {peak[1]:.1f}C at {fmt(peak[0],t0)} (tmin {peak[2]:.1f})")
        for state in ["hourly"]:
            pass
        step = max(1, len(temps) // 40)
        print("  temp trace (sampled):")
        for i in range(0, len(temps), step):
            t, tmax, tmin = temps[i]
            print(f"    {fmt(t,t0)}  tmax={tmax:5.1f}  tmin={tmin:5.1f}")


def load_440():
    rows = []
    with open(CSV_440) as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["t"]),
                         int(float(r["balancing"])) if r["balancing"] else None,
                         int(float(r["balancing_cnt"])) if r["balancing_cnt"] else None,
                         float(r["fgd"]) if r["fgd"] else None))
    rows.sort(key=lambda x: x[0])
    return rows


def phase4(rows440, t0):
    print("\n=== Phase4: balancing (0x440) timeline ===")
    prev = None
    for t, bal, cnt, fgd in rows440:
        if bal is None:
            continue
        if bal != prev:
            print(f"  {fmt(t,t0)}  bcm_balancing -> {bal}  cnt={cnt}")
            prev = bal
    balpct = 100 * sum(1 for r in rows440 if r[1] == 1) / max(1, sum(1 for r in rows440 if r[1] is not None))
    print(f"  balancing=1 fraction of session: {balpct:.1f}%")
    cnts = [r[2] for r in rows440 if r[2] is not None]
    if cnts:
        print(f"  balancing_cnt range: {min(cnts)} .. {max(cnts)}")


def chunk_windows(files, windows):
    starts = [(f, parse_header_time(f)) for f in files]
    starts = [(f, s) for f, s in starts if s is not None]
    sel = set()
    for i, (f, s) in enumerate(starts):
        nxt = starts[i + 1][1] if i + 1 < len(starts) else s + timedelta(hours=1)
        for ws, we in windows:
            if s < we and nxt > ws:
                sel.add(f)
    return sel


def phase5():
    print("\n=== Phase5: cross-ID byte-diff, fan-OFF vs fan-ON window ===")
    base_day = datetime(2026, 7, 14)
    def w(h1, m1, h2, m2):
        return (base_day.replace(hour=h1, minute=m1),
                base_day.replace(hour=h2, minute=m2))
    winA = w(18, 50, 19, 20)   # early big charge, SoC ~50-58, fan OFF
    winB = w(20, 40, 21, 5)    # late big charge, SoC ~98-100, fan ON candidate
    windows = [winA, winB]
    files = sorted(chunk_windows(chunk_files(), windows),
                   key=lambda f: int(os.path.basename(f).split("_T")[1].split(".")[0]))
    print(f"  parsing {len(files)} chunks overlapping windows")
    A = {}  # (arb,byte) -> set(values)
    B = {}
    freqA = {}
    freqB = {}
    for path in files:
        base = parse_header_time(path)
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if " Rx " not in line and " Tx " not in line:
                    continue
                dec = decode_line(line, base)
                if dec is None:
                    continue
                t, arb, data = dec
                if winA[0] <= t < winA[1]:
                    tgt, freq = A, freqA
                elif winB[0] <= t < winB[1]:
                    tgt, freq = B, freqB
                else:
                    continue
                freq[arb] = freq.get(arb, 0) + 1
                for bi, bv in enumerate(data):
                    tgt.setdefault((arb, bi), set()).add(bv)
    allids = set(freqA) | set(freqB)
    print(f"  IDs: winA={len(freqA)} winB={len(freqB)}")
    idsA, idsB = set(freqA), set(freqB)
    only_b = idsB - idsA
    only_a = idsA - idsB
    if only_b:
        print(f"  IDs present ONLY in fan-ON window: {sorted(hex(i) for i in only_b)}")
    if only_a:
        print(f"  IDs present ONLY in fan-OFF window: {sorted(hex(i) for i in only_a)}")
    print("  bytes that are STABLE-but-DIFFERENT between windows (candidate state flip):")
    hits = 0
    for (arb, bi), avals in sorted(A.items()):
        bvals = B.get((arb, bi))
        if bvals is None:
            continue
        if len(avals) <= 2 and len(bvals) <= 2 and avals != bvals and not (avals & bvals):
            print(f"    {hex(arb):>10} B{bi}: OFF={sorted(avals)} -> ON={sorted(bvals)}")
            hits += 1
    if hits == 0:
        print("    (none with disjoint stable values)")
    print("  bytes with LOW entropy in both but shifted range:")
    for (arb, bi), avals in sorted(A.items()):
        bvals = B.get((arb, bi))
        if bvals is None:
            continue
        if len(avals) <= 4 and len(bvals) <= 4 and avals != bvals and (avals & bvals):
            print(f"    {hex(arb):>10} B{bi}: OFF={sorted(avals)} ON={sorted(bvals)}")


if __name__ == "__main__":
    if RUN_PHASE1:
        phase1()
    rows = load_410()
    rows430 = load_430()
    print(f"loaded {len(rows)} 0x410, {len(rows430)} 0x430 rows")
    t0 = None
    if RUN_PHASE2:
        t0, merged = phase2(rows)
    if RUN_PHASE3:
        if t0 is None:
            t0 = rows[0][0]
        phase3(rows, rows430, t0)
    if RUN_PHASE4:
        if t0 is None:
            t0 = rows[0][0]
        phase4(load_440(), t0)
    if RUN_PHASE5:
        phase5()
