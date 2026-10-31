#!/usr/bin/env python3
"""Serve SLCAN over TCP: a 914 VCU stream (capture or live serial), or a BUSMASTER log as one
stream per bus (the Coda emulator harness).

The Android app reads SLCAN from the VCU's USB CDC port. Getting bytes to a phone without
solving USB host mode first is what this is for: run it on a laptop, point the phone at it with

    adb reverse tcp:9000 tcp:9000

and the phone's `localhost:9000` reaches this server. No root, no network configuration, over
USB or wireless ADB. It stays useful after the USB transport works, as the replay harness for
regression tests -- the analogue of `tools/can_display_server.py` for this vehicle.

Replay is PACED BY DEFAULT to match what the link actually does, measured on the car on
2026-08-13 (verification A2). Blasting a capture at socket speed would exercise the parser but
misrepresent the consumer's experience: on the real link, frames arrive in ~1024-byte bursts
about every 212 ms, not smoothly. A display fed an unpaced replay looks better than it will in
the car. Pass `--rate 0` to disable pacing.

Serial mode is READ-ONLY. Nothing is ever written to the VCU.

BUSMASTER MODE (--busmaster) is the Coda emulator harness. The chunks given are merged onto one
timeline, each channel is named by content (canre.utils.buses, the vehicle's anchor IDs -- never
by channel number), and each bus is served on its own port, base port + its position in
--buses. Replay starts once every port has a client and is paced by the log's own timestamps
(--speed). The direction is two-way: SLCAN lines the app writes back -- its transmitted frames --
are decoded, printed and recorded with --tx-log. See
android-app/notes/plans/coda-slcan-harness-0x600.md.

ASCII-only output, per the project rules.

Usage:
    py -3.12 tools/slcan_bridge.py --file <capture.log[.gz]> [--loop]
    py -3.12 tools/slcan_bridge.py --serial COM3
    py -3.12 tools/slcan_bridge.py --file <capture> --selftest
    py -3.11 tools/slcan_bridge.py --busmaster <T0.log> [<T1.log> ...] --vehicle coda
        [--buses b_can,d_can] [--speed 1.0] [--drop-id 0x600] [--tx-log <file>] [--loop]
        [--nmea <dbc>:<message>:<signal>[,<signal>...] --nmea-scale <km/h per unit>]
    py -3.11 tools/slcan_bridge.py --busmaster <logs...> --vehicle coda --selftest [--dump <dir>]
"""
from __future__ import annotations

import argparse
import gzip
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Measured on the car, SLCAN-only build (the deployment configuration).
DEFAULT_RATE = 6705      # bytes/sec
DEFAULT_CHUNK = 1024     # the mbed CDC buffer, and therefore the delivery granularity
DEFAULT_PORT = 9000
SERIAL_BAUD = 460800

# Busmaster mode: frames due within this many seconds of the current one go out in one write.
BATCH_S = 0.005


def load(path: Path) -> bytes:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as fh:
            return fh.read()
    return path.read_bytes()


def serve_file(conn, data, rate, chunk, loop):
    """Write the capture out in chunk-sized bursts, paced to `rate` bytes/sec."""
    sent = 0
    start = time.perf_counter()
    while True:
        pos = 0
        while pos < len(data):
            piece = data[pos:pos + chunk]
            conn.sendall(piece)
            pos += len(piece)
            sent += len(piece)
            if rate > 0:
                # Sleep until this many bytes *should* have gone out, so pacing does not drift.
                target = start + sent / float(rate)
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        if not loop:
            return sent
        # Restart the clock so a looped replay does not try to catch up on the previous pass.
        start = time.perf_counter()
        sent = 0


def serve_serial(conn, port, baud):
    try:
        import serial
    except ImportError:
        sys.exit("pyserial not installed: py -3.12 -m pip install pyserial")
    ser = serial.Serial(port, baud, timeout=0.1)
    sent = 0
    try:
        while True:
            n = ser.in_waiting
            data = ser.read(n if n else 1)
            if data:
                conn.sendall(data)
                sent += len(data)
    finally:
        ser.close()
    return sent


