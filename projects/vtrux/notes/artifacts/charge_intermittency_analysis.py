"""
Q2 — Charge Intermittency & AC Voltage Analysis
rainy-day-charge-failures.md investigation

For each log (or per-session segment within a multi-session log):
  1. Full state machine transition history (charger state throughout session)
  2. AC input voltage timeseries — baseline, spikes, correlation with state transitions
  3. Intermittency event catalogue (12->15->12 mini-cycles)

Multi-session logs (e.g. multiple plug cycles or export+charge in one file) are split
automatically on gaps > SESSION_GAP_S between consecutive 0x18FFD4C0 frames.

Export mode detection: the 'exporting' bit (bit 19, byte 2 bit 3) in BINV_status mux=0
is SET when the charger is inverting (export panel mode).  Each session is tagged charge
or export accordingly, and export sessions are reported separately without failure analysis.

IDs:
  0x18FFD4C0  BINV_status (mux=0): B5=state, B6=shutdownSource, B2[3]=exporting
  0x18FFD7C0  BELINV_hvBatteryAndCharger:
              B0-1 hvBatteryVoltage  (LE signed x0.05 V)
              B2-3 hvBatteryCurrent  (LE signed x0.05 A)
              B4-5 chargerInputVoltage (LE signed x0.05 V)  <-- AC line voltage
              B6-7 chargerInputCurrent (LE signed x0.05 A)
  0x18FFD8C0  BELINV_j1772Info: B2=pilotDuty (raw counts)
"""

import sys
import os
import argparse
import struct
from collections import defaultdict

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from canre.parsers import parse_file

ID_STATUS  = 0x18FFD4C0
ID_POWER   = 0x18FFD7C0
ID_J1772   = 0x18FFD8C0

SPIKE_THRESHOLD_V = 5.0   # AC voltage deviation from session median (V) to flag as spike
SESSION_GAP_S     = 10.0  # gap between consecutive status frames that marks a new session


def decode_status_mux0(data):
    if len(data) < 8 or data[0] != 0x00:
        return None
    exporting = bool(data[2] & 0x08)   # bit 19 = byte 2 bit 3
    return {'state': data[5], 'shutdown_source': data[6], 'exporting': exporting}


def decode_power(data):
    if len(data) < 8:
        return None
    batt_v  = struct.unpack_from('<h', data, 0)[0] * 0.05
    batt_i  = struct.unpack_from('<h', data, 2)[0] * 0.05
    ac_v    = struct.unpack_from('<h', data, 4)[0] * 0.05
    ac_i    = struct.unpack_from('<h', data, 6)[0] * 0.05
    return {'batt_v': batt_v, 'batt_i': batt_i, 'ac_v': ac_v, 'ac_i': ac_i}


def decode_j1772(data):
    """pilot_duty raw byte from B2 of 0x18FFD8C0."""
    if len(data) < 3:
        return None
    return {'pilot_duty': data[2]}


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def split_sessions(status_frames, gap=SESSION_GAP_S):
    """Split a flat list of status frames into per-session sublists on gaps > gap seconds."""
    if not status_frames:
        return []
    sessions = []
    cur = [status_frames[0]]
    for sf in status_frames[1:]:
        if sf[0] - cur[-1][0] > gap:
            sessions.append(cur)
            cur = [sf]
        else:
            cur.append(sf)
    sessions.append(cur)
    return sessions


def is_export_session(status_frames):
    """Return True if the majority of mux=0 frames have the exporting bit set."""
    export_count = sum(1 for f in status_frames if f[3])  # index 3 = exporting
    return export_count > len(status_frames) // 2


def analyze_log(log_path, label=None):
    label = label or os.path.basename(log_path)
    print(f"\n{'='*70}")
    print(f"LOG: {label}")
    print(f"{'='*70}")

    frames = parse_file(log_path)

    status_frames = []   # (t, state, shutdown_src, exporting)
    power_frames  = []   # (t, batt_v, batt_i, ac_v, ac_i)
    j1772_frames  = []   # (t, pilot_duty)

    for f in frames:
        if f.arbitration_id == ID_STATUS:
            d = decode_status_mux0(f.data)
            if d is not None:
                status_frames.append((f.timestamp, d['state'], d['shutdown_source'], d['exporting']))
        elif f.arbitration_id == ID_POWER:
            d = decode_power(f.data)
            if d is not None:
                power_frames.append((f.timestamp, d['batt_v'], d['batt_i'], d['ac_v'], d['ac_i']))
        elif f.arbitration_id == ID_J1772:
            d = decode_j1772(f.data)
            if d is not None:
                j1772_frames.append((f.timestamp, d['pilot_duty']))

    if not status_frames:
        print("  [!] No 0x18FFD4C0 mux=0 frames found")
        return
    if not power_frames:
        print("  [!] No 0x18FFD7C0 frames found")
        return

    # Split into per-plug-cycle sessions
    sessions = split_sessions(status_frames)
    print(f"\n  Sessions detected: {len(sessions)}")
    for si, sess in enumerate(sessions):
        t_start, t_end = sess[0][0], sess[-1][0]
        export = is_export_session(sess)
        tag = " [EXPORT]" if export else " [CHARGE]"
        print(f"    Session {si+1}: t={t_start:.1f}s - t={t_end:.1f}s  ({t_end-t_start:.0f}s){tag}")

    for si, sess_status in enumerate(sessions):
        t_start = sess_status[0][0]
        t_end   = sess_status[-1][0]
        export  = is_export_session(sess_status)
        tag     = "EXPORT" if export else "CHARGE"

        sess_power  = [f for f in power_frames  if t_start <= f[0] <= t_end]
        sess_j1772  = [f for f in j1772_frames  if t_start <= f[0] <= t_end]

        print(f"\n{'='*70}")
        print(f"  SESSION {si+1}/{len(sessions)}: {tag}  t={t_start:.1f}s - t={t_end:.1f}s")
        print(f"{'='*70}")

        analyze_session_data(sess_status, sess_power, sess_j1772, export)


