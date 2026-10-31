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
per-file `msg_hashes`. (Measured in Phase 1.2; see the internal `influx-sync` plan.)

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
OPT_IN_SUBFOLDERS: list[dict] = [
    # Brought in scope 2026-09-12 for the charge-termination characterisation.
    # Discovery is non-recursive, so these sat outside the corpus entirely --
    # and they hold exactly the three cases the question needs: the part-truck
    # full charge on a badly imbalanced pack, the failed charges, and the
    # post-battery-swap full charges. The termination survey run before they
    # were added saw 44 charging sessions and only one evap-80 among them.
    {"path": "projects/vtrux/logs/big-logs", "vehicle": "vtrux"},
    {"path": "projects/vtrux/logs/actual-failed-charges", "vehicle": "vtrux"},
    {"path": "projects/vtrux/logs/after-battery-swap-charges", "vehicle": "vtrux"},
]

# Hard deny-list, checked even when a path is named explicitly on the command
# line. Truck 3 is a fellow owner's vehicle: it is a different physical
# truck from the main and parts trucks, and he is a third party covered by the
# privacy scrub in git-publish.md, so his name must never reach a session tag.
EXCLUDE_PATHS = [
    "projects/vtrux/logs/truck3-logs",
    # Parts-truck chunk kept under its capture name only because the gen-inhibit
    # firmware replay suite names it. The same file is uploaded as
    # partsdrive_20260802_T0.log (moved and renamed 2026-10-21, user decision);
    # the old session tag vtrux_20260802_123318 was deleted from InfluxDB.
    "projects/vtrux/logs/vtrux_20260802_123318_T0.log",
    # Bench replays of generator-on-then-off.log recorded by the :vtrux app, not
    # drives (quarantined 2026-10-30, user decision; the rest of both evenings is in
    # android-app/notes/artifacts/vtrux_bench_replay_captures/). These two copies
    # stay here because the gen-inhibit host harness and spec name them; their
    # sessions were deleted from InfluxDB the same day.
    "projects/vtrux/logs/vtrux_20260322_165622_T1.log",
    "projects/vtrux/logs/vtrux_20260403_194203_T2.log",
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


def load_manifest_history() -> dict:
    """-> {(vehicle, file_basename): [rows oldest-first]}

    `load_manifest()` keeps only the newest row per file, which is right for
    every staleness test that asks "what does this file look like now". The
    bus-label test needs the opposite: what this file was uploaded AS before.
    """
    try:
        res = q("SELECT * FROM upload_manifest")
    except RuntimeError:
        return {}
    s = res["results"][0].get("series")
    if not s:
        return {}
    cols = s[0]["columns"]
    hist = defaultdict(list)
    for v in s[0]["values"]:
        row = dict(zip(cols, v))
        hist[(row["vehicle"], row["file"])].append(row)
    for rows in hist.values():
        rows.sort(key=lambda r: r["uploaded_at"])
    return dict(hist)


def stale_points_in_window(vehicle, session, bus, t0, t1) -> int:
    """Field-values stored under `bus` inside [t0, t1] for this session.

    Split out of label_drift_work so the overlap and convergence tests can
    drive it without a database.
    """
    try:
        res = q(f"SELECT COUNT(*) FROM signals WHERE "
                f"vehicle='{esc(vehicle)}' AND session='{esc(session)}' "
                f"AND bus='{esc(bus)}' AND time >= {t0} AND time <= {t1}")
    except RuntimeError:
        return 0
    ser = res["results"][0].get("series")
    if not ser:
        return 0
    return int(sum(v for c, v in zip(ser[0]["columns"], ser[0]["values"][0])
                   if c.startswith("count_") and v is not None))


def label_drift_work(history) -> list:
    """Series left behind when a file's BUS LABEL changed between uploads.

    This is the one kind of staleness the three sync keys are structurally
    blind to, and data-sources.md says so in general terms: file sha1, DBC
    message hashes and the policy hash are all functions of the bytes and the
    encoding, and a bus label is a function of neither. Re-uploading the file
    writes the frames under the NEW bus tag and leaves the old tag's points
    exactly where they were, so the same frames are then live under two bus
    names at once and every later run reports the file as current.

    Measured on 2026-10-04, when a new `min_anchor_hits` guard moved three
    tail chunks off bus labels that rested on a single anchor hit:

        coda_20260608_095955_T6   c_can -> ch1    211 field-values stranded
        coda_20260722_102259_T6   d_can -> ch1    141 field-values stranded
        coda_20260807_192700_T6   d_can -> ch1      0 (all ids d_can-excluded)

    The manifest already holds everything needed to find them -- each row
    records the `bus_map` that produced it -- so this costs one extra query and
    no parsing.

    THE WINDOW IS THE DANGEROUS PART. The repair must delete the old bus tag
    only within the file's own recorded window, and that is sound only while no
    other chunk of the session overlaps it; the Android logger can emit a T0
    spanning 24 h with later chunks nested inside it, and a delete on the wider
    window takes the nested chunks with it. Overlapping files are reported and
    NOT queued, for the same reason `overlapping_files()` exists on the id
    repair path.
    """
    # Every file's current window, per session -- the overlap test below needs
    # ALL of them, not just the drifting ones. A first version compared the
    # drifting files only against each other, which is the null-discriminator
    # shape again: with one drifting file per session there is nothing to
    # compare against, so the test passed vacuously and would have authorised a
    # windowed delete straight over whatever non-drifting chunk shared the
    # window.
    session_spans = defaultdict(list)
    for (vehicle, fname), rows in history.items():
        latest = rows[-1]
        t0, t1 = latest.get("t_start_ns"), latest.get("t_end_ns")
        if t0 is None or t1 is None:
            continue
        session_spans[(vehicle, latest["session"])].append(
            (int(t0), int(t1), fname))

    by_session = defaultdict(list)
    for (vehicle, fname), rows in history.items():
        latest = rows[-1]
        try:
            now_map = json.loads(latest.get("bus_map") or "{}")
        except (ValueError, TypeError):
            continue
        current = {v for v in now_map.values() if v}
        was = set()
        for r in rows[:-1]:
            try:
                was |= {v for v in (json.loads(r.get("bus_map") or "{}")
                                    ).values() if v}
            except (ValueError, TypeError):
                continue
        stale = was - current
        if not stale:
            continue
        t0, t1 = latest.get("t_start_ns"), latest.get("t_end_ns")
        if t0 is None or t1 is None:
            continue
        by_session[(vehicle, latest["session"])].append(
            (fname, sorted(stale), int(t0), int(t1)))

    out = []
    for (vehicle, session), entries in sorted(by_session.items()):
        spans = session_spans.get((vehicle, session), [])
        overlapped = set()
        for fname, _stale, t0, t1 in entries:
            for b0, b1, bf in spans:
                if bf == fname:
                    continue
                if b0 <= t1 and t0 <= b1:
                    overlapped.add(fname)
                    break
        for fname, stale, t0, t1 in sorted(entries):
            # The manifest finds CANDIDATES; the data decides. A bus_map
            # history is append-only, so a label change is a permanent fact
            # about the file and repairing it does not alter the record --
            # emitting on the history alone makes the item re-fire on every
            # run forever, repaired or not. That is the same never-converging
            # loop as the `upload_new` captures and the `ch<N>` hash drift,
            # built fresh. Observed immediately after the first --apply: all
            # three items came straight back, two of them printing "nothing to
            # do".
            #
            # So confirm there is actually something to delete. Only the few
            # drifting files are queried, which is why this is affordable
            # outside --check-existing.
            present = [b for b in stale
                       if stale_points_in_window(vehicle, session, b, t0, t1)]
            if not present:
                continue
            out.append({"action": ("report_label_drift" if fname in overlapped
                                   else "drop_label_window"),
                        "vehicle": vehicle, "session": session,
                        "file": fname, "keys": present,
                        "windows": [[t0, t1]],
                        "reason": ("bus_label_changed_but_windows_overlap"
                                   if fname in overlapped
                                   else "bus_label_changed_since_upload")})
    return out


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
                          heartbeat, False, None,
                          profile.get("min_anchor_hits"))


