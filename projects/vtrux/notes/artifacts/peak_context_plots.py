import sys, collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cantools

sys.path.insert(0, r"<repo>")
from canre.parsers import parse_file

base     = r"<repo>\projects\vtrux"
logs_dir = base + r"\logs"
out_dir  = base + r"\notes\plots"

pt_db      = cantools.database.load_file(base + r"\epri-pt-bus.dbc")
pt_exp_db  = cantools.database.load_file(base + r"\vtrux-powertrain-experimental.dbc")
obd_db     = cantools.database.load_file(base + r"\epri-obd-bus.dbc")
obd_exp_db = cantools.database.load_file(base + r"\vtrux-obd-experimental.dbc")
gmlan_db   = cantools.database.load_file(base + r"\GMW8762_PPEI_GMLAN.dbc")

WINDOW = 10.0

PEAKS = [
    ("gen_peak_motoring",       "vtruxanotherevaplogpart2.log",            1455.580, "gene", -10, 120),
    ("gen_peak_generating",     "vtruxanotherevaplogpart3.log",             233.409,  "gene", -10, 10),
    ("gen_peak_torque",         "vtruxanotherevaplogpart3.log",             222.064,  "gene", -10, 10),
    ("trac_peak_motoring",      "vtruxanotherevaplogpart2.log",             245.119,  "trac", -10, 10),
    ("trac_peak_regen",         "vtruxanotherevaplogpart4-batteryonly.log", 590.901,  "trac", -10, 10),
    ("trac_peak_torque_neg",    "vtruxanotherevaplogpart4-batteryonly.log",  91.276,  "trac", -10, 10),
    ("trac_peak_torque_pos",    "vtruxanotherevaplogpart3.log",              74.255,  "trac", -10, 10),
]

from collections import defaultdict
peaks_by_log = defaultdict(list)
for p in PEAKS:
    peaks_by_log[p[1]].append(p)

data = {}
for label, logfile, t, motor, w_lo, w_hi in PEAKS:
    data[label] = {
        "motor": motor, "peak_t": t,
        "rpm":      ([], []),
        "trq":      ([], []),
        "cmd":      ([], []),
        "curr":     ([], []),
        "volt":     ([], []),
        "pwr":      ([], []),
        "throttle": ([], []),
    }

ID_GENE_RPM = 0x054
ID_GENE_TRQ = 0x471
ID_GENE_CMD = 0x051
ID_GENE_PWR = 0x482
ID_TRAC_RPM = 0x044
ID_TRAC_TRQ = 0x442
ID_TRAC_PWR = 0x462
ID_THROTTLE_ENG   = 0x3D1   # Engine TPS, OBD bus — for generator plots
ID_THROTTLE_PEDAL = 0x592   # Driver pedal position, PT bus — for traction plots

OBD_ANCHORS = set(range(0x040, 0x045))  # TRAC MCU only — 0x441-0x464 has GMLAN bleed onto Vehicle bus

for logfile, plist in peaks_by_log.items():
    print(f"Reading {logfile} ...")
    windows = [(label, t + w_lo, t + w_hi, motor) for label, _, t, motor, w_lo, w_hi in plist]
    obd_channel = None

    for frame in parse_file(logs_dir + "\\" + logfile):
        ts  = frame.timestamp
        aid = frame.arbitration_id
        d   = bytes(frame.data)

        if obd_channel is None and aid in OBD_ANCHORS:
            obd_channel = frame.bus

        for label, t_lo, t_hi, motor in windows:
            if ts < t_lo or ts > t_hi:
                continue
            s = data[label]

            if motor == "gene" and aid == ID_THROTTLE_ENG and len(d) >= 2 and frame.bus == obd_channel:
                try:
                    sig = gmlan_db.decode_message(aid, d)
                    thr = sig.get("Throttle_Position")
                    if thr is not None:
                        s["throttle"][0].append(ts)
                        s["throttle"][1].append(thr)
                except Exception:
                    pass

            if motor == "trac" and aid == ID_THROTTLE_PEDAL and len(d) >= 4:
                sig = pt_exp_db.decode_message(aid, d)
                pedal = sig.get("throttle_pos")
                if pedal is not None:
                    s["throttle"][0].append(ts)
                    s["throttle"][1].append(pedal)

            if motor == "gene":
                if aid == ID_GENE_RPM:
                    sig = pt_db.decode_message(aid, d)
                    s["rpm"][0].append(ts); s["rpm"][1].append(sig["GENE_RotSpd"])

                elif aid == ID_GENE_TRQ:
                    sig = pt_db.decode_message(aid, d)
                    s["trq"][0].append(ts); s["trq"][1].append(sig["GENE_Mot_Trq"])

                elif aid == ID_GENE_CMD and len(d) >= 4:
                    raw = d[1] | (d[2] << 8)
                    s["cmd"][0].append(ts); s["cmd"][1].append((raw - 32768) * 0.125)

                elif aid == ID_GENE_PWR:
                    sig = pt_db.decode_message(aid, d)
                    curr = sig["GENE_HighPwr_Curr"]
                    volt = sig["GENE_HighPwr_Volt"]
                    s["curr"][0].append(ts); s["curr"][1].append(curr)
                    s["volt"][0].append(ts); s["volt"][1].append(volt)
                    if volt > 0:
                        s["pwr"][0].append(ts); s["pwr"][1].append(curr * volt / 1000.0)

            else:
                if aid == ID_TRAC_RPM:
                    sig = obd_db.decode_message(aid, d)
                    s["rpm"][0].append(ts); s["rpm"][1].append(sig["TRAC_RotSpd"])

                elif aid == ID_TRAC_TRQ:
                    sig = obd_exp_db.decode_message(aid, d)
                    s["trq"][0].append(ts); s["trq"][1].append(sig["TRAC_TrqFbk"])

                elif aid == ID_TRAC_PWR:
                    sig = obd_db.decode_message(aid, d)
                    curr = sig["TRAC_HighPwr_Curr"]
                    volt = sig["TRAC_HighPwr_Volt"]
                    s["curr"][0].append(ts); s["curr"][1].append(curr)
                    s["volt"][0].append(ts); s["volt"][1].append(volt)
                    if volt > 0:
                        s["pwr"][0].append(ts); s["pwr"][1].append(curr * volt / 1000.0)

