import sys
sys.path.insert(0, '.')
from canre.parsers.autodetect import parse_file

log = "projects/vtrux/logs/generator on then off.log"

frames_by_bus = {}
for f in parse_file(log):
    if f.bus not in frames_by_bus:
        frames_by_bus[f.bus] = []
    frames_by_bus[f.bus].append(f)

BITRATE = 500_000

for bus, frames in sorted(frames_by_bus.items()):
    duration = frames[-1].timestamp - frames[0].timestamp
    total_bits = 0
    for f in frames:
        if f.is_extended:
            overhead = 67
        else:
            overhead = 47
        data_bits = f.dlc * 8
        raw_bits = overhead + data_bits
        stuffed_bits = raw_bits + raw_bits // 4
        total_bits += stuffed_bits

    utilization = total_bits / (BITRATE * duration) * 100
    fps = len(frames) / duration
    avg_dlc = sum(f.dlc for f in frames) / len(frames)
    print(f"Bus {bus}: {len(frames):,} frames  {fps:.0f} fps  avg DLC {avg_dlc:.1f}  duration {duration:.1f}s  utilization ~{utilization:.1f}%")
