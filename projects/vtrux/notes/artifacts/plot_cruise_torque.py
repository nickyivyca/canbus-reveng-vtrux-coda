"""
plot_cruise_torque.py

6-panel plot of drivetrain + generator signals, both log parts stitched together.

Part 1: vtruxevapdrivelog4.log      (cruise control active)
Part 2: vtruxevapdrivelog4part2.log (no cruise; timestamps offset by P1 end + 10s gap)

Signals extracted inline from both logs (no CSV dependency):
  - Motor speed              (0x5A2 B2-B3 LE)
  - Traction drive cmd       (0x051 B3-B4 LE) -- hypothesis: generator speed reference (RPM)
  - Motor torque feedback    (0x5A2 B4-B5 LE)
  - Drivetrain current       (0x598 B4-B5 LE)
  - Generator torque cmd     (0x051 B1-B2 LE)
  - Generator current/power  (0x598 B2-B3 LE)
  - Generator RPM            (0x63C B6, raw byte) -- overlaid on traction cmd panel (right axis)

All offset-binary signals displayed as raw - 32768.
Output: cruise_cmd_feedback_plot.png
"""

import sys
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

ARTIFACTS = 'projects/vtrux/notes/artifacts'
LOG_P1    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
LOG_P2    = 'projects/vtrux/logs/vtruxevapdrivelog4part2.log'
OUTPUT    = f'{ARTIFACTS}/cruise_cmd_feedback_plot.png'

LOG_GAP   = 10.0   # seconds of white space between parts

# P1 annotations (absolute timestamps)
P1_GEN_START    = 431.31
P1_CRUISE_ENGAGE = 705.68
P1_CRUISE_WIN   = (720,     1080)
P1_HWY_EXIT     = (1080,    1122)
P1_BTN_EVENTS   = (1103.68, 1108.43)

# IDs to collect (PT bus only; these IDs are exclusive to PT bus)
TARGET_IDS = {0x5A2, 0x051, 0x598, 0x63C}


def le16(data, lo):
    """Little-endian uint16 from bytes at index lo, lo+1."""
    return (data[lo + 1] << 8) | data[lo]


def extract_log(log_path, t_offset=0.0):
    """
    Single-pass extraction of all 6 signals from a log.
    Returns dict of signal_name -> (timestamps, values).
    t_offset is added to every timestamp (for stitching part 2).
    """
    sigs = {k: ([], []) for k in ('spd', 'cmd', 'tfb', 'drv', 'gcmd', 'gcur', 'grpm')}
    t_max = 0.0

    for frame in parse_file(log_path):
        aid = frame.arbitration_id
        if aid not in TARGET_IDS:
            continue
        t  = frame.timestamp + t_offset
        d  = bytes(frame.data)
        n  = len(d)
        t_max = max(t_max, frame.timestamp)

        if aid == 0x5A2:
            if n >= 4:
                sigs['spd'][0].append(t);  sigs['spd'][1].append(le16(d, 2) - 32768)
            if n >= 6:
                sigs['tfb'][0].append(t);  sigs['tfb'][1].append(le16(d, 4) - 32768)

        elif aid == 0x051:
            if n >= 5:
                sigs['cmd'][0].append(t);  sigs['cmd'][1].append(le16(d, 3) - 32768)
            if n >= 3:
                sigs['gcmd'][0].append(t); sigs['gcmd'][1].append(le16(d, 1) - 32768)

        elif aid == 0x598:
            if n >= 6:
                sigs['drv'][0].append(t);  sigs['drv'][1].append(le16(d, 4) - 32768)
            if n >= 4:
                sigs['gcur'][0].append(t); sigs['gcur'][1].append(le16(d, 2) - 32768)

        elif aid == 0x63C:
            if n >= 7:
                sigs['grpm'][0].append(t); sigs['grpm'][1].append(d[6])

    return sigs, t_max


# ------------------------------------------------------------------
# Extract both parts
# ------------------------------------------------------------------
print(f"Extracting Part 1: {LOG_P1}")
p1, p1_end = extract_log(LOG_P1, t_offset=0.0)
p2_offset  = p1_end + LOG_GAP
print(f"  Part 1 end: {p1_end:.1f}s  ->  Part 2 offset: {p2_offset:.1f}s")

print(f"Extracting Part 2: {LOG_P2}")
p2, p2_end_rel = extract_log(LOG_P2, t_offset=p2_offset)
t_total = p2_offset + p2_end_rel
print(f"  Part 2 end (stitched): {t_total:.1f}s")

for key in ('spd', 'cmd', 'tfb', 'drv', 'gcmd', 'gcur', 'grpm'):
    n1 = len(p1[key][0]); n2 = len(p2[key][0])
    print(f"  {key}: P1={n1}  P2={n2}")


