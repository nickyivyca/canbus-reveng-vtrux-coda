#!/usr/bin/env python3
"""
Confirm 0x592 brake (B4-B5) and throttle (B2-B3) against known references
in vtruxcurrentlimitingtest.log.

Reference signals (all confirmed, in DBC):
  0x5A2 B4-B5  traction motor torque feedback  LE uint16, centered 32768 (signed)
  0x598 B0-B1  battery current                 LE uint16, centered 32768 (signed)
  0x050        VCU DC bus current limit         10-bit: (B1&0x03)<<8 | B0

Candidate signals:
  0x592 B2-B3  throttle position               LE uint16, centered 32768
  0x592 B4-B5  brake pedal                     LE uint16, centered 32768
"""
import sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

ARTIFACT_DIR = Path(__file__).parent
LOG = "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

print("Parsing ...", flush=True)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Done.", flush=True)

# Identify PT bus by anchor 0x051
pt_bus = next((b for b, ids in bus_data.items() if 0x051 in ids), None)
print(f"PT bus = {pt_bus}", flush=True)

def get_raw(bus, can_id):
    return sorted(bus_data[bus].get(can_id, []))

def le16(d, lo):
    """LE uint16 from bytes lo, lo+1. Centered at 32768 -> signed."""
    if len(d) > lo + 1:
        return (d[lo] | d[lo+1] << 8) - 32768
    return None

def b10(d):
    """10-bit value from 0x050: (B1 & 0x03)<<8 | B0"""
    if len(d) > 1:
        return (d[1] & 0x03) << 8 | d[0]
    return None

def extract(raw_frames, decode_fn):
    pts = [(t, v) for t, d in raw_frames if (v := decode_fn(d)) is not None]
    return [x[0] for x in pts], [x[1] for x in pts]

# Extract all signals
raw_592 = get_raw(pt_bus, 0x592)
raw_5a2 = get_raw(pt_bus, 0x5A2)
raw_598 = get_raw(pt_bus, 0x598)
raw_050 = get_raw(pt_bus, 0x050)

t_thr, v_thr   = extract(raw_592, lambda d: le16(d, 2))   # throttle B2-B3
t_brk, v_brk   = extract(raw_592, lambda d: le16(d, 4))   # brake B4-B5
t_trq, v_trq   = extract(raw_5a2, lambda d: le16(d, 4))   # motor torque B4-B5
t_bat, v_bat   = extract(raw_598, lambda d: le16(d, 0))   # battery current B0-B1
t_ccl, v_ccl   = extract(raw_050, lambda d: b10(d))       # current limit

print(f"0x592 throttle: {len(t_thr)} pts, range {min(v_thr)}-{max(v_thr)}")
print(f"0x592 brake:    {len(t_brk)} pts, range {min(v_brk)}-{max(v_brk)}")
print(f"0x5A2 torque:   {len(t_trq)} pts, range {min(v_trq)}-{max(v_trq)}")
print(f"0x598 batt I:   {len(t_bat)} pts, range {min(v_bat)}-{max(v_bat)}")
print(f"0x050 CCL:      {len(t_ccl)} pts, range {min(v_ccl)}-{max(v_ccl)}")

# ---- Plot ----
PANELS = [
    (t_thr, v_thr, "0x592 B2-B3\nThrottle (raw-32768)",   "darkorange",  None),
    (t_brk, v_brk, "0x592 B4-B5\nBrake (raw-32768)",      "royalblue",   None),
    (t_trq, v_trq, "0x5A2 B4-B5\nMotor torque (raw-32768)","forestgreen", 0),
    (t_bat, v_bat, "0x598 B0-B1\nBattery current (raw-32768)","crimson",  0),
    (t_ccl, v_ccl, "0x050\nVCU current limit (10-bit)",   "purple",      None),
]

fig, axes = plt.subplots(len(PANELS), 1, figsize=(20, 3.0 * len(PANELS)), sharex=True)

t0 = min(t_thr[0], t_trq[0]) if t_thr and t_trq else 0
t1 = max(t_thr[-1], t_trq[-1]) if t_thr and t_trq else 1

for ax, (t, v, label, color, zero_line) in zip(axes, PANELS):
    ax.plot(t, v, color=color, linewidth=0.7, rasterized=True)
    if zero_line is not None:
        ax.axhline(zero_line, color="black", linewidth=0.5, linestyle="--", alpha=0.5)
    ax.set_ylabel(label, fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_xlim(t0, t1)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(5))
    # shade known event windows
    for ws, we, lbl, c in [
        (30,   72,   "downhill regen",      "lightblue"),
        (348.6, 365.6, "regen limit",       "lightyellow"),
        (598,  700,  "discharge limit",     "lightsalmon"),
    ]:
        ax.axvspan(ws, we, alpha=0.25, color=c, zorder=0)
        if ax is axes[0]:
            ax.text((ws + we) / 2, ax.get_ylim()[1] * 0.85, lbl,
                    ha="center", fontsize=6, color="gray")

axes[-1].set_xlabel("Time (s)", fontsize=9)
fig.suptitle(
    "Brake & throttle confirmation -- vtruxcurrentlimitingtest.log\n"
    "blue=downhill regen  yellow=regen limit  salmon=discharge limit",
    fontsize=10, fontweight="bold"
)
plt.tight_layout(rect=[0, 0, 1, 0.97])
out = ARTIFACT_DIR / "confirm_brake_throttle.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}", flush=True)
