"""Two questions on Truck 3's post-swap log:
  1. Interlock health: full HVIL (0x410 B0 bit3) timeline -- does it close cleanly and stay closed?
     Cross-check 0x644 B0 (VCU leading indicator) and hsc bits.
  2. 12V behaviour: is there ANY lvbat sag during the start attempt (contactor coil inrush)?
     If coils energize they draw current -> 12V dips. Flat rail => coils not being energized.

Compare truck3-post-swap vs a normal start (M3_T11) vs truck3-pre-swap (welded).
"""

import sys
sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

DBC = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")

LOGS = [
    ("truck3-POST-swap",
     "projects/vtrux/logs/truck3-logs/keithlog2.log"),
    ("Normal start (M3_T11)",
     "projects/vtrux/logs/debuglog_M3_T11.log"),
    ("truck3-PRE-swap (welded)",
     "projects/vtrux/logs/truck3-logs/truck3-canlog.log"),
]


def hvil_of(data):
    try:
        d = DBC.decode_message(0x410, data)
        v = d.get("bcm_hvil_mon")
        return None if v is None else int(v)
    except Exception:
        return None


def analyze(label, path):
    frames = list(parse_file(path))
    t0 = frames[0].timestamp

    print("\n" + "=" * 74)
    print(f"{label}   ({len(frames):,} frames)")
    print("=" * 74)

    # --- Interlock timeline (0x410 hvil bit) ---
    print("\n  INTERLOCK (bcm_hvil_mon):")
    last = None
    for f in frames:
        if f.arbitration_id != 0x410:
            continue
        v = hvil_of(f.data)
        if v is not None and v != last:
            print(f"    t={f.timestamp - t0:7.3f}s   hvil {last} -> {v}  ({'CLOSED' if v else 'OPEN'})")
            last = v

    # --- Locate contactor-close command (hsc_mainc_close 0->1 in 0x400) ---
    cmd_t = None
    last_mc = None
    for f in frames:
        if f.arbitration_id != 0x400:
            continue
        try:
            b0 = f.data[0]
        except Exception:
            continue
        mc = (b0 >> 2) & 1
        if mc != last_mc:
            if mc == 1 and cmd_t is None:
                cmd_t = f.timestamp
            last_mc = mc
    if cmd_t is not None:
        print(f"\n  hsc_mainc_close asserted at t={cmd_t - t0:.3f}s")

    # --- 12V (lvbat) fine trace around the attempt ---
    print("\n  12V RAIL (bcm_lvbat, 0x430 B7):")
    lv_series = []
    for f in frames:
        if f.arbitration_id != 0x430:
            continue
        try:
            lv = DBC.decode_message(0x430, f.data).get("bcm_lvbat")
        except Exception:
            lv = None
        if lv is not None:
            lv_series.append((f.timestamp - t0, lv))

    if lv_series:
        vals = [v for _, v in lv_series]
        print(f"    full-log min/max: {min(vals):.2f}V / {max(vals):.2f}V")
        if cmd_t is not None:
            c = cmd_t - t0
            win = [(t, v) for t, v in lv_series if c - 0.3 <= t <= c + 1.2]
            if win:
                wvals = [v for _, v in win]
                print(f"    window [cmd-0.3s .. cmd+1.2s]: min {min(wvals):.2f}V  max {max(wvals):.2f}V  sag {max(wvals)-min(wvals):.2f}V")
                print("    trace (25ms buckets):")
                seen = set()
                for t, v in win:
                    b = round((t - c) * 1000 / 25) * 25
                    if b in seen:
                        continue
                    seen.add(b)
                    bar = "#" * max(0, int(round((13.0 - v) / 0.1)))
                    print(f"      cmd{(t-c)*1000:+7.0f}ms  {v:5.2f}V  {bar}")


if __name__ == "__main__":
    for label, path in LOGS:
        analyze(label, path)
