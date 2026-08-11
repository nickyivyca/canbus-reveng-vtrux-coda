import sys, glob, math, collections, cantools
sys.path.insert(0, r"<repo>")
from canre.parsers import parse_file

base = r"<repo>\projects\vtrux"
LOGS = sorted(
    glob.glob(base + r"\logs\vtruxevapdrivelog*.log") +
    glob.glob(base + r"\logs\vtruxanotherevaplog*.log")
)

pt_db      = cantools.database.load_file(base + r"\epri-pt-bus.dbc")
obd_db     = cantools.database.load_file(base + r"\epri-obd-bus.dbc")
obd_exp_db = cantools.database.load_file(base + r"\vtrux-obd-experimental.dbc")

ID_GENE_PWR = 0x482
ID_GENE_TRQ = 0x471
ID_GENE_RPM = 0x054
ID_GENE_CMD = 0x051  # GENE torque command from VCM (PT bus)
ID_TRAC_PWR = 0x462
ID_TRAC_TRQ = 0x442
ID_TRAC_RPM = 0x044

GENE_CMD_SCALE  = 1.0
GENE_CMD_OFFSET = -32768.0

RPM_HISTORY = 10  # frames of RPM history to detect falling RPM

def make_state():
    return {
        "peak_dc_pwr_pos": 0.0, "ctx_pos": None,
        "peak_dc_pwr_neg": 0.0, "ctx_neg": None,
        "peak_trq_neg": 0.0, "ctx_trq_neg": None,
        "peak_trq_pos": 0.0, "ctx_trq_pos": None,
        "last_curr": None, "last_volt": None, "last_trq": None, "last_rpm": None,
        "last_cmd": None,
        "rpm_history": collections.deque(maxlen=RPM_HISTORY),
        "count_pwr": 0, "count_trq": 0,
    }

def snap(state, ts, log, pwr_dc, pwr_mech):
    rpm_hist = list(state["rpm_history"])
    rpm_rate = None
    if len(rpm_hist) >= 2:
        t0, r0 = rpm_hist[0]
        t1, r1 = rpm_hist[-1]
        dt = t1 - t0
        if dt > 0:
            rpm_rate = (r1 - r0) / dt
    return {
        "ts": ts, "log": log,
        "pwr_dc": pwr_dc, "pwr_mech": pwr_mech,
        "curr": state["last_curr"], "volt": state["last_volt"],
        "trq": state["last_trq"], "rpm": state["last_rpm"],
        "cmd": state["last_cmd"],
        "rpm_rate": rpm_rate,
        "rpm_history": [(r, t) for t, r in rpm_hist[-5:]],
    }

def track(state, ts, log):
    curr_a = state["last_curr"]
    volt_v = state["last_volt"]
    trq_nm = state["last_trq"]
    rpm    = state["last_rpm"]

    pwr_dc = None
    if curr_a is not None and volt_v is not None and volt_v > 0:
        pwr_dc = curr_a * volt_v / 1000.0

    pwr_mech = None
    if trq_nm is not None and rpm is not None and rpm > 0:
        pwr_mech = abs(trq_nm) * rpm * 2 * math.pi / 60 / 1000.0

    if pwr_dc is not None and pwr_dc > state["peak_dc_pwr_pos"]:
        state["peak_dc_pwr_pos"] = pwr_dc
        state["ctx_pos"] = snap(state, ts, log, pwr_dc, pwr_mech)

    if pwr_dc is not None and pwr_dc < state["peak_dc_pwr_neg"]:
        state["peak_dc_pwr_neg"] = pwr_dc
        state["ctx_neg"] = snap(state, ts, log, pwr_dc, pwr_mech)

    if trq_nm is not None and trq_nm < state["peak_trq_neg"]:
        state["peak_trq_neg"] = trq_nm
        state["ctx_trq_neg"] = snap(state, ts, log, pwr_dc, pwr_mech)

    if trq_nm is not None and trq_nm > state["peak_trq_pos"]:
        state["peak_trq_pos"] = trq_nm
        state["ctx_trq_pos"] = snap(state, ts, log, pwr_dc, pwr_mech)

