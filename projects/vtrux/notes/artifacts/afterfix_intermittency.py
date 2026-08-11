"""
After-fix charge session Q2-style intermittency analysis.

Same state machine + AC voltage analysis as charge_intermittency_analysis.py
but operates on chunked _M0_T# sessions.

Uses a fast pre-filter: reads each line, checks for target ID strings
before doing any full parsing, making it ~100x faster than parse_file
on large multi-bus captures.

Sessions analysed (logs/after-battery-swap-charges/):
  charge_M0      charge_M0_T0 .. charge_M0_T59
  another_M0     another_M0_T0 .. another_M0_T55
  charge_9pm     charge_9pm.log  (standalone)
"""

import sys
import os
import re
import struct
import glob
import argparse

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

ID_STATUS = 0x18FFD4C0
ID_POWER  = 0x18FFD7C0
TARGET_STRS = ('18FFD4C0', '18FFD7C0')   # match in log line (case insensitive)

SPIKE_THRESHOLD_V = 5.0


# ---------------------------------------------------------------------------
# Minimal fast BUSMASTER line parser
# ---------------------------------------------------------------------------
def _parse_ts(ts_str):
    """HH:MM:SS:TTTT -> seconds (float)."""
    h, m, s, t = ts_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) * 0.0001


def parse_busmaster_line(line):
    """Parse a single BUSMASTER data line.
    Returns (timestamp, arb_id, data_bytes) or None if not a data line.
    """
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        timestamp = _parse_ts(parts[0])
        arb_id    = int(parts[3], 16)
        dlc       = int(parts[5])
        data      = bytes(int(b, 16) for b in parts[6:6 + dlc])
        return timestamp, arb_id, data
    except (ValueError, IndexError):
        return None


def stream_target_frames(paths):
    """Yield (timestamp, arb_id, data) for the two target IDs only,
    reading chunk files in T-number order.

    Timestamps are adjusted so the first frame of the session is t=0.
    Handles midnight rollover.
    """
    t_session_start = None
    t_prev = 0.0

    def sort_key(p):
        m = re.search(r'_T(\d+)', os.path.basename(p))
        return int(m.group(1)) if m else 0

    for path in sorted(paths, key=sort_key):
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line_upper = line.upper()
                if '18FFD4C0' not in line_upper and '18FFD7C0' not in line_upper:
                    continue
                parsed = parse_busmaster_line(line)
                if parsed is None:
                    continue
                raw_ts, arb_id, data = parsed

                # Midnight rollover: if raw timestamp jumps back more than 1 s
                if t_session_start is None:
                    t_session_start = raw_ts
                    adjusted = 0.0
                else:
                    adj = raw_ts - t_session_start
                    # Rollover: add 86400 s (one day)
                    while adj < t_prev - 1.0:
                        adj += 86400.0
                    adjusted = adj

                t_prev = adjusted
                yield adjusted, arb_id, data


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------
def decode_status_mux0(data):
    if len(data) < 8 or data[0] != 0x00:
        return None
    return {'state': data[5], 'shutdown_source': data[6]}


