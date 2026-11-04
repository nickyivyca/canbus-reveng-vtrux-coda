"""Reference values for WheelRatioParityTest (CanLoggerApps/tpms/src/test/...).

Runs the Python extract_one from projects/coda/notes/artifacts/tpms_wheel_ratio_trend.py
on a few real multi-segment Coda sessions and writes what it returns, plus the input
paths, to a JSON file. The Kotlin test reads that JSON, runs WheelRatioExtractor on the
same logs and compares.

This is a parity harness, not an analysis: it computes nothing of its own.

Usage. Runs from the reverse-it root, because it imports the TPMS prototype from
`projects/coda/notes/artifacts/` there:
    cd "$REVERSE_IT_DIR" && <python> <clone>/tools/tpms_ratio_parity.py [--v24] <out.json> [session ...]

Default is the pre-v24 ("legacy") rule set, for TPMS_PARITY_JSON. With --v24 it runs the tool's
v24 rule set and the output is for TPMS_PARITY_V24_JSON (same test class, Filters.V24).

Needs grep on PATH (extract_one pre-filters with it) and CC_SCRATCH pointing at a
writable scratch directory, which extract_one uses for its filtered copies.
Then run the JVM test with TPMS_PARITY_JSON=<out.json>.
"""
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "projects/coda/notes/artifacts")

if not os.environ.get("CC_SCRATCH"):
    raise SystemExit("set CC_SCRATCH to a writable scratch directory first")

import tpms_wheel_ratio_trend as T   # noqa: E402  (reads CC_SCRATCH at import)

# The corpus tool defaults to the v24 rule set since 2026-09-26, so the rule set is always pinned
# here explicitly, matching the Kotlin Filters the test uses for that file.
V24 = "--v24" in sys.argv
if V24:
    sys.argv.remove("--v24")
T.FSET = "v24" if V24 else "legacy"

CORPUS = "../../CANLogs/CodaLogs"
DEFAULT_SESSIONS = ["coda_20260618_195906", "coda_20260618_185031"]


def chunks(session):
    """T0.. in numeric order, found by probing names rather than listing the
    folder -- listing CANLogs from git-bash hydrates the whole library."""
    out, i = [], 0
    while True:
        p = os.path.join(CORPUS, "%s_T%d.log" % (session, i))
        if not os.path.exists(p):
            return out
        out.append(p)
        i += 1


def main():
    out_path = sys.argv[1]
    sessions = sys.argv[2:] or DEFAULT_SESSIONS
    result = {}
    for s in sessions:
        paths = chunks(s)
        # extract_one sorts nothing itself; find_sessions() sorts by name, which is
        # T0, T1, ... T10 lexically. Match that order exactly.
        paths_sorted = sorted(paths)
        row = T.extract_one((s, paths_sorted))
        print("%s: %d chunks -> %s" % (s, len(paths), "None" if row is None
                                         else "n=%d kmh=%.3f DEL=%.9f" % (row["n"], row["kmh"], row["DEL"])))
        result[s] = {"paths": [os.path.abspath(p) for p in paths_sorted], "row": row, "fset": T.FSET}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print("wrote %s" % out_path)


if __name__ == "__main__":
    main()
