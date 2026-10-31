"""Forensics on the 2026-06-18 00:21:26 drive-mode EPO trip (vtrux_20260618_002023_T0).

The trip pushed 0x460 record `AC 10 01` -- the only non-zero AC parameter in the
corpus -- from MAIN_PN_CLOSED_DRIVE via SHUTDOWN_REQUEST with the interlock still
closed. This script asks what else happened on the bus around it.

Phases (all run from T0 only; the trip and restart both lie inside T0):
  1  load + decode helpers
  2  per-ID silence scan across the whole chunk (module dropouts, 0x400 gap)
  3  ms change-log of every decoded signal around the EPO and around the restart
  4  1 s precursor table for the minute before the EPO
  5  raw distinct-payload dump of the BMS block + 0x400/0x617/0x053 around the EPO
  6  driver-actions timeline after the trip (key position, engine, 12V, speed)
  7  order in which the VCM-sourced IDs stopped, and raw payload changes on the
     GENE status block + VCM command block in the last 1.5 s before silence
  8  12V / DCDC detail at frame resolution in the last 0.8 s before the EPO

Phases 1 and 2 always run (they find T_EPO). Select others with argv, e.g.
  python3.13 projects/vtrux/notes/artifacts/ac1001_trip_forensics.py 6 7 8 > projects/vtrux/notes/artifacts/ac1001_trip_forensics_p678.txt
Default (no argv) runs 3 4 5.
"""
import sys
sys.path.insert(0, ".")

from collections import defaultdict
import statistics

import cantools

from canre.parsers import parse_file

PHASES = {int(a) for a in sys.argv[1:]} or {3, 4, 5}

LOG = "../../CANLogs/VtruxLogs/vtrux_20260618_002023_T0.log"
PT_BUS = 2
GM_BUS = 1

db_pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
db_ex = cantools.database.load_file("projects/vtrux/vtrux-powertrain-experimental.dbc")
db_gm = cantools.database.load_file("projects/vtrux/GMW8762_PPEI_GMLAN.dbc")

GM_WANT = {
    0x3E9: ("Vehicle_Speed_Average_Driven",),
    0x0C9: ("Engine_Run_Active", "Accelerator_Actual_Position", "Powertrain_Brake_Pedal_Discrete_Input_Status", "Engine_Speed"),
    0x1C3: ("Engine_Torque_Actual_Extended_Range", "Engine_Torque_Driver_Requested_Extended_Range"),
}


def decode_pt(aid, data):
    out = {}
    for db in (db_pt, db_ex):
        try:
            msg = db.get_message_by_frame_id(aid)
        except KeyError:
            continue
        if not msg.signals:
            continue
        try:
            d = msg.decode(data[:msg.length], decode_choices=True, allow_truncated=True)
        except Exception:
            continue
        for k, v in d.items():
            if hasattr(v, "name"):
                v = v.name
            elif isinstance(v, float):
                v = round(v, 3)
            out[k] = v
    return out


def decode_gm(aid, data):
    if aid not in GM_WANT:
        return {}
    try:
        msg = db_gm.get_message_by_frame_id(aid)
        d = msg.decode(data, decode_choices=False, allow_truncated=True)
    except Exception:
        return {}
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items() if k in GM_WANT[aid]}


print("Phase 1: loading", LOG)
frames = list(parse_file(LOG))
t0 = frames[0].timestamp
print("  %d frames, span %.1f s" % (len(frames), frames[-1].timestamp - t0))

epo_t = None
epo_clear_t = None
for f in frames:
    if f.bus == PT_BUS and f.arbitration_id == 0x410:
        e = (f.data[0] >> 1) & 1
        if epo_t is None and e == 1:
            epo_t = f.timestamp
        elif epo_t is not None and epo_clear_t is None and e == 0 and f.timestamp > epo_t + 1:
            epo_clear_t = f.timestamp
print("  EPO asserted at t=%.3f, cleared at t=%.3f" % (epo_t - t0, epo_clear_t - t0))
T_EPO = epo_t - t0
T_CLR = epo_clear_t - t0

print()
print("Phase 2: per-ID silence scan (gaps > max(0.5 s, 8x median) anywhere in chunk)")
by_id = defaultdict(list)
for f in frames:
    by_id[(f.bus, f.arbitration_id)].append(f.timestamp - t0)
rows = []
for key, ts in sorted(by_id.items()):
    if len(ts) < 20:
        continue
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    med = statistics.median(gaps)
    thr = max(0.5, 8 * med)
    big = [(ts[i], g) for i, g in enumerate(gaps) if g > thr]
    if big:
        rows.append((key, len(ts), med, big))