def selftest(data, rate, chunk):
    """Serve to ourselves over loopback and check the bytes arrive intact."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    received = bytearray()

    def client():
        c = socket.create_connection(("127.0.0.1", port))
        while True:
            b = c.recv(65536)
            if not b:
                break
            received.extend(b)
        c.close()

    t = threading.Thread(target=client, daemon=True)
    t.start()
    conn, _ = srv.accept()
    t0 = time.perf_counter()
    serve_file(conn, data, rate, chunk, loop=False)
    conn.close()
    t.join(timeout=30)
    srv.close()
    elapsed = time.perf_counter() - t0

    ok = bytes(received) == data
    print("selftest: sent %d bytes in %.2f s (%.0f B/s)" % (len(data), elapsed,
                                                            len(data) / elapsed if elapsed else 0))
    print("selftest: received %d bytes, identical: %s" % (len(received), "YES" if ok else "NO"))
    if rate > 0:
        expected = len(data) / float(rate)
        print("selftest: pacing target %.2f s, actual %.2f s" % (expected, elapsed))
    return 0 if ok else 1


# ------------------------------------------------------------------ busmaster mode (Coda harness)

def encode_slcan(fid, is_ext, dlc, data):
    """One frame as an SLCAN line, CR included -- the form SlcanReader.kt parses."""
    body = bytes(data[:dlc]).ljust(dlc, b"\x00")
    head = ("T%08X" % fid) if is_ext else ("t%03X" % fid)
    return ("%s%X%s\r" % (head, dlc, body.hex().upper())).encode("ascii")


def decode_slcan(line):
    """(id, is_ext, dlc, data) for a t/T line without its CR, or None if it is not one."""
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not text or text[0] not in "tT":
        return None
    n = 8 if text[0] == "T" else 3
    try:
        fid = int(text[1:1 + n], 16)
        dlc = int(text[1 + n], 16)
        data = bytes.fromhex(text[2 + n:])
    except (ValueError, IndexError):
        return None
    if dlc > 8 or len(data) != dlc:
        return None
    return fid, text[0] == "T", dlc, data


def bus_anchors(vehicle):
    """The vehicle's bus anchor sets, from the one place the project keeps them."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import influx_upload
    return influx_upload.VEHICLE_PROFILES[vehicle]["bus_anchors"]


class Session:
    """A multi-chunk BUSMASTER capture, merged and named by bus, replayable any number of times."""

    def __init__(self, paths, vehicle, buses=None, drop_ids=()):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from canre.utils.buses import resolve_files, describe
        from canre.utils.merge import merge_files
        self._merge = merge_files
        self.paths = [Path(p) for p in paths]
        self.bus_map = resolve_files(self.paths, bus_anchors(vehicle))
        for line in describe(self.bus_map):
            print("  " + line)
        present = sorted({n for m in self.bus_map.values() for n in m.values() if n})
        self.buses = buses or present
        missing = [b for b in self.buses if b not in present]
        if missing:
            sys.exit("bus(es) %s not found in the capture; present: %s" % (missing, present))
        self.index = {b: i for i, b in enumerate(self.buses)}
        self.drop_ids = set(drop_ids)

    def frames(self):
        """(t seconds from the first frame, bus index, id, is_ext, dlc, data), in time order."""
        for f in self._merge(self.paths, bus_map=self.bus_map):
            i = self.index.get(f.bus)
            if i is None or f.arbitration_id in self.drop_ids:
                continue
            yield f.timestamp, i, f.arbitration_id, f.is_extended, f.dlc, bytes(f.data)


