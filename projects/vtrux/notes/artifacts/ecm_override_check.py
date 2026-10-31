"""Does the ECM ever override the VCM's throttle request? (outstanding-changes Change 9)

The VCM drives the ECM's accelerator input (APP GEN MOD); the ECM echoes it as
Accelerator_Actual_Position (0x0C9). This looks across the InfluxDB corpus,
OBD bus only, for the ECM doing something other than what that input asks for:

  phase 0  sessions with OBD APP data, and which of them ran the engine
  phase 1  Accelerator_Effective_Position (0x1C3) vs Accelerator_Actual_Position
  phase 2  Engine_Torque_Driver_Requested vs Engine_Torque_Actual (0x1C3), engine running;
           shortfalls > 30 Nm: all >= 0.5 s counted by length, >= 3 s listed
  phase 3  Engine_Torque_Reduction_Failure_Status (0x1C3) non-zero episodes
  phase 4  Throttle_Position (0x3D1) against APP while running: per APP band

Signals are forward-filled onto a 100 ms grid per session. InfluxDB stores on
change plus a 1 s heartbeat, so values are exact but durations are only as good
as the grid; no rates are inferred from point counts (data-sources.md).

Usage: python3.13 projects/vtrux/notes/artifacts/ecm_override_check.py [--phase N ...] [--session S ...]
"""
import sys

sys.path.insert(0, ".")

import argparse
import base64
import bisect
import json
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

INFLUX = "http://localhost:8086/query"
AUTH = base64.b64encode(b"claude:claude").decode()
DB = "canbus-data"
GRID_MS = 100

# Bench replays of generator-on-then-off.log made to test the :vtrux app, still in
# InfluxDB after their logs were quarantined (2026-10-30); copies of a real drive.
BENCH_REPLAYS = ["vtrux_20260322_165622", "vtrux_20260403_194203", "vtrux_20260403_202041",
                 "vtrux_20260403_205705", "vtrux_20260403_210944", "vtrux_20260403_211130",
                 "vtrux_20260403_212302", "vtrux_20260403_212731", "vtrux_20260403_215807",
                 "vtrux_20260403_225754"]

SIGS = {
    "0x0C9": ["Accelerator_Actual_Position", "Accelerator_Actual_Position_Validity",
              "Engine_Speed", "Engine_Run_Active", "Cruise_Control_Active"],
    "0x1C3": ["Accelerator_Effective_Position", "Accelerator_Effective_Position_Validity",
              "Engine_Torque_Actual_Extended_Range", "Engine_Torque_Driver_Requested_Extended_Range",
              "Engine_Torque_Reduction_Failure_Status"],
    "0x3D1": ["Throttle_Position", "Engine_Coast_Fuel_Cut_Off_Active"],
}


def q(query):
    url = INFLUX + "?" + urllib.parse.urlencode({"db": DB, "q": query, "epoch": "ms"})
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + AUTH})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())["results"][0]
    if "error" in res:
        raise RuntimeError(res["error"])
    return res.get("series", [])


def sessions_with_app():
    out = {}
    for s in q("SELECT count(\"Accelerator_Actual_Position\"), max(\"Accelerator_Actual_Position\"), "
               "max(\"Engine_Run_Active\") FROM signals WHERE vehicle='vtrux' AND bus='obd' "
               "AND can_id='0x0C9' GROUP BY session"):
        _, n, app_max, run_max = s["values"][0]
        out[s["tags"]["session"]] = (n, app_max, run_max)
    return out


def load_session(session):
    """Return {signal: (times, values)} for the OBD signals in SIGS."""
    data = {}
    for cid, names in SIGS.items():
        fields = ", ".join(f'"{n}"' for n in names)
        for s in q(f"SELECT {fields} FROM signals WHERE vehicle='vtrux' AND bus='obd' "
                   f"AND can_id='{cid}' AND session='{session}'"):
            cols = s["columns"]
            rows = sorted(s["values"], key=lambda r: r[0])
            for n in names:
                i = cols.index(n)
                pts = [(r[0], r[i]) for r in rows if r[i] is not None]
                data[n] = ([p[0] for p in pts], [p[1] for p in pts])
    return data


