"""Reference fixture for the :tpms detector port (Coda TPMS plan Step 5).

Replays `tpms_app_prototype.run()` -- the executable spec -- over the corpus
epoch file the prototype's phase 1 writes, under a grid of settings, and saves
what it reported so `TpmsDetectorParityTest` can demand the Kotlin port
reproduce it exactly.

Writes into the :tpms test resources, so the parity test runs on every build
with no environment variable:

    detector_parity/epoch.jsonl     copy of the prototype's corpus epoch file
    detector_parity/expected.json   per settings case: events, final level,
                                    baseline drive count, and the full per-drive
                                    history (DEL psi and outlier corner psi)

Re-run after the corpus CSV or the prototype changes. Runs from the reverse-it root, because it imports the TPMS prototype from
`projects/coda/notes/artifacts/` there:

    cd "$REVERSE_IT_DIR" && <python> <clone>/tools/tpms_detector_parity.py

It reads the prototype's existing output file and never writes into the
algorithm session's artifacts folder.
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/coda/notes/artifacts")
import glob
import json
import os
import shutil

import tpms_app_prototype as proto
from pathlib import Path

CLONE = Path(__file__).resolve().parent.parent

SRC_GLOB = "projects/coda/notes/artifacts/tpms_proto_*.jsonl"
OUT = str(CLONE / "CanLoggerApps/tpms/src/test/resources/detector_parity")


def cases():
    yield "default", proto.Settings()
    yield "step_off", proto.Settings(step_psi=999.0)
    for k in (2, 3, 5, 8):
        for m in (3, 5, 10):
            yield "K%d_M%d" % (k, m), proto.Settings(learn_drives=k, window_drives=m)
    yield "confirm1", proto.Settings(confirm_drives=1)
    yield "confirm3", proto.Settings(confirm_drives=3)
    yield "floor400", proto.Settings(min_samples=400)
    yield "floor1600", proto.Settings(min_samples=1600)
    yield "step_win5", proto.Settings(step_window=5)
    yield "tight", proto.Settings(advise_psi=1.5, advise_clear_psi=1.0,
                                  warn_psi=2.5, warn_clear_psi=2.0)
    # The corpus has no sudden loss, so the default 6 psi fast path never fires on it. These
    # lower thresholds make it fire, so its port is exercised on real drives too.
    yield "fast3", proto.Settings(fast_warn_psi=3.0)
    yield "fast4_floor1600", proto.Settings(fast_warn_psi=4.0, fast_min_samples=1600)
    yield "fast2_step_off", proto.Settings(fast_warn_psi=2.0, step_psi=999.0)


def main():
    src = sorted(glob.glob(SRC_GLOB))
    if len(src) != 1:
        raise SystemExit("expected exactly one prototype epoch file, found %r" % src)
    src = src[0]
    cal, drives = proto.read_file(src)
    if not drives:
        raise SystemExit("prototype epoch file has no drives: %s" % src)

    os.makedirs(OUT, exist_ok=True)
    shutil.copyfile(src, os.path.join(OUT, "epoch.jsonl"))

    out = {"source": os.path.basename(src), "drives": len(drives), "cases": []}
    for name, s in cases():
        st, events = proto.run(cal, drives, s, verbose=False)
        out["cases"].append({
            "name": name,
            "settings": {
                "learnDrives": s.learn_drives, "learnMinSamples": s.learn_min_samples,
                "windowDrives": s.window_drives, "minSamples": s.min_samples,
                "warnPsi": s.warn_psi, "advisePsi": s.advise_psi,
                "warnClearPsi": s.warn_clear_psi, "adviseClearPsi": s.advise_clear_psi,
                "confirmDrives": s.confirm_drives, "stepPsi": s.step_psi,
                "stepWindow": s.step_window,
                "fastWarnPsi": s.fast_warn_psi, "fastMinSamples": s.fast_min_samples,
            },
            "level": st.level,
            "baseline_drives": st.baseline.drives,
            "events": [{"ts": ts, "kind": kind, "detail": detail}
                       for ts, kind, detail in events],
            "history": [{"ts": ts, "del": dp, "dev": dev}
                        for ts, dp, dev in st.history],
        })
        print("%-10s %-7s %2d events, %3d history rows"
              % (name, st.level, len(events), len(st.history)))

    with open(os.path.join(OUT, "expected.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("wrote %s (%d drives from %s)" % (OUT, len(drives), os.path.basename(src)))


if __name__ == "__main__":
    main()
