"""
Investigate BELINV_overallTemperaturePercent encoding in 0x18FFD5C0.
Question: is it 8-bit (B6 only) as EPRI Ghidra decompile says,
or 16-bit (B6:B7 LE) as the original manufacturer DBC has?

Usage:
    py -3.12 projects/vtrux/notes/artifacts/bel_temp_percent_check.py
"""

import re

LOG = "projects/vtrux/logs/full charge then fail.log"

def main():
    frames = []
    with open(LOG, encoding="latin-1") as f:
        for line in f:
            m = re.match(r"(\d+:\d+:\d+:\d+)\s+Rx\s+\S+\s+0x18FFD5C0\s+x\s+8\s+(.+)", line)
            if not m:
                continue
            ts = m.group(1)
            b = [int(x, 16) for x in m.group(2).split()]
            # B4:B5 = BDC temperature (signed int16 LE, scale 0.1)
            raw_t = b[4] | (b[5] << 8)
            if raw_t >= 0x8000:
                raw_t -= 0x10000
            temp_c = raw_t * 0.1
            # 8-bit interpretation: B6 only
            pct8 = b[6]
            # 16-bit interpretation: LE uint16(B6:B7)
            pct16 = b[6] | (b[7] << 8)
            frames.append((ts, temp_c, pct8, pct16, b[6], b[7]))

    print(f"Total 0x18FFD5C0 frames: {len(frames)}")
    print()

    b6_unique = sorted(set(f[4] for f in frames))
    b7_unique = sorted(set(f[5] for f in frames))
    print(f"B6 unique values ({len(b6_unique)}): {b6_unique}")
    print(f"B7 unique values ({len(b7_unique)}): {b7_unique}")
    print()

    pct8_min  = min(f[2] for f in frames)
    pct8_max  = max(f[2] for f in frames)
    pct16_min = min(f[3] for f in frames)
    pct16_max = max(f[3] for f in frames)
    print(f"pct8  range: {pct8_min} - {pct8_max} %")
    print(f"pct16 range: {pct16_min} - {pct16_max} %")
    print()

    print("Sample every ~300 frames:")
    print(f"  {'timestamp':>14}  {'BDC_temp':>8}  B6  B7  pct8  pct16")
    for i in range(0, len(frames), max(1, len(frames) // 25)):
        ts, temp, p8, p16, b6, b7 = frames[i]
        print(f"  {ts:>14}  {temp:>7.1f}C  {b6:3d} {b7:3d}  {p8:4d}  {p16:5d}")


def b7_nonzero():
    frames = []
    with open(LOG, encoding="latin-1") as f:
        for line in f:
            m = re.match(r"(\d+:\d+:\d+:\d+)\s+Rx\s+\S+\s+0x18FFD5C0\s+x\s+8\s+(.+)", line)
            if not m:
                continue
            ts = m.group(1)
            b = [int(x, 16) for x in m.group(2).split()]
            raw_t = b[4] | (b[5] << 8)
            if raw_t >= 0x8000:
                raw_t -= 0x10000
            temp_c = raw_t * 0.1
            frames.append((ts, temp_c, b[6], b[7]))

    nonzero = [(i, ts, temp, b6, b7) for i, (ts, temp, b6, b7) in enumerate(frames) if b7 != 0]
    print(f"B7 non-zero frames: {len(nonzero)}")
    print(f"{'idx':>6}  {'timestamp':>14}  {'BDC_temp':>8}  B6  B7  prev_B7  next_B7")
    for idx, ts, temp, b6, b7 in nonzero:
        prev_b7 = frames[idx-1][3] if idx > 0 else -1
        next_b7 = frames[idx+1][3] if idx < len(frames)-1 else -1
        print(f"  {idx:6d}  {ts:>14}  {temp:>7.1f}C  {b6:3d} {b7:3d}   prev={prev_b7}  next={next_b7}")


if __name__ == "__main__":
    b7_nonzero()
