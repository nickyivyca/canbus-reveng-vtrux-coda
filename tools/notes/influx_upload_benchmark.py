"""Benchmark tools/influx_upload.py against a churny Android Vtrux T0 log.

Captures three independent measurements per run:
  1. Dry-run cProfile      -- Python-side cost, no network in the loop.
  2. Real-upload cProfile  -- total cost incl. network round-trips.
  3. dumpcap pcap of TCP   -- packet-level view of writes to InfluxDB.

Then summarises the cProfile output (top functions by cumulative time) and
the pcap (packet count, bytes, request/response RTT) so we can pick out
whether the bottleneck is parsing, decoding, line-protocol serialization,
or the network.

The test log is vtrux_20260503_171127_T0.log -- the canonical Android
startup churn case (per projects/vtrux/README.md), 13.75 MB / 271k frames /
11 channels. It exercises both the churn filter and a representative
upload volume.

Run: py -3.12 tools/notes/influx_upload_benchmark.py
"""
import sys
sys.path.insert(0, ".")

import pstats
import shutil
import subprocess
import time
from pathlib import Path

LOG = Path("../../CANLogs/VtruxLogs/vtrux_20260503_171127_T0.log")
OUT_DIR = Path("tools/notes/influx_bench")
DUMPCAP = r"C:\Program Files\Wireshark\dumpcap.exe"
CAPINFOS = r"C:\Program Files\Wireshark\capinfos.exe"
TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
NIC = r"\Device\NPF_{76631CB5-04A4-499F-8975-ED8AE689D629}"
INFLUX_HOST = "localhost"
INFLUX_PORT = "8086"
SESSION = "bench_171127_T0"
PY = "py"
PY_ARGS = ["-3.12"]


def run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kwargs)


def profile_run(prof_path: Path, extra_args: list, label: str) -> float:
    print(f"\n=== {label} ===")
    t0 = time.time()
    cmd = [PY, *PY_ARGS, "-m", "cProfile", "-o", str(prof_path),
           "tools/influx_upload.py", str(LOG),
           "--vehicle", "vtrux", "--session", SESSION,
           *extra_args]
    r = run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    print(f"  exit={r.returncode}  elapsed={elapsed:.2f}s")
    if r.returncode != 0:
        print("STDERR (last 30 lines):")
        for line in r.stderr.splitlines()[-30:]:
            print(f"    {line}")
    return elapsed


def summarise_profile(prof_path: Path, label: str, top: int = 25):
    print(f"\n--- {label} top {top} cumulative ---")
    s = pstats.Stats(str(prof_path))
    s.strip_dirs().sort_stats("cumulative").print_stats(top)


def capture_upload(pcap_path: Path) -> tuple[float, int]:
    """Start dumpcap, run real upload with --delete first, stop dumpcap.
    Returns (upload_seconds, exit_code).
    """
    print(f"\n=== real upload + pcap capture ===")
    capture_filter = f"host {INFLUX_HOST} and tcp port {INFLUX_PORT}"
    dump = subprocess.Popen(
        [DUMPCAP, "-i", NIC, "-f", capture_filter,
         "-w", str(pcap_path), "-q"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(2)
    try:
        t0 = time.time()
        cmd = [PY, *PY_ARGS, "tools/influx_upload.py", str(LOG),
               "--vehicle", "vtrux", "--session", SESSION, "--delete"]
        r = run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0
    finally:
        time.sleep(1)
        dump.terminate()
        try:
            dump.wait(timeout=10)
        except subprocess.TimeoutExpired:
            dump.kill()
    print(f"  exit={r.returncode}  elapsed={elapsed:.2f}s")
    if r.returncode != 0:
        print("STDERR (last 30 lines):")
        for line in r.stderr.splitlines()[-30:]:
            print(f"    {line}")
    return elapsed, r.returncode


def summarise_pcap(pcap_path: Path):
    print(f"\n--- pcap summary: {pcap_path.name} ---")
    run([CAPINFOS, "-c", "-d", "-u", "-S", str(pcap_path)])

    print(f"\n--- request/response timing (POST /write) ---")
    run([TSHARK, "-r", str(pcap_path), "-q",
         "-z", "http,tree", "-z", "io,stat,1"])

    print(f"\n--- TCP conversation (single-row summary) ---")
    run([TSHARK, "-r", str(pcap_path), "-q",
         "-z", "conv,tcp"])


def main():
    if not LOG.exists():
        sys.exit(f"Log not found: {LOG}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for tool in (DUMPCAP, CAPINFOS, TSHARK):
        if not Path(tool).exists():
            sys.exit(f"Missing tool: {tool}")

    dry_prof = OUT_DIR / "dry.prof"
    real_prof = OUT_DIR / "real.prof"
    pcap = OUT_DIR / "upload.pcapng"

    dry_elapsed = profile_run(dry_prof, ["--dry-run"], "dry-run cProfile")

    upload_elapsed, exit_code = capture_upload(pcap)
    if exit_code != 0:
        print("Real upload failed -- skipping cProfile pass and pcap analysis.")
        return

    real_elapsed = profile_run(real_prof, ["--delete"], "real-upload cProfile")

    summarise_profile(dry_prof, "dry-run profile")
    summarise_profile(real_prof, "real-upload profile")
    if pcap.exists():
        summarise_pcap(pcap)

    print(f"\n=== summary ===")
    print(f"  dry-run elapsed:      {dry_elapsed:.2f}s")
    print(f"  upload (1st)  elapsed:{upload_elapsed:.2f}s")
    print(f"  upload (prof) elapsed:{real_elapsed:.2f}s")
    overhead = real_elapsed - dry_elapsed
    print(f"  upload-vs-dry overhead: {overhead:.2f}s "
          f"({overhead / max(real_elapsed, 0.01) * 100:.1f}% of real-upload time)")


if __name__ == "__main__":
    main()
