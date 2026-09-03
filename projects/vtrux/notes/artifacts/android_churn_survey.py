"""Survey Android Vtrux T0 logs for the bus-number churn artifact.

Per projects/vtrux/README.md "Bus number churn in Android T0": each USB
reconnect on the Android logger spawns a new bus number that briefly
carries a few frames. T0 captures from such sessions show many distinct
bus numbers; only the one with sustained high frame counts is the real
PT bus.

This script walks ../../CANLogs/VtruxLogs/, parses each T0 log once with
canre.parsers.parse_file, tallies frames per bus, and writes a CSV ranked
by the noisiness (number of channels with >0 frames). Run with:

    py -3.12 projects/vtrux/notes/artifacts/android_churn_survey.py
"""
import sys
sys.path.insert(0, ".")

import csv
import time
from collections import defaultdict
from pathlib import Path

from canre.parsers import parse_file

LOGS_DIR = Path("../../CANLogs/VtruxLogs")
OUT_CSV = Path("projects/vtrux/notes/artifacts/android_churn_survey.csv")


def survey_log(path: Path) -> dict:
    counts: dict[int, int] = defaultdict(int)
    saw_anchor: dict[int, bool] = defaultdict(bool)
    t_start = time.time()
    n_frames = 0
    try:
        for f in parse_file(path):
            counts[f.bus] += 1
            if f.arbitration_id == 0x051:
                saw_anchor[f.bus] = True
            n_frames += 1
    except Exception as exc:
        return {"path": path.name, "error": str(exc), "frames": n_frames,
                "channels": 0, "anchor_channels": 0, "elapsed_s": time.time() - t_start}
    return {
        "path": path.name,
        "frames": n_frames,
        "channels": len(counts),
        "anchor_channels": sum(saw_anchor.values()),
        "elapsed_s": round(time.time() - t_start, 2),
        "size_mb": round(path.stat().st_size / 1e6, 2),
        "counts": dict(counts),
    }


def main():
    t0_logs = sorted(p for p in LOGS_DIR.iterdir()
                     if p.is_file() and p.name.endswith("_T0.log"))
    print(f"Surveying {len(t0_logs)} T0 logs ...")

    rows = []
    for i, path in enumerate(t0_logs):
        if i % 50 == 0:
            print(f"  [{i}/{len(t0_logs)}] {path.name}")
        rows.append(survey_log(path))

    rows.sort(key=lambda r: (-r.get("channels", 0), -r.get("frames", 0)))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["log", "size_mb", "frames", "channels",
                    "anchor_channels", "elapsed_s", "channel_breakdown"])
        for r in rows:
            counts = r.get("counts", {})
            breakdown = ";".join(f"ch{k}={v}" for k, v in
                                 sorted(counts.items(), key=lambda kv: -kv[1]))
            w.writerow([r["path"], r.get("size_mb", ""), r.get("frames", 0),
                        r.get("channels", 0), r.get("anchor_channels", 0),
                        r.get("elapsed_s", ""), breakdown])

    churny = [r for r in rows if r.get("channels", 0) >= 5]
    print(f"\nFound {len(churny)} logs with >= 5 distinct channels.")
    print("\nTop 20 churniest:")
    for r in rows[:20]:
        print(f"  {r['path']:<50} channels={r.get('channels', 0):>3} "
              f"frames={r.get('frames', 0):>8} size={r.get('size_mb', 0):>6} MB")

    print(f"\nWrote: {OUT_CSV}")


if __name__ == "__main__":
    main()
