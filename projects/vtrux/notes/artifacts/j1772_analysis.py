"""
J1772 Pilot/Prox Signal Health Analysis — Q1 of rainy-day-charge-failures investigation.

Analyzes 0x18FFD4C0 (BINV_status, mux=0) and 0x18FFD8C0 (BELINV_j1772Info)
across the rainy day charge failure logs to check for pilot/prox anomalies.

Output: printed report per log. Save with --output to a .txt file.
"""

import sys
import os
import argparse
import struct
from collections import defaultdict

# Add project root to path
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from canre.parsers import parse_file

# Extended CAN IDs (29-bit)
ID_STATUS   = 0x18FFD4C0   # BINV_status (multiplexed)
ID_J1772    = 0x18FFD8C0   # BELINV_j1772Info

# mux=0 B1 bit meanings (bits relative to B1)
B1_BITS = {
    0: 'keySwitch',
    1: 'pilotControlSignal',
    2: 'proxEnabled',
    3: 'evseConnected',
    4: 'vehicleConnected',
    5: 'auxPowerSupply',
    6: 'chargerEnergyFlowEnable',
    7: 's2Switch',
}


def decode_j1772(data):
    """Decode 0x18FFD8C0 frame."""
    if len(data) < 8:
        return None
    v12  = struct.unpack_from('<H', data, 0)[0] * 0.02
    duty = data[2]
    freq = struct.unpack_from('<H', data, 3)[0]
    # 24-bit LE for chargePilotOnlineTime
    t    = data[5] | (data[6] << 8) | (data[7] << 16)
    return {'12v': v12, 'duty': duty, 'freq': freq, 'online_time': t}


def decode_status_mux0(data):
    """Decode 0x18FFD4C0 mux=0 frame (B0=0x00)."""
    if len(data) < 8 or data[0] != 0x00:
        return None
    b1    = data[1]
    state = data[5]
    src   = data[6]
    return {'b1': b1, 'state': state, 'shutdown_source': src}


