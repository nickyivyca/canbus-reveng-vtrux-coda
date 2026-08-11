"""Exhaust-contribution hunt on the 20260714 final drive.

Drive profile (per driver): EV-only for a while -> engine ON to climb a hill ->
engine OFF at the top. The exhaust runs around the REAR-RIGHT corner of the pack
behind a heat shield; the PE-loop cold-plate is FRONT-RIGHT. If the exhaust feeds
heat into the pack, expect the tmax-tmin SPREAD to widen tied to engine-on timing
(a different corner than the loop, faster than the loop's slow response).

Detect engine-on via GENE_RotSpd (0x0054, generator RPM). Track tmax/tmin/spread,
PE-loop temp, and pack current, at fine resolution through the final drive.
Short timescale + 0.5C quantization -> look for trends, not proof.
"""
import sys
sys.path.insert(0, ".")

import glob
import struct
import subprocess
from datetime import datetime

import cantools

from battery_fan_signature import parse_header_time, decode_line

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = pt.get_message_by_frame_id(0x410)
M430 = pt.get_message_by_frame_id(0x430)
M0054 = pt.get_message_by_frame_id(0x0054)

LOG_DIR = "<home>/Seafile/CANLogs/VtruxLogs"
WIN0 = datetime(2026, 7, 14, 21, 40)
WIN1 = datetime(2026, 7, 14, 22, 50)


def gene_rpm(data):
    try:
        v = M0054.decode(data, allow_truncated=True).get("GENE_RotSpd")
        return v
    except Exception:
        return None


def run():
    files = sorted(glob.glob(f"{LOG_DIR}/vtrux_20260714_161319_T*.log"),
                   key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
    sel = []
    for f in files:
        base = parse_header_time(f)
        if base is None:
            continue
        if base <= WIN1 and base.replace(minute=base.minute):  # cheap; refine below
            sel.append((f, base))
    # keep chunks whose start is < WIN1 and (next start) > WIN0
    chunks = []
    for i, (f, b) in enumerate(sel):
        nxt = sel[i + 1][1] if i + 1 < len(sel) else WIN1
        if b <= WIN1 and nxt >= WIN0:
            chunks.append(f)

    rows = []
    last = dict(rpm=None, ib=None, pe=None)
    last_emit = None
    for path in chunks:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x(54|410|430|18FFD6B3) ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if t < WIN0 or t > WIN1:
                continue
            if arb == 0x54:
                last["rpm"] = gene_rpm(data)
            elif arb == 0x410:
                try:
                    last["ib"] = M410.decode(data, allow_truncated=True).get("bcm_ibat")
                except Exception:
                    pass
            elif arb == 0x18FFD6B3 and len(data) >= 8:
                last["pe"] = struct.unpack("<h", bytes(data[6:8]))[0] * 0.1
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax"); tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                if tmax is None or tmax < -30 or tmax > 80:
                    continue
                ep = t.timestamp()
                if last_emit is not None and ep - last_emit < 20:
                    continue
                last_emit = ep
                rows.append((t, tmax, tmin, last["rpm"], last["ib"], last["pe"]))
    if not rows:
        print("no data in window"); return

    # engine-on window
    on = [r for r in rows if r[3] is not None and r[3] > 500]
    if on:
        print(f"ENGINE ON (GENE_RotSpd>500): {on[0][0].strftime('%H:%M:%S')} -> "
              f"{on[-1][0].strftime('%H:%M:%S')}  "
              f"({(on[-1][0]-on[0][0]).total_seconds()/60:.1f} min), "
              f"peak RPM {max(r[3] for r in on):.0f}")
    print(f"\n{'time':>8} {'gRPM':>6} {'tmax':>5} {'tmin':>5} {'spread':>6} {'loop':>5} {'ibat':>6}")
    for r in rows:
        t, tmax, tmin, rpm, ib, pe = r
        rp = f"{rpm:.0f}" if rpm is not None else "?"
        pes = f"{pe:.1f}" if pe is not None else "?"
        ibs = f"{ib:.0f}" if ib is not None else "?"
        mark = " <ENG" if (rpm is not None and rpm > 500) else ""
        print(f"{t.strftime('%H:%M:%S'):>8} {rp:>6} {tmax:5.1f} {tmin:5.1f} "
              f"{tmax-tmin:6.1f} {pes:>5} {ibs:>6}{mark}")


if __name__ == "__main__":
    run()
