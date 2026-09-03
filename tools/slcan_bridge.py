#!/usr/bin/env python3
"""Serve a 914 VCU SLCAN stream over TCP, from a capture file or a live serial port.

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

ASCII-only output, per the project rules.

Usage:
    py -3.12 tools/slcan_bridge.py --file <capture.log[.gz]> [--loop]
    py -3.12 tools/slcan_bridge.py --serial COM3
    py -3.12 tools/slcan_bridge.py --file <capture> --selftest
"""
from __future__ import annotations

import argparse
import gzip
import socket
import sys
import threading
import time
from pathlib import Path

# Measured on the car, SLCAN-only build (the deployment configuration).
DEFAULT_RATE = 6705      # bytes/sec
DEFAULT_CHUNK = 1024     # the mbed CDC buffer, and therefore the delivery granularity
DEFAULT_PORT = 9000
SERIAL_BAUD = 460800


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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="capture to replay (.log or .log.gz)")
    src.add_argument("--serial", metavar="PORT", help="live serial port, read-only (e.g. COM3)")
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
