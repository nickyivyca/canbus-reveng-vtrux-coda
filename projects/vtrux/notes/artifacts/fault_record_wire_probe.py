"""What 0x460 signals actually arrive over the display protocol?

The rendered fault card for `05-interlock-fault-drive` lists two records
(`AC 10 00`, `F0 00 00`) where the raw log shows four -- pages 1 *and* 2 are
populated at that point (`FC 16 F2`, `FB B6 E4` on page 2). The app merges
signal frames cumulatively, so a page it ever received should stay in the map.
This connects to `can_display_server.py` exactly as the app does and records,
per 0x460 signal, how many frames carried it and what the last value was.

If `fr_p2_*` never appears, the record list the driver reads out is truncated
and a named record living on page 2 would be missed entirely.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_record_wire_probe.py \
        --log projects/vtrux/notes/artifacts/fault-slices/05-interlock-fault-drive.log \
        --seconds 55
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

import websockets

PY = ["py", "-3.11"]
SERVER = Path("tools/can_display_server.py")
BUS_IDENTITY = Path("tools/can_display_bus_identity_vtrux.json")
TOKEN = "ex-g6_55Kt46lWujZCwlw9n60FZt51yI"
MANIFEST = Path("android-app/CanLoggerApps/vtrux/src/main/assets/live-display/manifest.json")


async def probe(port: int, seconds: float) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    uri = f"ws://127.0.0.1:{port}/stream"

    counts: dict[str, int] = {}
    last: dict[str, float] = {}
    merged: dict[str, float] = {}

    dbc_dir = MANIFEST.parent / "dbcs"
    dbcs = {p.stem: p.read_text(encoding="utf-8") for p in dbc_dir.glob("*.dbc")}

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with websockets.connect(uri, max_size=None,
                                  additional_headers=headers) as ws:
        hello = json.loads(await ws.recv())
        await ws.send(json.dumps({
            "type": "config",
            "protocol_version": hello["protocol_versions"][0],
            "wire_format": "json",
            "dbcs": dbcs,
            "subscriptions": manifest["subscriptions"],
        }))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") != "frame":
                continue
            merged.update(msg["s"])
            if msg.get("message_id") != 1120:
                continue
            for name, val in msg["s"].items():
                counts[name] = counts.get(name, 0) + 1
                last[name] = val

    print("\n0x460 signals seen on the wire:")
    for name in ["fr_page", "fr_pages", "fr_grp3", "fr_grp2", "fr_grp1", "fr_total"] + \
            [f"fr_p{p}_r{r}" for p in (1, 2, 3, 4) for r in (1, 2)]:
        n = counts.get(name, 0)
        v = last.get(name)
        shown = "-" if v is None else f"{int(v):06X}"
        print(f"   {name:12s} frames={n:6d}  last={shown}")

    print("\nWhat the classifier would see from the final merged map:")
    pages = merged.get("fr_pages")
    slots = merged.get("fr_total")
    print(f"   fr_pages={pages}  fr_total={slots}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--port", type=int, default=9879)
    ap.add_argument("--seconds", type=float, default=55.0)
    args = ap.parse_args()

    proc = subprocess.Popen(
        PY + [str(SERVER), "--log", str(args.log),
              "--bus-identity", str(BUS_IDENTITY), "--token", TOKEN,
              "--port", str(args.port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        bufsize=1, encoding="utf-8", errors="replace",
    )
    try:
        for line in proc.stdout:
            print("  |", line.rstrip()[:120])
            if "listening on ws://" in line:
                break
        asyncio.run(probe(args.port, args.seconds))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