gene = make_state()
trac = make_state()

for LOG in LOGS:
    logname = LOG.split("\\")[-1]
    print(f"Reading {logname} ...")
    for frame in parse_file(LOG):
        aid = frame.arbitration_id
        d = bytes(frame.data)
        ts = frame.timestamp

        if aid == ID_GENE_RPM:
            sig = pt_db.decode_message(aid, d)
            gene["last_rpm"] = sig.get("GENE_RotSpd")
            gene["rpm_history"].append((ts, gene["last_rpm"]))

        elif aid == ID_GENE_CMD and len(d) >= 4:
            raw = d[1] | (d[2] << 8)
            gene["last_cmd"] = raw * GENE_CMD_SCALE + GENE_CMD_OFFSET

        elif aid == ID_GENE_TRQ:
            sig = pt_db.decode_message(aid, d)
            gene["last_trq"] = sig.get("GENE_Mot_Trq")
            gene["count_trq"] += 1
            track(gene, ts, logname)

        elif aid == ID_GENE_PWR:
            sig = pt_db.decode_message(aid, d)
            gene["last_curr"] = sig.get("GENE_HighPwr_Curr")
            gene["last_volt"] = sig.get("GENE_HighPwr_Volt")
            gene["count_pwr"] += 1
            track(gene, ts, logname)

        elif aid == ID_TRAC_RPM:
            sig = obd_db.decode_message(aid, d)
            trac["last_rpm"] = sig.get("TRAC_RotSpd")
            trac["rpm_history"].append((ts, trac["last_rpm"]))

        elif aid == ID_TRAC_TRQ:
            sig = obd_exp_db.decode_message(aid, d)
            trac["last_trq"] = sig.get("TRAC_TrqFbk")
            trac["count_trq"] += 1
            track(trac, ts, logname)

        elif aid == ID_TRAC_PWR:
            sig = obd_db.decode_message(aid, d)
            trac["last_curr"] = sig.get("TRAC_HighPwr_Curr")
            trac["last_volt"] = sig.get("TRAC_HighPwr_Volt")
            trac["count_pwr"] += 1
            track(trac, ts, logname)

def fmt_ctx(c):
    if c is None:
        return "  (no data)"
    rpm_rate_str = f"{c['rpm_rate']:+.0f} RPM/s" if c["rpm_rate"] is not None else "unknown"
    lines = [
        f"  log={c['log']}  t={c['ts']:.3f}s",
        f"  curr={c['curr']} A,  volt={c['volt']} V,  dc_pwr={c['pwr_dc']:.1f} kW",
        f"  trq_fbk={c['trq']} Nm,  rpm={c['rpm']},  trq_cmd={c['cmd']}",
        f"  RPM rate (last {RPM_HISTORY} samples): {rpm_rate_str}",
        f"  recent RPM history (rpm, t): {c['rpm_history']}",
    ]
    return "\n".join(lines)

def report(label, s):
    print(f"=== {label} ===")
    print(f"  Peak DC power (motoring +): {s['peak_dc_pwr_pos']:.1f} kW")
    print(fmt_ctx(s["ctx_pos"]))
    print(f"  Peak DC power (generating -): {s['peak_dc_pwr_neg']:.1f} kW")
    print(fmt_ctx(s["ctx_neg"]))
    print(f"  Peak torque (negative): {s['peak_trq_neg']:.1f} Nm")
    print(fmt_ctx(s["ctx_trq_neg"]))
    print(f"  Peak torque (positive): {s['peak_trq_pos']:.1f} Nm")
    print(fmt_ctx(s["ctx_trq_pos"]))
    print(f"  Frames (pwr/trq): {s['count_pwr']} / {s['count_trq']}")
    print()

print()
report("Generator (0x482 + 0x471 + 0x054)", gene)
report("Traction Inverter (0x462 + 0x442 + 0x044)", trac)