def analyze_session_data(status_frames, power_frames, j1772_frames, export_mode):
    """Analyze one session (already time-sliced). status_frames tuples: (t, state, src, exporting)."""

    # J1772 pilot summary
    if j1772_frames:
        duties = [d for _, d in j1772_frames]
        nonzero = [d for d in duties if d > 0]
        print(f"\n--- J1772 Pilot Duty (0x18FFD8C0 B2): {len(j1772_frames)} frames ---")
        print(f"  Export mode (exporting bit): {export_mode}")
        print(f"  pilotDuty range: {min(duties)}-{max(duties)}  nonzero count: {len(nonzero)}")

    # ----------------------------------------------------------------
    # 1. FULL STATE MACHINE HISTORY
    # ----------------------------------------------------------------
    print(f"\n--- State Machine — {len(status_frames)} mux=0 frames ---")

    transitions = []   # (t, old_state, new_state, shutdown_src)
    prev_state = status_frames[0][1]
    for t, state, src, _exp in status_frames[1:]:
        if state != prev_state:
            transitions.append((t, prev_state, state, src))
            prev_state = state

    print(f"  Total state transitions: {len(transitions)}")
    print(f"  All transitions:")
    for t, old, new, src in transitions:
        print(f"    t={t:9.3f}s  {old} -> {new}  (shutdownSource={src})")

    if export_mode:
        print(f"\n  [Export session — skipping failure/intermittency analysis]")
        # Still show V/I profile for export sessions
        if power_frames:
            batt_vs = [bv for _, bv, _, _, _ in power_frames if bv != 0]
            batt_is = [bi for _, _, bi, _, _ in power_frames if bi != 0]
            ac_vs   = [av for _, _, _, av, _ in power_frames if av != 0]
            if batt_vs:
                print(f"\n--- Export V/I profile ---")
                print(f"  battV: {min(batt_vs):.1f} - {max(batt_vs):.1f}V")
            if batt_is:
                print(f"  battI: {min(batt_is):.1f} - {max(batt_is):.1f}A")
            if ac_vs:
                print(f"  AC output V: {min(ac_vs):.1f} - {max(ac_vs):.1f}V")
        return

    # Identify intermittency events: 12->15->12 cycles
    intermittency = []
    i = 0
    while i < len(transitions) - 1:
        t0, old0, new0, src0 = transitions[i]
        t1, old1, new1, src1 = transitions[i+1]
        if old0 == 12 and new0 == 15 and old1 == 15 and new1 == 12:
            intermittency.append((t0, t1, t1 - t0, src0))
            i += 2
        else:
            i += 1

    # Find the final failure (last 12->15 that doesn't recover)
    final_failure_t = None
    for t, old, new, src in reversed(transitions):
        if old == 12 and new == 15:
            idx = next((i for i, tr in enumerate(transitions) if tr[0] == t), None)
            if idx is not None and idx + 1 < len(transitions) and transitions[idx+1][1] == 15 and transitions[idx+1][2] == 12:
                break
            final_failure_t = t
            break

    print(f"\n  Intermittency events (12->15->12 mini-cycles): {len(intermittency)}")
    for i, (t0, t1, dur, src) in enumerate(intermittency):
        dt_from_final = f"  (dt={t0 - final_failure_t:+.1f}s from final failure)" if final_failure_t else ""
        print(f"    [{i+1}] t={t0:.3f}s -> t={t1:.3f}s  duration={dur:.3f}s  shutdownSrc={src}{dt_from_final}")

    if final_failure_t:
        print(f"\n  Final failure (permanent 12->15): t={final_failure_t:.3f}s")
    else:
        print(f"\n  No permanent failure detected in this session")

    # ----------------------------------------------------------------
    # 2. AC INPUT VOLTAGE ANALYSIS
    # ----------------------------------------------------------------
    if not power_frames:
        print(f"\n--- AC Input Voltage: no power frames in this session ---")
        return

    print(f"\n--- AC Input Voltage (0x18FFD7C0 B4-5), {len(power_frames)} frames ---")

    ac_voltages = [ac_v for _, _, _, ac_v, _ in power_frames]

    # Build state lookup for power frames (within this session's status frames)
    state_at = {}
    si = 0
    for pf in power_frames:
        t_p = pf[0]
        while si + 1 < len(status_frames) and status_frames[si + 1][0] <= t_p:
            si += 1
        state_at[t_p] = status_frames[si][1]

    ac_charging    = [ac_v for t, _, _, ac_v, _ in power_frames if state_at.get(t) == 12]
    ac_notcharging = [ac_v for t, _, _, ac_v, _ in power_frames if state_at.get(t) != 12]

    if ac_charging:
        med_ac = median(ac_charging)
        print(f"  During state=12:  min={min(ac_charging):.2f}V  max={max(ac_charging):.2f}V  median={med_ac:.2f}V  n={len(ac_charging)}")
        spikes = [(t, ac_v) for t, _, _, ac_v, _ in power_frames
                  if state_at.get(t) == 12 and abs(ac_v - med_ac) > SPIKE_THRESHOLD_V]
        if spikes:
            print(f"\n  AC voltage SPIKES during charging (>{SPIKE_THRESHOLD_V:.0f}V from median {med_ac:.1f}V):")
            clusters = []
            cur_cluster = [spikes[0]]
            for s in spikes[1:]:
                if s[0] - cur_cluster[-1][0] < 2.0:
                    cur_cluster.append(s)
                else:
                    clusters.append(cur_cluster)
                    cur_cluster = [s]
            clusters.append(cur_cluster)
            for c in clusters:
                t0 = c[0][0]
                t1 = c[-1][0]
                vmin = min(v for _, v in c)
                vmax = max(v for _, v in c)
                dt = f"  (dt={t0 - final_failure_t:+.1f}s from final failure)" if final_failure_t else ""
                print(f"    t={t0:.3f}s-{t1:.3f}s  V={vmin:.1f}-{vmax:.1f}V  ({len(c)} frames){dt}")
        else:
            print(f"  No AC voltage spikes during charging (all within {SPIKE_THRESHOLD_V:.0f}V of median {med_ac:.1f}V)")
    else:
        med_ac = median(ac_voltages) if ac_voltages else 0.0
        print(f"  No state=12 power frames in this session")

    if ac_notcharging:
        nz = [v for v in ac_notcharging if v != 0]
        if nz:
            print(f"  During non-charging states: min={min(nz):.2f}V  max={max(nz):.2f}V")

    # ----------------------------------------------------------------
    # 3. CROSS-CORRELATE: voltage spikes vs state transitions
    # ----------------------------------------------------------------
    print(f"\n--- AC Voltage around intermittency events ---")
    if not intermittency:
        print("  No intermittency events to correlate")
    else:
        for idx, (t0, t1, dur, src) in enumerate(intermittency):
            window = [(t, ac_v) for t, _, _, ac_v, _ in power_frames if t0 - 1.0 <= t <= t1 + 2.0]
            if window:
                vmin = min(v for _, v in window)
                vmax = max(v for _, v in window)
                peak = max(window, key=lambda x: abs(x[1] - med_ac))
                print(f"  Event [{idx+1}] t={t0:.3f}s (dur={dur:.3f}s): AC range={vmin:.1f}-{vmax:.1f}V  peak={peak[1]:.1f}V at t={peak[0]:.3f}s")

    if final_failure_t:
        print(f"\n--- AC Voltage around final failure (t={final_failure_t:.3f}s) ---")
        window = [(t, ac_v) for t, _, _, ac_v, _ in power_frames
                  if final_failure_t - 2.0 <= t <= final_failure_t + 2.0]
        prev_v = None
        for t, v in window:
            if prev_v is None or abs(v - prev_v) > 0.5:
                print(f"  t={t:.3f}s (dt={t - final_failure_t:+.3f}s)  AC={v:.2f}V")
                prev_v = v


def main():
    parser = argparse.ArgumentParser(description='Q2: charge intermittency + AC voltage analysis')
    parser.add_argument('logs', nargs='*', help='Log files (default: all rainy day logs)')
    parser.add_argument('--output', '-o', help='Write report to file')
    args = parser.parse_args()

    LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')

    if args.logs:
        log_paths = [(p, os.path.basename(p)) for p in args.logs]
    else:
        names = [
            'rainychargedebug.log',
            'rainychargedebug3.log',
            'rainychargedebug4.log',
            'chargingafterturningaroundandnotusingextension.log',
        ]
        log_paths = [(os.path.join(LOGS_DIR, n), n) for n in names]

    if args.output:
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf

    for path, label in log_paths:
        if not os.path.exists(path):
            print(f"\n[SKIP - file not found: {path}]")
            continue
        analyze_log(path, label)

    if args.output:
        sys.stdout = old_stdout
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(buf.getvalue())
        print(f"Report written to: {args.output}")


if __name__ == '__main__':
    main()
