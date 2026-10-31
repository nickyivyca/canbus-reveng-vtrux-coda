"""Anchor DISCOVERY for the Vtrux buses -- can the unattributable channels be named?

WHY THIS EXISTS. The rule adopted 2026-10-04 is that a channel matching no
anchor set must not be uploaded to InfluxDB at all: `ch<N>` is an admission the
bus is unknown, the number is dongle insertion order, and a bus-scoped
`exclude` entry cannot match it, so such a channel uploads gateway-bridged
copies that the same frames would have had excluded under a named bus.

Applied to Vtrux as it stands, that rule would stop uploading SEVEN channels
holding 332,082 frames (tools/artifacts/unidentified_channel_census.py):

    vtruxextensioncabletest                 ch1   86,469   21% of file  19 ids
    vtruxwoodwardbconnectordisconnected     ch1   58,764   50% of file  50 ids
    vtrux_partstruck_chargeagain3           ch1   46,743   21% of file  17 ids
    vtruxoverflowrecoverytest{,3,4}         ch2  ~42,000   47% of file  19 ids
    vtruxunpluggingchargehandleendofcharge  ch3   13,940   21% of file  19 ids

Those are not noise. The Woodward channel carries 50 distinct GMLAN ids
(0x0C9, 0x0C1, 0x0C5, 0x1C3, 0x3E9, 0x4C1, 0x1F5 ...) and half the file's
traffic, and `vtruxextensioncabletest` shows three real buses at once: ch3
powertrain, ch2 obd, and ch1 an 86k-frame bus matching nothing.

AND LOOK AT WHAT THE FILES ARE. woodward-b-connector-DISCONNECTED,
extension-cable-test, overflow-recovery-test, unplugging-charge-handle. These
are disconnect experiments, and `powertrain` has exactly ONE anchor, 0x051. A
capture loses its only identifying message precisely BECAUSE the test
disconnected the thing emitting it. So the channels most likely to be discarded
are the ones the experiments were run to capture -- including
`vtrux_partstruck_chargeagain3`, which influx_sync's OPT_IN_SUBFOLDERS was
extended to cover for the charge-termination work.

The answer is to ATTRIBUTE them, not discard them: find ids that are exclusive
to one Vtrux bus and common enough to anchor on, exactly as
projects/coda/notes/artifacts/anchor_discovery_audit.py did for Coda, where
b_can went from 2 anchors to 18 and the unattributable population collapsed.

THE CIRCULARITY, AND A WEAKNESS THIS VERSION HAS THAT CODA'S DID NOT.
Candidates are scored only against channels identified at FULL anchor strength
-- every published anchor of that bus present -- so nothing being measured can
influence the label it is scored against. On Coda that meant 26, 5 and 2 ids.
On Vtrux `powertrain` full strength is ONE id, which is a thin basis for a
training label, so two extra conditions apply:

  * the channel must match exactly one bus's anchor set, as on Coda; and
  * MIN_TRAIN_FRAMES, below which a channel does not train at all, so a handful
    of stray frames carrying 0x051 cannot define what powertrain looks like.

If 0x051 is itself bridged, it will show up here as non-exclusive and the
powertrain column should be distrusted wholesale -- the profile claims it is
exclusive and fires at 100 Hz, and that claim has never been audited either.

PRESENCE IS NOT THE TEST. A gateway bridges frame for frame, so a real copy
shows a near-even split; stray traffic is a fraction of a percent. A verdict
needs BOTH a real share AND more than a handful of frames -- the Coda version's
first run called c_can 0x00C a rebroadcast on a 50.00 % split of two frames
against two, which is the exact defect the 2026-09-29 Coda audit was written to
fix, committed by the script auditing for it.

Nothing is written and no profile is changed: the output is a proposal to be
reviewed, and on Vtrux it also decides whether 332k frames are attributable or
genuinely have to go.
"""

import sys
sys.path.insert(0, ".")

import glob
import multiprocessing as mp
import os
import re
from collections import Counter, defaultdict

from canre.parsers import parse_file
import tools.influx_upload as iu

ROOTS = ["<home>/Seafile/CANLogs/VtruxLogs", "projects/vtrux/logs"]
WORKERS = max(1, (os.cpu_count() or 8) - 4)

# The published sets as they stand BEFORE this audit. Pinned rather than read
# from the live profile: if the profile is later expanded from these findings,
# pointing at it would silently re-base the training population on the very
# sets this audit produced, and a re-run would measure something else while
# looking identical.
ANCHORS = [
    ("powertrain", {0x051}),
    ("vehicle",    {0x1E5, 0x500}),
    ("obd",        {0x040, 0x041, 0x042, 0x043, 0x044}),
]

MIN_MINORITY_SHARE = 0.05
MIN_MINORITY_FRAMES = 20
MIN_TRAIN_FRAMES = 1000


def sessions():
    groups = defaultdict(list)
    for root in ROOTS:
        for p in sorted(glob.glob(os.path.join(root, "*.log"))):
            stem = os.path.basename(p)[:-4]
            m = re.match(r"^(.*)_T\d+$", stem)
            groups[m.group(1) if m else stem].append(p)
    return sorted(groups.items())