def decode_power(data):
    if len(data) < 8:
        return None
    batt_v = struct.unpack_from('<h', data, 0)[0] * 0.05
    batt_i = struct.unpack_from('<h', data, 2)[0] * 0.05
    ac_v   = struct.unpack_from('<h', data, 4)[0] * 0.05
    ac_i   = struct.unpack_from('<h', data, 6)[0] * 0.05
    return {'batt_v': batt_v, 'batt_i': batt_i, 'ac_v': ac_v, 'ac_i': ac_i}


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_session(paths, label, standalone=False):
    print(f"\n{'='*70}")
    print(f"SESSION: {label}")
    print(f"{'='*70}")

    if standalone:
        from canre.parsers import parse_file
        raw_frames = parse_file(paths)
        frame_stream = ((f.timestamp, f.arbitration_id, f.data) for f in raw_frames
                        if f.arbitration_id in (ID_STATUS, ID_POWER))
    else:
        frame_stream = stream_target_frames(paths)

    status_frames = []   # (t, state, shutdown_src)
    power_frames  = []   # (t, ac_v)

    for t, arb_id, data in frame_stream:
        if arb_id == ID_STATUS:
            d = decode_status_mux0(data)
            if d is not None:
                status_frames.append((t, d['state'], d['shutdown_source']))
        elif arb_id == ID_POWER:
            d = decode_power(data)
            if d is not None:
                power_frames.append((t, d['ac_v']))

    if not status_frames:
        print("  [!] No 0x18FFD4C0 mux=0 frames found")
        return
    if not power_frames:
        print("  [!] No 0x18FFD7C0 frames found")
        return

    t_start = status_frames[0][0]
    t_end   = status_frames[-1][0]
    print(f"  Duration: {t_end - t_start:.1f}s ({(t_end - t_start)/60:.1f} min)")
    print(f"  Status frames (mux=0): {len(status_frames)}")
    print(f"  Power frames: {len(power_frames)}")

    # --- State machine ---
    transitions = []
    prev_state = status_frames[0][1]
    for t, state, src in status_frames[1:]:
        if state != prev_state:
            transitions.append((t, prev_state, state, src))
            prev_state = state

    print(f"\n--- State Machine ---")
    print(f"  Total state transitions: {len(transitions)}")
    print(f"  All transitions:")
    for t, old, new, src in transitions:
        print(f"    t={t:9.3f}s  {old} -> {new}  (shutdownSource={src})")

    # Intermittency events: 12->15->12 cycles
    intermittency = []
    i = 0
    while i < len(transitions) - 1:
        t0, old0, new0, src0 = transitions[i]
        t1, old1, new1, src1 = transitions[i + 1]
        if old0 == 12 and new0 == 15 and old1 == 15 and new1 == 12:
            intermittency.append((t0, t1, t1 - t0, src0))
            i += 2
        else:
            i += 1

    # Final failure
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
        dt = f"  (dt={t0 - final_failure_t:+.1f}s from final failure)" if final_failure_t else ""
        print(f"    [{i+1}] t={t0:.3f}s -> t={t1:.3f}s  duration={dur:.3f}s  shutdownSrc={src}{dt}")

    if final_failure_t:
        print(f"\n  Final failure (permanent 12->15): t={final_failure_t:.3f}s")
    else:
        last_state = status_frames[-1][1]
        print(f"\n  No permanent failure — session ended in state {last_state}")

    # --- AC Voltage ---
    print(f"\n--- AC Input Voltage ---")

    # State at each power frame
    si = 0
    state_at = {}
    for pf_t, _ in power_frames:
        while si + 1 < len(status_frames) and status_frames[si + 1][0] <= pf_t:
            si += 1
        state_at[pf_t] = status_frames[si][1]

    ac_charging    = [ac_v for t, ac_v in power_frames if state_at.get(t) == 12]
    ac_notcharging = [ac_v for t, ac_v in power_frames if state_at.get(t) != 12]

    if ac_charging:
        med_ac = median(ac_charging)
        print(f"  During state=12 (charging):  min={min(ac_charging):.2f}V  max={max(ac_charging):.2f}V  median={med_ac:.2f}V  n={len(ac_charging)}")

        spikes = [(t, ac_v) for t, ac_v in power_frames
                  if state_at.get(t) == 12 and abs(ac_v - med_ac) > SPIKE_THRESHOLD_V]
        if spikes:
            print(f"\n  AC voltage SPIKES during charging (>{SPIKE_THRESHOLD_V:.0f}V from median {med_ac:.1f}V):")
            clusters = []
            cur = [spikes[0]]
            for s in spikes[1:]:
                if s[0] - cur[-1][0] < 2.0:
                    cur.append(s)
                else:
                    clusters.append(cur)
                    cur = [s]
            clusters.append(cur)
            for c in clusters:
                t0 = c[0][0]
                t1 = c[-1][0]
                vmin = min(v for _, v in c)
                vmax = max(v for _, v in c)
                dt = f"  (dt={t0 - final_failure_t:+.1f}s from final failure)" if final_failure_t else ""
                print(f"    t={t0:.3f}s-{t1:.3f}s  V={vmin:.1f}-{vmax:.1f}V  ({len(c)} frames){dt}")
        else:
            print(f"  No AC spikes during charging (all within {SPIKE_THRESHOLD_V:.0f}V of median)")
    else:
        med_ac = None
        print("  No state=12 frames found")

    if ac_notcharging:
        print(f"  During non-charging states: min={min(ac_notcharging):.2f}V  max={max(ac_notcharging):.2f}V")

    # AC around intermittency events
    print(f"\n--- AC Voltage around intermittency events ---")
    if not intermittency:
        print("  None")
    elif med_ac is not None:
        for idx, (t0, t1, dur, src) in enumerate(intermittency):
            window = [(t, ac_v) for t, ac_v in power_frames if t0 - 1.0 <= t <= t1 + 2.0]
            if window:
                vmin = min(v for _, v in window)
                vmax = max(v for _, v in window)
                peak = max(window, key=lambda x: abs(x[1] - med_ac))
                print(f"  [{idx+1}] t={t0:.3f}s (dur={dur:.3f}s): AC={vmin:.1f}-{vmax:.1f}V  peak={peak[1]:.1f}V at t={peak[0]:.3f}s  src={src}")

    # AC around final failure
    if final_failure_t:
        print(f"\n--- AC Voltage around final failure (t={final_failure_t:.3f}s) ---")
        window = [(t, ac_v) for t, ac_v in power_frames
                  if final_failure_t - 2.0 <= t <= final_failure_t + 2.0]
        prev_v = None
        for t, v in window:
            if prev_v is None or abs(v - prev_v) > 0.5:
                print(f"  t={t:.3f}s (dt={t - final_failure_t:+.3f}s)  AC={v:.2f}V")
                prev_v = v


