"""
Battery health comparison: main-orig pack vs parts-orig pack.

BATTERY SEPARATION (VIN + odometer + date -- NOT bcm_alarm TYPE2)
-----------------------------------------------------------------
TYPE2 is deliberately NOT used: as of mid-2026 it is present on both packs, so
it no longer discriminates (it did in the Apr-2026 survey; see
notes/specific-trucks/bcm-alarm-type2-investigation.md, now superseded for this
purpose).

  truck identity:
    VIN  (0x514 digits 2-9 + 0x4E1 digits 10-17, ASCII) when a GM bus is captured
         main  = 3GCUKPEH2EG488714
         parts = 3GCUKPEHXEG537190
    odo  (0x625 B0:B2 24-bit BE, 1 km/count) on PT-bus-only captures
         main  >= 90000 km, parts ~44000 km

  battery identity = truck + date vs the 2025-12-09 swap:
    pre-swap  MAIN  -> main-orig     pre-swap  PARTS -> parts-orig
    post-swap MAIN  -> parts-orig    post-swap PARTS -> main-orig

Health metrics reuse battery_degradation_characterize.py (R_step / R_win / R_reg,
resting-spread decomposition), plus a matched-SoC resting-spread comparison.

Phases (toggle below):
  PHASE1  identity scan of candidate sessions (odo/VIN/date -> truck, battery)
  PHASE2  full characterization (R + spread) of the selected sessions per battery
  PHASE3  matched-SoC resting-spread comparison across the two batteries

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/battery_identity_health_compare.py
"""
import sys
import os
import glob
import re

sys.path.insert(0, ".")
sys.path.insert(0, "projects/vtrux/notes/artifacts")

PHASE1 = False
PHASE2 = False
PHASE3 = False

ANDROID = "../../CANLogs/VtruxLogs"
L = "projects/vtrux/logs"
OTHER = "projects/vtrux/logs/other-logs"

SWAP = "2025-12-09"
ODO_MAIN_MIN = 90000        # main truck odometer floor (km)
ODO_PARTS_MAX = 50000       # parts truck odometer ceiling (km)
VIN_MAIN = "3GCUKPEH2EG488714"
VIN_PARTS = "3GCUKPEHXEG537190"
ALARM_NAMES = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}


# ------------------------------------------------------------------ shared ---
def android_session(stem):
    fs = glob.glob(f"{ANDROID}/{stem}_T*.log")
    return sorted(fs, key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))


def scan_identity(files, max_lines_per_file=3_000_000):
    """Odometer set + VIN fragments from 0x625 / 0x514 / 0x4E1.

    Cheap line scan -- never decodes anything else.
    """
    odos = set()
    vin_hi = None   # 0x514, digits 2-9
    vin_lo = None   # 0x4E1, digits 10-17
    hex_mode = True
    for fp in files:
        n = 0
        with open(fp, "r", errors="replace") as f:
            for line in f:
                n += 1
                if n > max_lines_per_file:
                    break
                if "***HEX***" in line:
                    hex_mode = True
                    continue
                if "***DEC***" in line:
                    hex_mode = False
                    continue
                parts = line.split()
                if len(parts) < 7:
                    continue
                try:
                    aid = int(parts[3], 16)
                except ValueError:
                    continue
                if aid not in (0x0625, 0x0514, 0x04E1):
                    continue
                try:
                    dlc = int(parts[5])
                    base = 16 if hex_mode else 10
                    data = bytes(int(x, base) for x in parts[6:6 + dlc])
                except Exception:
                    continue
                if aid == 0x0625:
                    if len(data) >= 3:
                        odos.add((data[0] << 16) | (data[1] << 8) | data[2])
                elif aid == 0x0514 and vin_hi is None and len(data) >= 8:
                    vin_hi = data.decode("ascii", "replace")
                elif aid == 0x04E1 and vin_lo is None and len(data) >= 8:
                    vin_lo = data.decode("ascii", "replace")
        if odos and vin_hi and vin_lo:
            break
    vin = ("3" + vin_hi + vin_lo) if (vin_hi and vin_lo) else None
    return {"odos": odos, "vin": vin}


def identify(odos, vin, date_str):
    """Return (truck, battery, evidence). VIN wins; odometer is the fallback."""
    truck, ev = None, []
    if vin:
        if vin == VIN_MAIN:
            truck, _ = "MAIN", ev.append(f"VIN={vin}")
        elif vin == VIN_PARTS:
            truck, _ = "PARTS", ev.append(f"VIN={vin}")
        else:
            ev.append(f"VIN={vin}(unknown)")
    if truck is None and odos:
        lo, hi = min(odos), max(odos)
        if lo >= ODO_MAIN_MIN:
            truck = "MAIN"
        elif hi <= ODO_PARTS_MAX:
            truck = "PARTS"
        ev.append(f"odo={lo}..{hi}")
    if truck is None:
        return "TRUCK?", "UNKNOWN", "; ".join(ev) or "no odo/VIN"

    post = date_str >= SWAP
    if truck == "MAIN":
        battery = "parts-orig" if post else "main-orig"
    else:
        battery = "main-orig" if post else "parts-orig"
    ev.append("post-swap" if post else "pre-swap")
    return truck, battery, "; ".join(ev)


