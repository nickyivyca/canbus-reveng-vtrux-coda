#!/usr/bin/env python3
"""CAN Display Protocol v1 reference test server.

Replays a recorded CAN log over WebSocket so display clients can be
developed and tested without phone hardware. Implements the protocol
exactly as specified in:

    android-app/notes/protocols/can-display-protocol.md

Bus identification is anchor-ID-based: the server pre-scans the first
few seconds of the log to assign each physical channel/bus number to a
named bus from the --bus-identity file (e.g. "vehicle", "obd"). Clients
always speak in named buses; channel numbers never appear on the wire.

The DBC used for decode normally comes from the client's `config` message
(per spec). `--dbc` overrides the client's DBC with a server-side file
for testing scenarios where the client doesn't have one to send.

Usage:
    py -3.12 tools/can_display_server.py \\
        --log projects/vtrux/logs/<some>.log \\
        --bus-identity tools/can_display_bus_identity_vtrux.json
"""
from __future__ import annotations

import argparse
import asyncio
import http
import json
import logging
import math
import secrets
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cantools
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file  # noqa: E402

SERVER_NAME = "test-server"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = [1]
SUPPORTED_AGGREGATIONS = ["decimate", "latest", "min", "max", "mean"]
SUPPORTED_WIRE_FORMATS = ["json"]

DEFAULT_PORT = 9878
ID_WINDOW_SECONDS = 2.0
ID_TIMEOUT_SECONDS = 10.0

log = logging.getLogger("can_display_server")


# ---------------------------------------------------------------------------
# Bus identities
# ---------------------------------------------------------------------------


@dataclass
class BusIdentity:
    name: str
    anchor_ids: set[int]


def _parse_id_spec(spec: Any) -> set[int]:
    if isinstance(spec, int):
        return {spec}
    if isinstance(spec, str):
        s = spec.strip()
        if "-" in s:
            lo, hi = s.split("-", 1)
            return set(range(int(lo, 0), int(hi, 0) + 1))
        return {int(s, 0)}
    raise ValueError(f"unrecognised anchor id spec: {spec!r}")


def load_bus_identities(path: Path) -> list[BusIdentity]:
    raw = json.loads(path.read_text())
    out: list[BusIdentity] = []
    for entry in raw:
        ids: set[int] = set()
        for spec in entry["anchor_ids"]:
            ids |= _parse_id_spec(spec)
        out.append(BusIdentity(name=entry["name"], anchor_ids=ids))
    return out


def identify_buses(
    frames: list,
    identities: list[BusIdentity],
    window_seconds: float = ID_WINDOW_SECONDS,
) -> tuple[dict[str, int], dict[str, str]]:
    """Match each named bus to a channel using the first `window_seconds` of frames.

    Returns (assignments, reasons) where assignments is identity_name -> bus_num
    for buses that were identified, and reasons is identity_name -> human string.
    """
    if not frames:
        return {}, {n.name: "no frames in log" for n in identities}

    t0 = frames[0].timestamp
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in frames:
        if f.timestamp - t0 > window_seconds:
            break
        for ident in identities:
            if f.arbitration_id in ident.anchor_ids:
                counts[f.bus][ident.name] += 1

    assignments: dict[str, int] = {}
    reasons: dict[str, str] = {}
    used_buses: set[int] = set()

    for ident in identities:
        threshold = min(3, len(ident.anchor_ids))
        candidates = [
            (counts[bus][ident.name], bus)
            for bus in counts
            if counts[bus][ident.name] >= threshold
            and bus not in used_buses
        ]
        candidates.sort(reverse=True)
        if candidates:
            best_count, bus_num = candidates[0]
            assignments[ident.name] = bus_num
            used_buses.add(bus_num)
            reasons[ident.name] = (
                f"matched {best_count}/{len(ident.anchor_ids)} anchor IDs on bus {bus_num} "
                f"in {window_seconds:.1f}s"
            )
        else:
            reasons[ident.name] = (
                f"no channel matched >= {threshold} anchor IDs in {window_seconds:.1f}s"
            )

    return assignments, reasons