def one_session(job):
    name, paths = job
    try:
        per_ch = defaultdict(Counter)
        for p in paths:
            for f in parse_file(p):
                per_ch[f.bus][f.arbitration_id] += 1
    except Exception as exc:
        return (name, None, f"{type(exc).__name__}: {exc}")

    labelled = {}
    for ch, counts in per_ch.items():
        if sum(counts.values()) < MIN_TRAIN_FRAMES:
            continue
        ids = set(counts)
        full = [bus for bus, anch in ANCHORS if anch <= ids]
        if len(full) != 1:
            continue
        bus = full[0]
        if bus in labelled and sum(counts.values()) <= sum(labelled[bus].values()):
            continue
        labelled[bus] = counts
    return (name, {b: dict(c) for b, c in labelled.items()}, None)


def main():
    jobs = sessions()
    print(f"sessions: {len(jobs)}   workers: {WORKERS}")
    print(f"training requires: exactly one full anchor set AND "
          f">= {MIN_TRAIN_FRAMES} frames", flush=True)

    tally = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    bus_sessions = Counter()
    worst_minority = defaultdict(float)
    worst_detail = {}
    strays = Counter()
    n_ok = n_err = used = 0

    with mp.Pool(WORKERS) as pool:
        for i, (name, labelled, err) in enumerate(
                pool.imap_unordered(one_session, jobs, chunksize=1), 1):
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
            if err is not None:
                n_err += 1
                continue
            n_ok += 1
            if not labelled:
                continue
            used += 1
            for bus in labelled:
                bus_sessions[bus] += 1
            for bus, counts in labelled.items():
                for cid, n in counts.items():
                    tally[cid][bus][0] += 1
                    tally[cid][bus][1] += n
            if len(labelled) >= 2:
                allids = set().union(*(set(c) for c in labelled.values()))
                for cid in allids:
                    nz = {b: labelled[b].get(cid, 0) for b in labelled}
                    nz = {b: v for b, v in nz.items() if v}
                    if len(nz) < 2:
                        continue
                    minority = min(nz.values())
                    share = minority / sum(nz.values())
                    if minority < MIN_MINORITY_FRAMES:
                        strays[cid] += minority
                        continue
                    if share > worst_minority[cid]:
                        worst_minority[cid] = share
                        worst_detail[cid] = (name, dict(nz))

    print(f"\nsessions parsed ok: {n_ok}   errors: {n_err}")
    print(f"sessions contributing a training channel: {used}")
    print("sessions per identified bus: " +
          "  ".join(f"{b}={bus_sessions[b]}" for b, _ in ANCHORS))
    print()

    published = {b: a for b, a in ANCHORS}
    rows = []
    for cid, buses in tally.items():
        present = {b: v for b, v in buses.items() if v[1] > 0}
        share = worst_minority.get(cid, 0.0)
        if share >= MIN_MINORITY_SHARE:
            continue
        bus = max(present, key=lambda b: present[b][1])
        sess, frames = present[bus]
        cov = sess / bus_sessions[bus] if bus_sessions[bus] else 0.0
        rows.append((bus, cov, sess, frames, cid, share, strays.get(cid, 0)))

    print(f"EXCLUSIVE: no session shows a second copy of >= "
          f"{MIN_MINORITY_FRAMES} frames at >= {MIN_MINORITY_SHARE:.0%} share.")
    print("'stray' totals frames seen on any OTHER bus, all below that floor.")
    print("Sorted by bus then coverage. '*' = already a published anchor.\n")
    print(f"{'bus':11s} {'id':6s} {'cov':>7s} {'sess':>5s} {'frames':>10s} "
          f"{'worst_min':>10s} {'stray':>7s}  published")
    for bus, cov, sess, frames, cid, share, stray in sorted(
            rows, key=lambda r: (r[0], -r[1], r[4])):
        star = "*" if cid in published[bus] else ""
        print(f"{bus:11s} 0x{cid:03X} {cov:7.3f} {sess:5d} {frames:10d} "
              f"{share:10.4f} {stray:7d}  {star}")

    print("\nNOT exclusive -- a real second copy somewhere (bridged):\n")
    print(f"{'id':6s} {'worst_min':>10s}  session / split")
    for cid, s in sorted(((c, s) for c, s in worst_minority.items()
                          if s >= MIN_MINORITY_SHARE), key=lambda r: -r[1]):
        name, nz = worst_detail[cid]
        print(f"0x{cid:03X} {s:10.4f}  {name}  "
              + " ".join(f"{b}:{v}" for b, v in sorted(nz.items())))

    print("\nPublished anchors that did NOT come out exclusive here:")
    ok = {(b, c) for b, _cv, _s, _f, c, _sh, _st in rows}
    any_bad = False
    for bus, anch in ANCHORS:
        missing = sorted(c for c in anch if (bus, c) not in ok)
        if missing:
            any_bad = True
            print(f"  {bus}: " + " ".join(f"0x{c:03X}" for c in missing))
    if not any_bad:
        print("  (none -- every published anchor confirmed)")
    print("\nIf 0x051 appears above, the powertrain column of this whole report "
          "rests on a bridged id and must not be used.")


if __name__ == "__main__":
    main()
