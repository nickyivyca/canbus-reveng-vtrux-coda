"""hold_msgrate_check.py -- is the "message rate drops during the Low Power
hold" claim real, or an InfluxDB point-count artefact? (2026-10-10)

Infrastructure/vehicle-cost-per-mile.md 6.2 says the charger's status message
rate drops to 55 % of normal during the hold and the BMS message to 20 %. No
script derivation was found. Theory: it was counted from InfluxDB points, which
are written on change plus a 1 s heartbeat, so a steady hold value yields far
fewer points than frames.

For the 10 Low Power hold sessions (vcu_hold_character.txt):
  1  grep-filter the raw logs to 0x18FFD7C0 (Bel) and 0x410 (BMS), in parallel,
     into msgrate_filtered/ (deleted afterwards; regenerable)
  2  RAW frame rate per state. Bus: the channel carrying BOTH ids is taken as
     powertrain, per file. Each second is classed from the forward-filled
     charger reading -- bulk (|Idc| >= 10 A, Iac > 15 A) or hold (0.5 <= |Idc|
     < 3.5 A, Iac > 5 A) -- and EVERY second between first and last frame counts
     in the denominator, so a silent second lowers the rate instead of
     vanishing from it.
  3  INFLUXDB point rate, same classes and the same denominator rule, from the
     powertrain series bounded by each session's upload_manifest window.
"""
import sys
sys.path.insert(0, ".")
import base64
import glob
import json
import multiprocessing as mp
import os
import subprocess
import urllib.parse
import urllib.request

import cantools
from canre.parsers import parse_file

PHASES = {1, 2, 3}
ART = "projects/vtrux/notes/artifacts/"
FILT = ART + "msgrate_filtered/"
OUT2 = ART + "hold_msgrate_raw.json"
SESS = {
    "another_M0": "projects/vtrux/logs/after-battery-swap-charges/another_M0_T*.log",
    "charge_M0": "projects/vtrux/logs/after-battery-swap-charges/charge_M0_T*.log",
    "full-charge-then-fail": "projects/vtrux/logs/full-charge-then-fail.log",
    "vtrux_20260503_192242": "../../CANLogs/VtruxLogs/vtrux_20260503_192242_T*.log",
    "vtrux_20260726_191901": "../../CANLogs/VtruxLogs/vtrux_20260726_191901_T*.log",
    "vtrux_20260816_111915": "../../CANLogs/VtruxLogs/vtrux_20260816_111915_T*.log",
    "vtrux_20260912_192748": "../../CANLogs/VtruxLogs/vtrux_20260912_192748_T*.log",
    "vtrux_charge_M1": "projects/vtrux/logs/vtrux_charge_M1_T*.log",
    "vtrux_partstruck_charge": "projects/vtrux/logs/big-logs/vtrux_partstruck_charge.log",
    "vtruxchargeafterexportchargetest-80pctcv":
        "projects/vtrux/logs/vtruxchargeafterexportchargetest-80pctcv.log",
}
CHG, BMS = 0x18FFD7C0, 0x410


def cls(idc, iac):
    if idc is None or iac is None:
        return None
    a = abs(idc)
    if a >= 10 and iac > 15:
        return "bulk"
    if 0.5 <= a < 3.5 and iac > 5:
        return "hold"
    return None


def filt(job):
    src, dst = job
    with open(src, "rb") as f, open(dst, "wb") as o:
        for line in f:
            o.write(line)
            if line.startswith(b"***<Time>"):
                break
        o.flush()
        subprocess.run(["grep", "-aE", " 0x18FFD7C0 | 0x410 ", src], stdout=o)
    return dst


def raw_one(path):
    bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
    ids = {}
    frames = []
    for f in parse_file(path):
        ids.setdefault(f.bus, set()).add(f.arbitration_id)
        frames.append(f)
    pt = [b for b, s in ids.items() if CHG in s and BMS in s]
    out = []
    for b in pt:
        fr = sorted((f for f in frames if f.bus == b), key=lambda f: f.timestamp)
        t0, t1 = int(fr[0].timestamp), int(fr[-1].timestamp)
        cnt = {}
        state = {}
        idc = iac = None
        for f in fr:
            s = int(f.timestamp)
            c = cnt.setdefault(s, [0, 0])
            if f.arbitration_id == CHG:
                c[0] += 1
                d = bel.decode_message(CHG, f.data)
                if abs(d["BELINV_hvBatteryCurrent"]) < 100 and d["BELINV_chargerInputCurrent"] < 60:
                    idc, iac = d["BELINV_hvBatteryCurrent"], d["BELINV_chargerInputCurrent"]
            else:
                c[1] += 1
            state[s] = cls(idc, iac)
        agg = {"bulk": [0, 0, 0], "hold": [0, 0, 0]}
        cur = None
        for s in range(t0, t1 + 1):
            cur = state.get(s, cur)
            if cur in agg:
                c = cnt.get(s, [0, 0])
                agg[cur][0] += 1
                agg[cur][1] += c[0]
                agg[cur][2] += c[1]
        out.append(agg)
    return os.path.basename(path), out


