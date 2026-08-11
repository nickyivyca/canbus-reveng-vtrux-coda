"""
plot_483_stitched.py

Stitched plot of vtruxgeneratorpumpunplug.log + vtruxgeneratoroverheattest.log.

Signals plotted:
  - 0x483 9-bit   (B2[0]<<8)|B1              -- existing notes decode
  - 0x483 13-bit  (((B2[7:4]<<1)|B2[0])<<8)|B1 -- full carry chain decode
  - 0x483 B0                                 -- coarse temp A (raw-100=C)
  - 0x484 B0                                 -- reference (gen motor temp candidate)
  - 0x18FF0320 B5                            -- PE pump speed (shows the unplug)
  - 0x595 B2                                 -- PE glycol loop temp candidate
  - 0x619 B2                                 -- thermal fault accumulator
  - 0x051 B1-B2 gen torque cmd
  - 0x054 B0-B1 gen RPM
  - Combined panel: computed power (|torque|*RPM) + 0x598 B2-B3 gen current (same axes,
    both normalised 0-1 so they can be compared directly)

Shaded areas: windows where generator is under load but gen current is significantly
below what torque*RPM would predict -- evidence of thermal derating.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_483_stitched.py
"""

import sys, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

LOG1 = "projects/vtrux/logs/vtruxgeneratorpumpunplug.log"
LOG2 = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT  = "projects/vtrux/notes/artifacts/483_stitched.png"

COLLECT = {
    0x483,
    0x484,
    0x18FF0320,
    0x595,
    0x619,
    0x051,
    0x054,
    0x598,
    0x06000002,
}

MAX_PTS = 6000


def collect_log(path, t_offset=0.0, pt_bus_hint=None):
    pt_bus = pt_bus_hint
    frames = {aid: [] for aid in COLLECT}
    t_first = t_last = None
    for frame in parse_file(path):
        t = frame.timestamp
        if t_first is None:
            t_first = t
        t_last = t
        if frame.arbitration_id == 0x051 and pt_bus is None:
            pt_bus = frame.bus
        if pt_bus is not None and frame.bus == pt_bus and frame.arbitration_id in COLLECT:
            frames[frame.arbitration_id].append((t + t_offset, bytes(frame.data)))
    return frames, pt_bus, t_first, t_last


def decode_signal(frames_for_id, spec, max_pts=MAX_PTS):
    ts, vs = [], []
    for t, d in frames_for_id:
        v = spec(d)
        if v is not None:
            ts.append(t)
            vs.append(v)
    n = len(ts)
    if n > max_pts:
        s = n // max_pts
        ts = ts[::s]
        vs = vs[::s]
    return ts, vs


def interp1(ref_t, ref_v, t):
    n = len(ref_t)
    if n == 0:
        return None
    if t <= ref_t[0]:
        return ref_v[0]
    if t >= ref_t[-1]:
        return ref_v[-1]
    lo, hi = 0, n - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if ref_t[mid] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = ref_t[lo], ref_t[hi]
    frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return ref_v[lo] + frac * (ref_v[hi] - ref_v[lo])


def merge_frames(f1, f2):
    return {aid: f1.get(aid, []) + f2.get(aid, []) for aid in COLLECT}


def norm01_series(ts, vs, p_lo=0.02, p_hi=0.98):
    """Normalise vs to [0,1] using percentile clipping. Returns new vs list."""
    sv = sorted(vs)
    n = len(sv)
    lo = sv[max(0, int(p_lo * n))]
    hi = sv[min(n-1, int(p_hi * n))]
    rng = hi - lo
    if rng < 1e-9:
        return [0.0] * len(vs)
    return [max(0.0, min(1.0, (v - lo) / rng)) for v in vs]