class NmeaFeed:
    """
    Speed-only GPS for the emulator: an RMC sentence per second via `adb emu geo nmea`, its speed
    decoded from the replayed frames. The position is a fixed dummy point -- the app reads speed
    only and never position, and nothing real is ever sent.
    """
    LAT, LON = "0000.0000,N", "00000.0000,E"

    def __init__(self, spec, scale, adb):
        import cantools
        dbc, message, signals = spec.split(":")
        db = cantools.database.load_file(dbc, strict=False)
        self.msg = db.get_message_by_name(message)
        self.signals = signals.split(",")
        self.scale = scale
        self.adb = adb
        self.kmh = None
        self.next_t = 0.0
        self.sent = 0

    def observe(self, fid, data):
        if fid != self.msg.frame_id:
            return
        try:
            d = self.msg.decode(data, decode_choices=False)
        except Exception:
            return
        vals = [d[s] for s in self.signals if s in d]
        if vals:
            self.kmh = sum(vals) / len(vals) * self.scale

    def tick(self, now_wall):
        if self.kmh is None or now_wall < self.next_t:
            return
        self.next_t = now_wall + 1.0
        knots = max(self.kmh, 0.0) / 1.852
        utc = time.gmtime(now_wall)
        body = "GPRMC,%s.00,A,%s,%s,%.2f,0.0,%s,,,A" % (
            time.strftime("%H%M%S", utc), self.LAT, self.LON, knots, time.strftime("%d%m%y", utc))
        ck = 0
        for c in body:
            ck ^= ord(c)
        sentence = "$%s*%02X" % (body, ck)
        subprocess.Popen([self.adb, "emu", "geo", "nmea", sentence],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sent += 1


class TxRecorder:
    """Decodes what the app writes back up each stream: its transmitted frames."""

    def __init__(self, bus_names, path):
        self.names = bus_names
        self.fh = open(path, "a", encoding="ascii") if path else None
        self.lock = threading.Lock()
        self.t0 = time.perf_counter()
        self.count = [0] * len(bus_names)

    def start(self, conn, bus):
        threading.Thread(target=self._read, args=(conn, bus), daemon=True).start()

    def _read(self, conn, bus):
        pending = b""
        while True:
            try:
                b = conn.recv(4096)
            except OSError:
                return
            if not b:
                return
            pending += b
            while b"\r" in pending:
                line, pending = pending.split(b"\r", 1)
                f = decode_slcan(line.strip(b"\n"))
                if f is None:
                    continue
                fid, ext, dlc, data = f
                t = time.perf_counter() - self.t0
                text = "%10.3f TX %s 0x%X %s %d %s" % (
                    t, self.names[bus], fid, "x" if ext else "s", dlc, data.hex(" ").upper())
                with self.lock:
                    self.count[bus] += 1
                    print(text)
                    if self.fh:
                        self.fh.write(text + "\n")
                        self.fh.flush()


def accept_all(servers):
    """One client per port, each accepted on its own thread; returns when all are in."""
    conns = [None] * len(servers)

    def take(i):
        c, addr = servers[i].accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conns[i] = c
        print("bus %d client %s:%d connected" % (i, addr[0], addr[1]))

    ts = [threading.Thread(target=take, args=(i,), daemon=True) for i in range(len(servers))]
    for t in ts:
        t.start()
    for t in ts:
        while t.is_alive():
            t.join(0.5)
    return conns


def replay(session, conns, speed, nmea=None):
    """One pass of the session to the connected clients. Returns (frames sent per bus, seconds)."""
    sent = [0] * len(conns)
    bufs = [bytearray() for _ in conns]
    start = time.perf_counter()
    first = None
    for t, bus, fid, ext, dlc, data in session.frames():
        if first is None:
            first = t
        if speed > 0:
            due = start + (t - first) / speed
            if due - time.perf_counter() > BATCH_S:
                for i, b in enumerate(bufs):
                    if b:
                        conns[i].sendall(b)
                        b.clear()
                if nmea:
                    nmea.tick(time.time())
                delay = due - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        bufs[bus] += encode_slcan(fid, ext, dlc, data)
        sent[bus] += 1
        if nmea:
            nmea.observe(fid, data)
        if len(bufs[bus]) > 65536:
            conns[bus].sendall(bufs[bus])
            bufs[bus].clear()
    for i, b in enumerate(bufs):
        if b:
            conns[i].sendall(b)
    return sent, time.perf_counter() - start


def serve_busmaster(args):
    buses = args.buses.split(",") if args.buses else None
    drop = [int(x, 16) for x in args.drop_id]
    session = Session(args.busmaster, args.vehicle, buses, drop)
    nmea = NmeaFeed(args.nmea, args.nmea_scale, args.adb) if args.nmea else None
    servers = []
    for i, name in enumerate(session.buses):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", args.port + i))
        srv.listen(1)
        servers.append(srv)
        print("bus %d = %s on port %d" % (i, name, args.port + i))
    ports = ",".join(str(args.port + i) for i in range(len(servers)))
    print("for the AVD:  adb reverse tcp:<port> tcp:<port> for each of %s" % ports)
    print("              adb shell setprop debug.coda.slcan %s   (then restart the app)" % ports)
    print("replay: %s, dropping %s" % ("%.2fx" % args.speed if args.speed > 0 else "unpaced",
                                        ", ".join("0x%X" % d for d in drop) or "nothing"))
    tx = TxRecorder(session.buses, args.tx_log)
    try:
        while True:
            print("waiting for %d client(s)..." % len(servers))
            conns = accept_all(servers)
            for i, c in enumerate(conns):
                tx.start(c, i)
            try:
                while True:
                    sent, took = replay(session, conns, args.speed, nmea)
                    print("pass done in %.1f s: %s; app transmitted %s" % (
                        took, ", ".join("%s %d" % (session.buses[i], n) for i, n in enumerate(sent)),
                        ", ".join("%s %d" % (session.buses[i], n) for i, n in enumerate(tx.count))))
                    if nmea:
                        print("gps: %d RMC sentences sent" % nmea.sent)
                    if not args.loop:
                        return 0
            except OSError as e:
                print("client disconnected (%s)" % e.__class__.__name__)
            finally:
                for c in conns:
                    c.close()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        for s in servers:
            s.close()
    return 0


def selftest_busmaster(args):
    """
    Serve every bus to loopback clients unpaced, decode what arrives, and compare frame for frame
    with the parsed capture. With --dump, also write what was sent per bus plus the expected
    frames, for the Kotlin side's parity test (SlcanBridgeParityTest, env SLCAN_BRIDGE_DUMP).
    """
    buses = args.buses.split(",") if args.buses else None
    session = Session(args.busmaster, args.vehicle, buses, [int(x, 16) for x in args.drop_id])
    expected = [[] for _ in session.buses]
    for _, bus, fid, ext, dlc, data in session.frames():
        expected[bus].append((fid, ext, dlc, bytes(data[:dlc]).ljust(dlc, b"\x00")))

    servers, received, clients = [], [], []
    for _ in session.buses:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        servers.append(srv)
        received.append(bytearray())
    for i, srv in enumerate(servers):
        def client(port=srv.getsockname()[1], out=received[i]):
            c = socket.create_connection(("127.0.0.1", port))
            while True:
                b = c.recv(65536)
                if not b:
                    break
                out.extend(b)
            c.close()
        t = threading.Thread(target=client, daemon=True)
        t.start()
        clients.append(t)
    conns = accept_all(servers)
    sent, took = replay(session, conns, 0)
    for c in conns:
        c.close()
    for t in clients:
        t.join(60)

    ok = True
    for i, name in enumerate(session.buses):
        got = [decode_slcan(line) for line in bytes(received[i]).split(b"\r") if line]
        same = got == expected[i]
        ok &= same
        print("selftest: %s sent %d, received %d, identical: %s"
              % (name, sent[i], len(got), "YES" if same else "NO"))
    print("selftest: %.1f s unpaced" % took)

    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        manifest = {"source": [str(p.resolve()) for p in session.paths], "buses": [],
                    "drop_ids": sorted(session.drop_ids)}
        for i, name in enumerate(session.buses):
            stream = "bus%d_%s.slcan" % (i, name)
            exp = "bus%d_%s.expected" % (i, name)
            (out / stream).write_bytes(bytes(received[i]))
            with open(out / exp, "w", encoding="ascii") as fh:
                for fid, ext, dlc, data in expected[i]:
                    fh.write("%X %d %d %s\n" % (fid, 1 if ext else 0, dlc, data.hex().upper()))
            manifest["buses"].append({"index": i, "name": name, "stream": stream,
                                      "expected": exp, "frames": len(expected[i])})
        with open(out / "manifest.json", "w", encoding="ascii") as fh:
            json.dump(manifest, fh, indent=1)
        print("selftest: dump written to %s" % out)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="capture to replay (.log or .log.gz)")
    src.add_argument("--serial", metavar="PORT", help="live serial port, read-only (e.g. COM3)")
    src.add_argument("--busmaster", nargs="+", type=Path, metavar="LOG",
                     help="BUSMASTER chunk(s) of one session; one stream per bus (Coda harness)")
    ap.add_argument("--vehicle", default="coda", help="busmaster mode: bus anchor profile")
    ap.add_argument("--buses", help="busmaster mode: bus names in port order (default: sorted)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="busmaster mode: replay speed factor; 0 = unpaced (default 1.0)")
    ap.add_argument("--drop-id", action="append", default=[], metavar="HEX",
                    help="busmaster mode: leave this ID out of the replay (repeatable)")
    ap.add_argument("--tx-log", help="busmaster mode: append the app's transmitted frames here")
    ap.add_argument("--nmea", metavar="DBC:MESSAGE:SIG[,SIG]",
                    help="busmaster mode: feed the emulator speed-only RMC from these signals")
    ap.add_argument("--nmea-scale", type=float, default=1.0, help="km/h per signal unit")
    ap.add_argument("--adb", default="adb", help="adb executable, for --nmea")
    ap.add_argument("--dump", help="busmaster --selftest: write streams + expected frames here")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--rate", type=int, default=DEFAULT_RATE,
                    help="bytes/sec for file replay; 0 = unpaced (default: %d, measured)" % DEFAULT_RATE)
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                    help="bytes per burst (default: %d, the CDC flush size)" % DEFAULT_CHUNK)
    ap.add_argument("--loop", action="store_true", help="replay the capture repeatedly")
    ap.add_argument("--baud", type=int, default=SERIAL_BAUD)
    ap.add_argument("--selftest", action="store_true",
                    help="serve to ourselves over loopback and verify, then exit")
    args = ap.parse_args()

    if args.busmaster:
        sys.exit(selftest_busmaster(args) if args.selftest else serve_busmaster(args))

    data = load(args.file) if args.file else None

    if args.selftest:
        if data is None:
            sys.exit("--selftest needs --file")
        sys.exit(selftest(data, args.rate, args.chunk))

    if data is not None:
        est = len(data) / float(args.rate) if args.rate > 0 else 0
        print("serving %s (%d bytes) on port %d, rate %s, chunk %d%s"
              % (args.file.name, len(data), args.port,
                 ("%d B/s -> %.1f s per pass" % (args.rate, est)) if args.rate > 0 else "unpaced",
                 args.chunk, ", looping" if args.loop else ""))
    else:
        print("serving %s at %d baud on port %d (READ-ONLY -- nothing is written to the VCU)"
              % (args.serial, args.baud, args.port))
    print("for a phone:  adb reverse tcp:%d tcp:%d" % (args.port, args.port))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    try:
        while True:
            print("waiting for a client...")
            conn, addr = srv.accept()
            print("client %s:%d connected" % addr)
            try:
                if data is not None:
                    n = serve_file(conn, data, args.rate, args.chunk, args.loop)
                else:
                    n = serve_serial(conn, args.serial, args.baud)
                print("client finished, %s bytes sent" % n)
            except OSError as e:
                # A client going away is ordinary: BrokenPipeError, ConnectionResetError, and on
                # Windows ConnectionAbortedError (WinError 10053). Catching the specific subset
                # meant an aborted client killed the whole server instead of returning to accept.
                print("client disconnected (%s)" % e.__class__.__name__)
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