for (bus, aid), n, med, big in rows:
    s = ", ".join("t=%.2f +%.2fs" % (t, g) for t, g in big[:8])
    more = " (+%d more)" % (len(big) - 8) if len(big) > 8 else ""
    print("  bus%d 0x%03X n=%-6d med=%.3fs  gaps: %s%s" % (bus, aid, n, med, s, more))
print("  first/last frame time per PT ID that STOPS or STARTS inside [T_EPO-2, T_CLR+10]:")
for (bus, aid), ts in sorted(by_id.items()):
    if bus != PT_BUS:
        continue
    if T_EPO - 2 < ts[-1] < T_CLR + 10 or T_EPO - 2 < ts[0] < T_CLR + 10:
        print("    0x%03X  first=%.2f  last=%.2f  n=%d" % (aid, ts[0], ts[-1], len(ts)))


def changelog(lo, hi, title):
    print()
    print("Phase 3: change-log t=[%.1f, %.1f]  (%s)" % (lo, hi, title))
    last = {}
    for f in frames:
        t = f.timestamp - t0
        if t < lo - 5:
            continue
        if t > hi:
            break
        if f.bus == PT_BUS:
            d = decode_pt(f.arbitration_id, f.data)
            tag = "PT 0x%03X" % f.arbitration_id
            if f.arbitration_id == 0x460:
                d = {"page": f.data[0], "raw": f.data.hex(" ")}
            if f.arbitration_id == 0x617:
                d = {"B7": "0x%02X" % f.data[7], "raw": f.data.hex(" ")}
            if f.arbitration_id == 0x646:
                d = {"lamp_field": (f.data[7] >> 4) & 7}
        elif f.bus == GM_BUS:
            d = decode_gm(f.arbitration_id, f.data)
            tag = "GM 0x%03X" % f.arbitration_id
        else:
            continue
        for k, v in d.items():
            key = (tag, k)
            if key in last and last[key] == v:
                continue
            prev = last.get(key)
            last[key] = v
            if t >= lo:
                print("  %9.3f  %+8.3f  %-9s %-28s %s -> %s" % (t, t - T_EPO, tag, k, prev, v))


if 3 in PHASES:
    changelog(T_EPO - 6, T_EPO + 4, "EPO trip")
    changelog(T_CLR - 2, T_CLR + 12, "restart")

if 4 in PHASES:
  print()
  print("Phase 4: 1 s precursor table, t=[%.0f, %.0f]" % (T_EPO - 60, T_EPO + 2))
  WATCH = [
      ("PT", 0x410, "bcm_ibat"), ("PT", 0x410, "bcm_vbat"), ("PT", 0x410, "bcm_gfd"), ("PT", 0x410, "bcm_soc"),
      ("PT", 0x430, "bcm_cell_vmin"), ("PT", 0x430, "bcm_cell_vmax"), ("PT", 0x430, "bcm_cell_tmax"), ("PT", 0x430, "bcm_lvbat"),
      ("PT", 0x440, "bcm_vbus_pos"), ("PT", 0x440, "bcm_vbus_neg"),
      ("PT", 0x420, "bcm_dis_max"), ("PT", 0x420, "bcm_chg_max"),
      ("PT", 0x18FFD6B3, "DCDC_LV_Volt"), ("PT", 0x18FFD6B3, "DCDC_LV_Curr"), ("PT", 0x18FFD6B3, "DCDC_HV_Volt"),
      ("PT", 0x5A2, "trac_rpm"), ("PT", 0x5A2, "trac_torque_fbk"), ("PT", 0x592, "throttle_pos"),
      ("GM", 0x3E9, "Vehicle_Speed_Average_Driven"), ("GM", 0x0C9, "Accelerator_Actual_Position"),
  ]
  buckets = defaultdict(lambda: defaultdict(list))
  for f in frames:
      t = f.timestamp - t0
      if t < T_EPO - 60 or t > T_EPO + 2:
          continue
      sec = int(t - T_EPO)
      if f.bus == PT_BUS:
          d = decode_pt(f.arbitration_id, f.data)
          src = "PT"
      elif f.bus == GM_BUS:
          d = decode_gm(f.arbitration_id, f.data)
          src = "GM"
      else:
          continue
      for k, v in d.items():
          if (src, f.arbitration_id, k) in [(a, b, c) for a, b, c in WATCH] and isinstance(v, (int, float)):
              buckets[sec][k].append(v)
  cols = [k for _, _, k in WATCH]
  short = {"bcm_ibat": "ibat", "bcm_vbat": "vbat", "bcm_gfd": "gfd", "bcm_soc": "soc", "bcm_cell_vmin": "vmin", "bcm_cell_vmax": "vmax",
           "bcm_cell_tmax": "tmax", "bcm_lvbat": "lv12", "bcm_vbus_pos": "vb+", "bcm_vbus_neg": "vb-", "bcm_dis_max": "dmax", "bcm_chg_max": "cmax",
           "DCDC_LV_Volt": "dcLV", "DCDC_LV_Curr": "dcLA", "DCDC_HV_Volt": "dcHV", "trac_rpm": "rpm", "trac_torque_fbk": "trq", "throttle_pos": "thr",
           "Vehicle_Speed_Average_Driven": "kmh", "Accelerator_Actual_Position": "acc"}
  print("  sec   " + " ".join("%12s" % short[c] for c in cols))
  for sec in sorted(buckets):
      b = buckets[sec]
      cells = []
      for c in cols:
          v = b.get(c)
          if not v:
              cells.append("%12s" % "-")
          elif min(v) == max(v):
              cells.append("%12s" % ("%g" % min(v)))
          else:
              cells.append("%12s" % ("%g/%g" % (min(v), max(v))))
      print("  %+4d  %s" % (sec, " ".join(cells)))

