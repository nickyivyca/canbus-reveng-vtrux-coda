"""Cross-check of the powertrain anchor candidates from anchor_discovery_audit.py.

Raised 2026-10-30 at step 4 of the internal `can-replay-readers` plan (owner: evaluate other
Vtrux powertrain anchors before canbench's resolver goes strict; powertrain has one
anchor, 0x051, so a >= 2 distinct-anchor rule would name no powertrain channel).

WHAT THE AUDIT CANNOT SEE. anchor_discovery_audit.py measures a frame split only in
sessions where powertrain AND another bus were both identified at full strength, and
reports each id under the bus carrying most of its traffic. So an id that is present on
an identified OBD or Vehicle channel in OTHER sessions, or on channels nobody identified
(a charger-end segment behind the interposer, a disconnect test's leftover bus, a replay
merged onto one channel), is invisible to it. This script measures exactly that, for
the candidates the audit called exclusive with powertrain coverage >= MIN_COVERAGE.

Training labels are the audit's own, unchanged (pinned sets, >= 1000 frames, exactly one
full set), imported from it so the two cannot drift.

Phases (default: all):
  scan     one corpus pass -> pt_anchor_crosscheck.jsonl (per session, per channel: label,
           frames, adapters, candidate-id counts, 0x051 present, other-bus anchor hits)
  report   -> pt_anchor_crosscheck.txt: per candidate, sessions / frames on identified
           vehicle and obd channels and on unidentified channels; the co-identified
           opportunity count; unidentified channels carrying candidates; the
           quarantined unidentified-bus files

Run from the reverse-it root on the Linux box:
  python3.13 projects/vtrux/notes/artifacts/pt_anchor_crosscheck.py [scan] [report]
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/vtrux/notes/artifacts")

import json
import multiprocessing as mp
import re
from collections import Counter, defaultdict
from pathlib import Path

from canre.parsers import parse_file
import anchor_discovery_audit as audit

ART = Path("projects/vtrux/notes/artifacts")
AUDIT_OUT = ART / "anchor_discovery_audit.out.txt"
JSONL = ART / "pt_anchor_crosscheck.jsonl"
REPORT = ART / "pt_anchor_crosscheck.txt"
QUARANTINE = Path("projects/vtrux/logs/unidentified-bus")
MIN_COVERAGE = 0.9
CHAN = re.compile(r"^\*\*\*CHANNEL\s+(\d+)\s+-\s+(.*?)\s+-")


def candidates():
    """Powertrain ids the audit called exclusive at coverage >= MIN_COVERAGE."""
    out = set()
    for line in AUDIT_OUT.read_text().splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == "powertrain" and f[1].startswith("0x"):
            if float(f[2]) >= MIN_COVERAGE:
                out.add(int(f[1], 16))
    return out


CANDS = candidates()


def adapters(paths):
    seen = {}
    for p in paths:
        try:
            with open(p, errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 40:
                        break
                    m = CHAN.match(line)
                    if m:
                        seen.setdefault(m[1], m[2])
        except OSError:
            pass
    return seen


def one_session(job):
    name, paths = job
    try:
        per_ch = defaultdict(Counter)
        for p in paths:
            for f in parse_file(p):
                per_ch[f.bus][f.arbitration_id] += 1
    except Exception as exc:
        return {"session": name, "error": f"{type(exc).__name__}: {exc}"}
    labels = {}
    for ch, counts in per_ch.items():
        if sum(counts.values()) < audit.MIN_TRAIN_FRAMES:
            continue
        full = [b for b, a in audit.ANCHORS if a <= set(counts)]
        if len(full) == 1:
            labels[ch] = full[0]
    # The audit keeps one channel per bus (the busiest); others of that bus are churn.
    keep = {}
    for ch, b in labels.items():
        if b not in keep or sum(per_ch[ch].values()) > sum(per_ch[keep[b]].values()):
            keep[b] = ch
    ad = adapters(paths)
    chans = []
    for ch, counts in per_ch.items():
        lab = labels.get(ch)
        chans.append({
            "ch": ch,
            "label": lab,
            "train": lab is not None and keep.get(lab) == ch,
            "frames": sum(counts.values()),
            "n_ids": len(counts),
            "adapter": ad.get(str(ch), "?"),
            "has051": counts.get(0x051, 0),
            "other_full": [b for b, a in audit.ANCHORS if a & set(counts) and b != "powertrain"],
            "cands": {f"{i:X}": n for i, n in counts.items() if i in CANDS},
        })
    return {"session": name, "paths": paths, "chans": chans}


def phase_scan():
    jobs = audit.sessions()
    qs = sorted(str(p) for p in QUARANTINE.glob("*.log"))
    jobs += [(f"QUARANTINE:{Path(p).stem}", [p]) for p in qs]
    print(f"sessions {len(jobs)} (incl. {len(qs)} quarantined files), candidates {len(CANDS)}",
          flush=True)
    with mp.Pool(audit.WORKERS) as pool, JSONL.open("w") as out:
        for i, row in enumerate(pool.imap_unordered(one_session, jobs, chunksize=1), 1):
            out.write(json.dumps(row) + "\n")
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)


def phase_report():
    rows = [json.loads(l) for l in JSONL.open()]
    lines = []
    w = lines.append
    errs = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    quar = [r for r in rows if r["session"].startswith("QUARANTINE:")]
    rows = [r for r in rows if not r["session"].startswith("QUARANTINE:")]
    w(f"sessions {len(rows)} (+{len(quar)} quarantined files), parse errors {len(errs)}; "
      f"candidates {len(CANDS)} (audit powertrain coverage >= {MIN_COVERAGE})")

    co = sum(1 for r in rows
             if {c["label"] for c in r["chans"] if c["label"]} >= {"powertrain"}
             and len({c["label"] for c in r["chans"] if c["label"]}) >= 2)
    w(f"sessions with powertrain AND another bus identified (the audit's only chance to see "
      f"a split): {co}")

    # where[cid][place] = [sessions, frames]
    where = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    unl = []
    for r in rows:
        for c in r["chans"]:
            place = c["label"] or ("unidentified, has 0x051" if c["has051"]
                                   else "unidentified, no 0x051")
            for h, n in c["cands"].items():
                where[int(h, 16)][place][0] += 1
                where[int(h, 16)][place][1] += n
            if not c["label"] and c["cands"]:
                unl.append((len(c["cands"]), r["session"], c))
    places = ["powertrain", "vehicle", "obd", "unidentified, has 0x051", "unidentified, no 0x051"]
    w("")
    w("per candidate: sessions/frames by where it was seen (all channels, not only training)")
    w(f"{'id':>10s}  " + "  ".join(f"{p[:24]:>24s}" for p in places))
    for cid in sorted(CANDS):
        w(f"{cid:>#10x}  " + "  ".join(
            f"{where[cid][p][0]:>8d} / {where[cid][p][1]:>13d}" for p in places))

    w("")
    w("unidentified channels carrying candidates, most candidates first (top 60)")
    for k, sess, c in sorted(unl, key=lambda t: (-t[0], t[1]))[:60]:
        w(f"  {k:3d} cands  {sess}  ch{c['ch']} [{c['adapter']}] frames={c['frames']} "
          f"ids={c['n_ids']} 0x051={c['has051']} other-bus anchors={c['other_full']}")

    w("")
    w("quarantined unidentified-bus files: every channel")
    for r in sorted(quar, key=lambda r: r["session"]):
        for c in sorted(r["chans"], key=lambda c: c["ch"]):
            w(f"  {r['session'][11:]}  ch{c['ch']} [{c['adapter']}] label={c['label']} "
              f"frames={c['frames']} ids={c['n_ids']} 0x051={c['has051']} "
              f"cands={len(c['cands'])} other-bus anchors={c['other_full']}")
    for r in errs:
        w(f"  ERROR {r['session']}: {r['error']}")
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:80]))


if __name__ == "__main__":
    phases = sys.argv[1:] or ["scan", "report"]
    for ph in phases:
        {"scan": phase_scan, "report": phase_report}[ph]()
