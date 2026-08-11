"""
Corrected event-annotated plot for vtruxanotherevaplogpart2.log.
Events identified from RPM (0x63C B6) zero-crossings.
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

def load_csv(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    return zip(*[(float(r[0]), int(r[1])) for r in rows[1:]])

BASE = "projects/vtrux/notes/artifacts/"
rpm_t, rpm_v = [list(x) for x in load_csv(BASE + "anotherevap_p2_rpm.csv")]
b3_t,  b3_v  = [list(x) for x in load_csv(BASE + "anotherevap_p2_0x600_b3.csv")]

# Events from RPM transition analysis
events = [
    ( 12.31, "engine start",         "green",  "-",  "bottom"),
    (808.42, "stall start",          "red",    "--", "top"),
    (815.81, "stall restart",        "red",    "-",  "bottom"),
    (1392.79,"evap done? / eng off", "blue",   "-",  "top"),
    (1455.66,"M mode on",            "purple", "--", "bottom"),
    (1669.86,"M mode off",           "purple", "-",  "top"),
]

fig, (ax1_top, ax1_bot) = plt.subplots(2, 1, figsize=(18, 9),
                                        gridspec_kw={"height_ratios": [1, 1]})

def draw_panel(ax1, t_lo, t_hi, title):
    def filt(ts, vs):
        out = [(t, v) for t, v in zip(ts, vs) if t_lo <= t <= t_hi]
        return ([x[0] for x in out], [x[1] for x in out]) if out else ([], [])

    rt, rv = filt(rpm_t, rpm_v)
    bt, bv = filt(b3_t, b3_v)

    ax1.plot(rt, rv, color="steelblue", linewidth=0.7, label="RPM (0x63C B6 raw)")
    ax1.set_ylabel("RPM raw count", color="steelblue")
    ax1.tick_params(axis="y", labelcolor="steelblue")
    ax1.set_xlim(t_lo, t_hi)
    ax1.grid(True, alpha=0.3)
    ax1.set_title(title, fontsize=9)

    ax2 = ax1.twinx()
    ax2.step(bt, bv, color="darkorange", linewidth=0.9, alpha=0.75, where="post", label="B3")
    ax2.set_ylabel("0x600 B3", color="darkorange")
    ax2.tick_params(axis="y", labelcolor="darkorange")
    ax2.set_ylim(-0.5, 13)
    ax2.yaxis.set_major_locator(ticker.MultipleLocator(1))

    ymax = max(rv) if rv else 255
    span = t_hi - t_lo
    for t, label, color, ls, va in events:
        if t_lo <= t <= t_hi:
            ax1.axvline(t, color=color, linestyle=ls, linewidth=1.5, alpha=0.9)
            y_pos = ymax * 0.95 if va == "top" else ymax * 0.05
            ax1.text(t + span * 0.003, y_pos, f"{label}\nt={t:.1f}s",
                     fontsize=8, color=color, rotation=90,
                     va="top" if va == "top" else "bottom")

    lines1, labs1 = ax1.get_legend_handles_labels()
    lines2, labs2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labs1 + labs2, loc="upper right", fontsize=8)

draw_panel(ax1_top, 0, 2011,
           "Full log -- Engine RPM + 0x600 B3 (please verify annotated events)")
ax1_top.set_xlabel("")

draw_panel(ax1_bot, 700, 1750,
           "Zoomed: t=700-1750s (stall, evap complete, M mode)")
ax1_bot.set_xlabel("Time (s)")

plt.suptitle("vtruxanotherevaplogpart2 -- Corrected event annotations\n"
             "Awaiting user verification of timestamps",
             fontsize=10)
plt.tight_layout()
out = BASE + "anotherevap_p2_corrected_events.png"
plt.savefig(out, dpi=150)
print("Saved:", out)
