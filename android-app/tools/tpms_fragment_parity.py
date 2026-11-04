"""Parity: the app's fragment store (TpmsEpochStore) against the prototype's FragmentStore.

Both read the same copy of the live store folder, then both add the same drive row -- which on a
legacy (schema 1) folder is the automatic migration: the first write is a `_full` carrying the
whole epoch. Compares the epoch as read (calibration, every row) and the fragment each one writes.

Runs from the reverse-it root, because it imports the TPMS prototype from
`projects/coda/notes/artifacts/` there:
    cd "$REVERSE_IT_DIR" && <python> <clone>/tools/tpms_fragment_parity.py

Needs JAVA_HOME and ANDROID_HOME set for Gradle (values per machine: the clone's local-paths.md).

Phases: 1 prepare the work folder, 2 prototype, 3 app (Gradle, env-gated TpmsStoreParityTest),
4 compare. The work folder is deleted at the end unless --keep.
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/coda/notes/artifacts")

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import tpms_app_prototype as proto

CLONE = Path(__file__).resolve().parent.parent

SRC = "../../CANLogs/CodaLogs/tpms"
# Regenerable scratch: outside Seafile and the clone.
WORK = os.path.join(tempfile.gettempdir(), "android-canbus-apps", "fragment_parity")


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def records(path):
    recs, _ = proto.read_fragment(path)
    return [clean(r) for r in recs]


def newest(folder):
    return sorted(f for f in os.listdir(folder) if f.endswith(".jsonl"))[-1]


def main():
    # ---- phase 1: work folder -----------------------------------------------------------------
    for var in ("JAVA_HOME", "ANDROID_HOME"):
        if not os.environ.get(var):
            raise SystemExit("set %s first (see the clone's local-paths.md)" % var)
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(os.path.join(WORK, "in"))
    for e in os.scandir(SRC):                      # scandir does not hydrate; copy only the store
        if e.is_file() and e.name.endswith(".jsonl"):
            shutil.copy(e.path, os.path.join(WORK, "in", e.name))
    print("input: %s" % sorted(os.listdir(os.path.join(WORK, "in"))))

    # ---- phase 2: prototype -------------------------------------------------------------------
    py_dir = os.path.join(WORK, "py_store")
    shutil.copytree(os.path.join(WORK, "in"), py_dir)
    st = proto.FragmentStore(py_dir)
    cal, rows = st.read_epoch()
    row = dict(clean(rows[-1]))
    row.update(log="coda_20990101_000000_T0.log", ts="20990101T000000", partial=False)
    with open(os.path.join(WORK, "row.json"), "w", encoding="utf-8") as fh:
        json.dump(row, fh)
    py_read = {"key": cal["ts"], "psi": cal["psi"], "temp_c": cal["temp_c"],
               "rows": [clean(r) for r in rows]}
    st.add_drive(dict(row))

    # ---- phase 3: app -------------------------------------------------------------------------
    env = dict(os.environ, TPMS_PARITY_DIR=WORK)
    env["PATH"] = os.path.join(env["JAVA_HOME"], "bin") + os.pathsep + env["PATH"]
    apps = CLONE / "CanLoggerApps"
    gradlew = apps / ("gradlew.bat" if os.name == "nt" else "gradlew")
    r = subprocess.run([str(gradlew), "-p", str(apps),
                        ":tpms:testDebugUnitTest", "--tests", "*TpmsStoreParityTest*", "--rerun-tasks",
                        "--console=plain"], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("gradle failed")
    with open(os.path.join(WORK, "kotlin_read.json"), encoding="utf-8") as fh:
        kt_read = json.load(fh)

    # ---- phase 4: compare ---------------------------------------------------------------------
    bad = 0

    def check(what, a, b):
        nonlocal bad
        ok = a == b
        bad += not ok
        print("  %-44s %s" % (what, "same" if ok else "DIFFERENT"))
        if not ok:
            print("    prototype: %s\n    app:       %s" % (str(a)[:300], str(b)[:300]))

    print("epoch as read:")
    check("epoch key", py_read["key"], kt_read["key"])
    check("psi", {k: float(v) for k, v in py_read["psi"].items()},
          {k: round(v, 3) for k, v in kt_read["psi"].items()})
    check("temp_c", float(py_read["temp_c"]), round(kt_read["temp_c"], 3))
    check("row count", len(py_read["rows"]), len(kt_read["rows"]))
    check("rows, field by field", py_read["rows"], kt_read["rows"])
    gps_py = sum(1 for x in py_read["rows"] if x.get("gps"))
    gps_kt = sum(1 for x in kt_read["rows"] if x.get("gps"))
    check("rows carrying a GPS block (%d)" % gps_py, gps_py, gps_kt)
    print("  unparseable lines dropped by the app: %d" % kt_read["skipped"])

    print("after adding one row (the migration's first write):")
    kt_dir = os.path.join(WORK, "kotlin_store")
    fp, fk = newest(py_dir), newest(kt_dir)
    check("new fragment name", fp, fk)
    a, b = records(os.path.join(py_dir, fp)), records(os.path.join(kt_dir, fk))
    check("record types", [x["type"] for x in a], [x["type"] for x in b])
    check("records, field by field", a, b)

    print("\n%s" % ("PARITY OK" if bad == 0 else "%d DIFFERENCE(S)" % bad))
    if "--keep" not in sys.argv:
        shutil.rmtree(WORK, ignore_errors=True)
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