print("Plotting ...")

TITLES = {
    "gen_peak_motoring":    "Generator - Peak Motoring (+15.8 kW) [engine start]",
    "gen_peak_generating":  "Generator - Peak Generating (-144.7 kW)",
    "gen_peak_torque":      "Generator - Peak Torque (-367.2 Nm) [fbk spike]",
    "trac_peak_motoring":   "Traction - Peak Motoring (+183.9 kW)",
    "trac_peak_regen":      "Traction - Peak Regen (-94.2 kW)",
    "trac_peak_torque_neg": "Traction - Peak Neg Torque (-275.1 Nm) [artifact near 0 RPM]",
    "trac_peak_torque_pos": "Traction - Peak Pos Torque (+403.4 Nm)",
}

for label, logfile, peak_t, motor, w_lo, w_hi in PEAKS:
    s = data[label]
    has_throttle = len(s["throttle"][0]) > 0

    nrows = 5 if has_throttle else 4
    fig, axes = plt.subplots(nrows, 1, figsize=(14, 3 * nrows), sharex=True)
    fig.suptitle(f"{TITLES[label]}\n{logfile}  peak t={peak_t:.3f}s", fontsize=11)

    t_rel = lambda ts_list: [t - peak_t for t in ts_list]

    ax0, ax1, ax2, ax3 = axes[0], axes[1], axes[2], axes[3]

    ax0.plot(t_rel(s["rpm"][0]), s["rpm"][1], color="steelblue", lw=1)
    ax0.set_ylabel("RPM")
    ax0.axvline(0, color="red", lw=1, ls="--", label="peak")
    ax0.legend(fontsize=8)

    ax1.plot(t_rel(s["trq"][0]), s["trq"][1], color="darkorange", lw=1, label="trq fbk")
    if s["cmd"][0] and motor == "gene":
        ax1.plot(t_rel(s["cmd"][0]), s["cmd"][1], color="purple", lw=1, ls="--", label="trq cmd")
    ax1.set_ylabel("Torque (Nm)")
    ax1.axvline(0, color="red", lw=1, ls="--")
    ax1.axhline(0, color="gray", lw=0.5)
    ax1.legend(fontsize=8)

    ax2.plot(t_rel(s["curr"][0]), s["curr"][1], color="crimson", lw=1)
    ax2.set_ylabel("DC Current (A)")
    ax2.axvline(0, color="red", lw=1, ls="--")
    ax2.axhline(0, color="gray", lw=0.5)

    ax3_v = ax3
    ax3_p = ax3.twinx()
    ax3_v.plot(t_rel(s["volt"][0]), s["volt"][1], color="teal",  lw=1, label="voltage")
    ax3_p.plot(t_rel(s["pwr"][0]),  s["pwr"][1],  color="gold",  lw=1, label="DC pwr")
    ax3_v.set_ylabel("DC Voltage (V)", color="teal")
    ax3_p.set_ylabel("DC Power (kW)",  color="goldenrod")
    ax3_v.axvline(0, color="red", lw=1, ls="--")
    ax3_p.axhline(0, color="gray", lw=0.5)
    lines1, labs1 = ax3_v.get_legend_handles_labels()
    lines2, labs2 = ax3_p.get_legend_handles_labels()
    ax3_v.legend(lines1 + lines2, labs1 + labs2, fontsize=8)

    if has_throttle:
        ax4 = axes[4]
        ax4.plot(t_rel(s["throttle"][0]), s["throttle"][1], color="forestgreen", lw=1)
        ax4.set_ylabel("Engine TPS (%)" if motor == "gene" else "Pedal pos (counts)")
        ax4.set_ylim(bottom=0)
        ax4.axvline(0, color="red", lw=1, ls="--")
        ax4.set_xlabel("Time relative to peak (s)")
    else:
        ax3_v.set_xlabel("Time relative to peak (s)")

    plt.tight_layout()
    plt.savefig(out_dir + f"\\{label}.png", dpi=120)
    plt.close()
    print(f"  Saved {label}.png")

print("Done.")
