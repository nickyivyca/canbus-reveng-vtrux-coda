"""
Today's (2026-08-02) failed startups -- parts truck + main-orig pack.

Owner reports the first two startup attempts of the day failed. This extracts
every contactor sequence in the session and scores it against the documented
precharge-failure signature in notes/specific-trucks/precharge-fail-investigation.md:

    CLOSE_MAINR -> CLOSE_MAINN -> ALL_OPEN_SHUTDOWN   (abort 53-112 ms after
    CLOSE_MAINN entry), simultaneous bcm_epo 0->1, bcm_alarm -> TYPE3,
    0x410 B1 -> 0xCF (FAULT_LATCHED).

Metrics are defined to match the existing table in that file so the numbers are
directly comparable:
  - lvbat at CLOSE_MAINN entry and minimum during CLOSE_MAINN (0x430 bcm_lvbat)
  - HV DC link = bcm_vbus_pos - bcm_vbus_neg at ~55 ms post-MAINN
    (per that file: vbus_pos alone is a node voltage, NOT the bus)
  - cell_tmax at the attempt (0x430)

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/precharge_20260802.py
"""
import sys
sys.path.insert(0, ".")

import glob
import re
import cantools
from canre.parsers import parse_file

DBC = "projects/vtrux/epri-pt-bus.dbc"
ANDROID = "../../CANLogs/VtruxLogs"
SESSION = "vtrux_20260802_123318"
N_CHUNKS = 4          # startups are all in the first ~300 s

MAINC_STAT_STATES = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
ALARM_NAMES = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}

db = cantools.database.load_file(DBC)


def files():
    fs = glob.glob(f"{ANDROID}/{SESSION}_T*.log")
    fs.sort(key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))
    return fs[:N_CHUNKS]


def dec(aid, data):
    try:
        return db.decode_message(aid, bytes(data), decode_choices=False,
                                 allow_truncated=True)
    except Exception:
        return {}


# ---------------------------------------------------------------- collect ---
# One pass: keep a compact event list of everything the analysis needs.
events = []      # (t, kind, payload)
t0 = None
for fn in files():
    for fr in parse_file(fn, absolute=True):
        aid = fr.arbitration_id & 0x7FF
        if aid not in (0x410, 0x430, 0x440):
            continue
        if t0 is None:
            t0 = fr.timestamp
        t = fr.timestamp - t0
        if aid == 0x440:
            d = dec(0x440, fr.data)
            s = d.get("bcm_mainc_stat")
            events.append((t, "stat", (
                MAINC_STAT_STATES[int(s)] if s is not None and int(s) < 16 else "?",
                d.get("bcm_vbus_pos"), d.get("bcm_vbus_neg"))))
        elif aid == 0x410:
            d = dec(0x410, fr.data)
            events.append((t, "bms", (
                d.get("bcm_alarm"), d.get("bcm_epo"), d.get("bcm_hvil_mon"),
                d.get("bcm_vbat"), d.get("bcm_ibat"), fr.data[1])))
        else:
            d = dec(0x430, fr.data)
            events.append((t, "lv", (d.get("bcm_lvbat"), d.get("bcm_cell_tmax"))))

events.sort(key=lambda e: e[0])
print(f"Session {SESSION}: {len(events)} relevant frames over "
      f"{events[-1][0]:.1f}s from first {N_CHUNKS} chunks\n")

# ------------------------------------------------------------- sequences ---
seqs = []
prev = None
for t, kind, p in events:
    if kind != "stat":
        continue
    st = p[0]
    if st != prev:
        if st == "CLOSE_MAINR":
            seqs.append({"t_mainr": t, "trans": [(t, st)]})
        elif seqs:
            seqs[-1]["trans"].append((t, st))
        prev = st

print(f"Found {len(seqs)} CLOSE_MAINR sequences at: "
      f"{[f'{s['t_mainr']:.2f}s' for s in seqs]}\n")


