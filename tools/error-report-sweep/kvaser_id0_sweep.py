"""Validate a rule for marking desktop-BUSMASTER Kvaser id-0 status frames without touching real data.

Plan: the internal `can-replay-readers` plan, step 4c (owner, 2026-10-30: deal with these "in the
same way the innomaker stuff is: not just a simple drop"). Step 1's sweep
(prefix_error_report_sweep.py) is the model; kvaser_id0_survey.py is the first count.

Desktop BUSMASTER 3.2.2 captures with Kvaser adapters carry standard id 0x000, DLC 4 frames,
`00 00 NN 00` and `00 xx 00 00` / `20 xx 00 00`, that look like adapter error-counter and
error-state events rather than bus traffic (hypothesis, owner shown 2026-10-30). Coda C CAN
uses 0x000 for a real cell-voltage frame (DLC 8), so a rule must not touch that.

Candidate rule (all must hold):
  capture  the header names a Kvaser adapter on some channel
  frame    standard id 0x000, DLC 4
  payload  "count" form 00 00 NN 00, or "flags" form B0 00 00 with B0 in {00, 20}, xx != 00

Read-only. Runs on the Linux box from the reverse-it root:
    python3.13 tools/error-report-sweep/kvaser_id0_sweep.py scan
    python3.13 tools/error-report-sweep/kvaser_id0_sweep.py report

Phases:
  scan    one text pass per capture (12 workers): header adapters per channel, per-channel
          frame counts and id sets, every id-0 frame summarised per (channel, type, DLC, form)
          with samples, the count-form step sequence per channel, Tx/Rx split, and how the
          id-0 frames sit against the channel's traffic (gap before each, frames per second).
          Writes kvaser_id0_scan.jsonl.
  report  labels channels by anchors with 0x000 left out of every anchor set (so the frames
          under test cannot decide a label), then: population of id-0 frames by vehicle,
          adapter, bus, DLC and form; the rule's hits and everything it does not catch; any
          rule hit on a C CAN channel or any DLC-8 0x000 off C CAN; the count-form step
          structure; the Innomaker-header captures (desktop replays recorded by Android); and
          the resolver's ambiguous channels before and after ignoring rule hits.
          Writes kvaser_id0_report.txt.
"""
import json
import multiprocessing as mp
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, ".")
CLONE = Path(os.environ.get("CAN_TOOLS_DIR", Path.home() / "Git" / "can-tools"))
sys.path.insert(0, str(CLONE))

HERE = Path("tools/error-report-sweep/artifacts")
SCAN_OUT = HERE / "kvaser_id0_scan.jsonl"
REPORT_OUT = HERE / "kvaser_id0_report.txt"
ROOTS = {
    "coda": ["../../CANLogs/CodaLogs", "projects/coda/logs"],
    "vtrux": ["../../CANLogs/VtruxLogs", "projects/vtrux/logs"],
}
CHAN = re.compile(r"^\*\*\*CHANNEL\s+(\d+)\s+-\s+(.*?)\s+-")
LINE = re.compile(r"^(\d+):(\d+):(\d+):(\d+) (Rx|Tx) (\d+) 0x([0-9A-Fa-f]+) (\w+) (\d+) ?(.*)$")
SAMPLES = 6


def form(dlc, data):
    """'count', 'flags' or 'other' for an id-0 DLC-4 payload; None for other DLCs."""
    if dlc != 4 or len(data) != 4:
        return None
    b0, b1, b2, b3 = data
    if b0 == 0 and b1 == 0 and b3 == 0:
        return "count"
    if b0 in (0x00, 0x20) and b1 != 0 and b2 == 0 and b3 == 0:
        return "flags"
    return "other"