# ------------------------------------------------------- candidate sessions ---
CANDIDATES = []


def add(label, files, date):
    files = [f for f in files if os.path.exists(f)]
    if files:
        CANDIDATES.append((label, files, date))


# --- post-swap PARTS truck  => main-orig battery
add("20260802 partstruck drive (NEW)", android_session("vtrux_20260802_123318"), "2026-08-02")
add("20260801 partstruck", android_session("vtrux_20260801_175655"), "2026-08-01")
add("20260421 partstruck testdrive", [f"{L}/vtrux_partstruck_testdrive.log"], "2026-04-21")
add("20260421 partstruck testdrive p4", [f"{L}/vtrux_partstruck_testdrive_part4.log"], "2026-04-21")
add("20260408 partstruck reconnect", [f"{L}/vtrux__partstruck_reconnect.log"], "2026-04-08")

# --- pre-swap MAIN truck    => main-orig battery (its own chassis, 2025)
add("20250625 truklog_M0 drive", [f"{OTHER}/truklog_M0_T{i}.log" for i in (2, 3, 4, 5)], "2025-06-25")
add("20250821 debuglog_M0 drive", [f"{L}/debuglog_M0_T{i}.log" for i in range(1, 7)], "2025-08-21")
add("20250821 oghighwaydrive", [f"{L}/oghighwaydrive.log"], "2025-08-21")

# --- post-swap MAIN truck   => parts-orig battery
add("20260225 currentlimitingtest", [f"{L}/vtruxcurrentlimitingtest.log"], "2026-02-25")
add("20260617 red-SoC drive", android_session("vtrux_20260617_193900"), "2026-06-17")
add("20260724 main drive", android_session("vtrux_20260724_211556"), "2026-07-24")
add("20260726 main drive", android_session("vtrux_20260726_191901"), "2026-07-26")

# --- pre-swap PARTS truck   => parts-orig battery (the "horribly out of balance" era)
add("20250916 truklog_M0_T1 (parts)", [f"{OTHER}/truklog_M0_T1.log"], "2025-09-16")
add("20250920 truklog_M0_T0 (parts)", [f"{OTHER}/truklog_M0_T0.log"], "2025-09-20")


if PHASE1:
    print("=" * 104)
    print("PHASE 1 -- battery identity via VIN + odometer + swap date (TYPE2 NOT used)")
    print(f"swap={SWAP}  main VIN={VIN_MAIN}  parts VIN={VIN_PARTS}")
    print("=" * 104)
    print(f"{'session':<36}{'date':<12}{'truck':>7}  {'battery':<12} evidence")
    print("-" * 104)
    for label, files, date in CANDIDATES:
        r = scan_identity(files)
        truck, battery, ev = identify(r["odos"], r["vin"], date)
        print(f"{label:<36}{date:<12}{truck:>7}  {battery:<12} {ev}")


# ---------------------------------------------------------------- phase 2 ---
# Health characterization per session, grouped by battery identity.
# Reuses battery_degradation_characterize (R_step/R_win/R_reg + spread decomp).

# (label, battery) pairs to characterize, drive-type sessions with real current.
SELECT = [
    ("20260802 partstruck drive (NEW)", "main-orig"),
    ("20260421 partstruck testdrive", "main-orig"),
    ("20250625 truklog_M0 drive", "main-orig"),
    ("20250821 debuglog_M0 drive", "main-orig"),
    ("20260225 currentlimitingtest", "parts-orig"),
    ("20260617 red-SoC drive", "parts-orig"),
    ("20260724 main drive", "parts-orig"),
    ("20250916 truklog_M0_T1 (parts)", "parts-orig"),
]

