"""
Decode the VCU -> Bel charger command frame 0x18EFC000 across charge sessions.

0x18EFC000 is J1939 PDU1 proprietary-A: PF=0xEF, DA=0xC0 (Bel charger), SA=0x00 (VCU).
It carries no DBC definition anywhere in the project. This script correlates its
eight raw bytes against the BMS/charger signals that are already decoded, so the
command semantics can be worked out.

Phases:
    profile <filtered.log>   decimated table: cmd bytes + BMS/charger reference signals
    changes <filtered.log>   every byte-level transition of 0x18EFC000, with context
    window  <filtered.log> <t0> <t1>   dense dump over a time window

Input logs should be pre-filtered with charge_cmd_filter.sh.
"""

import sys

sys.path.insert(0, ".")

import cantools
from canre.parsers import parse_file

CMD_ID = 0x18EFC000

EPRI = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
BEL = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")

# ids we decode for context, and which database owns them
CTX = {
    0x410: EPRI, 0x420: EPRI, 0x430: EPRI, 0x440: EPRI, 0x411: EPRI,
    0x18FFD4C0: BEL, 0x18FFD7C0: BEL, 0x18FFD9C0: BEL,
}

WANT = [
    ("soc", 0x410, "bcm_soc"),
    ("vmax", 0x430, "bcm_cell_vmax"),
    ("vmin", 0x430, "bcm_cell_vmin"),
    ("ibat", 0x410, "bcm_ibat"),
    ("vbat", 0x410, "bcm_vbat"),
    ("chgmax", 0x420, "bcm_chg_max"),
    ("done", 0x410, "bcm_chg_done"),
    ("chgc", 0x410, "bcm_chgc_stat"),
    ("cpwr", 0x410, "bcm_cpwr_cmd"),
    ("chga_ena", 0x430, "bcm_chga_ena"),
    ("bal", 0x440, "bcm_balancing_cnt"),
    ("state", 0x18FFD4C0, "BELINV_state"),
    ("chgI", 0x18FFD7C0, "BELINV_hvBatteryCurrent"),
    ("chgV", 0x18FFD7C0, "BELINV_hvBatteryVoltage"),
    ("maxAvail", 0x18FFD9C0, "BELINV_maxAvailableChargingCurrent"),
    ("vehSt", 0x18FFD9C0, "BELINV_vehicleState"),
]


def decode(fid, data):
    db = CTX.get(fid)
    if db is None:
        return {}
    try:
        return db.decode_message(fid, data, decode_choices=False,
                                 allow_truncated=True)
    except Exception:
        return {}


def stream(path):
    """Yield (t, latest_ctx_dict, cmd_bytes_or_None) for each frame of interest."""
    ctx = {}
    cmd = None
    for fr in parse_file(path):
        fid = fr.arbitration_id
        if fid == CMD_ID:
            cmd = bytes(fr.data)
            yield fr.timestamp, ctx, cmd
        elif fid in CTX:
            d = decode(fid, fr.data)
            for name, mid, sig in WANT:
                if mid == fid and sig in d:
                    ctx[name] = d[sig]
            yield fr.timestamp, ctx, None


def fmt_ctx(ctx):
    out = []
    for name, _mid, _sig in WANT:
        v = ctx.get(name)
        if v is None:
            out.append("%s=-" % name)
        elif isinstance(v, float):
            out.append("%s=%.3f" % (name, v))
        else:
            out.append("%s=%s" % (name, v))
    return " ".join(out)


def phase_profile(path, step=60.0):
    print("t_s      cmd(hex)                 " + " ".join(n for n, _, _ in WANT))
    nxt = None
    for t, ctx, cmd in stream(path):
        if cmd is None:
            continue
        if nxt is None:
            nxt = t
        if t < nxt:
            continue
        nxt = t + step
        row = " ".join(
            ("-" if ctx.get(n) is None else
             ("%.3f" % ctx[n] if isinstance(ctx[n], float) else str(ctx[n])))
            for n, _, _ in WANT)
        print("%-8.1f %-24s %s" % (t, cmd.hex(" "), row))