def main():
    parser = argparse.ArgumentParser(description='After-fix charge intermittency analysis')
    parser.add_argument('--output', '-o', help='Write report to file')
    args = parser.parse_args()

    LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'after-battery-swap-charges')

    if args.output:
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf

    # --- charge_M0 session ---
    charge_m0 = sorted(
        [p for p in glob.glob(os.path.join(LOGS_DIR, 'charge_M0_T*.log'))
         if not p.endswith('.no')],
        key=lambda p: int(re.search(r'_T(\d+)', os.path.basename(p)).group(1))
    )
    if charge_m0:
        print(f"  [charge_M0: {len(charge_m0)} chunk files]", file=sys.stderr)
        analyze_session(charge_m0, label='charge_M0')

    # --- another_M0 session ---
    another_m0 = sorted(
        [p for p in glob.glob(os.path.join(LOGS_DIR, 'another_M0_T*.log'))
         if not p.endswith('.no')],
        key=lambda p: int(re.search(r'_T(\d+)', os.path.basename(p)).group(1))
    )
    if another_m0:
        print(f"  [another_M0: {len(another_m0)} chunk files]", file=sys.stderr)
        analyze_session(another_m0, label='another_M0')

    # --- charge_9pm standalone ---
    standalone = os.path.join(LOGS_DIR, 'charge_9pm.log')
    if os.path.exists(standalone):
        print(f"  [charge_9pm: standalone]", file=sys.stderr)
        analyze_session(standalone, label='charge_9pm', standalone=True)

    if args.output:
        sys.stdout = old_stdout
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(buf.getvalue())
        print(f"Report written to: {args.output}")


if __name__ == '__main__':
    main()
