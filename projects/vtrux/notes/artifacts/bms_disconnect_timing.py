"""
Check exact last-frame timing for BMS IDs around the t=75s HV battery LV connector disconnect.
Also checks for any messages that briefly continue after the disconnect (call-and-response stragglers).
Phase 2: full-log timeline for 0x460 to understand its anomalous late dropout.
"""
import sys
sys.path.insert(0, r"<repo>")
from canre.parsers.autodetect import parse_file

LOG = r"<repo>\projects\vtrux\logs\vtruxunplugpumpthenhvbatterylvconnector.log"

BMS_IDS = [0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
           0x400,
           0x410, 0x411, 0x412,
           0x420, 0x430, 0x440, 0x460,
           0x506, 0x507]

WINDOW_START = 70.0
WINDOW_END   = 85.0

frames_by_id = {arb_id: [] for arb_id in BMS_IDS}
frames_460_full = []

for frame in parse_file(LOG):
    if frame.arbitration_id == 0x460:
        frames_460_full.append(frame.timestamp)
    if WINDOW_START <= frame.timestamp <= WINDOW_END:
        if frame.arbitration_id in frames_by_id:
            frames_by_id[frame.arbitration_id].append(frame.timestamp)

print("BMS ID last-frame timing around t=75s disconnect")
print("=" * 60)
print(f"{'ID':>10}  {'First in window':>16}  {'Last in window':>14}  {'Count':>6}")
print("-" * 60)
for arb_id in BMS_IDS:
    ts_list = frames_by_id[arb_id]
    if ts_list:
        flag = "  <<< LATE DROPOUT" if ts_list[-1] > 76.0 else ""
        print(f"0x{arb_id:03X}  {ts_list[0]:>16.4f}  {ts_list[-1]:>14.4f}  {len(ts_list):>6}{flag}")
    else:
        print(f"0x{arb_id:03X}  {'(no frames in window)':>34}")

print()
print("Fine-grained view 74-77s:")
print("=" * 60)
fine_by_id = {arb_id: [] for arb_id in BMS_IDS}
for frame in parse_file(LOG):
    if 74.0 <= frame.timestamp <= 77.0:
        if frame.arbitration_id in fine_by_id:
            fine_by_id[frame.arbitration_id].append(frame.timestamp)

for arb_id in BMS_IDS:
    ts_list = fine_by_id[arb_id]
    if ts_list:
        gaps = [ts_list[i+1]-ts_list[i] for i in range(len(ts_list)-1)]
        last_gap = f"{gaps[-1]*1000:.1f}ms gap before last" if gaps else "only 1 frame"
        flag = "  <<< LATE" if ts_list[-1] > 76.0 else ""
        print(f"0x{arb_id:03X}  last={ts_list[-1]:.4f}s  n={len(ts_list):3d}  {last_gap}{flag}")
    else:
        print(f"0x{arb_id:03X}  (no frames)")

print()
print("0x460 full-log presence (presence gaps > 2s shown as breaks):")
print("=" * 60)
if frames_460_full:
    segments = []
    seg_start = frames_460_full[0]
    seg_end = frames_460_full[0]
    for i in range(1, len(frames_460_full)):
        gap = frames_460_full[i] - frames_460_full[i-1]
        if gap > 2.0:
            segments.append((seg_start, seg_end, frames_460_full[i-1] - seg_start))
            seg_start = frames_460_full[i]
        seg_end = frames_460_full[i]
    segments.append((seg_start, seg_end, seg_end - seg_start))
    for s, e, dur in segments:
        print(f"  present {s:.2f}s -> {e:.2f}s  ({dur:.2f}s duration)")
    print(f"  Total frames: {len(frames_460_full)}")
