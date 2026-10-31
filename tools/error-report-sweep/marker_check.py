"""Check canbench's inferred-error marker against the approved rule's predictions.

Step 3 of the internal `can-replay-readers` plan.  The marker under test is
canbench.parsers.inferred_errors in the can-tools git clone (branch
replay-readers), loaded ahead of the reverse-it mirror, which has no parsers.

Phases (run from the reverse-it root, on the Linux box):
  bench    the Android session's two pre-fix fault-matrix runs (build 31),
           2026-10-30: marked / unmarked counts per id against the IXXAT's
           sent counts (marks.json) and the session's report
  corpus   every capture in scan.jsonl whose Innomaker channels carry a
           0x004 / 0x00C / 0x024 DLC-8 standard frame: the marker's count per
           (channel, id) against the count the rule predicts from the scan's
           own pass / allzero / fail split (an independent hand-split reader)
  kvaser   step 4c: every capture in kvaser_id0_scan.jsonl whose header names a
           Kvaser: the marker's count per (channel, id) against the Kvaser rule's
           hits in that scan (kvaser_id0_sweep.py's own regex reader); any mark
           on an id other than 0x000 is a disagreement

    python3.13 tools/error-report-sweep/marker_check.py bench
    python3.13 tools/error-report-sweep/marker_check.py corpus
    python3.13 tools/error-report-sweep/marker_check.py kvaser
"""
import json
import os
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, ".")
CLONE = os.environ.get("CAN_TOOLS_DIR", str(Path.home() / "Git" / "can-tools"))
sys.path.insert(0, CLONE)

import canbench.parsers as cp                                   # noqa: E402
from canbench.parsers import parse_file                         # noqa: E402

assert Path(cp.__file__).resolve().is_relative_to(Path(CLONE).resolve()), cp.__file__

HERE = Path("tools/error-report-sweep/artifacts")
IDS = (0x004, 0x00C, 0x024)
BENCH = [Path("android-app/notes/artifacts/fault_matrix_20261030_prefix31"),
         Path("android-app/notes/artifacts/fault_matrix_20261030_prefix31_decoys")]


def phase_bench():
    for d in BENCH:
        log = next(d.glob("coda_*_T0.log"))
        c = Counter()
        for f in parse_file(log, mark_inferred_errors=True):
            if f.arbitration_id in IDS and not f.is_extended:
                kind = "allzero" if not any(f.data) else "nonzero"
                c[(f.arbitration_id, kind, "MARKED" if f.inferred_error else "data")] += 1
            elif f.inferred_error:
                c[(f.arbitration_id, "other-id", "MARKED")] += 1
        print(f"== {log}")
        for k in sorted(c):
            print(f"   0x{k[0]:03X} {k[1]:8s} {k[2]:7s} {c[k]}")
        marks = json.loads((d / "marks.json").read_text())
        sent = {k: v for k, v in marks.items() if "sent" in k or "decoy" in k}
        print(f"   marks.json sent/decoy keys: {json.dumps(sent)[:400]}")


def predicted(row):
    """Per (channel, id): the count the approved rule marks, from the scan."""
    if "Innomaker" not in row.get("adapter", "") or row.get("errs"):
        return {}
    out = {}
    for ch, i, st in row["stats"]:
        if i in IDS:
            out[(int(ch), i)] = st["pass"] + (st["allzero"] if st["fail"] == 0 else 0)
    return out


QUARANTINE = Path("android-app/notes/artifacts/vtrux_bench_replay_captures")


def current_path(path):
    """The scan predates the 2026-10-30 quarantine of the :vtrux bench-replay captures
    (moved out of CANLogs/VtruxLogs, see that folder's README): follow them there."""
    p = Path(path)
    if p.exists():
        return p
    moved = list(QUARANTINE.glob(f"*/{p.name}"))
    return moved[0] if len(moved) == 1 else p


def check_one(job):
    path, pred = job
    path = current_path(path)
    got = Counter()
    try:
        for f in parse_file(path, mark_inferred_errors=True):
            if f.inferred_error:
                got[(f.bus, f.arbitration_id)] += 1
    except Exception as e:                       # report, do not hide
        return path, pred, {"error": f"{type(e).__name__}: {e}"}
    return path, pred, dict(got)


def phase_corpus():
    jobs = []
    n_rows = 0
    with open(HERE / "scan.jsonl") as fh:
        for line in fh:
            row = json.loads(line)
            n_rows += 1
            if "error" in row:
                continue
            if not any(i in IDS for _, i, _ in row["stats"]):
                continue
            pred = {k: v for k, v in predicted(row).items()}
            jobs.append((row["path"], pred))
    print(f"scan rows {n_rows}; captures with a 0x004/0x00C/0x024 DLC-8 stream: {len(jobs)}")
    agree = disagree = 0
    tot_pred = tot_got = 0
    lines = []
    with Pool(12) as pool:
        for path, pred, got in pool.imap_unordered(check_one, jobs, chunksize=4):
            if "error" in got:
                disagree += 1
                lines.append(f"ERROR {path}: {got['error']}")
                continue
            p = {k: v for k, v in pred.items() if v}
            tot_pred += sum(p.values())
            tot_got += sum(got.values())
            if p == got:
                agree += 1
            else:
                disagree += 1
                lines.append(f"DIFF {path}: predicted {sorted(p.items())} got {sorted(got.items())}")
    print(f"agree {agree}, disagree {disagree}; frames predicted {tot_pred}, marked {tot_got}")
    for ln in sorted(lines)[:60]:
        print("  ", ln)


def predicted_kvaser(row):
    """Per (channel, 0x000): the Kvaser rule's hits on that channel, from the scan."""
    kv = {int(ch) for ch, a in row["adapters"].items() if "kvaser" in a.lower()}
    out = Counter()
    for key, rec in row["id0"].items():
        ch, typ, dlc, fm = key.split("|")
        if int(ch) in kv and typ == "s" and dlc == "4" and fm in ("count", "flags"):
            out[(int(ch), 0x000)] += rec["n"]
    return dict(out)


def phase_kvaser():
    jobs, n_rows, n_err = [], 0, 0
    with open(HERE / "kvaser_id0_scan.jsonl") as fh:
        for line in fh:
            row = json.loads(line)
            n_rows += 1
            if "error" in row:
                n_err += 1
                continue
            if any("kvaser" in a.lower() for a in row["adapters"].values()):
                jobs.append((row["path"], predicted_kvaser(row)))
    print(f"scan rows {n_rows} (read errors {n_err}); Kvaser-header captures: {len(jobs)}")
    agree = disagree = 0
    tot_pred = tot_got = 0
    lines = []
    with Pool(12) as pool:
        for path, pred, got in pool.imap_unordered(check_one, jobs, chunksize=4):
            if "error" in got:
                disagree += 1
                lines.append(f"ERROR {path}: {got['error']}")
                continue
            tot_pred += sum(pred.values())
            tot_got += sum(got.values())
            if pred == got:
                agree += 1
            else:
                disagree += 1
                lines.append(f"DIFF {path}: predicted {sorted(pred.items())} got {sorted(got.items())}")
    print(f"agree {agree}, disagree {disagree}; frames predicted {tot_pred}, marked {tot_got}")
    for ln in sorted(lines)[:60]:
        print("  ", ln)


if __name__ == "__main__":
    {"bench": phase_bench, "corpus": phase_corpus, "kvaser": phase_kvaser}[sys.argv[1]]()