def find_derating_windows(torque_t, torque_v, rpm_t, rpm_v, current_t, current_v,
                           grid_hz=2.0, threshold=0.30, min_dur=5.0,
                           rpm_min=400, torque_mag_min=300):
    """
    Shade windows where abs(torque)*rpm (power demand) significantly exceeds
    actual gen current -- generator is being asked for more than it delivers.

    Only fires when RPM > rpm_min AND |torque| > torque_mag_min (actively generating).
    Both signals normalised to 0-1 independently; shade where computed-current > threshold.
    """
    if not torque_t or not rpm_t or not current_t:
        return []

    t0 = min(torque_t[0], rpm_t[0], current_t[0])
    t1 = max(torque_t[-1], rpm_t[-1], current_t[-1])
    dt = 1.0 / grid_hz
    grid = [t0 + i * dt for i in range(int((t1 - t0) / dt) + 1)]

    torque_g  = [interp1(torque_t,  torque_v,  t) for t in grid]
    rpm_g     = [interp1(rpm_t,     rpm_v,     t) for t in grid]
    current_g = [interp1(current_t, current_v, t) for t in grid]

    # computed power: |torque| * RPM (always positive when generating)
    computed = [abs(torque_g[i]) * max(0.0, rpm_g[i]) for i in range(len(grid))]

    # Normalise both to 0-1 over generating-only frames
    # (use percentile clipping to ignore idle noise)
    def norm_list(vals):
        sv = sorted(v for v in vals if v > 0)
        if not sv:
            return [0.0] * len(vals)
        lo = sv[max(0, int(0.02 * len(sv)))]
        hi = sv[min(len(sv)-1, int(0.98 * len(sv)))]
        rng = hi - lo
        if rng < 1e-9:
            return [0.0] * len(vals)
        return [max(0.0, min(1.5, (v - lo) / rng)) for v in vals]

    comp_n    = norm_list(computed)
    current_n = norm_list(current_g)

    windows = []
    in_window = False
    w_start = None
    for i, t in enumerate(grid):
        rpm_ok    = rpm_g[i] is not None and rpm_g[i] > rpm_min
        torque_ok = torque_g[i] is not None and abs(torque_g[i]) > torque_mag_min
        gen_active = rpm_ok and torque_ok
        # derating: gen is commanded hard but delivering less current than expected
        diverging = (gen_active and
                     comp_n[i] > 0.25 and
                     comp_n[i] - current_n[i] > threshold)
        if diverging and not in_window:
            in_window = True
            w_start = t
        elif not diverging and in_window:
            if t - w_start >= min_dur:
                windows.append((w_start, t))
            in_window = False
    if in_window and grid[-1] - w_start >= min_dur:
        windows.append((w_start, grid[-1]))
    return windows


