"""
Plot candidate contiguous signals from 0x06000002 B0-B4 over the overheat test log.
Byte structure from prior analysis:
  B0: multiples of 4 only (bits[1:0]=00). B0>>2 = 6-bit field (0-63).
  B1: groups at {32,96,160,224} +fine. B1[7:6] = 2-bit sub-count.
  B2: full 0-255 range.
  B3: only 5 values {31-35}. Very slowly varying.
  B4: even values only (bit0=0). B4>>1 = 7-bit field (0-127).
  B7: always 0.

Candidate extractions to plot:
  A) B4 raw (proxy for 7-bit motor current/torque amplitude)
  B) B0 raw (proxy for 6-bit field)
  C) B3B4 LE16 (wider range composite, B3=coarse, B4=fine)
  D) B0B1 LE16 centered (wide range, possible bidirectional signal)
  E) B1-B2 LE16 centered (wide range, switches rapidly between extremes)

Events marked:
  t=393s:  pump unplugged
  t=1953s: torque cutback onset
  t=2253s: pump reconnected
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not available -- will write CSV only")

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                   'vtruxdrivetrainoverheattest.log')
OUT_CSV = os.path.join(os.path.dirname(__file__), '0x06000002_signals.csv')
OUT_PNG = os.path.join(os.path.dirname(__file__), '0x06000002_signals.png')

EVENTS = [
    (393,  'pump unplug'),
    (1953, 'torque cutback'),
    (2253, 'pump reconnect'),
]

def rolling_median(vals, w=5):
    """Smooth a list with a rolling window median."""
    result = []
    half = w // 2
    for i in range(len(vals)):
        lo = max(0, i - half)
        hi = min(len(vals), i + half + 1)
        chunk = sorted(vals[lo:hi])
        result.append(chunk[len(chunk)//2])
    return result

def main():
    print("Loading log...")
    frames = [f for f in parse_file(LOG)
              if f.bus == 3 and f.arbitration_id == 0x06000002]
    print(f"  {len(frames)} frames")

    ts = [f.timestamp for f in frames]
    d = [f.data for f in frames]

    # Extract candidate signals
    B0     = [b[0] for b in d]
    B1     = [b[1] for b in d]
    B2     = [b[2] for b in d]
    B3     = [b[3] for b in d]
    B4     = [b[4] for b in d]
    B56_temp = [(b[6]<<2)|(b[5]>>6) for b in d]  # confirmed motor temp, 2C/count

    # 6-bit field from B0
    B0_6bit = [v >> 2 for v in B0]
    # 7-bit field from B4
    B4_7bit = [v >> 1 for v in B4]

    # B3B4 LE16 (B4=lo, B4 is the fine byte with B3 as coarse integer counter)
    # Wait -- LE means B3 is at lower address. B3B4 LE16 = B3|(B4<<8)
    B3B4_LE = [B3[i] | (B4[i] << 8) for i in range(len(d))]

    # B0B1 LE16 centered
    B0B1_LE_c = [(B0[i] | (B1[i] << 8)) - 32768 for i in range(len(d))]

    # B1B2 LE16 centered
    B1B2_LE_c = [(B1[i] | (B2[i] << 8)) - 32768 for i in range(len(d))]

    # Smoothed versions (rolling median, window=9 frames ~0.45s at 20Hz)
    B4_sm   = rolling_median(B4_7bit,   w=9)
    B0_sm   = rolling_median(B0_6bit,   w=9)
    temp_sm = rolling_median(B56_temp,  w=9)

    # Write CSV
    with open(OUT_CSV, 'w') as f:
        f.write('t,B0_raw,B0_6bit,B1,B2,B3,B4_raw,B4_7bit,B3B4_LE,B0B1_LE_c,B1B2_LE_c,temp_2Cpercount\n')
        for i in range(len(ts)):
            f.write(f"{ts[i]:.4f},{B0[i]},{B0_6bit[i]},{B1[i]},{B2[i]},{B3[i]},"
                    f"{B4[i]},{B4_7bit[i]},{B3B4_LE[i]},{B0B1_LE_c[i]},{B1B2_LE_c[i]},"
                    f"{B56_temp[i]}\n")
    print(f"CSV written: {OUT_CSV}")

    if not HAS_MPL:
        print("No matplotlib -- CSV is all output.")
        return

    # --- Plot ---
    fig = plt.figure(figsize=(18, 14))
    gs = gridspec.GridSpec(5, 1, hspace=0.45)
    axes = [fig.add_subplot(gs[i]) for i in range(5)]

    event_kw = dict(color='red', linestyle='--', linewidth=1.2, alpha=0.7)

    def add_events(ax):
        for et, elabel in EVENTS:
            ax.axvline(et, **event_kw)
            ax.text(et+10, ax.get_ylim()[1]*0.92, elabel, fontsize=7, color='red',
                    rotation=90, va='top')

    # Panel 0: Motor temperature (confirmed reference)
    ax = axes[0]
    ax.plot(ts, [v*2 for v in B56_temp], color='darkred', linewidth=0.8, label='Motor temp B5/B6 (deg C)')
    ax.set_ylabel('Motor temp (deg C)')
    ax.set_title('0x06000002 — Confirmed: Motor winding temperature (B5/B6)')
    ax.legend(fontsize=8)
    ax.set_xlim(ts[0], ts[-1])
    ax.grid(True, alpha=0.3)
    for et, _ in EVENTS: ax.axvline(et, **event_kw)

    # Panel 1: B4 (7-bit, raw and smoothed)
    ax = axes[1]
    ax.plot(ts, B4_7bit, color='steelblue', linewidth=0.4, alpha=0.5, label='B4[7:1] raw')
    ax.plot(ts, B4_sm, color='navy', linewidth=1.2, label='B4[7:1] smoothed (w=9)')
    ax.set_ylabel('B4[7:1] (0-127)')
    ax.set_title('B4[7:1] = 7-bit field (even-only byte, bit0=0)')
    ax.legend(fontsize=8)
    ax.set_xlim(ts[0], ts[-1])
    ax.grid(True, alpha=0.3)
    for et, _ in EVENTS: ax.axvline(et, **event_kw)

    # Panel 2: B0 (6-bit)
    ax = axes[2]
    ax.plot(ts, B0_6bit, color='green', linewidth=0.4, alpha=0.5, label='B0[7:2] raw')
    ax.plot(ts, B0_sm, color='darkgreen', linewidth=1.2, label='B0[7:2] smoothed (w=9)')
    ax.set_ylabel('B0[7:2] (0-63)')
    ax.set_title('B0[7:2] = 6-bit field (mult-of-4-only byte, bits[1:0]=0)')
    ax.legend(fontsize=8)
    ax.set_xlim(ts[0], ts[-1])
    ax.grid(True, alpha=0.3)
    for et, _ in EVENTS: ax.axvline(et, **event_kw)

    # Panel 3: B3B4 LE16 (B3 coarse, B4 fine)
    ax = axes[3]
    ax.plot(ts, B3B4_LE, color='purple', linewidth=0.5, alpha=0.6, label='B3|B4<<8 (LE16)')
    ax.set_ylabel('B3B4 LE16')
    ax.set_title('B3B4 as LE16 (B3=coarse {31-35}, B4=fine even)')
    ax.legend(fontsize=8)
    ax.set_xlim(ts[0], ts[-1])
    ax.grid(True, alpha=0.3)
    for et, _ in EVENTS: ax.axvline(et, **event_kw)

    # Panel 4: B1B2 LE16 centered and B0B1 LE16 centered
    ax = axes[4]
    ax.plot(ts, B0B1_LE_c, color='orange', linewidth=0.5, alpha=0.5, label='B0B1 LE16 centered')
    ax.plot(ts, B1B2_LE_c, color='brown', linewidth=0.5, alpha=0.5, label='B1B2 LE16 centered')
    ax.set_ylabel('Centered value')
    ax.set_title('B0B1 and B1B2 as LE16 centered at 32768')
    ax.legend(fontsize=8)
    ax.set_xlim(ts[0], ts[-1])
    ax.grid(True, alpha=0.3)
    ax.set_xlabel('Time (s)')
    for et, _ in EVENTS: ax.axvline(et, **event_kw)

    plt.savefig(OUT_PNG, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"Plot saved: {OUT_PNG}")

if __name__ == '__main__':
    main()