def overlapping_files(id_repairs) -> set:
    """Files whose recorded windows overlap another file's, per can_id.

    `reupload_ids` deletes a can_id across each file's window before re-writing
    it, which is only safe while the windows are disjoint. The Android logger
    can emit a T0 spanning 24 h with the later chunks nested inside it, and then
    repairing T0 deletes the nested chunks' points as collateral. Callers route
    the files named here to a whole-file re-upload instead.

    Takes {can_id: [(file, t_start_ns, t_end_ns), ...]}; returns the set of
    files involved in any overlap.
    """
    overlapped = set()
    for entries in id_repairs.values():
        spans = sorted((a, b, f) for f, a, b in entries)
        for (_a0, a1, fa), (b0, _b1, fb) in zip(spans, spans[1:]):
            # Strictly greater: consecutive chunks normally share a boundary
            # instant (T0 ends exactly where T1 begins), which is the ordinary
            # shape here and must not be treated as overlap -- doing so would
            # send almost every multi-chunk session down the whole-file path.
            # At worst a shared instant costs one point, and both files carry
            # the same can_id so they drift together and are repaired in the
            # same item anyway.
            if b0 < a1:
                overlapped.update({fa, fb})
    return overlapped


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

        # Messages the DBCs define now that NO upload has ever recorded.
        #
        # The drift check below walks `claimed` -- the hashes a file recorded at
        # upload time -- so it can only ever notice a message whose definition
        # CHANGED. A message ADDED to a DBC afterwards appears in no row's
        # claimed set, is therefore never compared, and stays missing from
        # InfluxDB forever however often the sync is run. That is how
        # 0x18EFC000 (VCU_ChargerCmd, the charger mode/flow command) came to be
        # absent from all 564 vtrux sessions while --plan reported nothing to
        # do: every Bel charger message was present, the one the VCU sends was
        # not, and no amount of syncing would have fixed it.
        #
        # "Never recorded anywhere" is the usable signal: a message that is
        # genuinely in the captures would have been decoded by some earlier
        # upload, so its absence across the whole manifest means it is new.
        #
        # "Defined but never recorded" alone is NOT enough to call a message
        # new: the GMLAN DBC defines hundreds of standard GM messages this
        # truck never sends, and they are equally absent from every manifest.
        # Treating those as additions queued 33,625 backfills over 10.6 TB on
        # the first attempt. Distinguishing a genuinely new definition from a
        # never-present one needs a record of which ids each capture actually
        # contains, which the manifest does not keep -- so the ids to backfill
        # are named explicitly with --backfill-id, and "never recorded
        # anywhere" is used only to skip ones already present.
        # Note this is deliberately NOT filtered against known_anywhere. That
        # set is global to the vehicle, so as soon as ONE file had been
        # backfilled it contained the id and every remaining file silently
        # dropped out of the plan -- 248 sessions collapsed to zero after a
        # single-session test. Whether a file still needs the id is a property
        # of that file's own manifest row, and is checked below.
        wanted = set(getattr(args, "backfill_id", None) or [])
        added_keys = sorted(k for k in ("%s|%s" % (b, c) for b, c in hashes)
                            if k.split("|")[1] in wanted)
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
            backfills = defaultdict(set)     # can_id -> {file}
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
                # Normalise "no definition" before comparing. A message on an
                # unidentified channel -- `ch<N>`, the fallback bus name when a
                # channel matches no anchor set -- is stored with an empty hash,
                # while current_hashes() only carries the named buses and so
                # returns None for it. Comparing those two directly made every
                # such file drift on every run and never converge no matter how
                # often it was repaired: the 7 vtrux ch1 sessions and the 3 coda
                # ch2 fragments were stuck in exactly this loop. Nothing is
                # decoded for those keys either way, so there is nothing to
                # repair.
                drift = [k for k, h in claimed.items()
                         if (hashes.get(tuple(k.split("|"))) or "") != (h or "")]

                # Newly defined messages: backfill rather than repair. There is
                # nothing stored to delete, and reupload_ids refuses a delete
                # that matches no rows (correctly -- for a repair that means the
                # manifest and the data disagree). Only offer buses this file
                # actually carries, so a powertrain-only message is not queued
                # against an OBD-only capture.
                try:
                    file_buses = set(json.loads(row.get("bus_map") or "{}").values())
                except (ValueError, TypeError):
                    file_buses = set()
                for k in added_keys:
                    bus, cid = k.split("|")
                    if k in claimed:
                        continue          # this file already has it
                    if file_buses and bus not in file_buses:
                        continue
                    # A set, not a list: one can_id is defined on every bus in
                    # the profile, so the same file arrives here once per bus
                    # and would otherwise be uploaded three times over.
                    backfills[cid].add(p)
                for k in drift:
                    _bus, cid = k.split("|")
                    id_repairs[cid].append(
                        (p, row["t_start_ns"], row["t_end_ns"]))

            if new_files:
                work.append({"action": "upload_new", "vehicle": vehicle,
                             "session": session,
                             "files": [str(f) for f in new_files],
                             "reason": "not_in_manifest"})
            # A per-id repair deletes the id across each file's recorded
            # window. That is only safe while the windows are disjoint. The
            # Android logger can emit a T0 spanning 24 h with later chunks
            # nested inside it (coda_20260508_191742: T0 = 24.00 h, T1 = 3.4 min
            # inside it), and then repairing T0 deletes T1's points too. Route
            # any session with overlapping windows to a whole-file re-upload,
            # which needs no window arithmetic.
            overlapped = overlapping_files(id_repairs)
            if overlapped:
                for cid in list(id_repairs):
                    id_repairs[cid] = [e for e in id_repairs[cid]
                                       if e[0] not in overlapped]
                    if not id_repairs[cid]:
                        del id_repairs[cid]
                for f in overlapped:
                    if f not in reup_files:
                        reup_files.append(f)

            if reup_files:
                work.append({"action": "reupload_file", "vehicle": vehicle,
                             "session": session,
                             "files": [str(f) for f in sorted(reup_files)],
                             "reason": ("overlapping chunk windows"
                                        if overlapped and not any(
                                            f not in overlapped for f in reup_files)
                                        else "encoding/policy/size changed")})
            for cid, bfiles in sorted(backfills.items()):
                work.append({"action": "backfill_ids", "vehicle": vehicle,
                             "session": session, "can_ids": [cid],
                             "files": [str(f) for f in sorted(bfiles)],
                             "reason": "message_added_to_dbc_since_upload"})
            for cid, entries in sorted(id_repairs.items()):
                work.append({"action": "reupload_ids", "vehicle": vehicle,
                             "session": session, "can_ids": [cid],
                             "files": [str(f) for f, _a, _b in entries],
                             "windows": [[a, b] for _f, a, b in entries],
                             "reason": "msg_hash_mismatch"})

    # Bus-label drift. Manifest-only, so it runs unconditionally alongside L0
    # rather than behind --check-existing.
    work.extend(label_drift_work(load_manifest_history()))

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

            # A series is an orphan only if NO definition could produce it AND
            # its bus is one the profile names. The second half is not a
            # refinement, it is the difference between a repair and data loss.
            #
            # `current_hashes()` is built over the named buses only, so no
            # `ch<N>` pair can ever be in it -- see the note beside
            # `is_unidentified_bus` in influx_upload. Testing membership alone
            # therefore condemns EVERY unidentified-channel series, which is
            # exactly what it did: 147 keys on 2026-10-04, 8 of them written
            # minutes earlier by the uploader itself and 70 of them vtrux
            # series holding 161,917 field-values that had nothing to do with
            # the work in hand. L0 had already learned this lesson at its
            # `drift` comparison; L1 never did, so the two layers disagreed
            # with each other and both disagreed with the producer.
            #
            # The unidentified case is REPORTED, not dropped. The data is real
            # -- frames were captured and decoded -- and what is missing is a
            # bus label, which dropping the series does not supply. Whether
            # those frames should have been uploaded at all is a question about
            # the anchor sets (see notes/artifacts/anchor_discovery_audit.py),
            # not something an orphan sweep can answer.
            orphans, unidentified = [], []
            for (b, c) in view:
                if (b, c) in hashes:
                    continue
                (unidentified if iu.is_unidentified_bus(b) else orphans).append(
                    f"{b}|{c}")
            legacy = [f"{b}|{c}" for (b, c), f in view.items() if "value" in f]
            if orphans:
                work.append({"action": "drop_series", "vehicle": vehicle,
                             "session": session, "keys": sorted(orphans),
                             "reason": "not_defined_by_current_dbc_or_excluded"})
            if unidentified:
                work.append({"action": "review_unidentified_bus",
                             "vehicle": vehicle, "session": session,
                             "keys": sorted(unidentified),
                             "reason": "channel_matched_no_anchor_set"})
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
        elif act == "backfill_ids":
            # No delete. The id was never uploaded for these files, so there is
            # nothing to remove and a DELETE would only risk taking out a
            # neighbouring window.
            cid = item["can_ids"][0]
            for path in item["files"]:
                print(f"    backfilling {cid} in {Path(path).name}")
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
        elif act == "drop_label_window":
            # Remove the OLD bus tag's points inside this file's own window.
            # Count first and skip a zero match rather than raising: unlike a
            # per-id repair, zero here means the stale label is already gone,
            # which is a clean state and not a manifest-vs-data disagreement.
            t0, t1 = item["windows"][0]
            for bus in item["keys"]:
                before = q(f"SELECT COUNT(*) FROM signals WHERE "
                           f"vehicle='{esc(item['vehicle'])}' AND "
                           f"session='{esc(item['session'])}' AND "
                           f"bus='{esc(bus)}' AND time >= {t0} AND time <= {t1}")
                ser = before["results"][0].get("series")
                n_before = sum(
                    v for c, v in zip(ser[0]["columns"], ser[0]["values"][0])
                    if c.startswith("count_") and v is not None
                ) if ser else 0
                if n_before == 0:
                    print(f"    {item['file']}: no stale {bus} points in "
                          f"window, nothing to do")
                    continue
                q(f"DELETE FROM signals WHERE "
                  f"vehicle='{esc(item['vehicle'])}' AND "
                  f"session='{esc(item['session'])}' AND bus='{esc(bus)}' "
                  f"AND time >= {t0} AND time <= {t1}", post=True)
                print(f"    {item['file']}: deleted {n_before:,} stale "
                      f"{bus} values in {t0}..{t1}")
        elif act == "report_label_drift":
            print(f"    (reported, not executed -- {item['file']} changed bus "
                  f"label off {' '.join(item['keys'])}, but its window "
                  f"overlaps another chunk of this session, so a windowed "
                  f"delete would take that chunk's data too)")
        elif act == "review_unidentified_bus":
            # Deliberately not executed. These series hold real decoded frames
            # whose BUS is unknown; there is nothing here to repair without a
            # decision about the anchor sets. Dropping them would be data loss
            # dressed as a repair, which is what L1 used to propose.
            print(f"    (reported, not executed -- {len(item['keys'])} "
                  f"series on unidentified channels: "
                  f"{' '.join(item['keys'][:8])}"
                  f"{' ...' if len(item['keys']) > 8 else ''})")
        elif act == "rebuild_session":
            print("    (rebuild_session is reported, not executed -- it is "
                  "subsumed by the Phase 4 wipe)")
        else:
            print(f"    unknown action, skipped")