# ------------------------------------------------------------------
# Merge part 1 + part 2 for each signal
# ------------------------------------------------------------------
def merge(key):
    t = p1[key][0] + p2[key][0]
    v = p1[key][1] + p2[key][1]
    return t, v

t_spd,  v_spd  = merge('spd')
t_cmd,  v_cmd  = merge('cmd')
t_tfb,  v_tfb  = merge('tfb')
t_drv,  v_drv  = merge('drv')
t_gcmd, v_gcmd = merge('gcmd')
t_gcur, v_gcur = merge('gcur')
t_grpm, v_grpm = merge('grpm')

# ------------------------------------------------------------------
# Plotting
# ------------------------------------------------------------------
print("Plotting...")

PANEL_DEFS = [
    ('Motor Speed',             t_spd,  v_spd,  'royalblue',    '0x5A2 B2-B3'),
    ('Traction Drive Cmd / Gen Speed Ref?',  t_cmd,  v_cmd,  'darkorange',   '0x051 B3-B4  [null=-1; olive=gen RPM raw, right axis]'),
    ('Motor Torque Feedback',   t_tfb,  v_tfb,  'seagreen',     '0x5A2 B4-B5  [neg=regen]'),
    ('Drivetrain Current',      t_drv,  v_drv,  'crimson',      '0x598 B4-B5  [~0.04 A/ct]'),
    ('Generator Torque Cmd',    t_gcmd, v_gcmd, 'mediumpurple', '0x051 B1-B2  [neg=generating]'),
    ('Generator Current',       t_gcur, v_gcur, 'teal',         '0x598 B2-B3  [~0.04 A/ct]'),
]

fig, axes = plt.subplots(len(PANEL_DEFS), 1, figsize=(26, 18), sharex=True)
fig.suptitle(
    'Part 1 (cruise active) + Part 2 (no cruise) stitched  --  vtruxevapdrivelog4 / part2\n'
    'Blue: zero-throttle cruise window  |  Orange: hwy exit  |  Red: setpoint decrements + brake  |'
    '  Gray fill: log gap between parts',
    fontsize=10
)

stitch_x = p1_end + LOG_GAP / 2   # centre of the gap


def decorate(ax, last=False):
    # P1-specific shading
    ax.axvspan(*P1_CRUISE_WIN,  alpha=0.10, color='steelblue',  zorder=0)
    ax.axvspan(*P1_HWY_EXIT,    alpha=0.12, color='darkorange', zorder=0)
    ax.axvspan(*P1_BTN_EVENTS,  alpha=0.28, color='red',        zorder=0)
    # P1 event lines
    ax.axvline(P1_GEN_START,     color='gray',   lw=0.9, ls='--', alpha=0.7)
    ax.axvline(P1_CRUISE_ENGAGE, color='purple', lw=0.9, ls='--', alpha=0.7)
    # Log gap marker
    ax.axvspan(p1_end, p2_offset, alpha=0.25, color='lightgray', zorder=0)
    ax.axvline(p2_offset, color='black', lw=1.2, ls='-', alpha=0.5)
    # Zero line + grid
    ax.axhline(0, color='black', lw=0.5, ls=':')
    ax.grid(True, alpha=0.22)
    ax.set_xlim(0, t_total)
    ax.set_ylabel('cts − 32768', fontsize=8)
    if last:
        ax.set_xlabel('Time (s)', fontsize=10)


for i, (title, ts, vs, color, detail) in enumerate(PANEL_DEFS):
    ax = axes[i]
    lw = 0.8 if len(ts) < 5000 else 0.45
    ax.plot(ts, vs, color=color, linewidth=lw)
    decorate(ax, last=(i == len(PANEL_DEFS) - 1))
    ax.set_title(f'{title}  ({detail})', fontsize=9, loc='left')

    # Overlay generator RPM on the traction drive command panel
    if i == 1 and t_grpm:
        ax2 = ax.twinx()
        ax2.patch.set_visible(False)
        lw2 = 0.45 if len(t_grpm) > 5000 else 0.8
        ax2.plot(t_grpm, v_grpm, color='olive', linewidth=lw2, alpha=0.75)
        ax2.set_ylabel('Gen RPM (0x63C B6 raw)', fontsize=7, color='olive')
        ax2.tick_params(axis='y', labelsize=7, colors='olive')

# Annotate stitch and event lines on top panel only
ax0 = axes[0]
ymax = ax0.get_ylim()[1]
ax0.text(P1_GEN_START + 5, ymax * 0.92, 'gen start', fontsize=7, color='gray')
ax0.text(P1_CRUISE_ENGAGE + 5, ymax * 0.92, 'cruise\nengage', fontsize=7, color='purple')
ax0.text(stitch_x, ymax * 0.92, 'P1 | P2', fontsize=7, color='black',
         ha='center', va='top',
         bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='black', alpha=0.7))

plt.tight_layout()
plt.savefig(OUTPUT, dpi=150, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
