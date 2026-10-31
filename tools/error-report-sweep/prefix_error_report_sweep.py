"""Validate a rule for marking pre-Bug-11 gs_usb error reports without touching real data.

Plan: the internal `can-replay-readers` plan, step 1 (owner ruling 5, 2026-10-30).

Before the Bug 11 fix (Android builds before release 32), the Android logger wrote the
Innomaker's CAN error reports as ordinary standard frames: id = SocketCAN error-class mask
(< 0x400), DLC 8, payload as linux/can/error.h lays it out. Coda C CAN uses 0x000-0x019 for
real cell-voltage frames, so 0x004 / 0x00C (and any other id < 0x400) collide with real data.
This sweep measures, per bus (identified by anchors, never by channel number), how a
payload-layout rule separates the two populations.

Read-only. Runs on the Linux box from the reverse-it root (corpus on local disk):
    python3.13 tools/error-report-sweep/prefix_error_report_sweep.py scan
    python3.13 tools/error-report-sweep/prefix_error_report_sweep.py report
    python3.13 tools/error-report-sweep/prefix_error_report_sweep.py check
    python3.13 tools/error-report-sweep/prefix_error_report_sweep.py controls

Phases:
  scan      one text pass per capture (12 workers): header adapter + start date, per-channel
            frame counts and id sets, and for every standard id < 0x400 with DLC 8 the
            per-(channel, id) counts by rule outcome, plus samples. Also collects ERR lines.
            Writes scan.jsonl.
  report    resolves each channel to a bus by audited anchors (Coda) or provisional anchors
            (Vtrux), then aggregates rule outcomes per (vehicle, bus, id), split by stream
            kind (native periodic stream vs sporadic) and adapter. Writes report.txt.
  check     orthogonal check: frame counts of the hand split vs canre.parsers.parse_file on a
            sample of captures, so a scan that silently skipped lines shows up.
  controls  positive controls: the rule applied to every ERR line in the fault-matrix bench
            runs (android-app/notes/artifacts/fault_matrix_*), which are known error reports.
"""
import glob
import json
import multiprocessing as mp
import os
import sys
from collections import defaultdict

sys.path.insert(0, ".")

HERE = "tools/error-report-sweep/artifacts"
SCAN_OUT = os.path.join(HERE, "scan.jsonl")
REPORT_OUT = os.path.join(HERE, "report.txt")

ROOTS = {
    "coda": ["../../CANLogs/CodaLogs", "projects/coda/logs"],
    "vtrux": ["../../CANLogs/VtruxLogs", "projects/vtrux/logs"],
}

SAMPLE_CAP = 20     # sample payloads kept per (channel, id, outcome)
TIMES_CAP = 400     # rule-passing timestamps kept per (channel, id), for the 1 s tick test
NATIVE_MIN = 100    # a (capture, channel, id) stream with >= this many frames is "native"

# --- anchors -------------------------------------------------------------------------
# Coda: audited exclusive sets (projects/coda/README.md; codasim/io/logreplay.py), with the
# withdrawn 0x004 / 0x00C out of C CAN. Vtrux: NOT audited -- the sets the Vtrux probes use,
# minus the VCM-bridged 0x441-0x464 ids; labels from them are reported as provisional.
ANCHORS = {
    "coda": {
        "d_can": frozenset({0x308, 0x312, 0x325, 0x330, 0x580}),
        "b_can": frozenset({0x48A, 0x381, 0x615, 0x616, 0x617}),
        "c_can": frozenset(range(0x000, 0x01A)) - {0x004, 0x00C},
    },
    "vtrux": {
        "powertrain": frozenset({0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639}),
        "vehicle": frozenset({0x1E5, 0x500, 0x514, 0x52A, 0x778, 0x780}),
        "obd": frozenset({0x040, 0x041, 0x042, 0x043, 0x044}),
    },
}
MIN_ANCHORS = 2


def classify(vehicle, ids):
    """(label, reason): label only with >= MIN_ANCHORS of one bus and zero of all others."""
    hits = {b: len(ids & a) for b, a in ANCHORS[vehicle].items()}
    ok = [b for b, n in hits.items()
          if n >= MIN_ANCHORS and all(hits[o] == 0 for o in hits if o != b)]
    if len(ok) == 1:
        return ok[0], hits
    return None, hits