if 5 in PHASES:
  print()
  print("Phase 5: distinct payloads, t=[T_EPO-1.5, T_EPO+1.5] for BMS block + 0x400/0x617/0x053/0x592")
  IDS = [0x400, 0x410, 0x420, 0x430, 0x440, 0x460, 0x411, 0x412, 0x617, 0x053, 0x592, 0x5A0, 0x600, 0x601]
  last = {}
  for f in frames:
      t = f.timestamp - t0
      if f.bus != PT_BUS or f.arbitration_id not in IDS:
          continue
      if t < T_EPO - 1.5:
          last[f.arbitration_id] = f.data
          continue
      if t > T_EPO + 1.5:
          break
      if last.get(f.arbitration_id) != f.data:
          print("  %9.3f  %+7.3f  0x%03X  %s" % (t, t - T_EPO, f.arbitration_id, f.data.hex(" ")))
          last[f.arbitration_id] = f.data


if 6 in PHASES:
    print()
    print("Phase 6: driver-actions timeline t=[T_EPO-3, T_CLR+8] (change points)")
    last = {}
    def emit(t, k, v):
        if last.get(k) != v:
            prev = last.get(k)
            last[k] = v
            if t >= T_EPO - 3:
                print("  %9.3f  %+8.3f  %-34s %s -> %s" % (t, t - T_EPO, k, prev, v))
    trac_last = None
    for f in frames:
        t = f.timestamp - t0
        if t > T_CLR + 8:
            break
        if f.bus == GM_BUS:
            if f.arbitration_id == 0x1F1:
                try:
                    d = db_gm.get_message_by_frame_id(0x1F1).decode(f.data, decode_choices=False, allow_truncated=True)
                    for k in ("Power_Mode_Master_Run_Crank_Terminal_Status", "Park_Brake_Switch_Active"):
                        if k in d:
                            emit(t, "GM 0x1F1 " + k, d[k])
                    emit(t, "GM 0x1F1 B0..B1 raw", f.data[:2].hex())
                except Exception:
                    pass
            elif f.arbitration_id == 0x0C9:
                d = decode_gm(0x0C9, f.data)
                emit(t, "GM Engine_Run_Active", d.get("Engine_Run_Active"))
                emit(t, "GM Engine_Speed (100 rpm bins)", int(d.get("Engine_Speed", 0) // 100) * 100)
            elif f.arbitration_id == 0x3E9:
                d = decode_gm(0x3E9, f.data)
                emit(t, "GM speed (2 km/h bins)", int(d.get("Vehicle_Speed_Average_Driven", 0) // 2) * 2)
            elif f.arbitration_id == 0x044:
                if trac_last is not None and t - trac_last > 0.5:
                    print("  %9.3f  %+8.3f  %-34s gap %.2f s" % (t, t - T_EPO, "OBD-bus TRAC 0x044 returns after", t - trac_last))
                trac_last = t
        elif f.bus == PT_BUS:
            aid = f.arbitration_id
            if aid == 0x430:
                emit(t, "PT bcm_lvbat (0.5 V bins)", round(f.data[7] * 0.1 * 2) / 2)
            elif aid == 0x592:
                d = decode_pt(0x592, f.data)
                for k in ("IgnitionKeyState", "EVSESwitchState", "ExportPowerState"):
                    emit(t, "PT 0x592 " + k, d.get(k))
            elif aid == 0x053:
                d = decode_pt(0x053, f.data)
                emit(t, "PT 0x053 OperationState", d.get("OperationState"))
            elif aid == 0x054:
                emit(t, "PT 0x054 GENE_EmergcyStp_flg", (f.data[4] >> 3) & 1)
            elif aid == 0x410:
                emit(t, "PT bcm_epo", (f.data[0] >> 1) & 1)
                emit(t, "PT bcm_hvil_mon", (f.data[0] >> 3) & 1)
            elif aid == 0x440:
                emit(t, "PT bcm_mainc_stat(0x440)", (f.data[0] >> 2) & 0xF)
            elif aid == 0x18FFD6B3:
                d = decode_pt(aid, f.data)
                emit(t, "PT DCDC_LV_Volt (0.5 V bins)", round(d.get("DCDC_LV_Volt", 0) * 2) / 2)
                emit(t, "PT DCDC_HV_Volt (10 V bins)", int(d.get("DCDC_HV_Volt", 0) // 10) * 10)
            elif aid == 0x18FECAB3:
                emit(t, "PT DCDC DM1 raw", f.data.hex(" "))

if 7 in PHASES:
    print()
    print("Phase 7a: last frame before the ~T_EPO silence, per PT ID (IDs whose gap>0.5 s starts in [T_EPO-1.5, T_EPO+1.5])")
    rows = []
    for (bus, aid), ts in by_id.items():
        if bus != PT_BUS or len(ts) < 5:
            continue
        gaps = [(ts[i], ts[i + 1] - ts[i]) for i in range(len(ts) - 1)]
        med = statistics.median(g for _, g in gaps)
        for tlast, g in gaps:
            if g > 0.5 and T_EPO - 1.5 <= tlast <= T_EPO + 1.5:
                rows.append((tlast, aid, med, g))
    for tlast, aid, med, g in sorted(rows):
        print("  last=%.3f (%+.3f)  0x%08X  period=%.3f  next due=%.3f  silent %.2f s" % (tlast, tlast - T_EPO, aid, med, tlast + med, g))
    print()
    print("Phase 7b: raw distinct payloads, GENE status block + VCM command block + misc, t=[T_EPO-1.5, T_EPO+0.6]")
    IDS7 = [0x050, 0x051, 0x052, 0x053, 0x054, 0x470, 0x472, 0x473, 0x475, 0x479, 0x480, 0x481, 0x483, 0x484, 0x617, 0x619, 0x6A0, 0x600, 0x601, 0x18EF2000, 0x18EFB3FE, 0x18E8FFB3, 0x18FFD4B3, 0x590, 0x0C]
    NOISY = {0x051, 0x054, 0x471, 0x482}
    last = {}
    for f in frames:
        t = f.timestamp - t0
        if f.bus != PT_BUS or f.arbitration_id not in IDS7:
            continue
        if t < T_EPO - 1.5:
            last[f.arbitration_id] = f.data
            continue
        if t > T_EPO + 0.6:
            break
        aid = f.arbitration_id
        d = f.data
        if aid == 0x051:
            d = bytes([d[0]]) + b"\x00\x00\x00\x00" + bytes([d[5] & 0xF0]) if len(d) >= 6 else d
        if aid == 0x054:
            d = b"\x00\x00" + d[2:]
        if last.get(aid) != d:
            print("  %9.3f  %+7.3f  0x%08X  %s" % (t, t - T_EPO, aid, f.data.hex(" ")))
            last[aid] = d

if 8 in PHASES:
    print()
    print("Phase 8: 12V / DCDC / GENE electrical at frame resolution, t=[T_EPO-0.8, T_EPO+0.1]")
    for f in frames:
        t = f.timestamp - t0
        if t < T_EPO - 0.8:
            continue
        if t > T_EPO + 0.1:
            break
        if f.bus != PT_BUS:
            continue
        aid = f.arbitration_id
        if aid == 0x18FFD6B3:
            d = decode_pt(aid, f.data)
            print("  %9.3f  %+7.3f  DCDC  LV %.2f V  %.2f A   HV %.1f V" % (t, t - T_EPO, d["DCDC_LV_Volt"], d["DCDC_LV_Curr"], d["DCDC_HV_Volt"]))
        elif aid == 0x430:
            print("  %9.3f  %+7.3f  BMS   lvbat %.1f V" % (t, t - T_EPO, f.data[7] * 0.1))
        elif aid == 0x482:
            d = decode_pt(aid, f.data)
            print("  %9.3f  %+7.3f  GENE  %d V  %.2f A" % (t, t - T_EPO, d["GENE_HighPwr_Volt"], d["GENE_HighPwr_Curr"]))
        elif aid == 0x410:
            d = decode_pt(aid, f.data)
            print("  %9.3f  %+7.3f  BMS   ibat %.2f A  vbat %.2f V  epo=%d alarm=%s" % (t, t - T_EPO, d["bcm_ibat"], d["bcm_vbat"], d["bcm_epo"], d["bcm_alarm"]))
        elif aid == 0x400:
            print("  %9.3f  %+7.3f  VCM   0x400 %s" % (t, t - T_EPO, f.data.hex(" ")))
