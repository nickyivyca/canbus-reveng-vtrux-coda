"""Benchmark tools/influx_upload.py against the FULL 171127 T0-T12 series.

The 171127 series is the canonical Android churn case (vtrux.md):
  - T0 = 13.75 MB with 11 channels of bus-number churn (the startup artifact)
  - T1..T12 = stable single-bus captures, ~48 MB each
  - Total ~533 MB / ~12M frames across 13 files

Each file goes through its own scan_log + stream_and_write cycle, so this
exercises the per-file overhead (DBC reload is one-shot but the scan pass
runs 13 times). Useful for amortised throughput and for confirming that the
network-vs-Python ratio holds at larger volumes.

Run: py -3.12 tools/notes/influx_upload_benchmark_series.py
"""
import sys
sys.path.insert(0, ".")

import pstats
import subprocess
import time
from pathlib import Path

LOGS_DIR = Path("../../CANLogs/VtruxLogs")
SERIES_GLOB = "../../CANLogs/VtruxLogs/vtrux_20260503_171127_T*.log"
SERIES_PREFIX = "vtrux_20260503_171127_T"
OUT_DIR = Path("tools/notes/influx_bench_series")
DUMPCAP = r"C:\Program Files\Wireshark\dumpcap.exe"
CAPINFOS = r"C:\Program Files\Wireshark\capinfos.exe"
TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
NIC = r"\Device\NPF_{76631CB5-04A4-499F-8975-ED8AE689D629}"
INFLUX_HOST = "localhost"
INFLUX_PORT = "8086"
SESSION_PREFIX = "bench_series_171127"
PY = "py"
PY_ARGS = ["-3.12"]


def find_series() -> list[Path]:
    files = sorted(LOGS_DIR.glob(f"{SERIES_PREFIX}*.log"),
                   key=lambda p: int(p.stem.rsplit("_T", 1)[1]))
    return files


def run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd[:6])} ... [{len(cmd)-6} more args]"
          if len(cmd) > 8 else f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kwargs)


def upload_with_pcap(series_glob: str, pcap_path: Path,
                     prof_path: Path | None) -> tuple[float, int]:
    """Capture TCP traffic while running the real upload over the whole series.

    Passes the glob pattern through to influx_upload.py so it can do its own
    expansion -- no need to enumerate the file list here.
    """
    capture_filter = f"host {INFLUX_HOST} and tcp port {INFLUX_PORT}"
    print(f"\n=== capture + real upload ({series_glob}) ===")
    print(f"  pcap : {pcap_path.name}")
    if prof_path:
        print(f"  prof : {prof_path.name}")
    dump = subprocess.Popen(
        [DUMPCAP, "-i", NIC, "-f", capture_filter,
         "-w", str(pcap_path), "-q",
         "-b", "filesize:1000000"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(2)
    try:
        t0 = time.time()
        cmd = [PY, *PY_ARGS]
        if prof_path:
            cmd += ["-m", "cProfile", "-o", str(prof_path)]
        cmd += ["tools/influx_upload.py", series_glob,
                "--vehicle", "vtrux", "--session", SESSION_PREFIX, "--delete"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0
    finally:
        time.sleep(1)
        dump.terminate()
        try:
            dump.wait(timeout=15)
        except subprocess.TimeoutExpired:
            dump.kill()
    print(f"  exit={r.returncode}  elapsed={elapsed:.2f}s "
          f"({elapsed/60:.1f} min)")
    if r.returncode != 0:
        print("STDERR (last 30 lines):")
        for line in r.stderr.splitlines()[-30:]:
            print(f"    {line}")
    stdout_path = pcap_path.with_suffix(".stdout.txt")
    stdout_path.write_text(r.stdout, encoding="utf-8")
    print(f"  upload stdout saved: {stdout_path.name}")
    return elapsed, r.returncode


def summarise_profile(prof_path: Path, top: int = 30):
    print(f"\n--- {prof_path.name} top {top} cumulative ---")
    s = pstats.Stats(str(prof_path))
    s.strip_dirs().sort_stats("cumulative").print_stats(top)


def summarise_pcap(pcap_glob: list[Path]):
    if not pcap_glob:
        print("  no pcap files found")
        return
    print(f"\n--- pcap files: {len(pcap_glob)} ---")
    for p in pcap_glob:
        print(f"    {p.name} ({p.stat().st_size / 1e6:.1f} MB)")
    primary = pcap_glob[0]
    print(f"\n--- capinfos {primary.name} ---")
    run([CAPINFOS, "-c", "-d", "-u", "-S", str(primary)])


def main():
    files = find_series()
    if not files:
        sys.exit(f"No files matching {SERIES_PREFIX}*.log in {LOGS_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_mb = sum(f.stat().st_size for f in files) / 1e6
    print(f"Series: {len(files)} files, {total_mb:.1f} MB total (glob expansion done by influx_upload.py)")
    for f in files:
        print(f"  {f.name:<40} {f.stat().st_size / 1e6:>7.2f} MB")

    pcap = OUT_DIR / "series_upload.pcapng"
    prof = OUT_DIR / "series_real.prof"

    elapsed, rc = upload_with_pcap(SERIES_GLOB, pcap, prof)
    if rc != 0:
        print("Upload failed -- skipping post-analysis.")
        return

    pcap_glob = sorted(OUT_DIR.glob("series_upload*.pcapng"))
    summarise_pcap(pcap_glob)
    if prof.exists():
        summarise_profile(prof, top=30)

    print(f"\n=== summary ===")
    print(f"  files:           {len(files)}")
    print(f"  total bytes:     {total_mb:.1f} MB")
    print(f"  upload elapsed:  {elapsed:.2f}s ({elapsed/60:.1f} min)")
    print(f"  throughput:      {total_mb/elapsed:.2f} MB/s of input log")


if __name__ == "__main__":
    main()
