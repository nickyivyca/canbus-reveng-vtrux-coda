"""
Plot engine RPM (0x63C B6) and B3 for vtruxanotherevaplogpart2.log.
Annotates guessed event times based on B3 trajectory analysis.
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

def load_csv(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    data = [(float(r[0]), int(r[1])) for r in rows[1:]]
    return [x[0] for x in data], [x[1] for x in data]

BASE = "projects/vtrux/notes/artifacts/"
rpm_t, rpm_v = load_csv(BASE + "anotherevap_p2_rpm.csv")
b3_t,  b3_v  = load_csv(BASE + "anotherevap_p2_0x600_b3.csv")

# Guessed events based on B3 trajectory (times in seconds within part 2)
# Each entry: (time, label, color, linestyle)
events = [
    ( 69,  "engine start?",     "green",  "--"),
    (120,  "B3->12 reset?",     "orange", ":"),
    (175,  "engine restart?",   "green",  "--"),
    (1388, "B3=11 stable?",     "blue",   "-."),
    (1458, "evap complete?",    "blue",   "-"),
    (1521, "stall?",            "red",    "--"),
    (1534, "restart attempt?",  "red",    ":"),
    (1655, "manual stop?",      "purple", "--"),
]

fig, ax1 = plt.subplots(figsize=(18, 6))

# RPM (left axis)
ax1.plot(rpm_t, rpm_v, color="steelblue", linewidth=0.6, alpha=0.85, label="RPM (0x63C B6 raw)")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("RPM raw count", color="steelblue")
ax1.tick_params(axis="y", labelcolor="steelblue")
ax1.set_xlim(0, max(rpm_t))
ax1.grid(True, alpha=0.3)

# B3 (right axis)
ax2 = ax1.twinx()
ax2.step(b3_t, b3_v, color="darkorange", linewidth=0.8, alpha=0.7, where="post", label="0x600 B3")
ax2.set_ylabel("0x600 B3", color="darkorange")
ax2.tick_params(axis="y", labelcolor="darkorange")
ax2.set_ylim(-0.5, 13)
ax2.yaxis.set_major_locator(ticker.MultipleLocator(1))

# Annotate guessed events
for t, label, color, ls in events:
    ax1.axvline(t, color=color, linestyle=ls, linewidth=1.2, alpha=0.8)
    ax1.text(t + 4, ax1.get_ylim()[1] * 0.92, label,
             fontsize=7, color=color, rotation=90, va="top")

# Combined legend
lines1, labs1 = ax1.get_legend_handles_labels()
lines2, labs2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labs1 + labs2, loc="upper left", fontsize=8)

plt.title("vtruxanotherevaplogpart2 -- Engine RPM (0x63C B6) + 0x600 B3\nEvent times are guesses based on B3 trajectory")
plt.tight_layout()
out = BASE + "anotherevap_p2_rpm_events.png"
plt.savefig(out, dpi=150)
print("Saved:", out)
