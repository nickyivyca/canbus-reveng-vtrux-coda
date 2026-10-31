"""Decode the diag frames the firmware actually emits, with cantools.

WHY. The firmware, `wican_diag_schema.md` and `vtrux-wican-diag.dbc` are three
hand-maintained descriptions of the same bytes, and nothing has ever checked
that they agree. `diag_schema_ver` catches a DECODER holding the wrong DBC; it
cannot catch a DBC that disagrees with the firmware at the same version, which
is the likelier mistake when all three are edited in one sitting.

This takes real emitted frames -- from the host runner, which builds them with
the same build_diag() the ESP32 runs -- and decodes them against the DBC. A
field at the wrong offset, a width that truncates, or a VAL_ table that has
drifted from the enum shows up as a wrong value rather than as nothing.

It is the first piece of review E3 ("decode emitted diag frames with
cantools"). Run on the Linux box, where the host suite builds:

  python3.13 projects/vtrux/notes/artifacts/gen-inhibit/diag_decode_check.py \\
      ~/gi_host/test/gen_inhibit_host
"""

import os
import subprocess
import sys

sys.path.insert(0, ".")

DBC = "projects/vtrux/vtrux-wican-diag.dbc"

# One scenario per mode worth sampling. PASSIVE is the point of schema 4, so it
# must be in here; INHIBIT is the comparison.
CASES = (
    ("INHIBIT", 3, "keyon-normal"),
    ("PASSIVE", 4, "keyon-normal"),
)

DIAG_IDS = (0x7F1, 0x7F2, 0x7F3, 0x7F4)


def run_scenario(host_dir, name, mode):
    path = os.path.join(host_dir, "scenarios", name + ".scn")
    text = open(path).read()
    if mode != 3:
        out = []
        for ln in text.splitlines():
            p = ln.split()
            if len(p) == 4 and p[0] == "mode" and p[2] == "3":
                out.append("mode %s %d %s" % (p[1], mode, p[3]))
            else:
                out.append(ln)
        text = "\n".join(out) + "\n"
    r = subprocess.run([os.path.join(host_dir, "host_runner")], input=text,
                       capture_output=True, text=True, cwd=host_dir)
    if r.returncode != 0:
        raise RuntimeError("runner exited %d" % r.returncode)
    return r.stdout


def diag_frames(trace):
    """(id, bytes) for every TX DIAG line."""
    out = []
    for ln in trace.splitlines():
        if " TX DIAG " not in ln:
            continue
        ident = data = None
        for tok in ln.split():
            if tok.startswith("id="):
                ident = int(tok[3:], 16)
            elif tok.startswith("data="):
                data = bytes.fromhex(tok[5:])
        if ident is not None and data is not None:
            out.append((ident, data))
    return out


def main():
    host_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/gi_host/test/gen_inhibit_host")
    import cantools
    db = cantools.database.load_file(DBC)
    print("DBC: %s" % db.version)

    bad = 0
    for label, mode, scenario in CASES:
        trace = run_scenario(host_dir, scenario, mode)
        frames = diag_frames(trace)
        seen = {}
        for ident, data in frames:
            seen.setdefault(ident, 0)
            seen[ident] += 1
            try:
                dec = db.decode_message(ident, data)
            except Exception as exc:                      # noqa: BLE001
                print("  [FAIL] %s 0x%03X %s: %s" % (label, ident, data.hex(), exc))
                bad += 1
                continue
            if ident == 0x7F1:
                if int(dec["diag_schema_ver"]) != 4:
                    print("  [FAIL] %s 0x7F1 schema_ver=%s, expected 4"
                          % (label, dec["diag_schema_ver"]))
                    bad += 1
                got = str(dec["diag_mode"])
                if got != label:
                    print("  [FAIL] %s 0x7F1 diag_mode decodes as %s" % (label, got))
                    bad += 1
            if ident == 0x7F4 and int(dec["diag_flags2"]) & 0x08:
                print("  [FAIL] %s 0x7F4 emit_refused set -- firmware bug" % label)
                bad += 1

        missing = [i for i in DIAG_IDS if i not in seen]
        print("  %-8s pages seen: %s%s"
              % (label, ", ".join("0x%03X x%d" % (i, seen[i]) for i in sorted(seen)),
                 "   MISSING %s" % ["0x%03X" % i for i in missing] if missing else ""))
        if missing:
            bad += 1

        # Show one fully decoded 0x7F4, which is what schema 4 added.
        for ident, data in frames:
            if ident == 0x7F4:
                dec = db.decode_message(ident, data)
                print("    0x7F4 %s -> %s" % (data.hex(),
                                              ", ".join("%s=%s" % kv
                                                        for kv in dec.items())))
                break

    print()
    print("%s" % ("all emitted diag frames decode against the DBC"
                  if bad == 0 else "%d PROBLEM(S) -- firmware, schema doc and "
                                   "DBC disagree" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
