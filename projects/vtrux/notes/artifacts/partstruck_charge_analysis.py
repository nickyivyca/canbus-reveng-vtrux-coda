"""
partstruck_charge_analysis.py

Full analysis of vtrux_partstruck_charge.log (parts truck, original main truck battery reinstalled).
Session: 2026-04-22, 10:45:24 to 20:17:12 (~9h32min)

Three output sections:
  1. Session overview (10-min buckets) -- cross-battery comparison metrics
  2. Power dip at ~2:20pm (14:20 wall = t~12876s) -- detailed +-8 min window
  3. Balancing report -- onset, ramp, peak, convergence vs prior sessions

Run from project root:
  py -3.11 projects/vtrux/notes/artifacts/partstruck_charge_analysis.py
"""

import os, sys, collections
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from canre.utils.merge import merge_files
import cantools

LOG = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs", "vtrux_partstruck_charge.log")
EPRI_PT_DBC = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")
BEL_DBC_PATH = os.path.join(PROJECT_ROOT, "projects", "vtrux", "BelInverter-v2.dbc")

PT_ANCHOR = {0x410, 0x420, 0x430, 0x440}
BEL_VI_ID  = 0x18FFD7C0    # Ibat, Vbat, Iin_RMS, Vin_RMS
BEL_ST_ID  = 0x18FFD4C0    # BINV_status (muxed)
BEL_TMP_ID = 0x18FFD5C0    # charger temp

SESSION_START_H = 10
SESSION_START_M = 45
SESSION_START_S = 24
DIP_WALL_H = 14
DIP_WALL_M = 20
DIP_WALL_S = 0

DIP_T = ((DIP_WALL_H - SESSION_START_H) * 3600 +
         (DIP_WALL_M - SESSION_START_M) * 60 +
         (DIP_WALL_S - SESSION_START_S))
DIP_WIN = 480   # +-8 minutes

BUCKET = 600    # 10-minute buckets for overview

BEL_STATE_NAMES = {
    0:  "Init",
    2:  "Sleep",
    4:  "Wake",
    8:  "Idle",
    16: "CC",
    32: "CV",
    64: "ChargeDone",
    128:"Fault",
}

def bel_state_str(v):
    return BEL_STATE_NAMES.get(v, f"0x{v:02X}")


def identify_pt_bus(log_path, sample=300000):
    counts = {}
    for i, frame in enumerate(merge_files([log_path])):
        if frame.arbitration_id in PT_ANCHOR:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= sample:
            break
    return max(counts, key=counts.get) if counts else None


