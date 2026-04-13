"""
find_483_484_msb.py

Hunt for the MSB / carry bit that extends 0x483 B0 and 0x484 B0 beyond 255.

Method:
  For each candidate byte/bit in the same message, test whether
  (candidate_val << 8) | B0 (or variants) is monotonically increasing
  across the full overheat test log.

  Also tests multi-bit carry fields (lower nibble, upper nibble, full byte offset).

  Plots all bytes of both messages for visual inspection.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/find_483_484_msb.py
"""

import sys, math
from collections import defaultdict
sys.path.insert(0, '.')
from canre.parsers import parse_file

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("matplotlib not available")

LOG = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
OUT_TXT = "projects/vtrux/notes/artifacts/find_483_484_msb.txt"
OUT_PNG = "projects/vtrux/notes/artifacts/find_483_484_msb.png"

TARGET_IDS = [0x483, 0x484]

KEY_TIMES = [393, 1953, 2253]


def monotonicity_score(vals):
    """Fraction of consecutive pairs that are non-decreasing."""
    if len(vals) < 2:
        return 0.0
    nd = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
    return nd / (len(vals) - 1)


def max_drop(vals):
    """Largest single-step drop (for diagnosing wrap artifacts)."""
    if len(vals) < 2:
        return 0
    return max(a - b for a, b in zip(vals, vals[1:]) if a > b) if any(a > b for a, b in zip(vals, vals[1:])) else 0