# --- the rule under test ---------------------------------------------------------------
# linux/can/error.h: id bits 0x002 LOSTARB (data[0] = bit), 0x004 CRTL (data[1]), 0x008 PROT
# (data[2] type, data[3] location), 0x010 TRX (data[4]); data[5] controller-specific;
# data[6] TEC, data[7] REC. A byte whose class bit is clear must be zero.
def layout_ok(i, d):
    if len(d) != 8 or i == 0 or i >= 0x400:
        return False
    if d[0] and not i & 0x002:
        return False
    if d[1] and not i & 0x004:
        return False
    if d[1] & 0x80:
        return False
    if (d[2] or d[3]) and not i & 0x008:
        return False
    if d[3] > 0x1F:
        return False
    if d[4] and not i & 0x010:
        return False
    return True


def outcome(i, d):
    if not any(d):
        return "allzero"
    return "pass" if layout_ok(i, d) else "fail"


# --- scan ------------------------------------------------------------------------------
def bm_time(tok):
    try:
        h, m, s, t = tok.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(t) / 10000.0
    except ValueError:
        return None


def scan_one(job):
    vehicle, path = job
    adapter, start = "", ""
    per_ch = defaultdict(int)
    ids_ch = defaultdict(set)
    stats = {}
    errs = []
    n_bad = 0
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                if line.startswith("***"):
                    if "***CHANNEL " in line and " - " in line and not adapter:
                        adapter = line.split(" - ")[1].strip()
                    elif "START DATE AND TIME" in line:
                        start = line.strip("*\n ").replace("START DATE AND TIME", "").strip()
                    continue
                p = line.split()
                if len(p) < 6 or p[1] not in ("Rx", "Tx"):
                    if p:
                        n_bad += 1
                    continue
                ch, typ = p[2], p[4]
                try:
                    i = int(p[3], 16)
                    dlc = int(p[5])
                    d = bytes(int(x, 16) for x in p[6:6 + dlc])
                except ValueError:
                    n_bad += 1
                    continue
                if typ == "ERR":
                    if len(errs) < 500:
                        errs.append((ch, i, d.hex(" "), bm_time(p[0]), layout_ok(i, d)))
                    continue
                per_ch[ch] += 1
                if typ != "s":
                    continue
                ids_ch[ch].add(i)
                if i >= 0x400 or dlc != 8:
                    continue
                k = (ch, i)
                st = stats.get(k)
                if st is None:
                    st = stats[k] = {"n": 0, "pass": 0, "allzero": 0, "fail": 0, "d5nz": 0,
                                     "samples": {"pass": [], "allzero": [], "fail": []},
                                     "times": []}
                st["n"] += 1
                o = outcome(i, d)
                st[o] += 1
                if o == "pass" and d[5]:
                    st["d5nz"] += 1
                if len(st["samples"][o]) < SAMPLE_CAP:
                    st["samples"][o].append((bm_time(p[0]), d.hex(" ")))
                if o != "fail" and len(st["times"]) < TIMES_CAP:
                    st["times"].append(bm_time(p[0]))
    except OSError as e:
        return {"path": path, "vehicle": vehicle, "error": type(e).__name__}
    return {
        "path": path, "vehicle": vehicle, "adapter": adapter, "start": start,
        "n_bad": n_bad, "per_ch": dict(per_ch),
        "ids_ch": {c: sorted(s) for c, s in ids_ch.items()},
        "stats": [[c, i, st] for (c, i), st in stats.items()],
        "errs": errs,
    }


def jobs():
    out = []
    for v, roots in ROOTS.items():
        for r in roots:
            for p in sorted(glob.glob(os.path.join(r, "*.log"))):
                out.append((v, p))
    return out


def phase_scan():
    js = jobs()
    print(f"{len(js)} captures")
    ctx = mp.get_context("fork")
    done = 0
    with open(SCAN_OUT, "w", encoding="utf-8") as out, ctx.Pool(max(1, os.cpu_count() - 4)) as pool:
        for res in pool.imap_unordered(scan_one, js, chunksize=1):
            out.write(json.dumps(res) + "\n")
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(js)}", flush=True)
    print(f"wrote {SCAN_OUT}")


# --- report ----------------------------------------------------------------------------
def tick_fraction(times, tol=0.005):
    """Of consecutive gaps >= 0.9 s between rule-passing frames, the share within tol of an
    integer number of seconds (the Innomaker reports on a free-running 1 s tick)."""
    ts = sorted(t for t in times if t is not None)
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a >= 0.9]
    if not gaps:
        return None, 0
    near = sum(1 for g in gaps if abs(g - round(g)) <= tol)
    return near / len(gaps), len(gaps)