def near(t_at, kind, idx, window=5.0):
    """Most recent value of events[kind][idx] at or before t_at."""
    best = None
    for t, k, p in events:
        if t > t_at:
            break
        if k == kind and p[idx] is not None and t >= t_at - window:
            best = p[idx]
    return best


for i, s in enumerate(seqs, 1):
    trans = s["trans"]
    names = [n for _, n in trans]
    t_mainn = next((t for t, n in trans if n == "CLOSE_MAINN"), None)
    outcome = "SUCCESS" if "MAIN_PN_CLOSED_DRIVE" in names or "CLOSE_MAINP" in names \
        else ("ABORT" if "ALL_OPEN_SHUTDOWN" in names else "?")

    print("=" * 96)
    print(f"SEQUENCE {i}  CLOSE_MAINR @ t={s['t_mainr']:.3f}s   -> {outcome}")
    print("=" * 96)
    print("  transitions: " + "  ".join(f"{n}@{t - s['t_mainr']:+.3f}" for t, n in trans[:10]))

    if t_mainn is None:
        print("  (never reached CLOSE_MAINN)\n")
        continue

    t_abort = next((t for t, n in trans
                    if n == "ALL_OPEN_SHUTDOWN" and t > t_mainn), None)
    if t_abort:
        print(f"  CLOSE_MAINN -> ALL_OPEN_SHUTDOWN in {(t_abort - t_mainn) * 1000:.0f} ms "
              f"(documented failure range: 53-112 ms)")

    # 12V through the CLOSE_MAINN window
    end = t_abort if t_abort else t_mainn + 0.5
    lv_win = [p[0] for t, k, p in events
              if k == "lv" and t_mainn <= t <= end and p[0] is not None]
    lv_entry = near(t_mainn, "lv", 0)
    tmax = near(t_mainn, "lv", 1)
    print(f"  lvbat at CLOSE_MAINN entry: {lv_entry}  "
          f"min during CLOSE_MAINN: {min(lv_win) if lv_win else 'n/a'}  "
          f"cell_tmax: {tmax} C")

    # HV DC link (pos - neg) at ~55 ms post-MAINN
    for label, off in (("+55ms", 0.055), ("+100ms", 0.100)):
        cand = [(t, p) for t, k, p in events
                if k == "stat" and t_mainn + off - 0.03 <= t <= t_mainn + off + 0.03
                and p[1] is not None and p[2] is not None]
        if cand:
            _, p = cand[len(cand) // 2]
            print(f"  HV link at {label:>7}: pos={p[1]:.1f} neg={p[2]:.1f} "
                  f"DIFF={p[1] - p[2]:.1f} V")

    # BMS fault state right after the sequence
    after = [(t, p) for t, k, p in events if k == "bms" and t_mainn <= t <= t_mainn + 1.0]
    changes = []
    last = None
    for t, p in after:
        sig = (p[0], p[1], p[5])
        if sig != last:
            changes.append((t, p))
            last = sig
    print("  BMS state:")
    for t, p in changes[:6]:
        al = ALARM_NAMES.get(int(p[0]), p[0]) if p[0] is not None else "?"
        print(f"    t{t - t_mainn:+.3f}s  alarm={al:<6} epo={p[1]} hvil={p[2]} "
              f"B1=0x{p[5]:02X} vbat={p[3]}")
    print()


# ---------------------------------------------------------------- phase 2 ---
# The CLOSE_MAINN window is only ~55 ms; 0x430 runs at 20 Hz so "min during
# CLOSE_MAINN" is a 1-2 sample statistic. Re-trace 12V across the whole
# sequence window, and look for a BMS dropout between attempts (a 12V cycle,
# which per precharge-fail-investigation.md is what clears FAULT_LATCHED).

print("\n" + "=" * 96)
print("PHASE 2 -- 12V trace across each full sequence window, and BMS dropouts")
print("=" * 96)

for i, s in enumerate(seqs, 1):
    tm = s["t_mainr"]
    lv = [(t, p[0]) for t, k, p in events
          if k == "lv" and tm - 1.0 <= t <= tm + 1.5 and p[0] is not None]
    print(f"\nSEQ {i} @ {tm:.2f}s  ({len(lv)} lvbat samples in [-1.0s, +1.5s])")
    print("  " + "  ".join(f"{t - tm:+.2f}:{v:.1f}" for t, v in lv))
    if lv:
        print(f"  min={min(v for _, v in lv):.1f}  max={max(v for _, v in lv):.1f}")

print("\n" + "-" * 96)
print("BMS 0x410 gaps > 1.0 s (dropout => 12V cycle / BMS power loss)")
print("-" * 96)
bms_t = [t for t, k, _ in events if k == "bms"]
for a, b in zip(bms_t, bms_t[1:]):
    if b - a > 1.0:
        print(f"  gap {b - a:6.1f}s   from t={a:.2f}s to t={b:.2f}s")

print("\n" + "-" * 96)
print("0x410 B1 state around each attempt (0x3F=pre-init, 0xBF=normal, 0xCF=latched)")
print("-" * 96)
last = None
for t, k, p in events:
    if k != "bms" or p[5] is None:
        continue
    if p[5] != last:
        al = ALARM_NAMES.get(int(p[0]), "?") if p[0] is not None else "?"
        print(f"  t={t:8.2f}s  B1=0x{p[5]:02X}  alarm={al:<6} epo={p[1]}")
        last = p[5]


# ---------------------------------------------------------------- phase 3 ---
# Look for ANY pre-fault signal that separates the two failures from the
# success: isolation (bcm_gfd), pack state, cell voltages/temps, SoC.
# H4 in precharge-fail-investigation.md predicts nothing will.

print("\n" + "=" * 96)
print("PHASE 3 -- pre-fault discriminator search (state at CLOSE_MAINR entry)")
print("=" * 96)

EXTRA = {0x410: ["bcm_gfd", "bcm_soc", "bcm_vbat", "bcm_ibat", "bcm_ready",
                 "bcm_on_plug", "bcm_hvil_mon", "bcm_cpwr_cmd"],
         0x430: ["bcm_lvbat", "bcm_cell_vmax", "bcm_cell_vmin",
                 "bcm_cell_tmax", "bcm_cell_tmin"]}

snap = {i: {} for i in range(1, len(seqs) + 1)}
for fn in files():
    for fr in parse_file(fn, absolute=True):
        aid = fr.arbitration_id & 0x7FF
        if aid not in EXTRA:
            continue
        t = fr.timestamp - t0
        for i, s in enumerate(seqs, 1):
            # last frame in the 2 s before CLOSE_MAINR (pre-fault, settled)
            if s["t_mainr"] - 2.0 <= t <= s["t_mainr"]:
                d = dec(aid, fr.data)
                for k in EXTRA[aid]:
                    if d.get(k) is not None:
                        snap[i][k] = d[k]

keys = [k for grp in EXTRA.values() for k in grp]
outc = ["FAIL", "FAIL", "SUCCESS"][:len(seqs)]
print(f"  {'signal':<16}" + "".join(f"{f'SEQ{i} {outc[i-1]}':>16}" for i in range(1, len(seqs) + 1)))
print("  " + "-" * (16 + 16 * len(seqs)))
for k in keys:
    vals = [snap[i].get(k) for i in range(1, len(seqs) + 1)]
    if all(v is None for v in vals):
        continue
    cells = "".join(f"{(f'{v:.2f}' if isinstance(v, float) else str(v)):>16}" for v in vals)
    same = len({round(v, 3) if isinstance(v, float) else v for v in vals if v is not None}) == 1
    print(f"  {k:<16}{cells}   {'(same)' if same else ''}")