def measure_bus_rates(frames: list) -> dict[tuple[int, int], float]:
    """Return Hz per (bus, arbitration_id) measured across the whole log."""
    if not frames:
        return {}
    counts: dict[tuple[int, int], int] = defaultdict(int)
    span = frames[-1].timestamp - frames[0].timestamp
    if span <= 0:
        return {}
    for f in frames:
        counts[(f.bus, f.arbitration_id)] += 1
    return {k: v / span for k, v in counts.items()}


# ---------------------------------------------------------------------------
# Subscription state and aggregation
# ---------------------------------------------------------------------------


@dataclass
class Subscription:
    bus: str
    message_id: int
    signals: list[str] | str  # list of names or "*"
    rate_hz: float
    aggregation: str
    window_seconds: float = field(init=False)

    def __post_init__(self) -> None:
        self.window_seconds = 1.0 / self.rate_hz


@dataclass
class _AggState:
    """Tumbling-window aggregation state for one subscription."""
    sub: Subscription
    window_start: float | None = None
    window_end: float | None = None
    # signal -> running aggregation state
    state: dict[str, dict[str, Any]] = field(default_factory=dict)
    # decimate counter
    seen_in_cycle: int = 0
    decimate_n: int = 1
    # last emitted t per bus (for monotonicity guarantee)
    last_emit_t: float | None = None


def _agg_init(mode: str) -> dict[str, Any]:
    if mode == "mean":
        return {"sum": 0.0, "count": 0}
    if mode in ("min", "max", "latest", "decimate"):
        return {"value": None}
    raise ValueError(f"unsupported aggregation: {mode}")


def _agg_update(mode: str, st: dict[str, Any], value: float) -> None:
    if mode == "mean":
        st["sum"] += value
        st["count"] += 1
    elif mode == "min":
        st["value"] = value if st["value"] is None else min(st["value"], value)
    elif mode == "max":
        st["value"] = value if st["value"] is None else max(st["value"], value)
    elif mode in ("latest", "decimate"):
        st["value"] = value


def _agg_emit(mode: str, st: dict[str, Any]) -> float | None:
    if mode == "mean":
        return st["sum"] / st["count"] if st["count"] > 0 else None
    return st["value"]