def main():
    print("Parsing log (PT bus only)...")
    frames = defaultdict(list)  # id -> [(t, data)]
    pt_bus = None

    for frame in parse_file(LOG):
        if pt_bus is None and frame.arbitration_id == 0x051:
            pt_bus = frame.bus
        if pt_bus is not None and frame.bus != pt_bus:
            continue
        if frame.arbitration_id in TARGET_IDS:
            frames[frame.arbitration_id].append((frame.timestamp, bytes(frame.data)))

    print(f"  PT bus = {pt_bus}")
    for tid in TARGET_IDS:
        print(f"  0x{tid:X}: {len(frames[tid])} frames")

    results = []

    for tid in TARGET_IDS:
        data = frames[tid]
        if not data:
            continue
        times  = [t for t, _ in data]
        payloads = [d for _, d in data]
        dlc = len(payloads[0])

        b0 = [p[0] for p in payloads]

        # --- Visual: plot all raw bytes ---
        fig, axes = plt.subplots(dlc, 1, figsize=(14, 2.0 * dlc), sharex=True)
        if dlc == 1:
            axes = [axes]
        for bi in range(dlc):
            vals = [p[bi] if bi < len(p) else 0 for p in payloads]
            axes[bi].plot(times, vals, linewidth=0.6, color='steelblue')
            axes[bi].set_ylabel(f'B{bi}', fontsize=8)
            axes[bi].grid(True, alpha=0.3)
            for kt in KEY_TIMES:
                axes[bi].axvline(kt, color='red', linestyle='--', linewidth=0.6, alpha=0.6)
        axes[-1].set_xlabel('Time (s)', fontsize=9)
        fig.suptitle(f'0x{tid:X} -- all bytes raw\nvtruxdrivetrainoverheattest.log', fontsize=10)
        plt.tight_layout()
        png = OUT_PNG.replace('.png', f'_0x{tid:X}.png')
        plt.savefig(png, dpi=120, bbox_inches='tight')
        plt.close()
        print(f"  Saved {png}")

        # --- Carry-bit search ---
        # For each byte bi (bi != 0) and each bit k within that byte,
        # test: combined = (extracted_field << 8) | B0
        # where extracted_field cycles: 0, 1, 2, ... in sync with B0 overflows.

        print(f"\n  0x{tid:X} carry-bit search:")
        print(f"  {'Carry field':35}  {'mono%':>6}  {'max_drop':>8}  {'n_overflows':>11}  {'range':>12}")
        print("  " + "-" * 80)

        for bi in range(1, dlc):
            bx = [p[bi] if bi < len(p) else 0 for p in payloads]

            # 1. Single bit carries: bit k of byte bi
            for k in range(8):
                carry = [(v >> k) & 1 for v in bx]
                combined = [c << 8 | b for c, b in zip(carry, b0)]
                ms = monotonicity_score(combined)
                md = max_drop(combined)
                n_overflows = sum(1 for a, b in zip(combined, combined[1:]) if b - a < -200)
                results.append({
                    'id': tid, 'field': f'B{bi} bit{k}',
                    'combined': combined, 'times': times,
                    'mono': ms, 'max_drop': md, 'n_overflows': n_overflows,
                    'range': (min(combined), max(combined)),
                })
                if ms > 0.95:
                    rng = f"{min(combined)}-{max(combined)}"
                    print(f"  B{bi} bit{k}{'':28}  {ms:6.3f}  {md:8d}  {n_overflows:11d}  {rng:>12}  ***")

            # 2. Lower nibble (bits 3:0)
            carry = [v & 0x0F for v in bx]
            combined = [c << 8 | b for c, b in zip(carry, b0)]
            ms = monotonicity_score(combined)
            md = max_drop(combined)
            n_overflows = sum(1 for a, b in zip(combined, combined[1:]) if b - a < -200)
            results.append({
                'id': tid, 'field': f'B{bi} lo-nib',
                'combined': combined, 'times': times,
                'mono': ms, 'max_drop': md, 'n_overflows': n_overflows,
                'range': (min(combined), max(combined)),
            })
            if ms > 0.95:
                rng = f"{min(combined)}-{max(combined)}"
                print(f"  B{bi} lo-nib{'':28}  {ms:6.3f}  {md:8d}  {n_overflows:11d}  {rng:>12}  ***")

            # 3. Upper nibble (bits 7:4)
            carry = [(v >> 4) & 0x0F for v in bx]
            combined = [c << 8 | b for c, b in zip(carry, b0)]
            ms = monotonicity_score(combined)
            md = max_drop(combined)
            n_overflows = sum(1 for a, b in zip(combined, combined[1:]) if b - a < -200)
            results.append({
                'id': tid, 'field': f'B{bi} hi-nib',
                'combined': combined, 'times': times,
                'mono': ms, 'max_drop': md, 'n_overflows': n_overflows,
                'range': (min(combined), max(combined)),
            })
            if ms > 0.95:
                rng = f"{min(combined)}-{max(combined)}"
                print(f"  B{bi} hi-nib{'':28}  {ms:6.3f}  {md:8d}  {n_overflows:11d}  {rng:>12}  ***")

            # 4. Full byte as carry (offset-subtracted to start at 0)
            carry_raw = bx
            carry_min = min(carry_raw)
            carry = [v - carry_min for v in carry_raw]
            combined = [c << 8 | b for c, b in zip(carry, b0)]
            ms = monotonicity_score(combined)
            md = max_drop(combined)
            n_overflows = sum(1 for a, b in zip(combined, combined[1:]) if b - a < -200)
            results.append({
                'id': tid, 'field': f'B{bi} full (off={carry_min})',
                'combined': combined, 'times': times,
                'mono': ms, 'max_drop': md, 'n_overflows': n_overflows,
                'range': (min(combined), max(combined)),
            })
            if ms > 0.95:
                rng = f"{min(combined)}-{max(combined)}"
                print(f"  B{bi} full (off={carry_min}){'':20}  {ms:6.3f}  {md:8d}  {n_overflows:11d}  {rng:>12}  ***")

    # Print top results sorted by mono score
    results.sort(key=lambda x: -x['mono'])
    lines = [
        "0x483 / 0x484 B0 MSB carry search",
        "Ranked by monotonicity score (fraction of non-decreasing steps)",
        "",
        f"{'ID':>6}  {'Field':35}  {'mono%':>6}  {'max_drop':>8}  {'n_overflows':>11}  {'range':>14}",
        "-" * 90,
    ]
    for r in results[:40]:
        lines.append(
            f"0x{r['id']:X}  {r['field']:35}  {r['mono']:6.3f}  {r['max_drop']:8d}  "
            f"{r['n_overflows']:11d}  {r['range'][0]:6d}-{r['range'][1]:6d}"
        )
    output = "\n".join(lines)
    with open(OUT_TXT, 'w', encoding='ascii') as f:
        f.write(output)
    print(f"\nTop results written to {OUT_TXT}")

    # Plot top 5 combined signals per ID
    for tid in TARGET_IDS:
        top = [r for r in results if r['id'] == tid][:6]
        if not top:
            continue
        fig, axes = plt.subplots(len(top) + 1, 1, figsize=(14, 2.2 * (len(top) + 1)), sharex=True)
        # Row 0: raw B0
        raw_b0 = [(t, p[0]) for t, p in frames[tid]]
        axes[0].plot([t for t,_ in raw_b0], [v for _,v in raw_b0],
                     color='black', linewidth=0.6)
        axes[0].set_ylabel('B0 raw', fontsize=8)
        axes[0].set_title(f'0x{tid:X} B0 raw + top carry candidates', fontsize=9, loc='left')
        axes[0].grid(True, alpha=0.3)
        for kt in KEY_TIMES:
            axes[0].axvline(kt, color='red', linestyle='--', linewidth=0.6, alpha=0.6)

        colors = ['red','blue','green','orange','purple','brown']
        for i, (ax, r) in enumerate(zip(axes[1:], top)):
            ax.plot(r['times'], r['combined'], color=colors[i % len(colors)], linewidth=0.6)
            ax.set_ylabel('combined', fontsize=7)
            ax.set_title(f"{r['field']}  mono={r['mono']:.3f}  drop={r['max_drop']}",
                         fontsize=8, loc='left', pad=1)
            ax.grid(True, alpha=0.3)
            for kt in KEY_TIMES:
                ax.axvline(kt, color='red', linestyle='--', linewidth=0.6, alpha=0.6)

        axes[-1].set_xlabel('Time (s)', fontsize=9)
        plt.tight_layout()
        png = OUT_PNG.replace('.png', f'_carry_0x{tid:X}.png')
        plt.savefig(png, dpi=120, bbox_inches='tight')
        plt.close()
        print(f"  Saved {png}")


if __name__ == '__main__':
    main()
