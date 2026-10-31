"""Drive the Vtrux live-display app through recorded fault scenarios.

For each scenario this script:
  1. starts `tools/can_display_server.py` on a pre-cut slice (see
     `fault_display_replay.py`), with --verbose so the client handshake is
     observable on stdout;
  2. restarts the companion app's LiveDisplayActivity on the AVD so it
     reconnects to the freshly started server;
  3. waits for the server's `ready` message -- the instant the frame stream
     begins -- and uses that as t=0;
  4. screencaps at the scenario's listed offsets, which are chosen relative
     to the fault instants found by `fault_display_replay.py scan`.

The app's display host must already point at 10.0.2.2 (the AVD's alias for
the host loopback) on port 9878; the token is the project `sync.token` baked
into the APK at build time.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_display_capture.py
    py -3.11 projects/vtrux/notes/artifacts/fault_display_capture.py --only 04 05
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import queue
import subprocess
import threading
import time
from pathlib import Path

ADB = Path("<ANDROID_SDK_DIR>/platform-tools/adb.exe")
PY = ["py", "-3.11"]
SERVER = Path("tools/can_display_server.py")
BUS_IDENTITY = Path("tools/can_display_bus_identity_vtrux.json")
TOKEN = "ex-g6_55Kt46lWujZCwlw9n60FZt51yI"
PKG = "com.reverseit.vtruxcompanion"
ACTIVITY = f"{PKG}/com.reverseit.companion.LiveDisplayActivity"

SLICES = Path("projects/vtrux/notes/artifacts/fault-slices")
SHOTS = Path("projects/vtrux/notes/artifacts/fault-display-screenshots")

# (offset_seconds_into_replay, filename_suffix, what the frame should show)
SCENARIOS = [
    {
        "id": "01-healthy-drive",
        "title": "Healthy drive, HV closed, generator running",
        "shots": [
            (12, "a-hv-closed", "contactors closed, drive mode, no fault"),
            (40, "b-generator-running", "generator spun up"),
        ],
    },
    {
        "id": "02-normal-keyoff",
        "title": "Normal key-off (HVIL opens legitimately during shutdown)",
        "shots": [
            (15, "a-before-keyoff", "still driving"),
            (24, "b-at-keyoff", "HVIL drops inside SHUTDOWN_REQUEST"),
            (32, "c-after-keyoff", "ALL_OPEN_SHUTDOWN, should NOT read as a fault"),
        ],
    },
    {
        "id": "03-healthy-charge",
        "title": "Healthy AC charge session",
        "shots": [
            (20, "a-charging", "charge mode panel populated"),
            (45, "b-charging-later", "steady state"),
        ],
    },
    {
        "id": "04-isolation-fault",
        "title": "Isolation fault (deliberate 1 kOhm HV-to-chassis)",
        "shots": [
            (20, "a-before", "healthy drive"),
            (31, "b-at-fault", "gfd collapses to 0 then EPO"),
            (42, "c-latched", "ALL_OPEN_SHUTDOWN latched"),
        ],
    },
    {
        "id": "05-interlock-fault-drive",
        "title": "Interlock fault while driving (HVAC connector pull)",
        "shots": [
            (20, "a-before", "healthy drive"),
            (34, "b-at-fault", "HVIL drops 200 ms before EPO"),
            (48, "c-latched", "ALL_OPEN_SHUTDOWN latched"),
        ],
        # (offset, x, y) in device pixels -- centre of the collapsed strip.
        "expand": (52, 540, 1700),
    },
    {
        "id": "06-interlock-latched-flutter",
        "title": "Latched after interlock trip, HVIL switch cycled repeatedly",
        "shots": [
            (8, "a-hvil-bouncing", "operator cycling the interlock switch"),
            (25, "b-hvil-restored", "HVIL back to 1 but fault still latched"),
            (56, "c-relatch", "brief EPO clear then immediate re-latch"),
        ],
    },
    {
        "id": "07-charge-trip-hvil",
        "title": "Charge trip with HVIL drop, then recovery into drive",
        "shots": [
            (18, "a-charging", "charging normally"),
            (27, "b-trip", "HVIL drops, EPO, TYPE3"),
            (40, "c-latched", "latched shutdown"),
            (58, "d-recovered", "restarts and closes into drive"),
        ],
    },
    {
        "id": "08-operator-unplug",
        "title": "Operator unplugs the EVSE at end of charge (NOT a fault)",
        "shots": [
            (10, "a-charging", "charging"),
            (15, "b-unplug", "full EPO/TYPE3 signature from a normal unplug"),
            (22, "c-after", "cleared"),
        ],
    },
    {
        "id": "09-precharge-fail",
        "title": "Precharge abort at CLOSE_MAINR (Truck 3, welded MAINN)",
        "shots": [
            (3, "a-pre", "before the attempt"),
            (7, "b-abort", "aborts out of CLOSE_MAINR into shutdown"),
            (25, "c-latched", "latched, HV never came up"),
        ],
    },
    {
        "id": "10-bms-master-absent",
        "title": "BMS master never wakes (Truck 3) -- no 0x410 at all",
        "shots": [
            (12, "a-no-bms", "no BMS messages anywhere in the capture"),
            (28, "b-no-bms-later", "still nothing"),
        ],
    },
    {
        "id": "11-thermal-excursion",
        "title": "Drivetrain thermal excursion (PE pump CAN unplugged)",
        "shots": [
            (15, "a-hot", "TRAC thermal indicator ~88%, cool-flow demand 100%"),
            (40, "b-hot-later", "still hot"),
        ],
    },
    {
        "id": "12-drive-trip-ac1001",
        "title": "2026-06-18 00:21 drive-mode trip at 38 km/h (AC 10 01)",
        "shots": [
            (10, "a-driving", "healthy, strip absent"),
            (20, "b-trip", "EPO with interlock still closed; AC 10 01 + F0 00 00"),
            (40, "c-interlock-later", "interlock opens 19.8s in -- headline must NOT change"),
            (70, "d-cleared", "records clear, truck restarts"),
        ],
        "expand": (45, 540, 1700),
    },
]


def sh(*args: object) -> str:
    return subprocess.run([str(a) for a in args], capture_output=True,
                          text=True).stdout


def screencap(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        subprocess.run([str(ADB), "exec-out", "screencap", "-p"],
                       stdout=fh, check=True)


def pump(stream, q: "queue.Queue[str]") -> None:
    for line in stream:
        q.put(line.rstrip())
    q.put("<EOF>")


def wait_for(q: "queue.Queue[str]", needle: str, timeout: float,
             echo: bool = False) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = q.get(timeout=0.5)
        except queue.Empty:
            continue
        if echo:
            print(f"    | {line[:140]}")
        if needle in line:
            return True
        if line == "<EOF>":
            return False
    return False


def run_scenario(scn: dict, port: int) -> bool:
    log = SLICES / f"{scn['id']}.log"
    if not log.exists():
        print(f"!! missing slice {log}")
        return False
    out_dir = SHOTS / scn["id"]
    print(f"\n=== {scn['id']}: {scn['title']}")

    proc = subprocess.Popen(
        PY + [str(SERVER), "--log", str(log), "--bus-identity", str(BUS_IDENTITY),
              "--token", TOKEN, "--port", str(port), "--verbose"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        bufsize=1, encoding="utf-8", errors="replace",
    )
    q: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, q), daemon=True).start()

    try:
        print("  loading log into server...")
        if not wait_for(q, "listening on ws://", timeout=600, echo=True):
            print("!! server never reached listening state")
            return False

        # Restart the activity so RemoteCanDataSource reconnects to this
        # server instance rather than reusing a dead socket.
        sh(ADB, "shell", "am", "force-stop", PKG)
        time.sleep(1.0)
        sh(ADB, "shell", "am", "start", "-n", ACTIVITY)

        print("  waiting for stream start...")
        # The server serialises with compact separators, so the wire text is
        # `{"type":"ready",...` -- no space after the colon.
        if not wait_for(q, '"type":"ready"', timeout=90):
            print("!! client never completed the handshake")
            return False
        t0 = time.monotonic()
        print("  streaming.")

        for offset, name, what in scn["shots"]:
            delay = t0 + offset - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            dest = out_dir / f"{name}.png"
            screencap(dest)
            print(f"  t+{offset:5.1f}s  {dest.name:24s} {what}")

        # Optional extra frame with the fault strip tapped open. The strip is
        # the only tappable thing in that band, so a tap at its centre either
        # expands it or lands on inert background.
        exp = scn.get("expand")
        if exp:
            offset, x, y = exp
            delay = t0 + offset - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            sh(ADB, "shell", "input", "tap", str(x), str(y))
            time.sleep(0.6)
            dest = out_dir / "z-expanded.png"
            screencap(dest)
            print(f"  t+{offset:5.1f}s  {dest.name:24s} strip expanded")
        return True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                    help="scenario id prefixes to run (e.g. 04 05)")
    ap.add_argument("--port", type=int, default=9878)
    args = ap.parse_args()

    sh(ADB, "shell", "svc", "power", "stayon", "true")

    todo = SCENARIOS
    if args.only:
        todo = [s for s in SCENARIOS
                if any(s["id"].startswith(p) for p in args.only)]
    ok = 0
    for scn in todo:
        if run_scenario(scn, args.port):
            ok += 1
    print(f"\n{ok}/{len(todo)} scenarios captured -> {SHOTS}")


if __name__ == "__main__":
    main()
