"""Visual check of the live display's EVAP INHIBIT state in the AVD.

The generator inhibitor's 0x7F1 WICAN_Diag_Status page has never been seen on
the truck, so this injects synthetic pages into a copy of a recorded slice and
screenshots the companion app (vtrux flavour) at fixed offsets. The rule under
test is in `notes/protocols/gen-inhibit-status-interface.md` of the
android-canbus-apps repo (GenInhibitStatus.kt).

Timeline, seconds from the start of the replay:
   0 - 15  no 0x7F1                     -> normal EVAP status
  15 - 25  OBSERVE pages (mode 1)       -> pages present, not inhibiting
  25 - 40  INHIBIT pages (mode 3, 0x60) -> EVAP shows INHIBIT on purple
  40 -     silence                      -> clears 3 s after the last page

Phases:
  inject   write the injected log to the temp dir (regenerable)
  capture  run tools/can_display_server.py on it and screencap the AVD

Prerequisites: AVD running as emulator-5554 with the companion vtrux debug
build installed and its Live Display host set to 10.0.2.2; a Python with
websockets + cantools (tools/can_display_server_requirements.txt) passed as
--server-python. The token is read from the secrets folder named by
reverseit.secretsDir in ~/.gradle/gradle.properties and never printed.

Usage (the Linux box, from the reverse-it root):
    python3.13 projects/vtrux/notes/artifacts/gen_inhibit_display_check.py \
        --server-python <venv>/bin/python
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ADB = [str(Path.home() / "Android/Sdk/platform-tools/adb"), "-s", "emulator-5554"]
SERVER = Path("tools/can_display_server.py")
BUS_IDENTITY = Path("tools/can_display_bus_identity_vtrux.json")
PKG = "com.reverseit.vtruxcompanion"
ACTIVITY = f"{PKG}/com.reverseit.companion.LiveDisplayActivity"

SLICE = Path("projects/vtrux/notes/artifacts/fault-slices/01-healthy-drive.log")
OUT_LOG = Path(tempfile.gettempdir()) / "gen-inhibit-display-check" / "01-healthy-drive-0x7f1.log"
SHOTS = Path("projects/vtrux/notes/artifacts/gen-inhibit-display-screenshots")

PERIOD = 1.2
# (start_s, end_s, data bytes) -- schema 8, fw 9, mode, flags, rest as in GenInhibitStatusTest
PHASES = [
    (15.0, 25.0, [8, 9, 1, 0x40, 0, 3, 0x10, 0x27]),
    (25.0, 40.0, [8, 9, 3, 0x60, 0, 3, 0x10, 0x27]),
]
POWERTRAIN_ANCHORS = {0x051, *range(0x592, 0x5A3), *range(0x639, 0x64C)}

SHOT_PLAN = [
    (12.0, "a-baseline", "no 0x7F1 yet"),
    (22.0, "b-observe", "OBSERVE pages, must not show INHIBIT"),
    (30.0, "c-inhibit", "INHIBIT pages"),
    (38.0, "d-inhibit-late", "INHIBIT pages, near the end"),
]
# Burst after the last page to bracket the clear.
BURST = (40.0, 47.0, 0.5)
FINAL = (52.0, "z-cleared", "long after the last page")


def ts_to_s(ts: str) -> float:
    h, m, s, t = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) / 10000.0


def s_to_ts(x: float) -> str:
    ticks = int(round(x * 10000))
    h, ticks = divmod(ticks, 36000000)
    m, ticks = divmod(ticks, 600000)
    s, t = divmod(ticks, 10000)
    return f"{h:02d}:{m:02d}:{s:02d}:{t:04d}"


def phase_inject() -> tuple[str, float, list[float]]:
    lines = SLICE.read_text().splitlines()
    data_start = next(i for i, ln in enumerate(lines) if ln[:2].isdigit())
    t0 = ts_to_s(lines[data_start].split()[0])

    counts: dict[str, set[int]] = {}
    for ln in lines[data_start:]:
        f = ln.split()
        if ts_to_s(f[0]) - t0 > 2.0:
            break
        cid = int(f[3], 16)
        if cid in POWERTRAIN_ANCHORS:
            counts.setdefault(f[2], set()).add(cid)
    ranked = sorted(counts.items(), key=lambda kv: -len(kv[1]))
    if not ranked or len(ranked[0][1]) < 3 or (len(ranked) > 1 and len(ranked[1][1]) >= 3):
        raise SystemExit(f"powertrain channel ambiguous: { {k: len(v) for k, v in counts.items()} }")
    ch = ranked[0][0]

    inject: list[tuple[float, str]] = []
    page_times: list[float] = []
    for start, end, data in PHASES:
        t = start
        while t < end:
            page_times.append(t)
            body = " ".join(f"{b:02X}" for b in data)
            inject.append((t0 + t, f"{s_to_ts(t0 + t)} Rx {ch} 0x7F1 s 8 {body}"))
            t += PERIOD

    out = lines[:data_start]
    k = 0
    for ln in lines[data_start:]:
        tl = ts_to_s(ln.split()[0])
        while k < len(inject) and inject[k][0] <= tl:
            out.append(inject[k][1])
            k += 1
        out.append(ln)
    out.extend(x[1] for x in inject[k:])
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text("\n".join(out) + "\n")
    print(f"inject: powertrain = channel {ch} ({len(ranked[0][1])} anchors); "
          f"{len(inject)} pages, last at t+{page_times[-1]:.1f}s -> {OUT_LOG}")
    return ch, t0, page_times


def read_token() -> str:
    props = (Path.home() / ".gradle/gradle.properties").read_text().splitlines()
    sdir = next(p.split("=", 1)[1].strip() for p in props if p.startswith("reverseit.secretsDir="))
    for p in (Path(sdir) / "android.properties").read_text().splitlines():
        if p.startswith("sync.token="):
            return p.split("=", 1)[1].strip()
    raise SystemExit("sync.token not found in the secrets folder")


def sh(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True).stdout


def screencap(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        subprocess.run(ADB + ["exec-out", "screencap", "-p"], stdout=fh, check=True)


def purple_pixels(path: Path) -> int:
    try:
        from PIL import Image
    except ImportError:
        return -1
    im = Image.open(path).convert("RGB")
    return sum(1 for px in im.getdata() if abs(px[0] - 0x7B) <= 6 and abs(px[1] - 0x1F) <= 6 and abs(px[2] - 0xA2) <= 6)


def pump(stream, q: "queue.Queue[str]") -> None:
    for line in stream:
        q.put(line.rstrip())
    q.put("<EOF>")


def wait_for(q: "queue.Queue[str]", needle: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = q.get(timeout=0.5)
        except queue.Empty:
            continue
        if needle in line:
            return True
        if line == "<EOF>":
            return False
    return False


def phase_capture(server_python: str, page_times: list[float], port: int) -> None:
    proc = subprocess.Popen(
        [server_python, str(SERVER), "--log", str(OUT_LOG), "--bus-identity", str(BUS_IDENTITY),
         "--token", read_token(), "--port", str(port), "--verbose"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        bufsize=1, encoding="utf-8", errors="replace",
    )
    q: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, q), daemon=True).start()
    try:
        if not wait_for(q, "listening on ws://", timeout=600):
            raise SystemExit("server never reached listening state")
        sh(*ADB, "shell", "am", "force-stop", PKG)
        time.sleep(1.0)
        sh(*ADB, "shell", "am", "start", "-n", ACTIVITY)
        if not wait_for(q, '"type":"ready"', timeout=90):
            raise SystemExit("client never completed the handshake")
        t0 = time.monotonic()
        print("capture: streaming")

        def shot(offset: float, name: str, what: str) -> None:
            delay = t0 + offset - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            taken = time.monotonic() - t0
            dest = SHOTS / f"{name}.png"
            screencap(dest)
            print(f"  t+{taken:5.1f}s  {dest.name:22s} purple={purple_pixels(dest):6d}  {what}")

        for offset, name, what in SHOT_PLAN:
            shot(offset, name, what)
        last = page_times[-1]
        start, end, step = BURST
        x = start
        while x <= end:
            shot(x, f"e-burst-{x:04.1f}", f"{x - last:+.1f}s from last page")
            x += step
        shot(*FINAL)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server-python", required=True)
    ap.add_argument("--port", type=int, default=9878)
    ap.add_argument("--inject-only", action="store_true")
    args = ap.parse_args()
    _, _, page_times = phase_inject()
    if not args.inject_only:
        sh(*ADB, "shell", "svc", "power", "stayon", "true")
        phase_capture(args.server_python, page_times, args.port)


if __name__ == "__main__":
    main()