def main():
    print(f"Parsing log 1: {LOG1} ...")
    frames1, pt_bus, t1_first, t1_last = collect_log(LOG1, t_offset=0.0)
    print(f"  PT bus={pt_bus}, t={t1_first:.1f}-{t1_last:.1f}s")

    gap = 1.0
    t_offset = (t1_last - t1_first) + gap
    print(f"Parsing log 2: {LOG2} (t_offset={t_offset:.1f}s) ...")
    frames2, _, t2_first, t2_last = collect_log(LOG2, t_offset=t_offset, pt_bus_hint=pt_bus)
    print(f"  shifted to {t2_first+t_offset:.1f}-{t2_last+t_offset:.1f}s")

    frames = merge_frames(frames1, frames2)
    log_boundary = t_offset

    def sig(aid, fn):
        return decode_signal(frames[aid], fn)

    # 0x483 decodes
    # 10-bit: uses B2[1:0] as top 2 bits
    ten_t,    ten_v    = sig(0x483, lambda d: float(((d[2]&0x03)<<8)|d[1]) if len(d)>2 else None)
    # 13-bit: correct carry chain -- counter = (B2[7:4]<<1)|(B2[0]), value = counter*256 + B1
    wide_t,   wide_v   = sig(0x483, lambda d:
        float((((d[2]>>4)<<1)|(d[2]&0x01))<<8 | d[1]) if len(d)>2 else None)
    coarse_t, coarse_v = sig(0x483, lambda d: float(d[0]) if len(d)>0 else None)

    # 0x484 9-bit: (B1[0]<<8)|B0
    ref_t,    ref_v    = sig(0x484,      lambda d: float(((d[1]&0x01)<<8)|d[0]) if len(d)>1 else None)
    pump_t,   pump_v   = sig(0x18FF0320, lambda d: float(d[5]) if len(d)>5 else None)
    glycol_t, glycol_v = sig(0x595,      lambda d: float(d[2]) if len(d)>2 else None)
    fault_t,  fault_v  = sig(0x619,      lambda d: float(d[2]) if len(d)>2 else None)
    torque_t, torque_v = sig(0x051,      lambda d: float((d[2]<<8|d[1])-32768) if len(d)>2 else None)
    rpm_t,    rpm_v    = sig(0x054,      lambda d: float((d[1]<<8|d[0])-32768) if len(d)>1 else None)
    current_t,current_v= sig(0x598,     lambda d: float((d[3]<<8|d[2])-32768) if len(d)>3 else None)
    # 0x06000002 B5/B6: 10-bit LE startbit 46, (B6<<2)|(B5>>6), scale 2.0 degC/count
    dtm_t,    dtm_v    = sig(0x06000002, lambda d: float(((d[6]<<2)|(d[5]>>6))*2.0) if len(d)>6 else None)
    # 0x483/0x484 B6-B7 LE uint16: Kelvin*10 hypothesis -- value*0.1 - 273.1 = degC
    genwt_t, genwt_v = sig(0x483, lambda d: float(((d[7]<<8)|d[6])*0.1 - 273.1) if len(d)>7 else None)
    dtwt_t,  dtwt_v  = sig(0x484, lambda d: float(((d[7]<<8)|d[6])*0.1 - 273.1) if len(d)>7 else None)

    # Computed power on torque timestamps
    comp_t, comp_v = [], []
    for i, t in enumerate(torque_t):
        r = interp1(rpm_t, rpm_v, t)
        if r is not None:
            comp_t.append(t)
            comp_v.append(abs(torque_v[i]) * max(0.0, r))

    # Continuity check
    def bracket(ts, vs, t_b, w=30.0):
        before = [v for t, v in zip(ts, vs) if t_b - w < t < t_b]
        after  = [v for t, v in zip(ts, vs) if t_b < t < t_b + w]
        return (before[-1] if before else None, after[0] if after else None)

    for lbl, ts, vs in [("0x483 10-bit", ten_t, ten_v),
                         ("0x483 wide",   wide_t, wide_v),
                         ("0x483 B0",     coarse_t, coarse_v)]:
        be, af = bracket(ts, vs, log_boundary)
        if be is not None and af is not None:
            print(f"  Continuity {lbl}: end={be:.0f} -> start={af:.0f}")

    # Derating windows
    print("Computing derating windows ...")
    derating = find_derating_windows(torque_t, torque_v, rpm_t, rpm_v,
                                     current_t, current_v,
                                     threshold=0.30, min_dur=5.0,
                                     rpm_min=400, torque_mag_min=300)
    print(f"  {len(derating)} windows")
    for w in derating:
        print(f"    t={w[0]:.1f}-{w[1]:.1f}s  ({w[1]-w[0]:.1f}s)")

    # Normalised series for the combined power panel
    comp_n    = norm01_series(comp_t,    comp_v)     if comp_v    else []
    current_n = norm01_series(current_t, current_v)  if current_v else []

    # ------------------------------------------------------------------
    # Panel definitions
    # Each entry: (ts, vs, ylabel, color) -- or None for a dual panel (handled specially)
    # ------------------------------------------------------------------
    DUAL_POWER = 'dual_power'  # sentinel for the combined panel

    panels = [
        (genwt_t,   genwt_v,   "0x483 B6-B7 LE\ngen winding temp?\n[Kelvin*0.1-273 degC]",       '#d62728'),
        (dtwt_t,    dtwt_v,    "0x484 B6-B7 LE\ndrivetrain winding?\n[Kelvin*0.1-273 degC]",      '#ff7f0e'),
        (ten_t,     ten_v,     "0x483 10-bit\n(B2[1:0]<<8)|B1",                                   '#8c564b'),
        (coarse_t,  coarse_v,  "0x483 B0\ncoarse temp\n[raw-100=C]",                              '#2ca02c'),
        (ref_t,     ref_v,     "0x484 9-bit\n(B1[0]<<8)|B0",                                      '#1f77b4'),
        (dtm_t,     dtm_v,     "0x06000002 B5/B6\ndrivetrain motor temp\n[degC, 10-bit x2]",      '#9467bd'),
        (glycol_t,  glycol_v,  "0x595 B2\nPE glycol temp\ncandidate",                             '#e377c2'),
        (torque_t,  torque_v,  "0x051 B1-B2\ngen torque cmd\n[<0=generating]",                    '#17becf'),
        (rpm_t,     rpm_v,     "0x054 B0-B1\ngen RPM",                                            '#bcbd22'),
        DUAL_POWER,
    ]

    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(24, n * 1.8), sharex=True)
    fig.suptitle(
        "0x483 temp signal -- pumpunplug + overheat test (stitched)\n"
        "Red shading: |torque|*RPM >> gen current (derating)  |  Dashed: log boundary",
        fontsize=10
    )

    for i, panel in enumerate(panels):
        ax = axes[i]

        if panel is DUAL_POWER:
            # Overlay computed power (grey) and gen current (yellow-green), both 0-1
            if comp_n:
                ax.plot(comp_t, comp_n, color='#555555', linewidth=0.8,
                        label='|torque|*RPM (norm)', rasterized=True)
            if current_n:
                ax.plot(current_t, current_n, color='#bcbd22', linewidth=0.8,
                        label='0x598 gen current (norm)', rasterized=True)
            ax.set_ylim(-0.05, 1.15)
            ax.set_ylabel("power panel\n|torque|*RPM (grey)\nvs gen current (yellow)\n[both norm 0-1]",
                          fontsize=7, rotation=0, ha='right', va='center', labelpad=4)
            ax.yaxis.set_label_coords(-0.01, 0.5)
            ax.legend(fontsize=6, loc='upper left', framealpha=0.7)
        else:
            ts, vs, label, color = panel
            if ts:
                ax.plot(ts, vs, color=color, linewidth=0.85, rasterized=True)
            else:
                ax.text(0.5, 0.5, 'no data', transform=ax.transAxes,
                        ha='center', va='center', fontsize=8, color='grey')
            ax.set_ylabel(label, fontsize=7, rotation=0, ha='right', va='center', labelpad=4)
            ax.yaxis.set_label_coords(-0.01, 0.5)
            if ts and vs:
                lo, hi = min(vs), max(vs)
                pad = (hi - lo) * 0.08 if hi > lo else 1.0
                ax.set_ylim(lo - pad, hi + pad)
                ax.text(0.998, 0.90, f"{lo:.0f}-{hi:.0f}",
                        transform=ax.transAxes, fontsize=6, ha='right', va='top',
                        color='#555', style='italic')

        # Derating shading and log boundary on all panels
        for w_start, w_end in derating:
            ax.axvspan(w_start, w_end, alpha=0.18, color='red', linewidth=0)
        ax.axvline(log_boundary, color='#333', linewidth=1.0, linestyle='--', alpha=0.6)
        ax.tick_params(labelsize=6)
        ax.grid(axis='x', linestyle=':', linewidth=0.4, alpha=0.5)

    axes[-1].set_xlabel("Time (s)  [log1: pumpunplug | log2: overheat test]", fontsize=8)

    patch = mpatches.Patch(color='red', alpha=0.3,
                           label='Derating: |torque|*RPM >> gen current')
    axes[0].legend(handles=[patch], fontsize=7, loc='upper left', framealpha=0.7)

    plt.tight_layout(rect=[0.14, 0, 1, 0.995])
    print(f"Saving {OUT} ...")
    fig.savefig(OUT, dpi=110, bbox_inches='tight')
    plt.close(fig)
    print("Done.")


if __name__ == '__main__':
    main()
