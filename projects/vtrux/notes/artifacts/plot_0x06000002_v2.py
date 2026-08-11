"""
Cleaner plot of 0x06000002 B0-B4 candidate signals.
Uses 2s rolling mean (40-sample window at 20Hz) to suppress ADC dither.
Shows confirmed motor torque (0x5A2) and RPM side by side for alignment.

B1 and B2 are sequencing/counter bytes — confirmed by delta analysis:
  B1[7:6] steps +-1 each change (2-bit rolling sub-counter)
  B2 increments/decrements by 1 (byte counter)
  These do NOT carry physical measurements — excluded from signal plot.

B7 = always 0, excluded.

Candidates:
  B4[7:1] — 7-bit field (bit0 always 0); rapidly varying; appears non-zero when motor active
  B0[7:2] — 6-bit field (bits[1:0] always 0); more slowly varying
  B3      — 5 unique values {31-35}; very slow (ambient temp or slow status)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                   'vtruxdrivetrainoverheattest.log')
OUT = os.path.join(os.path.dirname(__file__), '0x06000002_v2.png')

EVENTS = [(393,'pump unplug'), (1953,'torque cutback'), (2253,'pump reconnect')]
EV_KW = dict(color='red', linestyle='--', linewidth=1.2, alpha=0.75)

def rolling_mean(ts, vals, window_s=2.0):
    """Time-based rolling mean over a window_s second window."""
    result = []
    n = len(ts)
    for i in range(n):
        lo = i
        while lo > 0 and ts[i] - ts[lo-1] <= window_s:
            lo -= 1
        chunk = vals[lo:i+1]
        result.append(sum(chunk)/len(chunk))
    return result

def add_events(ax):
    for et, elabel in EVENTS:
        ax.axvline(et, **EV_KW)
        ylo, yhi = ax.get_ylim()
        ax.text(et+8, ylo + (yhi-ylo)*0.88, elabel, fontsize=7,
                color='red', rotation=90, va='top')

def main():
    print("Loading log...")
    all_frames = list(parse_file(LOG))
    bus3 = [f for f in all_frames if f.bus == 3]

    t_frames  = [f for f in bus3 if f.arbitration_id == 0x06000002]
    ref_frames = [f for f in bus3 if f.arbitration_id == 0x5A2]

    print(f"  0x06000002: {len(t_frames)} frames")
    print(f"  0x5A2:      {len(ref_frames)} frames")

    ts  = [f.timestamp for f in t_frames]
    B0  = [f.data[0] for f in t_frames]
    B3  = [f.data[3] for f in t_frames]
    B4  = [f.data[4] for f in t_frames]
    temp = [(f.data[6]<<2)|(f.data[5]>>6) for f in t_frames]  # 2C/count

    # Derived 6-bit and 7-bit fields
    B0_6 = [v >> 2 for v in B0]   # 0-63
    B4_7 = [v >> 1 for v in B4]   # 0-127

    # 2-second rolling means
    B0_sm  = rolling_mean(ts, B0_6,  2.0)
    B4_sm  = rolling_mean(ts, B4_7,  2.0)
    temp_sm = rolling_mean(ts, [v*2 for v in temp], 2.0)

    # Reference signals from 0x5A2 (interpolated to target timestamps)
    ts_ref = [f.timestamp for f in ref_frames]
    rpm_ref = [(f.data[2]|(f.data[3]<<8)) - 32768 for f in ref_frames]
    trq_ref = [(f.data[4]|(f.data[5]<<8)) - 32768 for f in ref_frames]

    def interp_ref(ts_q, ts_r, vals_r):
        result = []
        j = 0
        n = len(ts_r)
        for t in ts_q:
            while j < n-2 and ts_r[j+1] < t:
                j += 1
            if j >= n-1:
                result.append(vals_r[-1])
            else:
                frac = (t - ts_r[j]) / max(1e-9, ts_r[j+1] - ts_r[j])
                result.append(vals_r[j]*(1-frac) + vals_r[j+1]*frac)
        return result

    rpm_i = interp_ref(ts, ts_ref, rpm_ref)
    trq_i = interp_ref(ts, ts_ref, trq_ref)
    rpm_sm = rolling_mean(ts, rpm_i, 2.0)
    trq_sm = rolling_mean(ts, trq_i, 2.0)

    # --- Plot ---
    fig, axes = plt.subplots(5, 1, figsize=(18, 16), sharex=True)
    fig.subplots_adjust(hspace=0.5)

    # Panel 0: confirmed motor temp
    ax = axes[0]
    ax.plot(ts, [v*2 for v in temp], color='darkred', lw=0.5, alpha=0.3)
    ax.plot(ts, temp_sm, color='darkred', lw=1.5, label='Motor temp (2C/count smoothed)')
    ax.set_ylabel('deg C')
    ax.set_title('Motor winding temp B5/B6 (confirmed, 2-s smoothed)')
    ax.set_ylim(0, 180); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    add_events(ax)

    # Panel 1: 0x5A2 torque feedback (reference)
    ax = axes[1]
    ax.plot(ts, trq_i, color='gray', lw=0.4, alpha=0.4)
    ax.plot(ts, trq_sm, color='black', lw=1.5, label='Motor torque 0x5A2 B4-B5 (centered, smoothed)')
    ax.axhline(0, color='black', lw=0.5, alpha=0.5)
    ax.set_ylabel('counts (centered)')
    ax.set_title('0x5A2 Motor torque feedback (reference signal)')
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    add_events(ax)

    # Panel 2: B4[7:1]
    ax = axes[2]
    ax.plot(ts, B4_7, color='steelblue', lw=0.4, alpha=0.3, label='B4[7:1] raw')
    ax.plot(ts, B4_sm, color='navy', lw=1.8, label='B4[7:1] 2-s mean')
    ax.set_ylabel('B4[7:1] (0-127)')
    ax.set_title('B4[7:1] — 7-bit field (B4 always even, bit0=0)')
    ax.set_ylim(-5, 135); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    add_events(ax)

    # Panel 3: B0[7:2]
    ax = axes[3]
    ax.plot(ts, B0_6, color='green', lw=0.4, alpha=0.3, label='B0[7:2] raw')
    ax.plot(ts, B0_sm, color='darkgreen', lw=1.8, label='B0[7:2] 2-s mean')
    ax.set_ylabel('B0[7:2] (0-63)')
    ax.set_title('B0[7:2] — 6-bit field (B0 always mult-of-4, bits[1:0]=0)')
    ax.set_ylim(-2, 70); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    add_events(ax)

    # Panel 4: B3 (raw — only 5 values, no smoothing needed)
    ax = axes[4]
    ax.plot(ts, B3, color='purple', lw=0.8, label='B3 raw (5 unique values: 31-35)')
    ax.set_ylabel('B3 (31-35)')
    ax.set_title('B3 — 5 unique values {31-35}, very slowly varying (ambient temp?)')
    ax.set_ylim(29, 37); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_xlabel('Time (s)')
    add_events(ax)

    plt.suptitle('0x06000002 B0-B4 signal candidates — overheat test log', fontsize=13, y=1.001)
    plt.savefig(OUT, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"Saved: {OUT}")

if __name__ == '__main__':
    main()