if PHASE2:
    from battery_degradation_characterize import characterize

    by_label = {lab: (files, date) for lab, files, date in CANDIDATES}
    results = []
    for lab, batt in SELECT:
        if lab not in by_label:
            print(f"\n!! {lab}: no files found, skipped")
            continue
        files, date = by_label[lab]
        r = characterize(f"[{batt}] {lab}  ({date})", files)
        if r:
            r["battery"] = batt
            r["date"] = date
            r["short"] = lab
            results.append(r)

    print("\n" + "=" * 104)
    print("PHASE 2 SUMMARY -- per-cell internal resistance (mOhm) and spread, by battery")
    print("=" * 104)
    hdr = (f"  {'battery':<12}{'session':<34}{'date':<12}{'SoC%':>12}{'I(A)':>15}"
           f"{'spread':>8}{'Rstep':>7}{'Rwin':>7}{'Rreg':>7}")
    print(hdr)
    for batt in ("main-orig", "parts-orig"):
        for r in results:
            if r["battery"] != batt:
                continue
            R = r["R"].get("avg", {})
            print(f"  {batt:<12}{r['short']:<34}{r['date']:<12}"
                  f"{r['soc'][0]:>6.1f}-{r['soc'][1]:<5.1f}"
                  f"{r['cur'][0]:>7.0f}-{r['cur'][1]:<7.0f}{r['spread_mean']:>8.1f}"
                  f"{R.get('R_step', float('nan')):>7.2f}{R.get('R_win', float('nan')):>7.2f}"
                  f"{R.get('R_reg', float('nan')):>7.2f}")


# ---------------------------------------------------------------- phase 3 ---
# Matched-SoC resting-spread comparison across the two batteries.
#
# Spread is SoC-amplified (steep LFP OCV curve at the extremes), so cross-pack
# imbalance comparisons are only valid within the same 1% SoC band at rest.
#
# Also decomposes the spread about the pack average into
#     low-side  = avg - vmin   (how far the weakest cell sags below the pack)
#     high-side = vmax - avg   (how far the strongest cell sits above it)
# A single weak cell shows as low-side >> high-side; broad imbalance shows both.

REST_SESSIONS = [
    # (label, battery)
    ("20260802 partstruck drive (NEW)", "main-orig"),
    ("20260421 partstruck testdrive", "main-orig"),
    ("20250625 truklog_M0 drive", "main-orig"),
    ("20250821 debuglog_M0 drive", "main-orig"),
    ("20260617 red-SoC drive", "parts-orig"),
    ("20260724 main drive", "parts-orig"),
    ("20260225 currentlimitingtest", "parts-orig"),
    ("20250916 truklog_M0_T1 (parts)", "parts-orig"),
]


def settled_rest(s, i_rest=10.0, i_prior=15.0, settle_s=2.0):
    """Samples at rest (|I| < i_rest) with no load spike in the prior settle_s."""
    out = []
    for i in range(len(s)):
        if abs(s[i]["ibat"]) >= i_rest:
            continue
        ok, j, span = True, i - 1, 0.0
        while j >= 0 and span < settle_s:
            dt = s[j + 1]["t"] - s[j]["t"]
            if dt < 0:
                break
            span += dt
            if abs(s[j]["ibat"]) >= i_prior:
                ok = False
                break
            j -= 1
        if ok:
            out.append(s[i])
    return out


if PHASE3:
    from battery_degradation_characterize import collect, median

    by_label = {lab: (files, date) for lab, files, date in CANDIDATES}
    rest = {}
    for lab, batt in REST_SESSIONS:
        if lab not in by_label:
            continue
        files, date = by_label[lab]
        s = collect(files)
        r = settled_rest(s)
        rest[lab] = {"batt": batt, "date": date, "rest": r, "n_all": len(s)}
        socs = [x["soc"] for x in r]
        tm = [x["tmax"] for x in r if x["tmax"] is not None]
        print(f"{batt:<11} {lab:<34} {date}  samples={len(s):>7}  rest={len(r):>7}"
              f"  SoC={min(socs) if socs else 0:.0f}-{max(socs) if socs else 0:.0f}%"
              f"  tmax={min(tm) if tm else 0:.0f}-{max(tm) if tm else 0:.0f}C")

    print("\n" + "=" * 104)
    print("PHASE 3 -- resting (|I|<10A, settled 2s) vmax-vmin spread by 1% SoC band, mV [n]")
    print("=" * 104)
    labels = [l for l, _ in REST_SESSIONS if l in rest]
    print(f"{'SoC':>7}", end="")
    for l in labels:
        print(f"{l[:15]:>17}", end="")
    print()
    print(f"{'':>7}", end="")
    for l in labels:
        print(f"{rest[l]['batt'][:15]:>17}", end="")
    print()
    print("-" * (7 + 17 * len(labels)))
    for lo in range(5, 101):
        row = {}
        for l in labels:
            band = [x["vmax"] - x["vmin"] for x in rest[l]["rest"]
                    if lo <= x["soc"] < lo + 1]
            if len(band) >= 20:
                row[l] = (median(band), len(band))
        if len(row) >= 2:
            print(f"{lo:>4}-{lo+1:<3}", end="")
            for l in labels:
                if l in row:
                    m, n = row[l]
                    print(f"{m:>11.1f}[{n:>4}]", end="")
                else:
                    print(f"{'':>17}", end="")
            print()

    print("\n" + "=" * 104)
    print("PHASE 3b -- spread decomposition about pack average (weak-cell test)")
    print("  low = avg-vmin (weak cell sag) | high = vmax-avg | at rest, per 5% SoC band")
    print("=" * 104)
    print(f"{'battery':<12}{'session':<34}{'SoC band':>10}{'n':>7}{'low mV':>9}{'high mV':>9}{'low/tot':>9}")
    for l in labels:
        r = rest[l]
        for lo in range(10, 100, 5):
            band = [x for x in r["rest"] if lo <= x["soc"] < lo + 5]
            if len(band) < 50:
                continue
            low = median([x["avg"] - x["vmin"] for x in band])
            high = median([x["vmax"] - x["avg"] for x in band])
            tot = low + high
            frac = low / tot if tot else float("nan")
            print(f"{r['batt']:<12}{l[:33]:<34}{lo:>6}-{lo+5:<3}{len(band):>7}"
                  f"{low:>9.1f}{high:>9.1f}{frac:>9.2f}")


