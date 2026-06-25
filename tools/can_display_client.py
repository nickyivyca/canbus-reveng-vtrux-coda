#!/usr/bin/env python3
"""Minimal CAN Display Protocol v1 client.

Connects to a server, sends a `config` with a DBC + subscriptions read
from a JSON manifest, and prints incoming `frame`/`status`/`error`
messages. Used to verify the test server end-to-end without writing the
Android client.

Manifest JSON format:
    {
        "subscriptions": [
            {"bus": "vehicle", "message_id": 1056,
             "signals": ["bcm_vbus"], "rate_hz": 10, "aggregation": "mean"}
        ]
    }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import websockets


async def run(url: str, token: str, dbc_path: Path, manifest_path: Path) -> None:
    dbc_text = dbc_path.read_text()
    manifest = json.loads(manifest_path.read_text())
    subscriptions = manifest["subscriptions"]

    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(url, additional_headers=headers, max_size=8 * 1024 * 1024) as ws:
        hello_raw = await ws.recv()
        hello = json.loads(hello_raw)
        if hello.get("type") != "hello":
            print(f"unexpected first message: {hello}", file=sys.stderr)
            return
        print(f"connected. server={hello.get('server_name')} v{hello.get('server_version')} "
              f"buses={hello.get('supported_buses')}")

        await ws.send(json.dumps({
            "type": "config",
            "protocol_version": 1,
            "wire_format": "json",
            "dbc": dbc_text,
            "subscriptions": subscriptions,
        }))

        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "ready":
                print(f"ready. active={len(msg.get('active_subscriptions', []))} "
                      f"pending_buses={msg.get('pending_buses')}")
            elif kind == "status":
                print(f"status [{msg.get('kind')}] {msg.get('bus')}: {msg.get('detail')}")
            elif kind == "error":
                print(f"error [{msg.get('code')}] {msg.get('message')}", file=sys.stderr)
                if msg.get("fatal"):
                    return
            elif kind == "frame":
                vals = ", ".join(f"{k}={v:.4g}" for k, v in msg.get("s", {}).items())
                print(f"t={msg.get('t'):8.3f} {msg.get('bus')} 0x{msg.get('message_id'):X}  {vals}")
            else:
                print(f"unknown: {msg}")


def main() -> None:
    p = argparse.ArgumentParser(description="CAN Display Protocol v1 minimal client")
    p.add_argument("--url", default="ws://localhost:9878/stream")
    p.add_argument("--token", required=True)
    p.add_argument("--dbc", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    args = p.parse_args()
    asyncio.run(run(args.url, args.token, args.dbc, args.manifest))


if __name__ == "__main__":
    main()