def phase_report():
    rows = [json.loads(l) for l in open(SCAN_OUT, encoding="utf-8")]
    lines = []
    w = lines.append
    w(f"captures scanned: {len(rows)}")
    w(f"read errors: {sum(1 for r in rows if 'error' in r)}")
    w(f"unparsed data lines (total): {sum(r.get('n_bad', 0) for r in rows if 'error' not in r)}")

    labels = defaultdict(int)
    agg = defaultdict(lambda: defaultdict(int))
    samples = defaultdict(list)
    tick_times = defaultdict(list)
    per_capture_native_pass = []
    err_lines = 0
    for r in rows:
        if "error" in r:
            continue
        v = r["vehicle"]
        inno = "Innomaker" in r["adapter"]
        adap = "innomaker" if inno else (r["adapter"] or "none")
        err_lines += len(r["errs"])
        chlab = {}
        for ch, ids in r["ids_ch"].items():
            lab, hits = classify(v, set(ids))
            chlab[ch] = lab or "UNRESOLVED"
            labels[(v, chlab[ch])] += 1
        for ch, i, st in r["stats"]:
            bus = chlab.get(ch, "UNRESOLVED")
            kind = "native" if st["n"] >= NATIVE_MIN else "sporadic"
            key = (v, bus, i, kind, "innomaker" if inno else "other")
            a = agg[key]
            a["captures"] += 1
            for o in ("n", "pass", "allzero", "fail", "d5nz"):
                a[o] += st[o]
            if kind == "native" and st["pass"]:
                per_capture_native_pass.append((v, bus, f"0x{i:03X}", st["pass"], st["n"],
                                                os.path.basename(r["path"]), adap,
                                                st["samples"]["pass"][:3]))
            if kind == "sporadic" and (st["pass"] or st["allzero"]):
                tick_times[(v, bus, inno)].append(st["times"])
                if len(samples[(v, bus, i, kind)]) < 6:
                    samples[(v, bus, i, kind)].append(
                        (os.path.basename(r["path"]), st["samples"]["pass"][:2],
                         st["samples"]["allzero"][:1], st["samples"]["fail"][:2]))
    w(f"ERR lines (post-fix writer) seen in corpus: {err_lines}")
    w("")
    w("== channel labels (MIN_ANCHORS=2, all other buses zero) ==")
    for (v, lab), n in sorted(labels.items()):
        w(f"  {v:6s} {lab:12s} {n}")
    w("")
    w("== std id < 0x400, DLC 8: frames by rule outcome ==")
    w("   stream kind: native = >= %d frames of that id on that channel in that capture" % NATIVE_MIN)
    w(f"   {'veh':6s} {'bus':11s} {'id':6s} {'kind':9s} {'adapter':9s} {'capt':>5s} "
      f"{'frames':>10s} {'pass':>8s} {'allzero':>8s} {'fail':>10s} {'d5nz':>5s}")
    for key in sorted(agg):
        v, bus, i, kind, ad = key
        a = agg[key]
        w(f"   {v:6s} {bus:11s} 0x{i:03X}  {kind:9s} {ad:9s} {a['captures']:5d} "
          f"{a['n']:10d} {a['pass']:8d} {a['allzero']:8d} {a['fail']:10d} {a['d5nz']:5d}")
    w("")
    w("== native streams with rule-passing (non-zero) frames: the false-positive risk ==")
    per_capture_native_pass.sort(key=lambda x: -x[3])
    w(f"   {len(per_capture_native_pass)} (capture, channel, id) streams; top 40:")
    for row in per_capture_native_pass[:40]:
        w(f"   {row[0]} {row[1]} {row[2]} pass={row[3]}/{row[4]} {row[5]} [{row[6]}] e.g. {row[7]}")
    w("")
    w("== 1 s tick test on sporadic rule-passing / all-zero frames ==")
    for (v, bus, inno), tl in sorted(tick_times.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        allt = []
        fr = []
        for ts in tl:
            f, n = tick_fraction(ts)
            if n:
                fr.append((f, n))
        tot = sum(n for _, n in fr)
        near = sum(f * n for f, n in fr)
        share = f"{near / tot:.2f}" if tot else "-"
        w(f"   {v} {bus} {'innomaker' if inno else 'other'}: streams={len(tl)} gaps>=0.9s={tot} "
          f"share on integer-second (+/-5 ms)={share}")
    w("")
    w("== samples of sporadic streams (capture, pass, allzero, fail) ==")
    for key in sorted(samples):
        v, bus, i, kind = key
        w(f"  {v} {bus} 0x{i:03X} {kind}:")
        for s in samples[key]:
            w(f"     {s}")
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {REPORT_OUT} ({len(lines)} lines)")


# --- check -----------------------------------------------------------------------------
def phase_check():
    from canre.parsers import parse_file
    rows = [json.loads(l) for l in open(SCAN_OUT, encoding="utf-8")]
    rows = [r for r in rows if "error" not in r]
    rows.sort(key=lambda r: r["path"])
    pick = rows[:: max(1, len(rows) // 12)][:12]
    for r in pick:
        mine = sum(r["per_ch"].values())
        theirs = sum(1 for _ in parse_file(r["path"]))
        print(f"{'OK ' if mine == theirs else 'DIFF'} {mine:9d} {theirs:9d} bad={r['n_bad']} "
              f"{os.path.basename(r['path'])}")


# --- controls --------------------------------------------------------------------------
def phase_controls():
    from canre.parsers import parse_file
    paths = sorted(glob.glob("android-app/notes/artifacts/fault_matrix_*/app/*.log"))
    for p in paths:
        n = ok = 0
        bad = []
        for fr in parse_file(p, include_errors=True):
            if not fr.is_error:
                continue
            n += 1
            if layout_ok(fr.arbitration_id, fr.data):
                ok += 1
            elif len(bad) < 5:
                bad.append((hex(fr.arbitration_id), fr.data.hex(" ")))
        print(f"{p}: ERR={n} rule-pass={ok} fail-examples={bad}")


# --- masks -----------------------------------------------------------------------------
# Added after the first report: the layout rule alone passes huge native streams of sparse
# payloads (e.g. Coda 0x07D, Vtrux 0x0F9), so it can only work behind an id allowlist. This
# phase looks for the ids the Innomaker actually emits: per (vehicle, bus, id), Innomaker
# frames that never fail the layout rule, set against whether the same (bus, id) carries
# traffic in non-Innomaker captures (desktop adapters, which never wrote error reports).
def phase_masks():
    rows = [json.loads(l) for l in open(SCAN_OUT, encoding="utf-8")]
    inn = defaultdict(lambda: defaultdict(int))
    oth = defaultdict(int)
    times = defaultdict(list)
    c_samples = []
    for r in rows:
        if "error" in r:
            continue
        v = r["vehicle"]
        is_inn = "Innomaker" in r["adapter"]
        chlab = {ch: (classify(v, set(ids))[0] or "UNRESOLVED") for ch, ids in r["ids_ch"].items()}
        for ch, i, st in r["stats"]:
            bus = chlab.get(ch, "UNRESOLVED")
            if not is_inn:
                oth[(v, bus, i)] += st["n"]
                continue
            a = inn[(v, bus, i)]
            a["captures"] += 1
            for o in ("n", "pass", "allzero", "fail"):
                a[o] += st[o]
            if i in (0x004, 0x00C, 0x024):
                times[(v, bus, i)].append(st["times"])
                if bus == "c_can" and st["pass"]:
                    c_samples.append((os.path.basename(r["path"]), f"0x{i:03X}", st["n"],
                                      st["samples"]["pass"][:3], st["samples"]["fail"][:2]))
    print("Innomaker (vehicle, bus, id) streams that NEVER fail the layout rule, id < 0x400:")
    print(f"  {'veh':6s} {'bus':11s} {'id':6s} {'capt':>5s} {'frames':>8s} {'pass':>7s} "
          f"{'allzero':>7s}  frames-on-same-bus-in-non-Innomaker-captures")
    for key in sorted(inn):
        a = inn[key]
        if a["fail"] == 0 and (a["pass"] + a["allzero"]) > 0:
            v, bus, i = key
            print(f"  {v:6s} {bus:11s} 0x{i:03X} {a['captures']:5d} {a['n']:8d} {a['pass']:7d} "
                  f"{a['allzero']:7d}  {oth.get(key, 0)}")
    print()
    print("1 s tick test restricted to 0x004 / 0x00C / 0x024 in Innomaker captures:")
    for key in sorted(times):
        fr = [tick_fraction(ts) for ts in times[key]]
        fr = [(f, n) for f, n in fr if n]
        tot = sum(n for _, n in fr)
        near = sum(f * n for f, n in fr)
        allg = []
        for ts in times[key]:
            s = sorted(t for t in ts if t is not None)
            allg += [b - a for a, b in zip(s, s[1:])]
        allg.sort()
        med = allg[len(allg) // 2] if allg else None
        print(f"  {key[0]} {key[1]} 0x{key[2]:03X}: gaps>=0.9s={tot} on-tick share="
              f"{(near / tot) if tot else float('nan'):.2f} median gap={med}")
    print()
    print("C CAN streams with a rule-passing 0x004/0x00C/0x024 frame:")
    for s in c_samples:
        print("  ", s)


if __name__ == "__main__":
    {"scan": phase_scan, "report": phase_report, "check": phase_check,
     "controls": phase_controls, "masks": phase_masks}[sys.argv[1]]()