def grid(data, names):
    """Forward-filled samples of `names` on a 100 ms grid over the span where all exist."""
    if any(n not in data or not data[n][0] for n in names):
        return []
    t0 = max(data[n][0][0] for n in names)
    t1 = min(data[n][0][-1] for n in names)
    out = []
    t = t0
    while t <= t1:
        row = [t]
        for n in names:
            ts, vs = data[n]
            row.append(vs[bisect.bisect_right(ts, t) - 1])
        out.append(row)
        t += GRID_MS
    return out


def episodes(rows, pred, min_len=1):
    """Contiguous runs of grid rows where pred(row) holds: list of (start_row, end_row, n)."""
    eps, start = [], None
    for i, r in enumerate(rows):
        if pred(r):
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                eps.append((rows[start], rows[i - 1], i - start))
            start = None
    if start is not None and len(rows) - start >= min_len:
        eps.append((rows[start], rows[-1], len(rows) - start))
    return eps


def fmt_t(ms):
    import datetime
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, nargs="*", default=[0, 1, 2, 3, 4])
    ap.add_argument("--session", nargs="*")
    ap.add_argument("--exclude", nargs="*", default=BENCH_REPLAYS,
                    help="sessions to leave out (default: the bench replays of generator-on-then-off.log)")
    args = ap.parse_args()

    sess = sessions_with_app()
    running = sorted(s for s, (n, a, r) in sess.items() if r and r >= 1)
    if 0 in args.phase:
        print("=" * 78)
        print("PHASE 0 -- sessions with OBD 0x0C9 APP")
        print("=" * 78)
        print(f"sessions with APP: {len(sess)}; with Engine_Run_Active=1 at some point: {len(running)}; "
              f"with APP max > 5%: {sum(1 for v in sess.values() if v[1] and v[1] > 5)}")
    todo = args.session or [s for s in running if s not in set(args.exclude)]
    if 0 in args.phase:
        print(f"excluded: {sorted(set(args.exclude) & set(running))}; analysed: {len(todo)}")

    app_hist = Counter()
    diff_hist = Counter()
    diff_eps = []
    tq_eps = []
    tq_len_hist = Counter()
    tq_kind = Counter()
    red_eps = []
    tps_by_band = defaultdict(list)
    grid_rows_total = 0
    run_rows_total = 0
    for k, session in enumerate(todo):
        data = load_session(session)
        if 1 in args.phase:
            rows = grid(data, ["Accelerator_Actual_Position", "Accelerator_Effective_Position",
                               "Accelerator_Actual_Position_Validity", "Accelerator_Effective_Position_Validity",
                               "Engine_Run_Active", "Cruise_Control_Active"])
            grid_rows_total += len(rows)
            valid = [r for r in rows if not r[3] and not r[4]]
            for r in valid:
                diff_hist[round(r[2] - r[1], 1)] += 1
            for a, b, n in episodes(valid, lambda r: abs(r[2] - r[1]) > 2.5, min_len=3):
                diff_eps.append((session, a[0], b[0], n, a[1], a[2], a[5], a[6]))
        if 2 in args.phase or 4 in args.phase:
            rows = grid(data, ["Engine_Run_Active", "Accelerator_Actual_Position", "Engine_Speed",
                               "Engine_Torque_Driver_Requested_Extended_Range", "Engine_Torque_Actual_Extended_Range",
                               "Throttle_Position", "Engine_Coast_Fuel_Cut_Off_Active"])
            run = [r for r in rows if r[1] == 1]
            run_rows_total += len(run)
            for r in run:
                app_hist[int(r[2] // 5) * 5] += 1
                tps_by_band[int(r[2] // 5) * 5].append(r[6])
            if 2 in args.phase:
                for a, b, n in episodes(run, lambda r: r[4] - r[5] > 30 and r[2] > 5, min_len=5):
                    tq_len_hist[min(n * GRID_MS // 1000, 10)] += 1
                    i0 = run.index(a)
                    prev = run[max(0, i0 - 1000 // GRID_MS)]
                    tq_kind[(n >= 30, 'request rose > 20 Nm in the 1 s before' if a[4] - prev[4] > 20 else 'request steady or falling')] += 1
                    if n < 30:
                        continue
                    seg = [r for r in run if a[0] <= r[0] <= b[0]]
                    gap = max(r[4] - r[5] for r in seg)
                    tq_eps.append((session, a[0], b[0], n, a[2], a[3], a[4], a[5], gap,
                                   max(r[7] for r in seg)))
        if 3 in args.phase:
            ts, vs = data.get("Engine_Torque_Reduction_Failure_Status", ([], []))
            cur = None
            for t, v in zip(ts, vs):
                if v and cur is None:
                    cur = [t, t, v]
                elif v and cur is not None:
                    cur[1] = t
                elif not v and cur is not None:
                    red_eps.append((session, cur[0], t, cur[2]))
                    cur = None
            if cur is not None:
                red_eps.append((session, cur[0], cur[1], cur[2]))
        print(f"  [{k + 1}/{len(todo)}] {session}", file=sys.stderr)

    if 1 in args.phase:
        print("=" * 78)
        print("PHASE 1 -- Accelerator_Effective_Position - Accelerator_Actual_Position (both valid)")
        print("=" * 78)
        tot = sum(diff_hist.values())
        print(f"grid samples: {grid_rows_total}, both valid: {tot}")
        for d, n in sorted(diff_hist.items(), key=lambda kv: -kv[1])[:12]:
            print(f"  diff {d:+7.1f}%  {n:9d}  {100 * n / tot:7.3f}%")
        print(f"episodes |diff| > 2.5% for >= 0.3 s: {len(diff_eps)}")
        for e in sorted(diff_eps, key=lambda e: -e[3])[:25]:
            s, t0, t1, n, act, eff, run, cc = e
            print(f"  {s:30s} {fmt_t(t0)} {n * GRID_MS / 1000:6.1f}s  actual={act:5.1f} effective={eff:5.1f} "
                  f"run={run} cruise={cc}")

    if 2 in args.phase:
        print("=" * 78)
        print("PHASE 2 -- requested - actual engine torque > 30 Nm, running, APP > 5%")
        print("=" * 78)
        print(f"running grid samples: {run_rows_total}")
        print("episodes >= 0.5 s by whole seconds (10 = 10 s or more):", dict(sorted(tq_len_hist.items())))
        print("episodes >= 0.5 s, (>= 3 s?, what the request did first):", dict(tq_kind))
        print(f"episodes >= 3 s: {len(tq_eps)}")
        for e in sorted(tq_eps, key=lambda e: -e[3])[:30]:
            s, t0, t1, n, app, rpm, req, act, gap, dfco = e
            print(f"  {s:30s} {fmt_t(t0)} {n * GRID_MS / 1000:6.1f}s APP={app:5.1f} rpm={rpm:6.0f} "
                  f"req={req:6.1f} act={act:6.1f} maxgap={gap:6.1f} dfco={dfco}")

    if 3 in args.phase:
        print("=" * 78)
        print("PHASE 3 -- Engine_Torque_Reduction_Failure_Status non-zero")
        print("=" * 78)
        by_val = Counter(e[3] for e in red_eps)
        print(f"episodes: {len(red_eps)} by value {dict(by_val)}; sessions: {len({e[0] for e in red_eps})}")
        for e in red_eps[:30]:
            print(f"  {e[0]:30s} {fmt_t(e[1])} -> {fmt_t(e[2])} value={e[3]}")

    if 4 in args.phase:
        print("=" * 78)
        print("PHASE 4 -- Throttle_Position by APP band, engine running (grid samples)")
        print("=" * 78)
        for band in sorted(tps_by_band):
            v = sorted(tps_by_band[band])
            n = len(v)
            pc = lambda p: v[min(n - 1, int(p * n))]
            print(f"  APP {band:3d}-{band + 5:<3d} n={n:8d}  TPS p1={pc(0.01):5.1f} p10={pc(0.10):5.1f} "
                  f"p50={pc(0.5):5.1f} p90={pc(0.9):5.1f} p99={pc(0.99):5.1f}")


if __name__ == "__main__":
    main()
