#!/usr/bin/env python3
"""Keep InfluxDB in agreement with the local logs and the local DBCs.

InfluxDB and the DBCs are the only sources of truth. Notes and success-logs may
inform the diff but are never required for correctness -- the old
`upload_success.txt` files store Windows absolute paths and match nothing on
any other machine, which is why they are ignored entirely.

Two layers, each catching what the cheaper one cannot:

  L0  manifest   -- `upload_manifest` rows written by influx_upload. Cheap.
                    The ONLY layer that sees a scale/offset/bit-position change
                    where the signal name did not change.
  L1  data       -- `SELECT COUNT(*) ... GROUP BY bus,can_id` per session. The
                    non-null column set IS the uploaded signal set. Trusts
                    nothing; catches a lying or missing manifest, partial
                    uploads, and orphan series.

L1 alone cannot drive per-file repair: a session's field set is the UNION across
its chunks, so after repairing 1 of 4 chunks it reports the message as current
while three are stale. Per-file staleness is only knowable from the manifest's
per-file `msg_hashes`. (Measured in Phase 1.2; see tools/plans/influx-sync.md.)

Discovery is NON-RECURSIVE by design. Specialised folders -- one-off
experiments, other people's vehicles, giant single captures -- must be opted
into explicitly, so nothing sweeps into the database by accident.

Usage:
    python3.13 tools/influx_sync.py --plan
    python3.13 tools/influx_sync.py --plan --out work.ndjson
    python3.13 tools/influx_sync.py --apply
    python3.13 tools/influx_sync.py --apply --from work.ndjson
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import tools.influx_upload as iu
from canre.dbc.msghash import message_hashes
from canre.utils.merge import detect_capture_sessions
from canre.utils.timebase import read_data_bounds

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Scope. Roots are scanned NON-RECURSIVELY; a subfolder is included only by
# naming it here. Rationale: `projects/vtrux/logs` alone holds 5 subfolders of
# specialised captures (another owner's truck, a single 6.2 GB file, one-off
# experiment sets). Recursive discovery would sweep 295 files / 16.0 GB into
# the database that nobody asked for, and would put a third party's name into a
# session tag.
# --------------------------------------------------------------------------

ROOTS = [
    {"path": "projects/vtrux/logs",     "vehicle": "vtrux"},
    {"path": "projects/coda/logs",      "vehicle": "coda"},
    {"path": "../../CANLogs/VtruxLogs", "vehicle": "vtrux"},
    {"path": "../../CANLogs/CodaLogs",  "vehicle": "coda"},
]

# Add a subfolder here to bring it in scope, e.g.
#   {"path": "projects/vtrux/logs/after-battery-swap-charges", "vehicle": "vtrux"},
OPT_IN_SUBFOLDERS: list[dict] = []

# Hard deny-list, checked even when a path is named explicitly on the command
# line. Truck 3 is a fellow owner's vehicle: it is a different physical
# truck from the main and parts trucks, and he is a third party covered by the
# privacy scrub in git-publish.md, so his name must never reach a session tag.
EXCLUDE_PATHS = [
    "projects/vtrux/logs/truck3-logs",
]

LOG_EXTS = {".log", ".asc", ".trc", ".csv"}
# 989 files in the corpus contain no data rows at all -- header only. Uploading
# them creates empty sessions and manifest noise. Tested by size plus the
# presence of a parseable data line, which is two cheap reads; counting frames
# would mean parsing every file just to plan.
MIN_LOG_BYTES = 2048

HOST, PORT, DB = "localhost", 8086, "canbus-data"
AUTH = ("<influx-user>", "<influx-password>")


# --------------------------------------------------------------------------
# InfluxDB access
# --------------------------------------------------------------------------

def q(query, post=False, timeout=600):
    fn = requests.post if post else requests.get
    kw = {"data": {"db": DB, "q": query}} if post else {"params": {"db": DB, "q": query}}
    r = fn(f"http://{HOST}:{PORT}/query", auth=AUTH, timeout=timeout, **kw)
    r.raise_for_status()
    body = r.json()
    for res in body.get("results", []):
        if "error" in res:
            raise RuntimeError(f"{query!r} -> {res['error']}")
    return body


def esc(v: str) -> str:
    """Escape a value for an InfluxQL single-quoted string literal."""
    return v.replace("\\", "\\\\").replace("'", "\\'")


def load_manifest() -> dict:
    """-> {(vehicle, file_basename): newest row}"""
    try:
        res = q("SELECT * FROM upload_manifest")
    except RuntimeError:
        return {}
    s = res["results"][0].get("series")
    if not s:
        return {}
    cols = s[0]["columns"]
    latest = {}
    for v in s[0]["values"]:
        row = dict(zip(cols, v))
        key = (row["vehicle"], row["file"])
        prev = latest.get(key)
        # Re-uploads append a new row; the newest wins.
        if prev is None or row["uploaded_at"] > prev["uploaded_at"]:
            latest[key] = row
    return latest


def l1_sessions() -> set:
    try:
        res = q('SHOW TAG VALUES FROM signals WITH KEY = "session"')
    except RuntimeError:
        return set()
    s = res["results"][0].get("series")
    return {v[1] for v in s[0]["values"]} if s else set()


def session_vehicles() -> dict:
    """-> {session: vehicle}, one cheap SHOW per vehicle.

    Avoids probing every session against every vehicle, which doubled the
    already-expensive L1 scan.
    """
    out = {}
    for vehicle in iu.VEHICLE_PROFILES:
        try:
            res = q(f'SHOW TAG VALUES FROM signals WITH KEY = "session" '
                    f"WHERE vehicle='{esc(vehicle)}'")
        except RuntimeError:
            continue
        s = res["results"][0].get("series")
        if s:
            for v in s[0]["values"]:
                out[v[1]] = vehicle
    return out


def l1_view(vehicle, session) -> dict:
    res = q(f"SELECT COUNT(*) FROM signals WHERE vehicle='{esc(vehicle)}' "
            f"AND session='{esc(session)}' GROUP BY bus,can_id")
    out = {}
    for g in res["results"][0].get("series", []):
        counts = {c[6:]: v for c, v in zip(g["columns"], g["values"][0])
                  if c.startswith("count_") and v is not None}
        out[(g["tags"]["bus"], g["tags"]["can_id"])] = counts
    return out


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def is_excluded(path: Path) -> bool:
    rp = path.resolve()
    for ex in EXCLUDE_PATHS:
        exr = (PROJECT_ROOT / ex).resolve()
        if rp == exr or exr in rp.parents:
            return True
    return False


def discover(extra_roots=None) -> list:
    """-> [(vehicle, Path), ...] from the configured roots, non-recursively."""
    out = []
    seen = set()
    for entry in ROOTS + OPT_IN_SUBFOLDERS + list(extra_roots or []):
        root = (PROJECT_ROOT / entry["path"]).resolve()
        if not root.is_dir():
            print(f"  warning: root not found: {entry['path']}", file=sys.stderr)
            continue
        for p in sorted(root.iterdir()):
            if not p.is_file() or p.suffix.lower() not in LOG_EXTS:
                continue
            if is_excluded(p) or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            out.append((entry["vehicle"], p))
    return out


def has_enough_frames(path: Path) -> bool:
    """Cheap emptiness test: a file with no data rows has no bounds."""
    b = read_data_bounds(path)
    if b is None:
        return False
    return path.stat().st_size > MIN_LOG_BYTES


def session_keys(vehicle, paths) -> dict:
    """-> {Path: session_tag} using the library's capture grouping.

    `detect_capture_sessions()` groups by each chunk's actual start time rather
    than by filename, so `_M{n}` groups that are separate sessions stay
    separate, chunks land in time order, and one prefix spanning unrelated
    captures splits. Its keys are used verbatim as session tags -- per capture,
    which is the agreed granularity.
    """
    if not paths:
        return {}
    try:
        groups = detect_capture_sessions(paths)
    except Exception as exc:
        print(f"  warning: session grouping failed ({exc}); "
              f"falling back to per-file", file=sys.stderr)
        return {p: p.stem for p in paths}
    out = {}
    for key, members in groups.items():
        for m in members:
            out[Path(m)] = key
    for p in paths:
        out.setdefault(p, p.stem)
    return out


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

def current_hashes(vehicle) -> dict:
    profile = iu.VEHICLE_PROFILES[vehicle]
    eg, ebs, ei, ebi = iu.build_exclude_sets(profile.get("exclude", []), [])
    return message_hashes(iu.load_databases(profile["dbcs"]),
                          [b for b, _ in profile["bus_anchors"]],
                          exclude_global=eg, exclude_bus_signal=ebs,
                          exclude_id=ei, exclude_bus_id=ebi)


def current_policy(vehicle, on_change=True, heartbeat=1.0) -> str:
    profile = iu.VEHICLE_PROFILES[vehicle]
    return iu.policy_hash(profile.get("exclude", []), [], on_change,
                          heartbeat, False, None)


def build_plan(args) -> list:
    manifest = load_manifest()
    live = l1_sessions()
    print(f"manifest rows: {len(manifest)}    sessions live in InfluxDB: {len(live)}")

    files = discover()
    print(f"discovered {len(files)} file(s) across "
          f"{len(ROOTS) + len(OPT_IN_SUBFOLDERS)} root(s), non-recursive")

    by_vehicle = defaultdict(list)
    for vehicle, p in files:
        by_vehicle[vehicle].append(p)

    work = []
    skipped_empty = 0
    for vehicle, paths in sorted(by_vehicle.items()):
        hashes = current_hashes(vehicle)
        pol = current_policy(vehicle)
        keep = []
        for p in paths:
            if has_enough_frames(p):
                keep.append(p)
            else:
                skipped_empty += 1
        smap = session_keys(vehicle, keep)

        # group by session so the uploader gets one --session per invocation
        per_session = defaultdict(list)
        for p in keep:
            per_session[smap[p]].append(p)

        for session, members in sorted(per_session.items()):
            new_files, reup_files = [], []
            id_repairs = defaultdict(list)   # can_id -> [(file, t0, t1)]
            for p in sorted(members):
                row = manifest.get((vehicle, p.name))
                st = p.stat()
                if row is None:
                    new_files.append(p)
                    continue
                if (row.get("encoding_ver") != iu.ENCODING_VER
                        or row.get("policy_hash") != pol
                        or row.get("log_bytes") != st.st_size):
                    reup_files.append(p)
                    continue
                claimed = json.loads(row.get("msg_hashes") or "{}")
                drift = [k for k, h in claimed.items()
                         if hashes.get(tuple(k.split("|"))) != h]
                for k in drift:
                    _bus, cid = k.split("|")
                    id_repairs[cid].append(
                        (p, row["t_start_ns"], row["t_end_ns"]))

            if new_files:
                work.append({"action": "upload_new", "vehicle": vehicle,
                             "session": session,
                             "files": [str(f) for f in new_files],
                             "reason": "not_in_manifest"})
            if reup_files:
                work.append({"action": "reupload_file", "vehicle": vehicle,
                             "session": session,
                             "files": [str(f) for f in reup_files],
                             "reason": "encoding/policy/size changed"})
            for cid, entries in sorted(id_repairs.items()):
                work.append({"action": "reupload_ids", "vehicle": vehicle,
                             "session": session, "can_ids": [cid],
                             "files": [str(f) for f, _a, _b in entries],
                             "windows": [[a, b] for _f, a, b in entries],
                             "reason": "msg_hash_mismatch"})

    # L1 is OPT-IN (--check-existing). It costs one full-session COUNT(*) per
    # session -- 212 of them against the current database, tens of minutes,
    # because COUNT(*) scans every point in the session. The filesystem+manifest
    # plan above needs none of that, and for a wipe-and-rebuild the answer is
    # discarded anyway. Run it when auditing data that is meant to be current.
    if args.check_existing:
        vehicles = session_vehicles()
        print(f"L1: scanning {len(vehicles)} session(s) "
              f"(one COUNT(*) each -- this is the slow path)")
        for n, (session, vehicle) in enumerate(sorted(vehicles.items()), 1):
            print(f"  [{n}/{len(vehicles)}] {vehicle} {session}", flush=True)
            try:
                view = l1_view(vehicle, session)
            except RuntimeError:
                continue
            if not view:
                continue
            hashes = current_hashes(vehicle)
            orphans = [f"{b}|{c}" for (b, c) in view if (b, c) not in hashes]
            legacy = [f"{b}|{c}" for (b, c), f in view.items() if "value" in f]
            if orphans:
                work.append({"action": "drop_series", "vehicle": vehicle,
                             "session": session, "keys": sorted(orphans),
                             "reason": "not_defined_by_current_dbc_or_excluded"})
            if legacy:
                work.append({"action": "rebuild_session", "vehicle": vehicle,
                             "session": session,
                             "reason": "legacy_signal_tag_schema"})

    if skipped_empty:
        print(f"skipped {skipped_empty} file(s) with no usable data "
              f"(header-only or under {MIN_LOG_BYTES} bytes)")
    return work


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

def run_upload(vehicle, session, files, only_ids=None, extra=()):
    cmd = [sys.executable, str(PROJECT_ROOT / "tools/influx_upload.py"),
           *[str(f) for f in files], "--vehicle", vehicle,
           "--session", session, *extra]
    if only_ids:
        cmd += ["--only-id", *only_ids]
    print(f"    $ influx_upload {len(files)} file(s) --session {session}"
          + (f" --only-id {' '.join(only_ids)}" if only_ids else ""))
    r = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"upload failed for session {session}")


def apply_plan(work, args):
    for i, item in enumerate(work, 1):
        act = item["action"]
        print(f"\n[{i}/{len(work)}] {act}  {item.get('session', '')}")
        if act in ("upload_new", "reupload_file"):
            run_upload(item["vehicle"], item["session"], item["files"])
        elif act == "reupload_ids":
            cid = item["can_ids"][0]
            for path, (t0, t1) in zip(item["files"], item["windows"]):
                # Delete by the RECORDED window, then verify it removed
                # something. A silent zero-row delete turns the repair into an
                # append -- the failure mode the Phase 1.2 slice hit.
                before = q(f"SELECT COUNT(*) FROM signals WHERE "
                           f"vehicle='{esc(item['vehicle'])}' AND "
                           f"session='{esc(item['session'])}' AND "
                           f"can_id='{cid}' AND time >= {t0} AND time <= {t1}")
                n_before = sum(
                    v for c, v in zip(before["results"][0]["series"][0]["columns"],
                                      before["results"][0]["series"][0]["values"][0])
                    if c.startswith("count_") and v is not None
                ) if before["results"][0].get("series") else 0
                q(f"DELETE FROM signals WHERE vehicle='{esc(item['vehicle'])}' "
                  f"AND session='{esc(item['session'])}' AND can_id='{cid}' "
                  f"AND time >= {t0} AND time <= {t1}", post=True)
                if n_before == 0:
                    raise RuntimeError(
                        f"refusing to repair {cid} in {Path(path).name}: the "
                        f"recorded window {t0}..{t1} matched no data. The "
                        f"manifest and the stored data disagree; re-upload the "
                        f"whole file instead.")
                print(f"    deleted {n_before:,} values for {cid} "
                      f"in {Path(path).name}")
                run_upload(item["vehicle"], item["session"], [path],
                           only_ids=[cid])
        elif act == "drop_series":
            for key in item["keys"]:
                bus, cid = key.split("|")
                q(f"DROP SERIES FROM signals WHERE "
                  f"vehicle='{esc(item['vehicle'])}' AND "
                  f"session='{esc(item['session'])}' AND bus='{bus}' "
                  f"AND can_id='{cid}'", post=True)
                print(f"    dropped {key}")
        elif act == "rebuild_session":
            print("    (rebuild_session is reported, not executed -- it is "
                  "subsumed by the Phase 4 wipe)")
        else:
            print(f"    unknown action, skipped")


# --------------------------------------------------------------------------

def summarize(work):
    by_action = defaultdict(lambda: {"items": 0, "files": 0, "bytes": 0})
    sessions = set()
    for w in work:
        a = by_action[w["action"]]
        a["items"] += 1
        for f in w.get("files", []):
            a["files"] += 1
            try:
                a["bytes"] += Path(f).stat().st_size
            except OSError:
                pass
        sessions.add(w.get("session"))
    print(f"\n{'action':<18}{'items':>8}{'files':>8}{'GB':>9}")
    for k, v in sorted(by_action.items()):
        print(f"{k:<18}{v['items']:>8}{v['files']:>8}{v['bytes']/1e9:>9.2f}")
    print(f"{'TOTAL':<18}{len(work):>8}"
          f"{sum(v['files'] for v in by_action.values()):>8}"
          f"{sum(v['bytes'] for v in by_action.values())/1e9:>9.2f}")
    print(f"sessions touched: {len(sessions)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="compute and print the work list")
    g.add_argument("--apply", action="store_true", help="compute and execute")
    ap.add_argument("--out", metavar="FILE", help="write the plan as NDJSON")
    ap.add_argument("--from", dest="from_file", metavar="FILE",
                    help="apply a previously written plan instead of recomputing")
    ap.add_argument("--limit", type=int, help="only act on the first N work items")
    ap.add_argument("--check-existing", action="store_true",
                    help="also run the L1 data-derived scan over sessions already in "
                         "InfluxDB, to find orphan series and legacy-schema data. Costs "
                         "one full-session COUNT(*) per session (tens of minutes on the "
                         "current database) and is pointless before a wipe-and-rebuild.")
    args = ap.parse_args()

    if args.from_file:
        work = [json.loads(l) for l in Path(args.from_file).read_text().splitlines() if l.strip()]
        print(f"loaded {len(work)} work item(s) from {args.from_file}")
    else:
        work = build_plan(args)

    if args.limit:
        work = work[:args.limit]

    summarize(work)

    if args.out:
        Path(args.out).write_text("".join(json.dumps(w) + "\n" for w in work))
        print(f"wrote {args.out}")

    if args.apply:
        if not work:
            print("\nnothing to do")
            return
        apply_plan(work, args)
        print("\nDone.")


if __name__ == "__main__":
    main()