def analyze_log(log_path, label=None):
    label = label or os.path.basename(log_path)
    print(f"\n{'='*70}")
    print(f"LOG: {label}")
    print(f"{'='*70}")

    frames = parse_file(log_path)

    # Collect all relevant frames
    status_frames   = []   # (t, b1, state, shutdown_src)
    j1772_frames    = []   # (t, duty, freq, online_time, v12)

    for f in frames:
        if f.arbitration_id == ID_STATUS:
            d = decode_status_mux0(f.data)
            if d is not None:
                status_frames.append((f.timestamp, d['b1'], d['state'], d['shutdown_source']))
        elif f.arbitration_id == ID_J1772:
            d = decode_j1772(f.data)
            if d is not None:
                j1772_frames.append((f.timestamp, d['duty'], d['freq'], d['online_time'], d['12v']))

    if not status_frames:
        print("  [!] No 0x18FFD4C0 mux=0 frames found")
        return
    if not j1772_frames:
        print("  [!] No 0x18FFD8C0 frames found")
        return

    # --- Find failure time: last state=12 before first permanent state=15 ---
    # Look for the final 12->15 transition
    failure_time = None
    last_state = None
    for t, b1, state, src in status_frames:
        if last_state == 12 and state == 15:
            failure_time = t
        last_state = state
    if failure_time:
        print(f"\nFailure time (last 12->15): t={failure_time:.3f}s")
    else:
        print("\n[No 12->15 failure transition found in this log]")

    # --- B1 status bit analysis (mux=0) ---
    print(f"\n--- BINV_status B1 (pilot/prox flags), mux=0 frames: {len(status_frames)} ---")

    # Track transitions per bit
    prev_b1 = status_frames[0][1]
    transitions = defaultdict(list)  # bit -> [(t, old, new)]
    for t, b1, state, src in status_frames[1:]:
        if b1 != prev_b1:
            diff = prev_b1 ^ b1
            for bit in range(8):
                if diff & (1 << bit):
                    transitions[bit].append((t, (prev_b1 >> bit) & 1, (b1 >> bit) & 1))
            prev_b1 = b1

    # Baseline B1 value (mode)
    from collections import Counter
    b1_counts = Counter(b1 for _, b1, _, _ in status_frames)
    baseline_b1 = b1_counts.most_common(1)[0][0]
    print(f"  Baseline B1 (most common): 0x{baseline_b1:02X}")
    for bit in range(8):
        val = (baseline_b1 >> bit) & 1
        print(f"    bit{bit} {B1_BITS[bit]:30s} = {val}")

    print(f"\n  B1 bit transitions:")
    if not any(transitions.values()):
        print("    [none — B1 was CONSTANT throughout session]")
    else:
        for bit in sorted(transitions.keys()):
            name = B1_BITS.get(bit, f'bit{bit}')
            print(f"    bit{bit} {name}:")
            for t, old, new in transitions[bit]:
                dt = f"(dt={t - failure_time:+.3f}s from failure)" if failure_time else ""
                print(f"      t={t:.3f}s  {old}->{new}  {dt}")

    # B1 at failure window
    if failure_time:
        window = [(t, b1) for t, b1, _, _ in status_frames
                  if abs(t - failure_time) <= 2.0]
        if window:
            print(f"\n  B1 in ±2s window around failure:")
            prev = None
            for t, b1 in window:
                if b1 != prev:
                    dt = t - failure_time
                    print(f"    t={t:.3f}s (dt={dt:+.3f}s)  B1=0x{b1:02X}", end='')
                    # decode bits
                    set_bits = [B1_BITS[i] for i in range(8) if (b1 >> i) & 1]
                    print(f"  [{', '.join(set_bits)}]")
                    prev = b1

    # --- J1772Info analysis ---
    print(f"\n--- BELINV_j1772Info (0x18FFD8C0), frames: {len(j1772_frames)} ---")

    duties  = [d for _, d, _, _, _ in j1772_frames]
    freqs   = [f for _, _, f, _, _ in j1772_frames]
    otimes  = [o for _, _, _, o, _ in j1772_frames]
    v12s    = [v for _, _, _, _, v in j1772_frames]

    print(f"  pilotDuty:        min={min(duties)}  max={max(duties)}  unique={len(set(duties))}")
    print(f"  pilotFrequency:   min={min(freqs)} Hz  max={max(freqs)} Hz  unique={len(set(freqs))}")
    print(f"  chargePilotOnlineTime: min={min(otimes)}  max={max(otimes)}  delta={max(otimes)-min(otimes)}")
    print(f"  12v system:       min={min(v12s):.2f}V  max={max(v12s):.2f}V")

    # Check if pilotDuty ever drops or changes significantly
    duty_vals = sorted(set(duties))
    if len(duty_vals) == 1:
        print(f"  pilotDuty: CONSTANT at {duty_vals[0]} throughout session")
    else:
        print(f"  pilotDuty values seen: {duty_vals}")
        # Find transitions
        prev_d = j1772_frames[0][1]
        print(f"  pilotDuty transitions:")
        for t, d, freq, ot, v12 in j1772_frames[1:]:
            if d != prev_d:
                dt = f"(dt={t - failure_time:+.3f}s)" if failure_time else ""
                print(f"    t={t:.3f}s  {prev_d}->{d}  {dt}")
                prev_d = d

    # Check if pilotFrequency glitches
    freq_vals = sorted(set(freqs))
    if len(freq_vals) == 1:
        print(f"  pilotFrequency: CONSTANT at {freq_vals[0]} Hz throughout session")
    else:
        print(f"  pilotFrequency values seen: {freq_vals}")
        prev_f = j1772_frames[0][2]
        print(f"  pilotFrequency transitions:")
        for t, d, freq, ot, v12 in j1772_frames[1:]:
            if freq != prev_f:
                dt = f"(dt={t - failure_time:+.3f}s)" if failure_time else ""
                print(f"    t={t:.3f}s  {prev_f}->{freq} Hz  {dt}")
                prev_f = freq

    # chargePilotOnlineTime: is it monotonically increasing?
    mono = all(otimes[i] <= otimes[i+1] for i in range(len(otimes)-1))
    print(f"  chargePilotOnlineTime: {'monotonically increasing' if mono else 'NOT monotonic (see below)'}")
    if not mono:
        drops = [(i, otimes[i], otimes[i+1], j1772_frames[i][0])
                 for i in range(len(otimes)-1) if otimes[i] > otimes[i+1]]
        for i, a, b, t in drops[:10]:
            dt = f"(dt={t - failure_time:+.3f}s)" if failure_time else ""
            print(f"    drop at t={t:.3f}s: {a}->{b}  {dt}")

    # J1772 around failure
    if failure_time:
        window = [(t, d, freq, ot, v12) for t, d, freq, ot, v12 in j1772_frames
                  if abs(t - failure_time) <= 2.0]
        if window:
            print(f"\n  J1772 in ±2s window around failure:")
            prev = None
            for t, d, freq, ot, v12 in window:
                sig = (d, freq)
                if sig != prev:
                    dt = t - failure_time
                    print(f"    t={t:.3f}s (dt={dt:+.3f}s)  duty={d}  freq={freq}Hz  onlineTime={ot}")
                    prev = sig


def main():
    parser = argparse.ArgumentParser(description='J1772 pilot/prox analysis for rainy day charge failures')
    parser.add_argument('logs', nargs='*', help='Log files to analyze (default: all rainy day logs)')
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
            'vtruxchargeafterevap (failed).log',
        ]
        log_paths = [(os.path.join(LOGS_DIR, n), n) for n in names]

    # Redirect output if requested
    if args.output:
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf

    for path, label in log_paths:
        if not os.path.exists(path):
            print(f"\n[SKIP — file not found: {path}]")
            continue
        analyze_log(path, label)

    if args.output:
        sys.stdout = old_stdout
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(buf.getvalue())
        print(f"Report written to: {args.output}")


if __name__ == '__main__':
    main()