def scan_one(job):
    vehicle, path = job
    adapters, ids, frames = {}, defaultdict(set), Counter()
    id0 = defaultdict(lambda: {"n": 0, "tx": 0, "samples": []})
    steps = defaultdict(Counter)        # ch -> Counter of count-form NN deltas
    last_nn = {}
    nn_max = Counter()
    flag_vals = Counter()
    gap_before = defaultdict(list)      # ch -> gap (s) since previous frame on that channel
    last_t = {}
    err_lines = 0
    try:
        with open(path, errors="replace") as f:
            for line in f:
                if line.startswith("***"):
                    m = CHAN.match(line)
                    if m:
                        adapters[m[1]] = m[2]
                    continue
                m = LINE.match(line)
                if not m:
                    continue
                t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1e4
                ch, cid, typ, dlc = m[6], int(m[7], 16), m[8], int(m[9])
                if typ == "ERR":
                    err_lines += 1
                    continue
                frames[ch] += 1
                ids[ch].add(cid)
                prev = last_t.get(ch)
                last_t[ch] = t
                if cid != 0:
                    continue
                try:
                    data = bytes.fromhex(m[10])
                except ValueError:
                    data = b""
                fm = form(dlc, data) if typ == "s" else None
                key = f"{ch}|{typ}|{dlc}|{fm}"
                rec = id0[key]
                rec["n"] += 1
                rec["tx"] += m[5] == "Tx"
                if len(rec["samples"]) < SAMPLES:
                    rec["samples"].append([round(t, 4), m[10].strip()])
                if fm in ("count", "flags"):
                    gap_before[ch].append(round(t - prev, 4) if prev is not None else None)
                if fm == "count":
                    nn = data[2]
                    nn_max[nn] += 1
                    if ch in last_nn:
                        d = nn - last_nn[ch]
                        steps[ch][d if -2 <= d <= 2 else ("up>2" if d > 0 else "down<-2")] += 1
                    last_nn[ch] = nn
                elif fm == "flags":
                    flag_vals[f"{data[0]:02X} {data[1]:02X}"] += 1
    except OSError as e:
        return {"path": path, "vehicle": vehicle, "error": str(e)}
    gaps = {ch: sorted(g for g in v if g is not None) for ch, v in gap_before.items()}
    return {
        "path": path, "vehicle": vehicle, "adapters": adapters, "err_lines": err_lines,
        "frames": dict(frames), "ids_ch": {c: sorted(s) for c, s in ids.items()},
        "id0": dict(id0), "steps": {c: {str(k): v for k, v in s.items()} for c, s in steps.items()},
        "nn_max": {str(k): v for k, v in nn_max.items()}, "flag_vals": dict(flag_vals),
        "gap_q": {ch: [g[len(g) // 2], g[int(len(g) * 0.9)], g[-1]] for ch, g in gaps.items() if g},
    }


def jobs():
    out = []
    for vehicle, roots in ROOTS.items():
        for r in roots:
            out += [(vehicle, str(p)) for p in sorted(Path(r).glob("*.log"))]
    return out


def phase_scan():
    js = jobs()
    print(f"captures {len(js)}", flush=True)
    with SCAN_OUT.open("w") as out, mp.Pool(max(1, os.cpu_count() - 4)) as pool:
        for i, row in enumerate(pool.imap_unordered(scan_one, js, chunksize=4), 1):
            out.write(json.dumps(row) + "\n")
            if i % 500 == 0:
                print(f"  {i}/{len(js)}", flush=True)


# Labelling only; never the frames under test. Vtrux powertrain = the set proposed to the
# owner at step 4b (not yet approved), which gives the same labels as the old single anchor.
def anchor_configs():
    from canbench.live import vehicle_configs as vc
    coda = vc.VEHICLES["coda"]
    coda_cfg = vc.VehicleConfig(coda.log_subdir, {
        n: vc.BusConfig(frozenset(b.anchors - {0x000}), b.description, b.min_anchors)
        for n, b in coda.buses.items()})
    vt = vc.VEHICLES["vtrux"]
    pt = frozenset({0x051, 0x592, 0x594, 0x596, 0x597, 0x599, 0x5A0, 0x5A2, 0x639, 0x63A,
                    0x63C, 0x63D, 0x63F, 0x640, 0x644, 0x645, 0x646, 0x647, 0x648, 0x649,
                    0x64A, 0x64B})
    vt_cfg = vc.VehicleConfig(vt.log_subdir, {
        "powertrain": vc.BusConfig(pt), "gm_unfiltered": vt.buses["gm_unfiltered"],
        "gm_obd": vt.buses["gm_obd"]})
    return vc, {"coda": coda_cfg, "vtrux": vt_cfg}


def is_kvaser(row):
    return any("kvaser" in a.lower() for a in row["adapters"].values())


def rule_hit(row, key):
    ch, typ, dlc, fm = key.split("|")
    return is_kvaser(row) and typ == "s" and dlc == "4" and fm in ("count", "flags")


def phase_report():
    vc, cfgs = anchor_configs()
    rows = [json.loads(l) for l in SCAN_OUT.open()]
    errs = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    L = []
    w = L.append
    w(f"captures {len(rows)}, read errors {len(errs)}")
    pop = Counter()
    hits, misses = Counter(), []
    c_can_hits, dlc8_off_c = [], []
    inno = []
    steps_all, nn_all, flags_all = Counter(), Counter(), Counter()
    gap_meds = []
    amb_before, amb_after = [], []
    kv_files = Counter()
    for r in rows:
        cfg = cfgs[r["vehicle"]]
        obs = {int(c): set(v) for c, v in r["ids_ch"].items()}
        res = vc.resolve_buses(cfg, obs)
        label = {c: res.assignments.get(c, "unlabelled") for c in obs}
        # Ambiguity with 0x000 kept as a C CAN anchor, as canbench's table has it.
        keep_cfg = vc.VEHICLES["coda"] if r["vehicle"] == "coda" else cfg
        res_keep = vc.resolve_buses(keep_cfg, obs)
        adapter = "Kvaser" if is_kvaser(r) else ("+".join(sorted(set(r["adapters"].values()))) or "none")
        if is_kvaser(r):
            kv_files[r["vehicle"]] += 1
        hit_ch = Counter()
        for key, rec in r["id0"].items():
            ch, typ, dlc, fm = key.split("|")
            bus = label.get(int(ch), "unlabelled")
            pop[(r["vehicle"], adapter, bus, typ, dlc, fm)] += rec["n"]
            if rule_hit(r, key):
                hits[(r["vehicle"], bus, fm)] += rec["n"]
                hit_ch[int(ch)] += rec["n"]
                if bus == "c_can":
                    c_can_hits.append((r["path"], ch, fm, rec["n"], rec["samples"][:2]))
                if rec["tx"]:
                    misses.append((r["path"], key, rec["n"], "rule hit includes Tx frames", rec["samples"][:2]))
            elif dlc != "8" or bus != "c_can":
                why = ("not a Kvaser capture" if not is_kvaser(r) else
                       f"type {typ}" if typ != "s" else f"DLC {dlc}" if dlc != "4" else f"form {fm}")
                misses.append((r["path"], key, rec["n"], why, rec["samples"][:2]))
            if dlc == "8" and bus != "c_can":
                dlc8_off_c.append((r["path"], ch, bus, rec["n"], rec["samples"][:2]))
        if not is_kvaser(r) and any(k.split("|")[2] == "4" for k in r["id0"]):
            inno.append((r["path"], adapter, {k: v["n"] for k, v in r["id0"].items()}))
        for s in r["steps"].values():
            steps_all.update(s)
        nn_all.update(r["nn_max"])
        flags_all.update(r["flag_vals"])
        for ch, q in r["gap_q"].items():
            gap_meds.append(q[0])
        if res_keep.ambiguous:
            amb_before.append((r["path"], res_keep.ambiguous))
            # Ignore rule hits: drop 0x000 from a channel's ids when every id-0 frame on it is a hit.
            obs2 = {}
            for c, ids in obs.items():
                total0 = sum(v["n"] for k, v in r["id0"].items() if k.split("|")[0] == str(c))
                obs2[c] = ids - {0x000} if total0 and hit_ch[c] == total0 else ids
            full = vc.resolve_buses(keep_cfg, obs2)
            if full.ambiguous:
                amb_after.append((r["path"], full.ambiguous))
    w(f"Kvaser-header captures: {dict(kv_files)}")
    w("")
    w("== population: id-0 frames by (vehicle, adapter, bus, type, DLC, form) ==")
    for k, n in sorted(pop.items(), key=lambda kv: -kv[1]):
        w(f"  {n:8d}  " + " | ".join(str(x) for x in k))
    w("")
    w("== rule hits by (vehicle, bus, form) ==")
    for k, n in sorted(hits.items(), key=lambda kv: -kv[1]):
        w(f"  {n:8d}  {k}")
    w(f"  total {sum(hits.values())}")
    w("")
    w(f"== rule hits on a C CAN channel: {len(c_can_hits)} ==")
    for x in c_can_hits[:20]:
        w(f"  {Path(x[0]).name} ch{x[1]} {x[2]} n={x[3]} {x[4]}")
    w(f"== DLC-8 0x000 off C CAN (real cell frames are expected only on C CAN): {len(dlc8_off_c)} ==")
    for x in dlc8_off_c[:20]:
        w(f"  {Path(x[0]).name} ch{x[1]} {x[2]} n={x[3]} {x[4]}")
    w("")
    by_why = Counter(m[3] for m in misses)
    w(f"== id-0 frames NOT caught (excluding DLC-8 on C CAN): {sum(m[2] for m in misses)} frames, {dict(by_why)} ==")
    for m in sorted(misses, key=lambda m: -m[2])[:40]:
        w(f"  {m[2]:7d}  {Path(m[0]).name}  {m[1]}  [{m[3]}]  {m[4]}")
    w("")
    w("== count form 00 00 NN 00: step between consecutive count frames on a channel ==")
    for k, n in sorted(steps_all.items(), key=lambda kv: -kv[1]):
        w(f"  {n:8d}  delta {k}")
    w("  NN values: " + ", ".join(f"{int(k):02X}:{v}" for k, v in sorted(nn_all.items(), key=lambda kv: int(kv[0]))))
    w("== flags form: (B0 B1) values ==")
    w("  " + ", ".join(f"{k}:{v}" for k, v in flags_all.most_common()))
    gm = sorted(gap_meds)
    if gm:
        w(f"== median gap before a rule frame, per channel: median {gm[len(gm)//2]} s, "
          f"90th pct {gm[int(len(gm)*0.9)]} s, max {gm[-1]} s ({len(gm)} channels) ==")
    w("")
    w(f"== non-Kvaser captures with DLC-4 id-0 frames (desktop replays recorded by Android): {len(inno)} ==")
    for p, a, d in inno:
        w(f"  {Path(p).name} [{a}] {d}")
    w("")
    w(f"== resolver: captures with an ambiguous channel, 0x000 kept as a C CAN anchor ==")
    w(f"  before ignoring rule hits: {len(amb_before)}; after: {len(amb_after)}")
    for p, a in amb_before:
        w(f"  before  {Path(p).name}: {a}")
    for p, a in amb_after:
        w(f"  after   {Path(p).name}: {a}")
    for e in errs:
        w(f"  READ ERROR {e['path']}: {e['error']}")
    REPORT_OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    for ph in sys.argv[1:] or ["scan", "report"]:
        {"scan": phase_scan, "report": phase_report}[ph]()