# ---------------------------------------------------------------- phase 4 ---
# Sanity checks on the phase-3b decomposition.
#  (a) avg = vbat/116 is a derived pack average; if it is biased low, avg-vmin
#      goes negative (physically impossible for a true minimum). Quantify the
#      bias so the low/high split can be read correctly.
#  (b) resting spread vs SoC curve per session -- a low-capacity cell should
#      diverge at the ends of the LFP curve and hide on the mid plateau.

PHASE4 = False

if PHASE4:
    from battery_degradation_characterize import collect, median

    by_label = {lab: (files, date) for lab, files, date in CANDIDATES}
    print("=" * 104)
    print("PHASE 4a -- bias check on avg=vbat/116 (median vmin-avg and vmax-avg at rest)")
    print("  vmin-avg should be <= 0 for a true pack minimum; positive => avg biased low")
    print("=" * 104)
    print(f"{'battery':<12}{'session':<34}{'n_rest':>8}{'vmin-avg':>10}{'vmax-avg':>10}{'spread':>9}")
    cache = {}
    for lab, batt in REST_SESSIONS:
        if lab not in by_label:
            continue
        files, _ = by_label[lab]
        r = settled_rest(collect(files))
        cache[lab] = (batt, r)
        if not r:
            continue
        print(f"{batt:<12}{lab[:33]:<34}{len(r):>8}"
              f"{median([x['vmin'] - x['avg'] for x in r]):>10.1f}"
              f"{median([x['vmax'] - x['avg'] for x in r]):>10.1f}"
              f"{median([x['vmax'] - x['vmin'] for x in r]):>9.1f}")

    print("\n" + "=" * 104)
    print("PHASE 4b -- resting spread vs SoC (5% bands), per session")
    print("=" * 104)
    for lab, (batt, r) in cache.items():
        cells = []
        for lo in range(10, 101, 5):
            band = [x["vmax"] - x["vmin"] for x in r if lo <= x["soc"] < lo + 5]
            cells.append(f"{lo}:{median(band):.0f}[{len(band)}]" if len(band) >= 30 else None)
        line = "  ".join(c for c in cells if c)
        print(f"\n{batt:<11} {lab}\n  {line}")


# ---------------------------------------------------------------- phase 5 ---
# Today's (main-orig) session opens with the BMS in TYPE3 before settling into
# TYPE2. Reconstruct the alarm timeline against pack state to see whether this
# is a live fault during the drive or a stale latch cleared at key-on.

PHASE5 = True

if PHASE5:
    import cantools
    from canre.parsers import parse_file

    db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
    M410 = db.get_message_by_name("EPRI_BCM_Status_0410")
    files = android_session("vtrux_20260802_123318")[:3]

    print("=" * 104)
    print("PHASE 5 -- today's session (main-orig): bcm_alarm timeline vs pack state")
    print("=" * 104)
    prev = None
    t0 = None
    rows = 0
    for fn in files:
        for fr in parse_file(fn, absolute=True):
            if (fr.arbitration_id & 0x7FF) != 0x410:
                continue
            if t0 is None:
                t0 = fr.timestamp
            a = (fr.data[1] >> 6) & 3
            if a == prev:
                continue
            prev = a
            try:
                d = M410.decode(fr.data, decode_choices=False, allow_truncated=True)
            except Exception:
                d = {}
            print(f"  t={fr.timestamp - t0:8.1f}s  alarm={ALARM_NAMES[a]:<6}"
                  f" B1=0x{fr.data[1]:02X} B2=0x{fr.data[2]:02X}"
                  f"  vbat={d.get('bcm_vbat')}  ibat={d.get('bcm_ibat')}"
                  f"  soc={d.get('bcm_soc')}  epo={d.get('bcm_epo')}"
                  f"  ready={d.get('bcm_ready')}  hvil={d.get('bcm_hvil_mon')}")
            rows += 1
            if rows > 40:
                break
        if rows > 40:
            break