def phase_changes(path):
    prev = None
    print("t_s      cmd(hex)                 changed  | context")
    for t, ctx, cmd in stream(path):
        if cmd is None:
            continue
        if prev is None:
            print("%-8.1f %-24s %-8s | %s" % (t, cmd.hex(" "), "INIT", fmt_ctx(ctx)))
            prev = cmd
            continue
        if cmd != prev:
            diff = ",".join("B%d:%02X->%02X" % (i, prev[i], cmd[i])
                            for i in range(len(cmd)) if prev[i] != cmd[i])
            print("%-8.1f %-24s %-8s | %s" % (t, cmd.hex(" "), diff, fmt_ctx(ctx)))
            prev = cmd


def phase_window(path, t0, t1, step=1.0):
    nxt = t0
    for t, ctx, cmd in stream(path):
        if t < t0:
            continue
        if t > t1:
            break
        if cmd is None or t < nxt:
            continue
        nxt = t + step
        print("%-9.2f %-24s %s" % (t, cmd.hex(" "), fmt_ctx(ctx)))




# --------------------------------------------------------------------------
# 0x18EFC000 is a rotating multiplexed frame: a fixed cycle of pages repeats at
# ~3.3 Hz (6 frames, ~20 Hz aggregate). B0 (and for B0=0x03, B1) selects the page.
# --------------------------------------------------------------------------

def page_key(cmd):
    return (cmd[0], cmd[1]) if cmd[0] == 0x03 else (cmd[0],)


def phase_pages(path):
    """Per-page byte-transition log with BMS/charger context."""
    last = {}
    first_seen = {}
    print("t_s      page      cmd(hex)                 changed              | context")
    for t, ctx, cmd in stream(path):
        if cmd is None:
            continue
        k = page_key(cmd)
        kn = ".".join("%02X" % b for b in k)
        prev = last.get(k)
        if prev is None:
            first_seen[k] = t
            print("%-8.1f %-9s %-24s %-20s | %s" % (t, kn, cmd.hex(" "), "FIRST", fmt_ctx(ctx)))
        elif prev != cmd:
            diff = ",".join("B%d:%02X->%02X" % (i, prev[i], cmd[i])
                            for i in range(len(cmd)) if prev[i] != cmd[i])
            print("%-8.1f %-9s %-24s %-20s | %s" % (t, kn, cmd.hex(" "), diff, fmt_ctx(ctx)))
        last[k] = cmd


def phase_pageprofile(path, step=300.0):
    """One row per time step showing every page's current payload side by side."""
    cur = {}
    order = []
    nxt = None
    rows = []
    for t, ctx, cmd in stream(path):
        if cmd is None:
            continue
        k = page_key(cmd)
        if k not in cur:
            order.append(k)
        cur[k] = cmd
        if nxt is None:
            nxt = t
        if t < nxt:
            continue
        nxt = t + step
        rows.append((t, dict(cur), dict(ctx)))
    order.sort()
    hdr = "t_s      " + " ".join("%-24s" % (".".join("%02X" % b for b in k)) for k in order)
    print(hdr + "  soc  vmax  vmin  ibat  chgmax done bal chgI")
    for t, c, ctx in rows:
        cells = " ".join("%-24s" % (c[k].hex(" ") if k in c else "-") for k in order)
        def g(n, f="%.3f"):
            v = ctx.get(n)
            return "-" if v is None else (f % v)
        print("%-8.1f %s  %s %s %s %s %s %s %s %s" %
              (t, cells, g("soc", "%.1f"), g("vmax"), g("vmin"), g("ibat", "%.2f"),
               g("chgmax", "%.1f"), g("done", "%.0f"), g("bal", "%.0f"), g("chgI", "%.2f")))


if __name__ == "__main__":
    ph = sys.argv[1]
    p = sys.argv[2]
    if ph == "profile":
        phase_profile(p, float(sys.argv[3]) if len(sys.argv) > 3 else 60.0)
    elif ph == "changes":
        phase_changes(p)
    elif ph == "pages":
        phase_pages(p)
    elif ph == "pageprofile":
        phase_pageprofile(p, float(sys.argv[3]) if len(sys.argv) > 3 else 300.0)
    elif ph == "window":
        phase_window(p, float(sys.argv[3]), float(sys.argv[4]),
                     float(sys.argv[5]) if len(sys.argv) > 5 else 1.0)
