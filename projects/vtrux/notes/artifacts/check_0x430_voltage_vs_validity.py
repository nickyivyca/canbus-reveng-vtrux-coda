"""
For 0x430 invalid_11 frames (bits[6:5]=11): what are V_max and V_min doing?
Are they always the 4094 sentinel, or sometimes in a normal LFP range?

Reports voltage distribution within invalid frames, separated by B7 sub-range.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))
from canre.parsers import parse_file
from collections import Counter, defaultdict

MASK = 0x60
LFP_MIN = 2500   # mV -- below this is clearly anomalous
LFP_MAX = 3800   # mV -- above this is clearly anomalous
SENTINEL = 4094  # the known BMS-offline sentinel value

def bits65(b7):
    return (b7 & MASK) >> 5

def analyze(log_path):
    try:
        frames = [f for f in parse_file(log_path) if f.arbitration_id == 0x430 and len(f.data) >= 8]
    except Exception as e:
        return f"  ERROR: {e}"

    if not frames:
        return "  (no 0x430 frames)"

    t0 = frames[0].timestamp

    # Bucket invalid frames by B7 value range
    invalid_frames = [f for f in frames if bits65(f.data[7]) != 0]
    valid_frames   = [f for f in frames if bits65(f.data[7]) == 0]

    def vmax(f): return (f.data[0] & 0x0F) * 256 + f.data[1]
    def vmin(f): return (f.data[2] & 0x0F) * 256 + f.data[3]

    lines = []
    lines.append(f"  invalid frames: {len(invalid_frames)}, valid frames: {len(valid_frames)}")

    if not invalid_frames:
        lines.append("  (no invalid frames to analyze)")
        return "\n".join(lines)

    # Classify invalid frames by voltage content
    sentinel_frames = [f for f in invalid_frames if vmax(f) == SENTINEL]
    in_range_frames = [f for f in invalid_frames if LFP_MIN <= vmax(f) <= LFP_MAX]
    other_frames    = [f for f in invalid_frames if vmax(f) != SENTINEL and not (LFP_MIN <= vmax(f) <= LFP_MAX)]

    lines.append(f"  of those invalid frames:")
    lines.append(f"    sentinel (V_max=4094): {len(sentinel_frames)} ({100*len(sentinel_frames)/len(invalid_frames):.1f}%)")
    lines.append(f"    in LFP range ({LFP_MIN}-{LFP_MAX} mV): {len(in_range_frames)} ({100*len(in_range_frames)/len(invalid_frames):.1f}%)")
    lines.append(f"    other/anomalous: {len(other_frames)} ({100*len(other_frames)/len(invalid_frames):.1f}%)")

    # For in-range invalid frames: show B7 values and voltage stats
    if in_range_frames:
        b7_counts = Counter(f.data[7] for f in in_range_frames)
        vmax_vals = sorted(set(vmax(f) for f in in_range_frames))
        vmin_vals = sorted(set(vmin(f) for f in in_range_frames))
        t_range = (in_range_frames[0].timestamp - t0, in_range_frames[-1].timestamp - t0)
        lines.append(f"    in-range invalid details:")
        lines.append(f"      B7 values: {dict(sorted(b7_counts.items()))}")
        lines.append(f"      V_max range: {min(vmax_vals)}-{max(vmax_vals)} mV")
        lines.append(f"      V_min range: {min(vmin_vals)}-{max(vmin_vals)} mV")
        lines.append(f"      time span: t={t_range[0]:.3f}s to t={t_range[1]:.3f}s")

        # Show first few and last few of these frames
        show = in_range_frames[:5] + (in_range_frames[-3:] if len(in_range_frames) > 5 else [])
        lines.append(f"      sample frames (t, B7, V_max, V_min):")
        shown = set()
        for f in show:
            key = id(f)
            if key not in shown:
                shown.add(key)
                lines.append(f"        t={f.timestamp-t0:.3f}s  B7=0x{f.data[7]:02X}={f.data[7]:08b}b  V_max={vmax(f)}  V_min={vmin(f)}")

    if other_frames:
        lines.append(f"    other/anomalous details:")
        for f in other_frames[:5]:
            lines.append(f"      t={f.timestamp-t0:.3f}s  B7=0x{f.data[7]:02X}  V_max={vmax(f)}  V_min={vmin(f)}")

    return "\n".join(lines)


logs = [
    "projects/vtrux/logs/vtruxcurrentlimitingtest.log",
    "projects/vtrux/logs/vtruxevapdrivelog4.log",
    "projects/vtrux/logs/vtruxgeneratoroverheattest.log",
    "projects/vtrux/logs/vtruxinterlocktest.log",
    "projects/vtrux/logs/vtruxinterlocktest2.log",
    "projects/vtrux/logs/vtruxisolationtest.log",
    "projects/vtrux/logs/vtruxisolationtestrecovery.log",
    "projects/vtrux/logs/vtruxchargeafterucsc4.log",
    "projects/vtrux/logs/vtruxchargeblueevse.log",
    "projects/vtrux/logs/vtruxunplugpumpthenhvbatterylvconnector.log",
    "projects/vtrux/logs/vtruxunpluggedpumpoverheattest.log",
    "projects/vtrux/logs/vtruxdrivetrainoverheattest.log",
    "projects/vtrux/logs/vtruxscottsvalleydrive.log",
]

for path in logs:
    print(f"\n{os.path.basename(path)}")
    print(analyze(path))
