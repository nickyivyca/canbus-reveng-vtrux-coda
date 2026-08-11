"""
Test hypothesis: B2 = [zone(bits7-4)] [const(bit3)] [1(bit2)] [0(bit1)] [carry(bit0)]
where bit0 of B2 is the 9th bit of the temperature (extends B1 to 9-bit value).
Upper nibble (B2>>4) = thermal zone {3,4,5,6}.
Also tries upper 2 bits of upper nibble (bits 7-6) as 2 MSBs -> 10-bit.
"""
import csv, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

def load(path):
    rows = list(csv.DictReader(open(path)))
    return (np.array([float(r["timestamp"]) for r in rows]),
            np.array([float(r["value"])     for r in rows]))

t_dcdc, v_dcdc = load("projects/vtrux/notes/artifacts/overheat_dcdc_temp.csv")
t_b0,   v_b0   = load("projects/vtrux/notes/artifacts/overheat_0x483_B0.csv")
t_b1,   v_b1   = load("projects/vtrux/notes/artifacts/overheat_0x483_B1.csv")
t_b2,   v_b2   = load("projects/vtrux/notes/artifacts/overheat_0x483_B2.csv")
t_pump, v_pump = load("projects/vtrux/notes/artifacts/overheat_pump_speed.csv")

temp_c = v_dcdc * 0.1
pump_reconnect = t_pump[0]
gaps = np.diff(t_dcdc)
big  = np.where(gaps > 2.0)[0]
gap_start = t_dcdc[big[0]]   if len(big) else None
gap_end   = t_dcdc[big[0]+1] if len(big) else None

v_b2i = v_b2.astype(int)
v_b1i = v_b1.astype(int)

# Decompose B2
zone       = (v_b2i >> 4) & 0x0F   # upper nibble: thermal zone
bit2_const = (v_b2i >> 2) & 0x01   # should be always 1
carry_bit  = (v_b2i >> 0) & 0x01   # bit0: 9th bit of temperature

# 9-bit temperature = carry<<8 | B1
temp9 = (carry_bit << 8) | v_b1i

# 10-bit attempt: use bits 5-4 of B2 (lower 2 bits of upper nibble) as MSBs
bits54    = (v_b2i >> 4) & 0x03    # bits 5,4 of B2 as 2 MSBs -> 10-bit
temp10_54 = (bits54 << 8) | v_b1i

# Print decomposition summary
print("B2 decomposition:")
print("%-6s %-8s %-6s %-8s %-6s" % ("B2", "binary", "zone", "bit2(1?)", "carry"))
for val in sorted(set(v_b2i)):
    z = (val >> 4) & 0xF
    b2 = (val >> 2) & 1
    c  = val & 1
    print("  %3d  0b%08d   z=%d   bit2=%d   carry=%d" % (
        val, int(bin(val)[2:].zfill(8)), z, b2, c))

print()
print("9-bit temp (carry<<8|B1): min=%d  max=%d" % (temp9.min(), temp9.max()))
print("  monotonic check: transitions down = %d out of %d" % (
    np.sum(np.diff(temp9) < -4), len(temp9)-1))

# correlation with DCDC temp (windowed, skip sentinel, skip key-off)
valid_mask = (t_b1 > 90) & (t_b1 < 410)
dcdc_interp = np.interp(t_b1[valid_mask], t_dcdc, temp_c)
def pearson(a, b):
    a = a - a.mean(); b = b - b.mean()
    denom = np.sqrt((a**2).sum() * (b**2).sum())
    return (a*b).sum() / denom if denom > 0 else 0.0

r9   = pearson(temp9[valid_mask].astype(float), dcdc_interp)
r_b1 = pearson(v_b1[valid_mask], dcdc_interp)
r_b0 = pearson(v_b0[valid_mask], dcdc_interp)
print("Windowed Pearson r vs DCDC temp (t=90-410s):")
print("  B0 alone:        r = %.4f" % r_b0)
print("  B1 alone:        r = %.4f" % r_b1)
print("  9-bit (carry|B1): r = %.4f" % r9)

print()
print("Zone sequence (upper nibble of B2):")
zone_changes = np.where(np.diff(zone) != 0)[0]
for i in zone_changes:
    print("  t=%.2f  zone %d -> %d  (B1=%d  carry=%d  9-bit=%d)" % (
        t_b2[i], zone[i], zone[i+1], v_b1i[i], carry_bit[i], temp9[i]))

# PLOT
fig = plt.figure(figsize=(13, 14))
gs  = gridspec.GridSpec(6, 1, hspace=0.10)
axs = [fig.add_subplot(gs[0])]
for i in range(1, 6):
    axs.append(fig.add_subplot(gs[i], sharex=axs[0]))

def annotate(ax):
    if gap_start:
        ax.axvspan(gap_start, gap_end, alpha=0.12, color="gray")
    ax.axvline(pump_reconnect, color="#27ae60", lw=1.2, ls="--", alpha=0.8)

axs[0].plot(t_dcdc, temp_c, color="#c0392b", lw=1.2)
axs[0].set_ylabel("DCDC temp (degC)", fontsize=9)
axs[0].set_title("0x483 B2 bit decomposition\n"
                 "green dashed = pump reconnect  |  gray = key-off", fontsize=9)
annotate(axs[0])

axs[1].plot(t_b0, v_b0 - 100, color="#8e44ad", lw=1.1, marker=".", markersize=2)
axs[1].set_ylabel("B0-100 (degC)", fontsize=9)
annotate(axs[1])

axs[2].plot(t_b2, zone, color="#2980b9", lw=1.1, marker=".", markersize=3, drawstyle="steps-post")
axs[2].set_ylabel("B2 upper nibble\n(zone)", fontsize=9)
axs[2].set_yticks(sorted(set(zone)))
annotate(axs[2])

axs[3].plot(t_b2, carry_bit, color="#e67e22", lw=1.0, marker=".", markersize=3, drawstyle="steps-post")
axs[3].set_ylabel("B2 bit0\n(carry?)", fontsize=9)
axs[3].set_yticks([0, 1])
annotate(axs[3])

axs[4].plot(t_b1, temp9, color="#16a085", lw=1.1, marker=".", markersize=2)
axs[4].set_ylabel("9-bit temp\n(carry<<8|B1)", fontsize=9)
axs[4].text(0.01, 0.92, "r_win=%.4f vs DCDC  |  r_B1=%.4f" % (r9, r_b1),
            transform=axs[4].transAxes, fontsize=8, va="top")
annotate(axs[4])

axs[5].plot(t_b1, temp10_54, color="#c0392b", lw=1.1, marker=".", markersize=2, alpha=0.7)
axs[5].set_ylabel("10-bit (bits54<<8|B1)", fontsize=9)
axs[5].set_xlabel("Time (s)", fontsize=9)
annotate(axs[5])

for ax in axs[:5]:
    plt.setp(ax.get_xticklabels(), visible=False)
axs[0].set_xlim(0, t_dcdc[-1] + 5)

out = "projects/vtrux/notes/artifacts/overheat_0x483_bitpack.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print("Saved:", out)
