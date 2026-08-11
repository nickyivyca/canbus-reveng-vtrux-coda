"""
Bel Inverter fault register + health bit analysis.

Decodes BOTH mux=0 (state machine + health flags) AND mux=3 (fault register)
frames from 0x18FFD4C0, then shows:
  1. Baseline values during stable state=12 charging
  2. Any changes to fault or health bits in the ±120s window around each
     12->15 state transition
  3. Whether fault bits PRECEDE the CAN state transition (cause) or follow it (effect)

DBC layout (BelInverter.dbc, message 419419328 BINV_status):

  mux=0 (B0=0x00):
    B1: keySwitch(0), pilotControl(1), proxEnabled(2), evseConnected(3),
        vehicleConnected(4), auxPower(5), chargerEFE(6), s2Switch(7)
    B2: chargingInProgress(0), powerChargingIP(1), exportEnergy(2),
        exporting(3), gridTied(4), wakeOutput(5), delayedSleep(7)
    B3: rewaked(0), inverterAlive(1), inverterReady(2),
        buckBoostAlive(3), buckBoostReady(4), alciResetOn(5), alciActive(6)
    B4: evseDisconnected(1), autoLowPower(2), standby(6), unitReady(7)
    B5: state
    B6: shutdownSource
    B7: stateBeforeLastShutdown

  mux=3 (B0=0x03) — fault register:
    B1: acOk(0), acOV(1), acUV(2), sysLVUV(3), hvBattOV(4),
        hvBattUV(5), overTemp(6), exportOverLoad(7)
    B2: inverterFault(0), buckBoostFault(1), wakeOutputError(3),
        underFreq(5), overFreq(6)
"""

import sys
import os
import re
import struct
import glob as glob_mod
import argparse

PROJECT_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

ID_STATUS    = 0x18FFD4C0
LOGS_DIR     = os.path.join(PROJECT_ROOT, 'projects', 'vtrux', 'logs')
BEL_DIR      = os.path.join(PROJECT_ROOT, 'projects', 'vtrux', 'Bel Inverter')
SESSION_GAP_S = 10.0   # gap between consecutive 0x18FFD4C0 frames that marks a new plug cycle


# ---------------------------------------------------------------------------
# BUSMASTER parser
# ---------------------------------------------------------------------------
def _parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) * 0.0001


def parse_busmaster_line(line):
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        return (_parse_ts(parts[0]),
                int(parts[3], 16),
                bytes(int(b, 16) for b in parts[6:6 + int(parts[5])]))
    except (ValueError, IndexError):
        return None


def sort_key_mt(path):
    base = os.path.basename(path)
    t = re.search(r'_T(\d+)', base)
    m = re.search(r'_M(\d+)', base)
    return (int(t.group(1)) if t else 0, int(m.group(1)) if m else 0)


def split_sessions(all_frames, gap=SESSION_GAP_S):
    """Split a flat list of (t, data) frames into per-session sublists on gaps > gap seconds."""
    if not all_frames:
        return []
    sessions = []
    cur = [all_frames[0]]
    for frame in all_frames[1:]:
        if frame[0] - cur[-1][0] > gap:
            sessions.append(cur)
            cur = [frame]
        else:
            cur.append(frame)
    sessions.append(cur)
    return sessions