def influx(q):
    url = "http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": "canbus-data", "q": q, "epoch": "ms", "chunked": "true",
         "chunk_size": "20000"})
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    rows, cols = [], None
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r.read().decode().splitlines():
            if line.strip():
                for res in json.loads(line).get("results", []):
                    for se in res.get("series", []):
                        cols = se["columns"]
                        rows.extend(se["values"])
    return cols, rows


def stored_window_s(session):
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % session)
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        if r["file"] not in newest or r["uploaded_at"] > newest[r["file"]]["uploaded_at"]:
            newest[r["file"]] = r
    return (min(r["t_start_ns"] for r in newest.values()) // 10**9,
            max(r["t_end_ns"] for r in newest.values()) // 10**9 + 1)


def fmt(agg):
    out = []
    for k in ("bulk", "hold"):
        n, a, b = agg[k]
        out.append("%s %6d s  chg %5.2f/s  bms %5.2f/s" % (k, n, a / n, b / n) if n
                   else "%s      0 s %30s" % (k, ""))
    return " | ".join(out)


if 1 in PHASES:
    os.makedirs(FILT, exist_ok=True)
    jobs = []
    for s, pat in SESS.items():
        for p in sorted(glob.glob(pat)):
            jobs.append((p, FILT + s + "__" + os.path.basename(p)))
    print("phase1: filtering %d files" % len(jobs), flush=True)
    with mp.get_context("fork").Pool(12) as pool:
        for _ in pool.imap_unordered(filt, jobs):
            pass

if 2 in PHASES:
    files = sorted(glob.glob(FILT + "*.log"))
    res = {}
    with mp.get_context("fork").Pool(12) as pool:
        for name, out in pool.imap_unordered(raw_one, files):
            res[name] = out
    with open(OUT2, "w") as f:
        json.dump(res, f)
else:
    res = json.load(open(OUT2))

print("\nphase2: RAW frames per second, powertrain channel (both ids present)")
for s in SESS:
    agg = {"bulk": [0, 0, 0], "hold": [0, 0, 0]}
    nch = 0
    for name, out in res.items():
        if name.startswith(s + "__"):
            for a in out:
                nch += 1
                for k in agg:
                    agg[k] = [x + y for x, y in zip(agg[k], a[k])]
    print("  %-42s ch-files %3d | %s" % (s, nch, fmt(agg)))

if 3 in PHASES:
    print("\nphase3: INFLUXDB points per second (on change + 1 s heartbeat), powertrain")
    for s in SESS:
        w0, w1 = stored_window_s(s)
        cols, rows = influx(
            "SELECT \"BELINV_hvBatteryCurrent\", \"BELINV_chargerInputCurrent\", "
            "\"bcm_ibat\", \"bcm_vbat\" FROM signals WHERE vehicle='vtrux' AND "
            "session='%s' AND bus='powertrain' AND time >= %ds AND time < %ds"
            % (s, w0, w1))
        rows.sort(key=lambda r: r[0])
        ix = {c: i for i, c in enumerate(cols)}
        cnt, state = {}, {}
        idc = iac = None
        for r in rows:
            t = r[0] // 1000
            c = cnt.setdefault(t, [0, 0, 0, 0])
            if r[ix["BELINV_hvBatteryCurrent"]] is not None:
                c[0] += 1
                idc = r[ix["BELINV_hvBatteryCurrent"]]
            if r[ix["BELINV_chargerInputCurrent"]] is not None:
                c[1] += 1
                iac = r[ix["BELINV_chargerInputCurrent"]]
            if r[ix["bcm_ibat"]] is not None:
                c[2] += 1
            if r[ix["bcm_vbat"]] is not None:
                c[3] += 1
            state[t] = cls(idc, iac)
        agg = {"bulk": [0, 0, 0, 0, 0], "hold": [0, 0, 0, 0, 0]}
        cur = None
        for t in range(rows[0][0] // 1000, rows[-1][0] // 1000 + 1):
            cur = state.get(t, cur)
            if cur in agg:
                c = cnt.get(t, [0, 0, 0, 0])
                agg[cur] = [agg[cur][0] + 1] + [x + y for x, y in zip(agg[cur][1:], c)]
        line = []
        for k in ("bulk", "hold"):
            n = agg[k][0]
            line.append("%s %6d s Idc %4.2f Iac %4.2f ibat %4.2f vbat %4.2f /s"
                        % ((k, n) + tuple(x / n for x in agg[k][1:])) if n
                        else "%s 0 s" % k)
        print("  %-42s %s" % (s, " | ".join(line)), flush=True)