def _to_scalar(v: Any) -> float | None:
    """Coerce a cantools-decoded value to float, or None if non-numeric.

    Per protocol v1, value-table enum mappings are client-side; the server
    emits the raw underlying scalar. cantools returns NamedSignalValue for
    enum-mapped signals; its integer cast yields the raw value.
    """
    if isinstance(v, str):
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(int(v))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class DisplayServer:
    def __init__(
        self,
        log_path: Path,
        identities: list[BusIdentity],
        token: str,
        port: int,
        speed: float,
        loop: bool,
        verbose: bool,
        dump_subscription_summary: bool,
        override_dbc_text: str | None = None,
    ) -> None:
        self.log_path = log_path
        self.identities = identities
        self.token = token
        self.port = port
        self.speed = speed
        self.loop = loop
        self.verbose = verbose
        self.dump_subscription_summary = dump_subscription_summary
        self.override_dbc_text = override_dbc_text

        self.frames: list = []
        self.bus_assignments: dict[str, int] = {}
        self.bus_reasons: dict[str, str] = {}
        self.bus_rates_hz: dict[tuple[int, int], float] = {}

        self._active: Any | None = None
        self._active_lock = asyncio.Lock()

    # -- preflight ---------------------------------------------------------

    def preflight(self) -> None:
        log.info("loading log %s", self.log_path)
        self.frames = list(parse_file(self.log_path))
        if not self.frames:
            raise SystemExit(f"log produced zero frames: {self.log_path}")
        log.info("loaded %d frames spanning %.2fs",
                 len(self.frames),
                 self.frames[-1].timestamp - self.frames[0].timestamp)

        self.bus_assignments, self.bus_reasons = identify_buses(self.frames, self.identities)
        for ident in self.identities:
            if ident.name in self.bus_assignments:
                log.info("bus '%s' -> channel %d (%s)",
                         ident.name, self.bus_assignments[ident.name],
                         self.bus_reasons[ident.name])
            else:
                log.warning("bus '%s' UNIDENTIFIED (%s)", ident.name, self.bus_reasons[ident.name])

        self.bus_rates_hz = measure_bus_rates(self.frames)

    # -- run ---------------------------------------------------------------

    async def run(self) -> None:
        async def gate(connection, request):
            if request.path != "/stream":
                return connection.respond(http.HTTPStatus.NOT_FOUND, "unknown path\n")
            auth_header = request.headers.get("Authorization", "")
            expected = f"Bearer {self.token}"
            if auth_header != expected:
                log.warning("auth failed for %s", connection.remote_address)
                return connection.respond(http.HTTPStatus.UNAUTHORIZED, "auth_failed\n")
            return None

        log.info("listening on ws://0.0.0.0:%d/stream  token=%s", self.port, self.token)
        async with websockets.serve(
            self._handle,
            "0.0.0.0",
            self.port,
            process_request=gate,
            max_size=8 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ):
            await asyncio.Future()

    # -- per-connection ----------------------------------------------------

    async def _handle(self, ws: Any) -> None:
        async with self._active_lock:
            old = self._active
            self._active = ws
        if old is not None:
            log.info("superseding existing client")
            await self._send(old, {
                "type": "error",
                "code": "superseded",
                "message": "replaced by new authenticated client",
                "fatal": True,
            })
            try:
                await old.close(code=1000, reason="superseded")
            except Exception:
                pass

        try:
            await self._serve(ws)
        except websockets.ConnectionClosed:
            log.info("client disconnected")
        finally:
            async with self._active_lock:
                if self._active is ws:
                    self._active = None

    async def _serve(self, ws: Any) -> None:
        await self._send(ws, {
            "type": "hello",
            "protocol_versions": PROTOCOL_VERSIONS,
            "wire_formats": SUPPORTED_WIRE_FORMATS,
            "server_name": SERVER_NAME,
            "server_version": SERVER_VERSION,
            "supported_aggregations": SUPPORTED_AGGREGATIONS,
            "supported_buses": [i.name for i in self.identities],
        })

        config_raw = await ws.recv()
        cfg = self._parse_message(config_raw)
        if cfg.get("type") != "config":
            await self._fatal(ws, "internal", f"expected config, got {cfg.get('type')!r}")
            return

        if cfg.get("protocol_version") not in PROTOCOL_VERSIONS:
            await self._fatal(ws, "protocol_version_mismatch",
                              f"client requested {cfg.get('protocol_version')!r}")
            return
        if cfg.get("wire_format", "json") not in SUPPORTED_WIRE_FORMATS:
            await self._fatal(ws, "unsupported_wire_format",
                              f"client requested {cfg.get('wire_format')!r}")
            return

        # v1 spec: client sends `dbcs` -- an object keyed by named bus, each
        # value a DBC covering that bus's subscribed messages. --dbc CLI
        # override applies to every bus uniformly for test convenience.
        if self.override_dbc_text:
            dbcs_raw = {ident.name: self.override_dbc_text for ident in self.identities}
        else:
            dbcs_raw = cfg.get("dbcs")
        if not isinstance(dbcs_raw, dict) or not dbcs_raw:
            await self._fatal(ws, "dbc_parse_error", "config.dbcs missing or empty")
            return
        dbs_by_bus: dict[str, cantools.database.Database] = {}
        for bus_name, text in dbcs_raw.items():
            if not isinstance(text, str) or not text.strip():
                await self._fatal(ws, "dbc_parse_error",
                                  f"config.dbcs[{bus_name!r}] missing or empty")
                return
            try:
                dbs_by_bus[bus_name] = cantools.database.load_string(
                    text, database_format="dbc", strict=False,
                )
            except Exception as e:
                await self._fatal(ws, "dbc_parse_error", f"bus {bus_name!r}: {e}")
                return
        # Flat lookup: (bus_name, frame_id) -> Message
        msg_lookup: dict[tuple[str, int], Any] = {
            (bus, m.frame_id): m
            for bus, db in dbs_by_bus.items()
            for m in db.messages
        }

        subs_raw = cfg.get("subscriptions") or []
        subs: list[Subscription] = []
        for s in subs_raw:
            err = self._validate_sub(s, msg_lookup, dbs_by_bus)
            if err is not None:
                await self._fatal(ws, err[0], err[1])
                return
            subs.append(Subscription(
                bus=s["bus"],
                message_id=int(s["message_id"]),
                signals=s["signals"],
                rate_hz=float(s["rate_hz"]),
                aggregation=s["aggregation"],
            ))

        if self.dump_subscription_summary:
            self._dump_summary(subs)

        active = []
        for s in subs:
            sigs = s.signals
            if sigs == "*":
                msg = msg_lookup[(s.bus, s.message_id)]
                sigs = [sg.name for sg in msg.signals]
            active.append({
                "bus": s.bus,
                "message_id": s.message_id,
                "signals": sigs,
                "rate_hz": s.rate_hz,
            })

        pending = sorted({
            s.bus for s in subs if s.bus not in self.bus_assignments
        })
        await self._send(ws, {
            "type": "ready",
            "active_subscriptions": active,
            "pending_buses": pending,
        })

        for ident in self.identities:
            if ident.name in self.bus_assignments:
                if any(s.bus == ident.name for s in subs):
                    await self._send(ws, {
                        "type": "status",
                        "kind": "bus_identified",
                        "bus": ident.name,
                        "detail": self.bus_reasons[ident.name],
                    })
            else:
                if any(s.bus == ident.name for s in subs):
                    await self._send(ws, {
                        "type": "status",
                        "kind": "bus_silent",
                        "bus": ident.name,
                        "detail": self.bus_reasons[ident.name],
                    })

        await self._stream(ws, dbs_by_bus, subs)

    # -- streaming / aggregation -------------------------------------------

    async def _stream(
        self,
        ws: Any,
        dbs_by_bus: dict[str, cantools.database.Database],
        subs: list[Subscription],
    ) -> None:
        # Build per-subscription aggregation state, indexed by (bus_num, msg_id)
        # for fast match against raw frames.
        aggregators: dict[tuple[int, int], list[_AggState]] = defaultdict(list)
        # bus_num -> bus_name (reverse mapping for decode lookup)
        bus_name_by_num: dict[int, str] = {v: k for k, v in self.bus_assignments.items()}
        for s in subs:
            bus_num = self.bus_assignments.get(s.bus)
            if bus_num is None:
                continue
            ag = _AggState(sub=s)
            rate = self.bus_rates_hz.get((bus_num, s.message_id), 0.0)
            ag.decimate_n = max(1, int(round(rate / s.rate_hz))) if rate > 0 else 1
            aggregators[(bus_num, s.message_id)].append(ag)

        cumulative_offset = 0.0
        log_span = self.frames[-1].timestamp - self.frames[0].timestamp
        while True:
            t0_log = self.frames[0].timestamp
            wall_start = time.monotonic()

            for frame in self.frames:
                local_t = frame.timestamp - t0_log
                # rel_t is monotonic across loop iterations so tumbling
                # aggregation windows keep advancing on --loop.
                rel_t = local_t + cumulative_offset
                target_wall = wall_start + (local_t / self.speed) if self.speed > 0 else wall_start
                now = time.monotonic()
                delay = target_wall - now
                if delay > 0.001:
                    await asyncio.sleep(delay)

                key = (frame.bus, frame.arbitration_id)
                if key not in aggregators:
                    continue

                bus_name = bus_name_by_num.get(frame.bus)
                if bus_name is None:
                    continue
                db = dbs_by_bus.get(bus_name)
                if db is None:
                    continue
                msg = next((m for m in db.messages if m.frame_id == frame.arbitration_id), None)
                if msg is None:
                    continue
                try:
                    # decode_choices=False returns raw scalars instead of
                    # NamedSignalValue strings for VAL_-mapped signals. The
                    # protocol emits numeric values; the client maps enums.
                    decoded = db.decode_message(
                        frame.arbitration_id, frame.data, decode_choices=False,
                    )
                except Exception as e:
                    if self.verbose:
                        log.warning("decode failed for 0x%X: %s", frame.arbitration_id, e)
                    continue

                for ag in aggregators[key]:
                    sub = ag.sub
                    sigs = sub.signals
                    if sigs == "*":
                        sigs = [sg.name for sg in msg.signals]
                    payload: dict[str, float] = {}
                    for name in sigs:
                        if name not in decoded:
                            continue
                        v = decoded[name]
                        scalar = _to_scalar(v)
                        if scalar is not None:
                            payload[name] = scalar
                    if sub.aggregation == "decimate":
                        ag.seen_in_cycle += 1
                        if ag.seen_in_cycle >= ag.decimate_n:
                            ag.seen_in_cycle = 0
                            await self._emit_frame(ws, sub.bus, sub.message_id, rel_t, payload)
                            ag.last_emit_t = rel_t
                        continue

                    # Tumbling-window aggregations (latest, min, max, mean)
                    if ag.window_start is None:
                        ag.window_start = rel_t
                        ag.window_end = rel_t + sub.window_seconds
                    while ag.window_end is not None and rel_t >= ag.window_end:
                        out = self._flush_window(ag)
                        if out is not None:
                            await self._emit_frame(ws, sub.bus, sub.message_id,
                                                   ag.window_end, out)
                            ag.last_emit_t = ag.window_end
                        ag.window_start = ag.window_end
                        ag.window_end = (ag.window_start or 0.0) + sub.window_seconds
                        ag.state = {}

                    for name, val in payload.items():
                        st = ag.state.get(name)
                        if st is None:
                            st = _agg_init(sub.aggregation)
                            ag.state[name] = st
                        _agg_update(sub.aggregation, st, val)

            if not self.loop:
                break
            cumulative_offset += log_span

    @staticmethod
    def _flush_window(ag: _AggState) -> dict[str, float] | None:
        if not ag.state:
            return None
        out: dict[str, float] = {}
        for name, st in ag.state.items():
            v = _agg_emit(ag.sub.aggregation, st)
            if v is not None:
                out[name] = v
        return out or None

    async def _emit_frame(
        self,
        ws: Any,
        bus: str,
        message_id: int,
        t: float,
        signals: dict[str, float],
    ) -> None:
        await self._send(ws, {
            "type": "frame",
            "bus": bus,
            "message_id": message_id,
            "t": round(t, 6),
            "s": signals,
        })

    # -- helpers -----------------------------------------------------------

    def _validate_sub(
        self,
        s: dict[str, Any],
        msg_lookup: dict[tuple[str, int], Any],
        dbs_by_bus: dict[str, cantools.database.Database],
    ) -> tuple[str, str] | None:
        bus = s.get("bus")
        if not isinstance(bus, str):
            return ("subscription_unknown_bus", "subscription.bus must be a string")
        if bus not in {i.name for i in self.identities}:
            return ("subscription_unknown_bus", f"unknown bus {bus!r}")
        if bus not in dbs_by_bus:
            return ("subscription_missing_bus_dbc",
                    f"subscription targets bus {bus!r} but config.dbcs has no entry for it")
        mid = s.get("message_id")
        if not isinstance(mid, int):
            return ("subscription_unknown_signal", "subscription.message_id must be int")
        msg = msg_lookup.get((bus, mid))
        if msg is None:
            return ("subscription_unknown_signal",
                    f"message_id {mid} not in DBC for bus {bus!r}")
        sigs = s.get("signals")
        if sigs == "*":
            pass
        elif isinstance(sigs, list) and all(isinstance(x, str) for x in sigs):
            valid = {sg.name for sg in msg.signals}
            for name in sigs:
                if name not in valid:
                    return ("subscription_unknown_signal",
                            f"signal {name!r} not in message {msg.name}")
        else:
            return ("subscription_unknown_signal",
                    "subscription.signals must be a list of strings or \"*\"")
        rate = s.get("rate_hz")
        if not isinstance(rate, (int, float)) or rate <= 0 or not math.isfinite(rate):
            return ("rate_invalid", f"rate_hz must be > 0, got {rate!r}")
        agg = s.get("aggregation")
        if agg not in SUPPORTED_AGGREGATIONS:
            return ("unsupported_aggregation", f"aggregation {agg!r} not supported")
        return None

    def _dump_summary(self, subs: list[Subscription]) -> None:
        lines = ["client subscriptions:"]
        for s in subs:
            sig_str = "*" if s.signals == "*" else ", ".join(s.signals)
            lines.append(f"  {s.bus}  0x{s.message_id:X}  [{sig_str}]  "
                         f"@ {s.rate_hz} Hz / {s.aggregation}")
        log.info("\n".join(lines))

    async def _send(self, ws: Any, msg: dict[str, Any]) -> None:
        text = json.dumps(msg, separators=(",", ":"))
        if self.verbose:
            log.info("-> %s", text[:300])
        await ws.send(text)

    def _parse_message(self, raw: str | bytes) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if self.verbose:
            log.info("<- %s", raw[:300])
        return json.loads(raw)

    async def _fatal(self, ws: Any, code: str, message: str) -> None:
        log.warning("fatal error to client: %s %s", code, message)
        await self._send(ws, {
            "type": "error",
            "code": code,
            "message": message,
            "fatal": True,
        })
        await ws.close(code=1002, reason=code)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="CAN Display Protocol v1 reference test server")
    p.add_argument("--log", required=True, type=Path, help="CAN log file to replay (auto-detected format)")
    p.add_argument("--bus-identity", required=True, type=Path,
                   help="JSON file: list of {name, anchor_ids:[..]} entries")
    p.add_argument("--dbc", type=Path, default=None,
                   help="Optional DBC file. Overrides the client's DBC if provided.")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--token", default=None,
                   help="Bearer auth token (random hex generated if omitted)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="Replay speed multiplier (default 1.0; 0 = no delay)")
    p.add_argument("--loop", action="store_true", help="Loop the log when it ends")
    p.add_argument("--verbose", action="store_true", help="Log every wire message")
    p.add_argument("--dump-subscription-summary", action="store_true",
                   help="Log a human-readable summary on each client config")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.log.exists():
        raise SystemExit(f"log not found: {args.log}")
    if not args.bus_identity.exists():
        raise SystemExit(f"bus-identity not found: {args.bus_identity}")

    identities = load_bus_identities(args.bus_identity)
    if not identities:
        raise SystemExit("bus-identity file produced zero identities")

    token = args.token or secrets.token_hex(8)
    override_dbc = args.dbc.read_text() if args.dbc else None

    server = DisplayServer(
        log_path=args.log,
        identities=identities,
        token=token,
        port=args.port,
        speed=args.speed,
        loop=args.loop,
        verbose=args.verbose,
        dump_subscription_summary=args.dump_subscription_summary,
        override_dbc_text=override_dbc,
    )
    server.preflight()

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
