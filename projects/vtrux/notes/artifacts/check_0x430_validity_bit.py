"""
Batch check: for each log, summarize B7 bits[6:5] of 0x430 as a validity indicator.
Shows: total frames, frames with bits[6:5]==00 (valid), ==11, ==01/10 (unexpected),
and transition timeline for bits[6:5].

Usage: py -3.12 check_0x430_validity_bit.py [log1 log2 ...]
       (or pass a directory to scan all .log files)
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))
from canre.parsers import parse_file

MASK = 0x60   # bits 6 and 5

def classify(b7):
    bits65 = (b7 & MASK) >> 5
    if bits65 == 0:
        return 'valid'
    elif bits65 == 3:
        return 'invalid_11'
    else:
        return f'unexpected_{bits65:02b}'

def summarize(log_path):
    try:
        frames = [f for f in parse_file(log_path) if f.arbitration_id == 0x430]
    except Exception as e:
        return f"  ERROR: {e}"

    if not frames:
        return "  (no 0x430 frames)"

    t0 = frames[0].timestamp
    duration = frames[-1].timestamp - t0

    counts = {'valid': 0, 'invalid_11': 0}
    unexpected = {}
    prev_cls = None
    transitions = []

    for f in frames:
        if len(f.data) < 8:
            continue
        b7 = f.data[7]
        cls = classify(b7)
        if cls not in counts:
            unexpected[cls] = unexpected.get(cls, 0) + 1
        else:
            counts[cls] = counts.get(cls, 0) + 1

        if cls != prev_cls:
            transitions.append((f.timestamp - t0, prev_cls, cls, b7))
            prev_cls = cls

    total = len(frames)
    valid_pct = 100 * counts['valid'] / total if total else 0
    inv_pct = 100 * counts['invalid_11'] / total if total else 0

    lines = []
    lines.append(f"  frames={total}, duration={duration:.1f}s, valid={counts['valid']}({valid_pct:.1f}%), "
                 f"invalid_11={counts['invalid_11']}({inv_pct:.1f}%)"
                 + (f", UNEXPECTED={unexpected}" if unexpected else ""))

    # Show transitions (skip the very first None->X transition)
    real_trans = [(t, old, new, b7) for (t, old, new, b7) in transitions if old is not None]
    if real_trans:
        lines.append(f"  transitions (bits[6:5] state changes, t=0 is first 0x430 frame):")
        for t, old, new, b7 in real_trans:
            lines.append(f"    t={t:8.3f}s: {old} -> {new}  (B7=0x{b7:02X}={b7:08b}b)")
    else:
        lines.append(f"  no transitions (first state={transitions[0][2] if transitions else '?'}, stable throughout)")

    # Show first and last B7 values
    first_b7 = frames[0].data[7] if len(frames[0].data) >= 8 else None
    last_b7 = frames[-1].data[7] if len(frames[-1].data) >= 8 else None
    lines.append(f"  first B7=0x{first_b7:02X}({classify(first_b7)}), last B7=0x{last_b7:02X}({classify(last_b7)})")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.12 check_0x430_validity_bit.py <log_or_dir> [...]")
        sys.exit(1)

    paths = []
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            paths += sorted(f for f in (os.path.join(arg, x) for x in os.listdir(arg))
                           if f.endswith('.log'))
        else:
            paths.append(arg)

    for path in paths:
        name = os.path.basename(path)
        print(f"\n{name}")
        print(summarize(path))


if __name__ == '__main__':
    main()