# --------------------------------------------------------------------------

def summarize(work):
    # Count DISTINCT paths, not file references. Work items routinely share
    # source files -- one log feeds every id defined in it -- so summing per
    # reference multiplies the same bytes by however many items touch it. A
    # redundant plan once reported 10.6 TB against a 104 GB corpus, which read
    # as a storage problem rather than "reads the same file 29 times".
    by_action = defaultdict(lambda: {"items": 0, "files": set()})
    sessions = set()
    sizes = {}

    def size_of(f):
        if f not in sizes:
            try:
                sizes[f] = Path(f).stat().st_size
            except OSError:
                sizes[f] = 0
        return sizes[f]

    for w in work:
        a = by_action[w["action"]]
        a["items"] += 1
        a["files"].update(w.get("files", []))
        sessions.add(w.get("session"))

    all_files = set()
    for v in by_action.values():
        all_files |= v["files"]

    print(f"\n{'action':<18}{'items':>8}{'files':>8}{'GB':>9}")
    for k, v in sorted(by_action.items()):
        nbytes = sum(size_of(f) for f in v["files"])
        print(f"{k:<18}{v['items']:>8}{len(v['files']):>8}{nbytes/1e9:>9.2f}")
    print(f"{'TOTAL':<18}{len(work):>8}{len(all_files):>8}"
          f"{sum(size_of(f) for f in all_files)/1e9:>9.2f}")
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
    ap.add_argument("--backfill-id", nargs="+", metavar="ID",
                    help="CAN id(s) newly added to a DBC, to upload into "
                         "sessions that predate the definition (e.g. 0x18EFC000). "
                         "Drift detection cannot find these on its own: it "
                         "compares the hashes a file recorded at upload time, "
                         "so a message that did not exist then is never "
                         "examined. Backfill only ADDS points -- it never "
                         "deletes -- and records the id in the manifest "
                         "afterwards so it is not re-queued.")
    ap.add_argument("--check-existing", action="store_true",
                    help="also run the L1 data-derived scan over sessions already in "
                         "InfluxDB, to find orphan series and legacy-schema data. Costs "
                         "one full-session COUNT(*) per session (tens of minutes on the "
                         "current database) and is pointless before a wipe-and-rebuild.")
    args = ap.parse_args()

    if args.backfill_id:
        # Normalise to the "0xNNN" form the manifest and the can_id tag use.
        args.backfill_id = ["0x%03X" % (int(x, 0) & 0x1FFFFFFF)
                            for x in args.backfill_id]
        print("backfilling can id(s): %s" % ", ".join(args.backfill_id))

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