def stream_status_frames(paths):
    """Yield (adj_t, data) for 0x18FFD4C0 only, timestamps zeroed to session start."""
    if isinstance(paths, str):
        paths = [paths]
    t_start = None
    t_prev  = 0.0
    for path in sorted(paths, key=sort_key_mt):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    if '18FFD4C0' not in line.upper():
                        continue
                    parsed = parse_busmaster_line(line)
                    if parsed is None:
                        continue
                    raw_ts, arb_id, data = parsed
                    if arb_id != ID_STATUS:
                        continue
                    if t_start is None:
                        t_start = raw_ts
                        adj = 0.0
                    else:
                        adj = raw_ts - t_start
                        while adj < t_prev - 1.0:
                            adj += 86400.0
                    t_prev = adj
                    yield adj, data
        except OSError as e:
            print(f'  [SKIP {os.path.basename(path)}: {e}]', file=sys.stderr)


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------
def decode_mux0(data):
    if len(data) < 8 or data[0] != 0x00:
        return None
    b1, b2, b3, b4 = data[1], data[2], data[3], data[4]
    return {
        'state':                 data[5],
        'shutdownSource':        data[6],
        'stateBefore':           data[7],
        # B1
        'keySwitch':             (b1 >> 0) & 1,
        'pilotControl':          (b1 >> 1) & 1,
        'proxEnabled':           (b1 >> 2) & 1,
        'evseConnected':         (b1 >> 3) & 1,
        'vehicleConnected':      (b1 >> 4) & 1,
        'auxPower':              (b1 >> 5) & 1,
        'chargerEFE':            (b1 >> 6) & 1,   # chargerEnergyFlowEnable
        's2Switch':              (b1 >> 7) & 1,
        # B2
        'chargingInProgress':    (b2 >> 0) & 1,
        'powerChargingIP':       (b2 >> 1) & 1,
        # B3
        'inverterAlive':         (b3 >> 1) & 1,
        'inverterReady':         (b3 >> 2) & 1,
        'buckBoostAlive':        (b3 >> 3) & 1,
        'buckBoostReady':        (b3 >> 4) & 1,
        # B4
        'evseDisconnected':      (b4 >> 1) & 1,
        'standby':               (b4 >> 6) & 1,
        'unitReady':             (b4 >> 7) & 1,
    }


