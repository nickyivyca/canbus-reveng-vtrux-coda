"""
plot_619_vs_torques.py

Plot 0x619 B4 and B0 against generator torque (0x051 B1-B2 LE)
and drivetrain torque (0x5A2 B4-B5 LE) for evap4 part 1.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_619_vs_torques.py
"""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = "projects/vtrux/notes/artifacts/619_vs_torques.png"

TARGET_IDS = {0x051, 0x5A2, 0x619, 0x18FF0320}


def le_uint16(data, lo_byte):
    if lo_byte + 1 >= len(data):
        return None
    return data[lo_byte] | (data[lo_byte + 1] << 8)


def identify_pt_bus(log_path):
    cnt = defaultdict(lambda: defaultdict(int))
    first_ts = {}
    for fr in parse_file(log_path):
        cnt[fr.bus][fr.arbitration_id] += 1
        if fr.bus not in first_ts:
            first_ts[fr.bus] = fr.timestamp
    pt_bus = next(b for b, c in cnt.items() if c.get(0x051, 0) > 1000)
    return pt_bus, first_ts[pt_bus]


def main():
    print("Pass 1: identifying PT bus...")
    pt_bus, t0 = identify_pt_bus(LOG)
    print(f"  PT bus = {pt_bus}, t0 = {t0:.4f}s")

    # Timeseries storage
    ts = {k: ([], []) for k in ['b4', 'b0', 'gen_torq', 'drv_torq', 'pump']}

    print("Pass 2: collecting timeseries...")
    for fr in parse_file(LOG):
        if fr.bus != pt_bus or fr.arbitration_id not in TARGET_IDS:
            continue
        t = fr.timestamp - t0
        aid = fr.arbitration_id

        if aid == 0x619:
            if len(fr.data) > 4:
                ts['b4'][0].append(t)
                ts['b4'][1].append(fr.data[4])
            if len(fr.data) > 0:
                ts['b0'][0].append(t)
                ts['b0'][1].append(fr.data[0])

        elif aid == 0x051:
            # Gen torque: B1-B2 LE uint16, centered at 32768
            w = le_uint16(fr.data, 1)
            if w is not None:
                ts['gen_torq'][0].append(t)
                ts['gen_torq'][1].append(abs(w - 32768))

        elif aid == 0x5A2:
            # Drivetrain torque: B4-B5 LE uint16, centered at 32768
            w = le_uint16(fr.data, 4)
            if w is not None:
                ts['drv_torq'][0].append(t)
                ts['drv_torq'][1].append(abs(w - 32768))

        elif aid == 0x18FF0320:
            # PE pump speed feedback: B5
            if len(fr.data) > 5:
                ts['pump'][0].append(t)
                ts['pump'][1].append(fr.data[5])

    print("Plotting...")
    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    fig.suptitle('0x619 thermal bytes vs motor torques + pump speed -- evap4 part 1', fontsize=12)

    # Row 1: Torques
    ax1 = axes[0]
    ax1.plot(ts['gen_torq'][0], ts['gen_torq'][1], color='tab:orange',
             lw=0.6, alpha=0.8, label='Gen torque |0x051 B1-B2 - 32768|')
    ax1.plot(ts['drv_torq'][0], ts['drv_torq'][1], color='tab:blue',
             lw=0.6, alpha=0.8, label='Drv torque |0x5A2 B4-B5 - 32768|')
    ax1.set_ylabel('Torque magnitude (raw)')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # Row 2: 0x619 B4 (fast IGBT-like)
    ax2 = axes[1]
    ax2.plot(ts['b4'][0], ts['b4'][1], color='tab:red',
             lw=0.7, alpha=0.85, label='0x619 B4 (raw, range 40-92)')
    ax2.set_ylabel('0x619 B4 (raw counts)')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # Row 3: 0x619 B0 (slow thermal)
    ax3 = axes[2]
    ax3.plot(ts['b0'][0], ts['b0'][1], color='tab:purple',
             lw=0.7, alpha=0.85, label='0x619 B0 (raw, range 244-254)')
    ax3.set_ylabel('0x619 B0 (raw counts)')
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3)

    # Row 4: PE pump speed
    ax4 = axes[3]
    ax4.plot(ts['pump'][0], ts['pump'][1], color='tab:green',
             lw=0.7, alpha=0.85, label='PE pump speed (0x18FF0320 B5)')
    ax4.set_ylim(-1, 20)  # clip: normal range 0-12; B5=55/38 spikes are anomalies noted separately
    ax4.set_ylabel('Pump speed (raw, clipped 0-20)')
    ax4.set_xlabel('Time (s)')
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT, dpi=150)
    print(f"Saved: {OUT}")


if __name__ == '__main__':
    main()