def fmt_t(t):
    """Format elapsed seconds as HH:MM:SS."""
    h = int(t) // 3600
    m = (int(t) % 3600) // 60
    s = int(t) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    print("Loading DBCs...")
    db_pt  = cantools.db.load_file(EPRI_PT_DBC)
    db_bel = cantools.db.load_file(BEL_DBC_PATH)
    msg_410  = db_pt.get_message_by_frame_id(0x410)
    msg_420  = db_pt.get_message_by_frame_id(0x420)
    msg_430  = db_pt.get_message_by_frame_id(0x430)
    msg_440  = db_pt.get_message_by_frame_id(0x440)
    msg_bst  = db_bel.get_message_by_frame_id(BEL_ST_ID)
    msg_bvi  = db_bel.get_message_by_frame_id(BEL_VI_ID)
    msg_btmp = db_bel.get_message_by_frame_id(BEL_TMP_ID)

    print(f"Identifying PT bus (first 300k frames)...")
    pt_bus = identify_pt_bus(LOG)
    print(f"PT bus: channel {pt_bus}")
    print(f"Dip analysis window: t={DIP_T-DIP_WIN}s to t={DIP_T+DIP_WIN}s  ({fmt_t(DIP_T-DIP_WIN)} to {fmt_t(DIP_T+DIP_WIN)} elapsed)")
    print()

    last = {}
    prev_bel_state = None
    prev_fault_byte = None
    prev_bal_nonzero = None

    state_events = []   # (t, kind, old, new)

    buckets = {}        # bucket_idx -> {soc_list, ibat_list, vmax_list, vmin_list, spread_list, cnt_list, iin_list, vin_list, ccl_list}

    dip_samples = []    # (t, soc, ibat_bms, vmax, vmin, spread, cnt, iin, vin, bel_state, fault_byte, chg_temp_pct)

    bal_samples = []    # (t, soc, vmax, vmin, spread, cnt)

    def get_bucket(t):
        return int(t) // BUCKET

    def record_bucket(t):
        idx = get_bucket(t)
        if idx not in buckets:
            buckets[idx] = collections.defaultdict(list)
        b = buckets[idx]
        for k in ('soc', 'ibat', 'vbat', 'hv_volt', 'hv_curr', 'vmax', 'vmin',
                  'spread', 'cnt', 'iin', 'vin', 'ccl', 'chg_temp_pct'):
            if last.get(k) is not None:
                b[k].append(last[k])

    last_record_t = -BUCKET

    print("Scanning log (single pass)...")
    frame_count = 0
    for frame in merge_files([LOG]):
        t = frame.timestamp
        aid = frame.arbitration_id
        data = bytes(frame.data) if frame.data else b''
        frame_count += 1

        if frame_count % 2000000 == 0:
            print(f"  ... {frame_count//1000000}M frames, t={fmt_t(t)}, soc={last.get('soc','?')}")

        is_pt = (frame.bus == pt_bus)

        if is_pt:
            if aid == 0x410:
                try:
                    dec = msg_410.decode(data, decode_choices=False)
                    soc = dec.get('bcm_soc')
                    if soc is not None and soc < 127.0:
                        last['soc'] = float(soc)
                    ibat = dec.get('bcm_ibat')
                    if ibat is not None:
                        last['ibat'] = round(float(ibat), 1)
                    vbat = dec.get('bcm_vbat')
                    if vbat is not None:
                        last['vbat'] = round(float(vbat), 1)
                except Exception:
                    pass

            elif aid == 0x430:
                try:
                    dec = msg_430.decode(data, decode_choices=False)
                    vmax = dec.get('bcm_cell_vmax')
                    vmin = dec.get('bcm_cell_vmin')
                    if vmax is not None and vmin is not None and vmax < 8.0 and vmin > 0:
                        last['vmax'] = round(vmax * 1000)
                        last['vmin'] = round(vmin * 1000)
                        last['spread'] = last['vmax'] - last['vmin']
                except Exception:
                    pass

            elif aid == 0x440:
                try:
                    dec = msg_440.decode(data, decode_choices=False)
                    cnt_raw = dec.get('bcm_balancing_cnt')
                    if cnt_raw is not None and int(cnt_raw) < 0xFE:
                        cnt = int(cnt_raw)
                        old_cnt = last.get('cnt', 0)
                        last['cnt'] = cnt
                        last['bal_flag'] = int(dec.get('bcm_balancing', 0))
                        if old_cnt == 0 and cnt > 0:
                            state_events.append((t, 'bal_start', old_cnt, cnt))
                        elif old_cnt > 0 and cnt == 0:
                            state_events.append((t, 'bal_stop', old_cnt, cnt))
                except Exception:
                    pass

            elif aid == 0x420:
                try:
                    dec = msg_420.decode(data, decode_choices=False)
                    ccl = dec.get('bcm_chg_max')
                    if ccl is not None:
                        last['ccl'] = round(float(ccl), 1)
                except Exception:
                    pass

        if aid == BEL_VI_ID:
            try:
                dec = msg_bvi.decode(data, decode_choices=False)
                hv_volt = dec.get('BELINV_hvBatteryVoltage')
                hv_curr = dec.get('BELINV_hvBatteryCurrent')
                vin     = dec.get('BELINV_chargerInputVoltage')
                iin     = dec.get('BELINV_chargerInputCurrent')
                if hv_volt is not None: last['hv_volt'] = round(float(hv_volt), 1)
                if hv_curr is not None: last['hv_curr'] = round(float(hv_curr), 2)
                if vin     is not None: last['vin']     = round(float(vin), 1)
                if iin     is not None: last['iin']     = round(float(iin), 2)
            except Exception:
                pass

        if aid == BEL_ST_ID:
            try:
                dec = msg_bst.decode(data, decode_choices=False)
                bel_state = dec.get('BELINV_state')
                if bel_state is not None:
                    bel_state = int(bel_state)
                    if prev_bel_state is not None and bel_state != prev_bel_state:
                        state_events.append((t, 'bel_state', prev_bel_state, bel_state))
                    prev_bel_state = bel_state
                    last['bel_state'] = bel_state
                chg_ip = dec.get('BELINV_powerChargingInProgress')
                if chg_ip is not None:
                    last['chg_ip'] = int(chg_ip)
                for fault_sig in ('BELINV_acOk', 'BELINV_inverterFault', 'BELINV_buckBoostFault',
                                  'BELINV_hvBatteryOverVoltage', 'BELINV_hvBatteryUnderVoltage',
                                  'BELINV_overTemperature', 'BELINV_acOverVoltage', 'BELINV_acUnderVoltage'):
                    v = dec.get(fault_sig)
                    if v is not None:
                        old_v = last.get(fault_sig)
                        last[fault_sig] = int(v)
                        if old_v is not None and int(v) != old_v:
                            state_events.append((t, 'fault_sig', fault_sig, (old_v, int(v))))
            except Exception:
                pass

        if aid == BEL_TMP_ID:
            try:
                dec = msg_btmp.decode(data, decode_choices=False)
                tpct = dec.get('BELINV_overallTemperaturePercent')
                if tpct is not None:
                    last['chg_temp_pct'] = round(float(tpct), 1)
            except Exception:
                pass

        if t - last_record_t >= 10.0 and last:
            record_bucket(t)
            last_record_t = t

        if abs(t - DIP_T) <= DIP_WIN:
            dip_samples.append({
                't': t,
                'soc':   last.get('soc'),
                'ibat':  last.get('ibat'),
                'vmax':  last.get('vmax'),
                'vmin':  last.get('vmin'),
                'spread':last.get('spread'),
                'cnt':   last.get('cnt', 0),
                'iin':   last.get('iin'),
                'vin':   last.get('vin'),
                'bst':   last.get('bel_state'),
                'fault': last.get('fault_byte'),
                'tpct':  last.get('chg_temp_pct'),
            })

        cnt_now = last.get('cnt')
        if cnt_now is not None and last.get('soc') is not None and last.get('vmax') is not None:
            if cnt_now > 0 or (len(bal_samples) > 0 and bal_samples[-1].get('cnt', 0) > 0):
                bal_samples.append({
                    't':      t,
                    'soc':    last.get('soc'),
                    'vmax':   last.get('vmax'),
                    'vmin':   last.get('vmin'),
                    'spread': last.get('spread'),
                    'cnt':    cnt_now,
                })

    print(f"Scan complete. {frame_count} total frames.")
    print()

    def mean(lst):
        return sum(lst) / len(lst) if lst else None

    def _f(v, fmt=".1f"):
        return f"{v:{fmt}}" if v is not None else "n/a"

    print("=" * 90)
    print("SECTION 1 -- SESSION OVERVIEW (10-min buckets)")
    print("=" * 90)
    print(f"Session: 2026-04-22 10:45:24 to 20:17:12 (~9h32min) | PT bus = channel {pt_bus}")
    print()
    hdr = (f"{'t_start':>8} {'SoC%':>6} {'Ibat A':>7} {'HV V':>6} {'Vmax mV':>8} "
           f"{'Vmin mV':>8} {'Sprd mV':>8} {'BalCnt':>7} {'CCL A':>6} {'Vin VAC':>8} {'Iin AAC':>8} {'TmpPct':>7}")
    print(hdr)
    print("-" * len(hdr))
    for idx in sorted(buckets.keys()):
        b = buckets[idx]
        t_start = fmt_t(idx * BUCKET)
        soc   = mean(b.get('soc', []))
        ibat  = mean(b.get('ibat', []))
        hv_v  = mean(b.get('hv_volt', []))
        vmax  = mean(b.get('vmax', []))
        vmin  = mean(b.get('vmin', []))
        sprd  = mean(b.get('spread', []))
        cnt   = mean(b.get('cnt', []))
        ccl   = mean(b.get('ccl', []))
        vin   = mean(b.get('vin', []))
        iin   = mean(b.get('iin', []))
        tpct  = mean(b.get('chg_temp_pct', []))
        print(f"{t_start:>8} {_f(soc):>6} {_f(ibat):>7} {_f(hv_v,'.0f'):>6} {_f(vmax,'.0f'):>8} "
              f"{_f(vmin,'.0f'):>8} {_f(sprd,'.0f'):>8} {_f(cnt,'.0f'):>7} {_f(ccl):>6} "
              f"{_f(vin,'.0f'):>8} {_f(iin):>8} {_f(tpct):>7}")

    print()
    print("Charger/BMS state events timeline:")
    for (t, kind, old, new) in state_events:
        t_str = fmt_t(t)
        if kind == 'bel_state':
            print(f"  {t_str} | bel_state  {bel_state_str(old):12s} -> {bel_state_str(new)}")
        elif kind == 'fault_sig':
            sig_name = old
            old_v, new_v = new
            print(f"  {t_str} | {sig_name:40s} {old_v} -> {new_v}")
        elif kind in ('bal_start', 'bal_stop'):
            arrow = "OFF->ON" if kind == 'bal_start' else "ON->OFF"
            print(f"  {t_str} | balancing  {arrow}  cnt={new}")

    print()
    print("=" * 90)
    print("SECTION 2 -- POWER DIP INVESTIGATION (~2:20pm, t=12876s)")
    print("=" * 90)
    print(f"Window: {fmt_t(DIP_T-DIP_WIN)} to {fmt_t(DIP_T+DIP_WIN)} (+-{DIP_WIN//60} min around t={DIP_T}s)")
    print()

    dip_state_changes = []
    for i, s in enumerate(dip_samples):
        if i == 0:
            continue
        prev = dip_samples[i-1]
        if s['bst'] != prev['bst'] and s['bst'] is not None and prev['bst'] is not None:
            dip_state_changes.append((s['t'], 'bel_state', prev['bst'], s['bst']))
        cnt_now = s.get('cnt') or 0
        cnt_prv = prev.get('cnt') or 0
        if (cnt_prv == 0) != (cnt_now == 0):
            dip_state_changes.append((s['t'], 'balancing', cnt_prv, cnt_now))

    print("State changes during dip window:")
    if dip_state_changes:
        for (t, kind, old, new) in dip_state_changes:
            t_str = fmt_t(t)
            if kind == 'bel_state':
                print(f"  {t_str} | bel_state {bel_state_str(old)} -> {bel_state_str(new)}")
            elif kind == 'fault':
                print(f"  {t_str} | fault_byte 0x{old:02X} -> 0x{new:02X}")
            elif kind == 'balancing':
                print(f"  {t_str} | balancing OFF->ON  cnt={new}" if new > 0 else f"  {t_str} | balancing ON->OFF")
    else:
        print("  (none detected)")

    print()
    print("1-minute averaged values across dip window:")
    min_buckets = {}
    for s in dip_samples:
        t_rel = s['t'] - DIP_T
        mb = int((t_rel + DIP_WIN) // 60)
        if mb not in min_buckets:
            min_buckets[mb] = collections.defaultdict(list)
        for k in ('iin', 'vin', 'ibat', 'soc', 'vmax', 'vmin', 'spread', 'cnt', 'tpct'):
            if s.get(k) is not None:
                min_buckets[mb][k].append(s[k])

    dhdr = f"{'t_rel':>8} {'Vin VAC':>8} {'Iin AAC':>8} {'P_ac W':>7} {'Ibat A':>7} {'SoC%':>5} {'Vmax mV':>8} {'Sprd mV':>8} {'BalCnt':>7} {'TmpPct':>7}"
    print(dhdr)
    print("-" * len(dhdr))
    for mb in sorted(min_buckets.keys()):
        bd = min_buckets[mb]
        t_rel_s = (mb * 60) - DIP_WIN
        vin  = mean(bd.get('vin', []))
        iin  = mean(bd.get('iin', []))
        ibat = mean(bd.get('ibat', []))
        soc  = mean(bd.get('soc', []))
        vmax = mean(bd.get('vmax', []))
        sprd = mean(bd.get('spread', []))
        cnt  = mean(bd.get('cnt', []))
        tpct = mean(bd.get('tpct', []))
        p_ac = (vin * iin) if (vin is not None and iin is not None) else None
        sign = "+" if t_rel_s >= 0 else ""
        abs_s = abs(t_rel_s)
        t_str = f"{sign}{abs_s//60}m{abs_s%60:02d}s"
        print(f"{t_str:>8} {_f(vin,'.0f'):>8} {_f(iin):>8} {_f(p_ac,'.0f'):>7} {_f(ibat):>7} {_f(soc,'.1f'):>5} "
              f"{_f(vmax,'.0f'):>8} {_f(sprd,'.0f'):>8} {_f(cnt,'.0f'):>7} {_f(tpct):>7}")

    print()
    print("=" * 90)
    print("SECTION 3 -- BALANCING REPORT")
    print("=" * 90)

    if not bal_samples:
        print("No balancing data found.")
    else:
        onset_idx = next((i for i, s in enumerate(bal_samples) if s['cnt'] > 0), None)
        if onset_idx is None:
            print("Balancing count never became non-zero.")
        else:
            onset = bal_samples[onset_idx]
            print(f"Balancing onset:")
            print(f"  t={fmt_t(onset['t'])}  SoC={_f(onset['soc'])}%  vmax={onset['vmax']} mV  cnt={onset['cnt']}")

            soc_100_t = None
            for s in bal_samples:
                if s['soc'] is not None and s['soc'] >= 99.9:
                    soc_100_t = s['t']
                    break
            if soc_100_t is not None:
                delay = onset['t'] - soc_100_t
                sign = "+" if delay >= 0 else ""
                print(f"  SOC first hit 100% at t={fmt_t(soc_100_t)}  (balancing onset {sign}{delay:.0f}s {'after' if delay>=0 else 'before'} 100%)")

            ramp_start = onset_idx
            milestones = {12: None, 52: None, 104: None, 116: None}
            for i, s in enumerate(bal_samples[ramp_start:], start=ramp_start):
                cnt = s['cnt']
                for m in list(milestones.keys()):
                    if milestones[m] is None and cnt >= m:
                        milestones[m] = s['t'] - onset['t']
            print()
            print("  Ramp milestones (seconds after onset):")
            for m, dt in milestones.items():
                print(f"    cnt={m:3d}: +{dt:.0f}s" if dt is not None else f"    cnt={m:3d}: not reached")

            peak_cnt = max(s['cnt'] for s in bal_samples)
            peak_sample = max(bal_samples, key=lambda s: s['cnt'])
            print()
            print(f"  Peak balancing count: {peak_cnt}  at t={fmt_t(peak_sample['t'])}")

            cnt_vals = [s['cnt'] for s in bal_samples]
            BUCKET10 = 600
            cnt_buckets = {}
            for s in bal_samples:
                bi = int(s['t']) // BUCKET10
                if bi not in cnt_buckets:
                    cnt_buckets[bi] = []
                cnt_buckets[bi].append(s['cnt'])
            print()
            print("  10-min balancing count averages (non-zero only):")
            print(f"  {'t_start':>8} {'mean_cnt':>9} {'max_cnt':>9} {'SoC%':>6}")
            for bi in sorted(cnt_buckets.keys()):
                vals = cnt_buckets[bi]
                nz = [v for v in vals if v > 0]
                if not nz:
                    continue
                soc_at = mean([s['soc'] for s in bal_samples if int(s['t'])//BUCKET10 == bi and s['soc'] is not None])
                print(f"  {fmt_t(bi*BUCKET10):>8} {mean(nz):>9.1f} {max(nz):>9d} {_f(soc_at):>6}")

            last_nonzero_t = max((s['t'] for s in bal_samples if s['cnt'] > 0), default=None)
            if last_nonzero_t is not None:
                print()
                print(f"  Balancing last active at t={fmt_t(last_nonzero_t)}")

            spread_at_onset = onset.get('spread')
            spread_final_samples = [s['spread'] for s in bal_samples[-200:] if s.get('spread') is not None and s['cnt'] == 0]
            spread_at_conv = mean(spread_final_samples) if spread_final_samples else None
            print()
            print(f"  Spread at balancing onset:    {spread_at_onset} mV")
            print(f"  Spread after convergence:     {_f(spread_at_conv)} mV")

            cnt_at_onset = onset['cnt']
            cnt_spike_counts = collections.Counter(s['cnt'] for s in bal_samples if s['cnt'] > 0)

            print()
            print("  Most frequent non-zero balancing count values (top 10):")
            for cnt_val, freq in cnt_spike_counts.most_common(10):
                pct = 100 * freq / sum(cnt_spike_counts.values())
                print(f"    cnt={cnt_val:3d}: {freq:6d} frames  ({pct:.1f}%)")

            print()
            print("  Count distribution spikes (>3x local median within +-8 neighbors):")
            cnt_hist = sorted(cnt_spike_counts.keys())
            spike_vals = []
            for i, v in enumerate(cnt_hist):
                neighbors = [cnt_spike_counts[cnt_hist[j]] for j in range(max(0,i-8), min(len(cnt_hist),i+9)) if j != i]
                local_median = sorted(neighbors)[len(neighbors)//2] if neighbors else 1
                if cnt_spike_counts[v] > 3 * local_median:
                    spike_vals.append((v, cnt_spike_counts[v]))
            if spike_vals:
                for (v, freq) in spike_vals:
                    pct = 100 * freq / sum(cnt_spike_counts.values())
                    print(f"    cnt={v:3d}: {freq} frames ({pct:.1f}%) -- spike")
            else:
                print("    (none above 3x threshold)")

    print()
    print("=" * 90)
    print("SECTION 3b -- COMPARISON TABLE vs PRIOR SESSIONS")
    print("=" * 90)
    print()
    print("Prior session reference values from balancing-investigation.md and logs/README.md:")
    print()
    prior = [
        ("full_charge_then_fail",  "main truck", "orig batt",  "2025-06-25", "53->100%",  "pre-swap",  "95.5%", "3401", "8",   "141s",  "~91",  "116", "n/a (ended in fault)"),
        ("after_swap_M0_a",        "main truck", "parts batt", "2026-01-16", "45->100%",  "post-swap", "100%",  "3405", "15",  "137s",  "~59",  "116", "~2-4 mV after 80min"),
        ("after_swap_M0_b",        "main truck", "parts batt", "2026-01-23", "25->100%",  "post-swap", "93.5%", "3400", "11",  "586s",  "~63",  "116", "~2-4 mV after 100min"),
        ("vtrux_charge_M1_Jan25",  "main truck", "parts batt", "2026-01-25", "76->100%",  "post-swap", "95.5%", "3404", "5",   "121s",  "n/a",  "116", "~2-4 mV after 60min"),
        ("truk1log_M1",            "main truck", "orig batt",  "2025-10-25", "?->?",      "pre-swap",  "n/a",   "n/a",  "n/a", "n/a",   "n/a",  "n/a", "not analyzed"),
    ]
    col = f"{'Session':30s} {'Truck':10s} {'Battery':10s} {'Date':10s} {'SoC range':10s} {'Era':10s} {'OnsetSoC':9s} {'Vmax-onset':11s} {'Sprd-onset':11s} {'Ramp':6s} {'PeakCnt':8s} {'MaxCnt':7s} {'Conv spread':12s}"
    print(col)
    print("-" * len(col))
    for row in prior:
        print(f"{row[0]:30s} {row[1]:10s} {row[2]:10s} {row[3]:10s} {row[4]:10s} {row[5]:10s} {row[6]:9s} {row[7]:11s} {row[8]:11s} {row[9]:6s} {row[10]:8s} {row[11]:7s} {row[12]:12s}")

    if bal_samples:
        onset_idx = next((i for i, s in enumerate(bal_samples) if s['cnt'] > 0), None)
        if onset_idx is not None:
            onset = bal_samples[onset_idx]
            ramp_to_116 = milestones.get(116)
            spf = mean([s['spread'] for s in bal_samples[-200:] if s.get('spread') is not None and s['cnt'] == 0])
            soc_start = bal_samples[0]['soc'] if bal_samples else None
            soc_range = f"{_f(soc_start)}->100%" if soc_start else "?->100%"
            row_new = (
                "partstruck_charge_TODAY",
                "parts truck",
                "orig batt",
                "2026-04-22",
                soc_range,
                "reinstalled",
                f"{_f(onset['soc'])}%",
                str(onset['vmax']),
                str(onset.get('spread', '?')),
                f"{ramp_to_116:.0f}s" if ramp_to_116 else "?",
                str(int(mean([s['cnt'] for s in bal_samples[-600:-1] if s['cnt'] > 0] or [0]))),
                str(peak_cnt),
                f"{_f(spf)} mV" if spf else "n/a",
            )
            print(f"\033[1m{row_new[0]:30s} {row_new[1]:10s} {row_new[2]:10s} {row_new[3]:10s} {row_new[4]:10s} {row_new[5]:10s} {row_new[6]:9s} {row_new[7]:11s} {row_new[8]:11s} {row_new[9]:6s} {row_new[10]:8s} {row_new[11]:7s} {row_new[12]:12s}\033[0m")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