def decode_mux3(data):
    if len(data) < 3 or data[0] != 0x03:
        return None
    b1, b2 = data[1], data[2]
    return {
        'acOk':              (b1 >> 0) & 1,
        'acOV':              (b1 >> 1) & 1,
        'acUV':              (b1 >> 2) & 1,
        'sysLVUV':           (b1 >> 3) & 1,
        'hvBattOV':          (b1 >> 4) & 1,
        'hvBattUV':          (b1 >> 5) & 1,
        'overTemp':          (b1 >> 6) & 1,
        'exportOverLoad':    (b1 >> 7) & 1,
        'inverterFault':     (b2 >> 0) & 1,
        'buckBoostFault':    (b2 >> 1) & 1,
        'wakeOutputError':   (b2 >> 3) & 1,
        'underFreq':         (b2 >> 5) & 1,
        'overFreq':          (b2 >> 6) & 1,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
WINDOW = 120.0   # seconds before/after each failure transition to show


def analyze_session(frames_m0, frames_m3, label):
    """Analyze one session from pre-split, pre-decoded frame lists.

    frames_m0: list of (t, dict) from decode_mux0  (timestamps zeroed to sub-session start)
    frames_m3: list of (t, dict) from decode_mux3  (same time base)
    """
    print(f'\n{"="*70}')
    print(f'SESSION: {label}')
    print(f'{"="*70}')

    if not frames_m0:
        print('  [!] No mux=0 status frames found')
        return
    if not frames_m3:
        print('  [!] No mux=3 fault frames found')
    else:
        print(f'  mux=0 frames: {len(frames_m0)}   mux=3 frames: {len(frames_m3)}')

    t0, t1 = frames_m0[0][0], frames_m0[-1][0]
    print(f'  Duration: {t1-t0:.1f}s ({(t1-t0)/60:.1f} min)')

    # State transitions from mux=0
    transitions = []
    prev_state = frames_m0[0][1]['state']
    for t, d in frames_m0[1:]:
        if d['state'] != prev_state:
            transitions.append((t, prev_state, d['state'], d['shutdownSource']))
            prev_state = d['state']

    # Find failure transitions (12->15 not immediately followed by 15->12)
    failure_times = []
    for i, (t, old, new, src) in enumerate(transitions):
        if old == 12 and new == 15:
            # Check if recovered (next transition is 15->12)
            if i + 1 < len(transitions) and transitions[i+1][1] == 15 and transitions[i+1][2] == 12:
                pass  # non-fatal intermittency
            else:
                failure_times.append((t, src))

    print(f'\n  State transitions:')
    for t, old, new, src in transitions:
        print(f'    t={t:10.3f}s  {old:2d} -> {new:2d}  src={src}')

    if not failure_times:
        print('\n  No permanent 12->15 failure found')
    else:
        ft, fsrc = failure_times[-1]
        print(f'\n  Final failure (12->15): t={ft:.3f}s  src={fsrc}')

    # -----------------------------------------------------------------------
    # Mux=0 health bits — baseline during state=12, then changes
    # -----------------------------------------------------------------------
    print(f'\n--- mux=0 health bits (baseline during state=12) ---')

    # Find a stable state=12 window (not near any transition)
    stable_samples = []
    for t, d in frames_m0:
        if d['state'] != 12:
            continue
        near = any(abs(t - tr[0]) < 5.0 for tr in transitions)
        if not near:
            stable_samples.append(d)
        if len(stable_samples) >= 50:
            break

    health_keys = ['inverterAlive', 'inverterReady', 'buckBoostAlive', 'buckBoostReady',
                   'unitReady', 'chargingInProgress', 'chargerEFE', 'auxPower',
                   'evseConnected', 'vehicleConnected', 'pilotControl', 'proxEnabled']

    if stable_samples:
        baseline_m0 = stable_samples[len(stable_samples)//2]  # use middle sample
        for k in health_keys:
            print(f'    {k:25s} = {baseline_m0[k]}')
    else:
        print('  No stable state=12 samples found')
        baseline_m0 = None

    # Show any changes to health bits during the session
    print(f'\n--- mux=0 health bit changes (any transition) ---')
    prev_d = frames_m0[0][1]
    changes_seen = 0
    for t, d in frames_m0[1:]:
        changed = [k for k in health_keys if d[k] != prev_d[k]]
        if changed:
            for k in changed:
                state_label = f'state={d["state"]}'
                src_label   = f'src={d["shutdownSource"]}'
                # Compute dt from each failure transition
                dt_strs = [f'dt={t-ft:+.2f}s from final' for ft, _ in failure_times]
                dt_str  = '  ' + ', '.join(dt_strs) if failure_times else ''
                print(f'  t={t:10.3f}s  {k:25s}: {prev_d[k]} -> {d[k]}  [{state_label} {src_label}]{dt_str}')
            changes_seen += 1
        prev_d = d
    if changes_seen == 0:
        print('  None')

    # -----------------------------------------------------------------------
    # Mux=3 fault bits — baseline and changes
    # -----------------------------------------------------------------------
    print(f'\n--- mux=3 fault register ---')
    if not frames_m3:
        print('  No mux=3 frames — cannot check fault register')
        return

    fault_keys = ['inverterFault', 'buckBoostFault', 'acOk', 'acOV', 'acUV',
                  'hvBattOV', 'hvBattUV', 'overTemp', 'sysLVUV',
                  'wakeOutputError', 'underFreq', 'overFreq', 'exportOverLoad']

    # Baseline: first stable cluster of mux=3 frames
    # Pick a sample at ~10% into the session
    mid_idx = min(len(frames_m3) - 1, max(0, len(frames_m3) // 10))
    baseline_m3 = frames_m3[mid_idx][1]
    print(f'  Baseline (t={frames_m3[mid_idx][0]:.1f}s):')
    for k in fault_keys:
        v = baseline_m3[k]
        flag = ' *** FAULT SET ***' if (k != 'acOk' and v == 1) or (k == 'acOk' and v == 0) else ''
        print(f'    {k:25s} = {v}{flag}')

    # Show any changes to fault register during the session
    print(f'\n--- mux=3 fault register changes ---')
    prev_f = frames_m3[0][1]
    fault_changes = 0
    for t, d in frames_m3[1:]:
        changed = [k for k in fault_keys if d[k] != prev_f[k]]
        if changed:
            dt_strs = [f'dt={t-ft:+.3f}s from final' for ft, _ in failure_times]
            dt_str  = '  ' + ', '.join(dt_strs) if failure_times else ''
            for k in changed:
                flag = ''
                if k == 'acOk' and d[k] == 0:
                    flag = '  *** AC LOST ***'
                elif k != 'acOk' and d[k] == 1:
                    flag = '  *** FAULT SET ***'
                elif k == 'acOk' and d[k] == 1:
                    flag = '  (AC restored)'
                elif d[k] == 0:
                    flag = '  (fault cleared)'
                print(f'  t={t:10.3f}s  {k:25s}: {prev_f[k]} -> {d[k]}{flag}{dt_str}')
            fault_changes += 1
        prev_f = d
    if fault_changes == 0:
        print('  No changes to fault register throughout session')

    # -----------------------------------------------------------------------
    # Detail window: ±WINDOW seconds around each failure
    # -----------------------------------------------------------------------
    for ft, fsrc in failure_times:
        print(f'\n--- Detail window ±{WINDOW:.0f}s around failure (t={ft:.3f}s) ---')
        lo, hi = ft - WINDOW, ft + WINDOW

        # mux=0 health changes in window
        print(f'  mux=0 changes in window:')
        prev_d = None
        any_m0 = False
        for t, d in frames_m0:
            if not (lo <= t <= hi):
                continue
            if prev_d is None:
                prev_d = d
                continue
            changed = [k for k in health_keys if d[k] != prev_d[k]]
            if changed:
                for k in changed:
                    print(f'    t={t:.3f}s (dt={t-ft:+.3f}s)  {k}: {prev_d[k]} -> {d[k]}  state={d["state"]} src={d["shutdownSource"]}')
                    any_m0 = True
            prev_d = d
        if not any_m0:
            print('    None')

        # mux=3 fault changes in window
        print(f'  mux=3 changes in window:')
        prev_f = None
        any_m3 = False
        for t, d in frames_m3:
            if not (lo <= t <= hi):
                continue
            if prev_f is None:
                prev_f = d
                continue
            changed = [k for k in fault_keys if d[k] != prev_f[k]]
            if changed:
                for k in changed:
                    flag = ''
                    if k == 'acOk' and d[k] == 0:
                        flag = ' *** AC LOST ***'
                    elif k != 'acOk' and d[k] == 1:
                        flag = ' *** FAULT SET ***'
                    print(f'    t={t:.3f}s (dt={t-ft:+.3f}s)  {k}: {prev_f[k]} -> {d[k]}{flag}  src={frames_m0[min(len(frames_m0)-1, next((i for i,(tt,_) in enumerate(frames_m0) if tt>=t), len(frames_m0)-1))][1]["shutdownSource"]}')
                    any_m3 = True
            prev_f = d
        if not any_m3:
            print('    None')

    # -----------------------------------------------------------------------
    # First fault event summary
    # -----------------------------------------------------------------------
    print(f'\n--- FIRST FAULT EVENT SUMMARY ---')
    if not failure_times:
        print('  No terminal failure detected in this session')
        return
    ft_final, _ = failure_times[-1]

    # Find last src=3 transition (the pre-failure recovery attempt)
    src3_t = None
    for t, old, new, src in transitions:
        if old == 12 and new == 15 and src == 3:
            src3_t = t  # keep updating to get the last one

    # Find when stable charging is established (chargingInProgress first goes 1).
    # Faults that SET before this are startup transients, not failure causes.
    stable_start_t = 0.0
    prev_cip = frames_m0[0][1].get('chargingInProgress', 0)
    for t, d in frames_m0[1:]:
        if d.get('chargingInProgress', 0) == 1 and prev_cip == 0:
            stable_start_t = t
            break
        prev_cip = d.get('chargingInProgress', 0)

    # Find the earliest fault bit that SET after stable charging is established
    first_fault_t   = None
    first_fault_bit = None
    if frames_m3:
        prev_f = frames_m3[0][1]
        for t, d in frames_m3[1:]:
            if t < stable_start_t:
                prev_f = d
                continue
            if first_fault_t is None:
                for k in fault_keys:
                    if k == 'acOk':
                        continue  # acOk clearing is a separate event type
                    if d[k] == 1 and prev_f[k] == 0:
                        first_fault_t   = t
                        first_fault_bit = k
                        break
            prev_f = d
            if first_fault_t is not None:
                break  # stop at the frame containing the first SET

    if first_fault_t is not None:
        dt_from_final = first_fault_t - ft_final
        dt_from_src3  = (first_fault_t - src3_t) if src3_t is not None else None
        print(f'  (Startup transients before t={stable_start_t:.1f}s excluded)')
        print(f'  First fault bit SET  : {first_fault_bit}')
        print(f'  Fired at             : t={first_fault_t:.3f}s')
        print(f'  dt from final (src=14) shutdown : {dt_from_final:+.3f}s')
        if dt_from_src3 is not None:
            print(f'  dt from src=3 transition        : {dt_from_src3:+.3f}s')
        print(f'  >> {first_fault_bit} is the FIRST observable fault event in this session.')
        print(f'     The src=3 state transition is the charger firmware response (100ms later).')
        print(f'     Any VCU/vehicle-side signal changes that follow are reactions, not causes.')
    else:
        print('  No fault bits SET in mux=3 register during session')
        print('  (Healthy session or mux=3 frames unavailable)')


# ---------------------------------------------------------------------------
# Multi-session log handling
# ---------------------------------------------------------------------------
def analyze_log(paths, label):
    """Read all 0x18FFD4C0 frames from paths, split into plug-cycle sessions, analyze each."""
    all_frames = list(stream_status_frames(paths))
    if not all_frames:
        print(f'\n  [!] No 0x18FFD4C0 frames found for {label}')
        return

    sessions = split_sessions(all_frames)

    print(f'\n{"="*70}')
    print(f'LOG: {label}')
    print(f'  Sessions detected: {len(sessions)}')
    for si, sess in enumerate(sessions):
        t0, t1 = sess[0][0], sess[-1][0]
        # Peek at states to tag charge vs export
        states = set()
        for _, data in sess:
            d0 = decode_mux0(data)
            if d0:
                states.add(d0['state'])
        tag = '[EXPORT]' if any(s in {30, 31, 32, 33} for s in states) else '[CHARGE]'
        print(f'    Session {si+1}: t={t0:.1f}s - t={t1:.1f}s  ({t1-t0:.0f}s) {tag}')
    print(f'{"="*70}')

    for si, sess_frames in enumerate(sessions):
        t_offset = sess_frames[0][0]
        # Zero timestamps to this sub-session's start
        frames_m0 = []
        frames_m3 = []
        for raw_t, data in sess_frames:
            t = raw_t - t_offset
            d0 = decode_mux0(data)
            if d0 is not None:
                frames_m0.append((t, d0))
                continue
            d3 = decode_mux3(data)
            if d3 is not None:
                frames_m3.append((t, d3))

        sess_label = f'{label} — Session {si+1}/{len(sessions)}'
        analyze_session(frames_m0, frames_m3, sess_label)


# ---------------------------------------------------------------------------
# Session definitions
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('logs', nargs='*', help='Log file paths (default: hardcoded rainy day set)')
    parser.add_argument('--output', '-o')
    args = parser.parse_args()

    if args.output:
        import io
        buf = io.StringIO()
        sys.stdout = buf

    if args.logs:
        for path in args.logs:
            if not os.path.exists(path):
                print(f'\n  [SKIP {path} — not found]')
                continue
            label = os.path.basename(path).replace('.log', '')
            mb = os.path.getsize(path) // 1024 // 1024
            print(f'\n  [{label}: {mb} MB]', file=sys.stderr)
            analyze_log(path, label)
    else:
        rainy_logs = ['rainychargedebug.log', 'rainychargedebug3.log',
                      'rainychargedebug4.log',
                      'chargingafterturningaroundandnotusingextension.log',
                      'vtruxchargeafterucsc.log']

        print('\n' + '#'*70)
        print('# Rainy Day / Post-Battery-Swap Charge Failures (fault register analysis)')
        print('#'*70)
        for name in rainy_logs:
            path = os.path.join(LOGS_DIR, name)
            if not os.path.exists(path):
                print(f'\n  [SKIP {name} — not found]')
                continue
            mb = os.path.getsize(path) // 1024 // 1024
            print(f'\n  [{name}: {mb} MB]', file=sys.stderr)
            analyze_log(path, name.replace('.log', ''))

        # One healthy session for baseline comparison
        print('\n' + '#'*70)
        print('# Healthy reference: vtruxchargeafterevaplogattempt2 (completed charge)')
        print('#'*70)
        ref = os.path.join(LOGS_DIR, 'vtruxchargeafterevaplogattempt2.log')
        if os.path.exists(ref):
            mb = os.path.getsize(ref) // 1024 // 1024
            print(f'\n  [reference: {mb} MB]', file=sys.stderr)
            analyze_log(ref, 'healthy_ref_chargeafterevap2')
        else:
            print('\n  [SKIP — not found]')

    if args.output:
        content = buf.getvalue()
        sys.stdout = sys.__stdout__
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Report written to: {args.output}')


if __name__ == '__main__':
    main()
