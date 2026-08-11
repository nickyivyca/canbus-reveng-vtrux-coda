"""
Bel Inverter charge log intermittency analysis — extended timeline.

Same fast pre-filter approach as afterfix_intermittency.py, applied to:
  1. Bel-Inverter/other-logs/             (Jan–Sep 2025, main truck only)
  2. Bel-Inverter/actual-failed-charges/  (May 2025 and June 2025 sessions)
  3. logs/full charge then fail.log       (Aug 22 2025 — unique: truck couldn't restart)

NOTE: truklog files dated October 2025 in 'other-logs/' are from the PARTS TRUCK
charging, not the main truck. These are intentionally excluded here.

Multi-bus captures: each session spans M0/M1/M2/etc. files for different buses.
The pre-filter passes only 0x18FFD4C0 and 0x18FFD7C0, so non-charger buses
contribute nothing and all M-numbers from the same session can be pooled.
"""

import sys
import os
import re
import struct
import glob
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

ID_STATUS = 0x18FFD4C0
ID_POWER  = 0x18FFD7C0
SPIKE_THRESHOLD_V = 5.0

BEL_DIR    = os.path.join(PROJECT_ROOT, 'projects', 'vtrux', 'Bel Inverter')
FAILED_DIR = os.path.join(BEL_DIR, 'actual-failed-charges')
OTHER_DIR  = os.path.join(BEL_DIR, 'other-logs')
LOGS_DIR   = os.path.join(PROJECT_ROOT, 'projects', 'vtrux', 'logs')


# ---------------------------------------------------------------------------
# Fast BUSMASTER pre-filter
# ---------------------------------------------------------------------------
def _parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) * 0.0001


def parse_busmaster_line(line):
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        return _parse_ts(parts[0]), int(parts[3], 16), \
               bytes(int(b, 16) for b in parts[6:6 + int(parts[5])])
    except (ValueError, IndexError):
        return None


def sort_key_mt(path):
    base = os.path.basename(path)
    t = re.search(r'_T(\d+)', base)
    m = re.search(r'_M(\d+)', base)
    return (int(t.group(1)) if t else 0, int(m.group(1)) if m else 0)


def stream_target_frames(paths):
    """Yield (t, arb_id, data) for charger IDs only, timestamps zeroed to session start.
    Files that cannot be read (e.g. not locally cached on SeaDrive) are skipped with a warning.
    """
    t_start = None
    t_prev  = 0.0
    for path in sorted(paths, key=sort_key_mt):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    lu = line.upper()
                    if '18FFD4C0' not in lu and '18FFD7C0' not in lu:
                        continue
                    parsed = parse_busmaster_line(line)
                    if parsed is None:
                        continue
                    raw_ts, arb_id, data = parsed
                    if t_start is None:
                        t_start = raw_ts
                        adj = 0.0
                    else:
                        adj = raw_ts - t_start
                        while adj < t_prev - 1.0:   # midnight rollover
                            adj += 86400.0
                    t_prev = adj
                    yield adj, arb_id, data
        except OSError as e:
            print(f"  [SKIP {os.path.basename(path)}: {e}]", file=sys.stderr)


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------
def decode_status_mux0(data):
    if len(data) < 8 or data[0] != 0x00:
        return None
    return data[5], data[6]   # state, shutdown_source


def decode_ac_v(data):
    if len(data) < 6:
        return None
    return struct.unpack_from('<h', data, 4)[0] * 0.05


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_session(paths, label):
    print(f"\n{'='*70}")
    print(f"SESSION: {label}")
    print(f"{'='*70}")

    if isinstance(paths, str):
        paths = [paths]

    status_frames = []
    power_frames  = []

    for t, arb_id, data in stream_target_frames(paths):
        if arb_id == ID_STATUS:
            d = decode_status_mux0(data)
            if d:
                status_frames.append((t, d[0], d[1]))
        elif arb_id == ID_POWER:
            v = decode_ac_v(data)
            if v is not None:
                power_frames.append((t, v))

    if not status_frames:
        print("  [!] No charger status frames — charger bus not present")
        return
    if not power_frames:
        print("  [!] No power frames")
        return

    t0, t1 = status_frames[0][0], status_frames[-1][0]
    print(f"  Duration: {t1-t0:.1f}s ({(t1-t0)/60:.1f} min)")
    print(f"  Status mux=0 frames: {len(status_frames)}   Power frames: {len(power_frames)}")

    # State transitions
    transitions = []
    prev = status_frames[0][1]
    for t, state, src in status_frames[1:]:
        if state != prev:
            transitions.append((t, prev, state, src))
            prev = state

    print(f"\n--- State Machine ({len(transitions)} transitions) ---")
    for t, old, new, src in transitions:
        print(f"    t={t:9.3f}s  {old} -> {new}  (shutdownSource={src})")

    # Intermittency events
    intermittency = []
    i = 0
    while i < len(transitions) - 1:
        t0_, old0, new0, src0 = transitions[i]
        t1_, old1, new1, _    = transitions[i+1]
        if old0 == 12 and new0 == 15 and old1 == 15 and new1 == 12:
            intermittency.append((t0_, t1_, t1_ - t0_, src0))
            i += 2
        else:
            i += 1

    # Final failure
    final_t = None
    for t, old, new, src in reversed(transitions):
        if old == 12 and new == 15:
            idx = next((j for j, tr in enumerate(transitions) if tr[0] == t), None)
            if idx is not None and idx+1 < len(transitions) \
                    and transitions[idx+1][1] == 15 and transitions[idx+1][2] == 12:
                break
            final_t = t
            break

    print(f"\n  12->15->12 intermittency events: {len(intermittency)}")
    for i, (ta, tb, dur, src) in enumerate(intermittency):
        dt = f"  (dt={ta-final_t:+.1f}s from final)" if final_t else ""
        print(f"    [{i+1}] t={ta:.3f}s  dur={dur:.3f}s  src={src}{dt}")

    if final_t:
        print(f"\n  Final failure (12->15): t={final_t:.3f}s")
        # Find the full final shutdown sequence
        idx = next((j for j, tr in enumerate(transitions) if tr[0] == final_t), None)
        if idx is not None and idx+1 < len(transitions):
            print(f"  Post-failure states:")
            for tr in transitions[idx+1:]:
                print(f"    {tr[1]} -> {tr[2]}  src={tr[3]}")
    else:
        print(f"\n  No permanent failure — ended in state {status_frames[-1][1]}")

    # AC voltage
    si = 0
    state_at = {}
    for pf_t, _ in power_frames:
        while si+1 < len(status_frames) and status_frames[si+1][0] <= pf_t:
            si += 1
        state_at[pf_t] = status_frames[si][1]

    ac_chg = [v for t, v in power_frames if state_at.get(t) == 12]

    print(f"\n--- AC Input Voltage ---")
    if not ac_chg:
        print("  No state=12 power frames")
        return

    med = median(ac_chg)
    print(f"  State=12: min={min(ac_chg):.1f}V  max={max(ac_chg):.1f}V  median={med:.1f}V  n={len(ac_chg)}")

    spikes = [(t, v) for t, v in power_frames
              if state_at.get(t) == 12 and abs(v - med) > SPIKE_THRESHOLD_V]
    if spikes:
        clusters, cur = [], [spikes[0]]
        for s in spikes[1:]:
            if s[0] - cur[-1][0] < 2.0:
                cur.append(s)
            else:
                clusters.append(cur); cur = [s]
        clusters.append(cur)
        print(f"  AC spikes (>{SPIKE_THRESHOLD_V:.0f}V from median): {len(clusters)} cluster(s)")
        for c in clusters:
            vmin = min(v for _, v in c)
            vmax = max(v for _, v in c)
            dt = f"  dt={c[0][0]-final_t:+.0f}s" if final_t else ""
            print(f"    t={c[0][0]:.1f}s-{c[-1][0]:.1f}s  V={vmin:.1f}-{vmax:.1f}V  ({len(c)} frames){dt}")
    else:
        print(f"  No AC spikes during charging")

    if final_t:
        print(f"\n--- AC around final failure (t={final_t:.1f}s) ---")
        window = [(t, v) for t, v in power_frames if final_t-2.0 <= t <= final_t+2.0]
        prev_v = None
        for t, v in window:
            if prev_v is None or abs(v - prev_v) > 0.5:
                print(f"  t={t:.3f}s (dt={t-final_t:+.3f}s)  AC={v:.2f}V")
                prev_v = v


# ---------------------------------------------------------------------------
# Session definitions
# ---------------------------------------------------------------------------
def glob_dir(directory, pattern):
    return glob.glob(os.path.join(directory, pattern))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o')
    args = parser.parse_args()

    if args.output:
        import io
        buf = io.StringIO()
        sys.stdout = buf

    # -----------------------------------------------------------------------
    # Bel Inverter / other-logs  (main truck, Jan–Sep 2025 only)
    # NOTE: Oct 2025 files excluded — those are the parts truck charging.
    # -----------------------------------------------------------------------
    print("\n" + "#"*70)
    print("# BEL INVERTER / other-logs  (main truck, Jan–Sep 2025)")
    print("#"*70)

    other_sessions = [
        ('Jan28_2025_charge_attempts',
         glob_dir(OTHER_DIR, 'chargelog_M*.log')
         + glob_dir(OTHER_DIR, 'charge2_M*.log')
         + glob_dir(OTHER_DIR, 'charge3_M*.log')
         + glob_dir(OTHER_DIR, 'charge4_M*.log')),

        ('Feb12_2025_212charge',
         glob_dir(OTHER_DIR, '212charge_M*.log')),

        ('Feb13_2025_truklog_M0',
         # T11-T24 from Feb 13 — use explicit pattern, exclude Oct "(2)" files
         [p for p in glob_dir(OTHER_DIR, 'truklog_M0_T*.log')
          if '(' not in os.path.basename(p)]),

        ('Jun20_2025_TRUKLOG_M2',
         glob_dir(OTHER_DIR, 'TRUKLOG_M2_T*.log')),

        ('Sep2025_truklog',
         # Sep 2025: TRUKLOG_M1_T0 and truklog_M0_T0/T1 only.
         # Exclude truklog_M0_T10 here — it has a Jun 2025 mtime and belongs
         # to the actual-failed-charges June session, not this one.
         glob_dir(OTHER_DIR, 'TRUKLOG_M1_T0.log')
         + [p for p in glob_dir(OTHER_DIR, 'truklog_M0_T*.log')
            if '(' not in os.path.basename(p)
            and not os.path.basename(p).endswith('T10.log')]),
    ]

    for label, paths in other_sessions:
        paths = [p for p in paths if os.path.exists(p) and os.path.getsize(p) > 0]
        if not paths:
            print(f"\n  [SKIP {label} — no files found]")
            continue
        print(f"\n  [{label}: {len(paths)} file(s)]", file=sys.stderr)
        analyze_session(paths, label)

    # -----------------------------------------------------------------------
    # Bel Inverter / actual-failed-charges
    # May 20 2025: original truklog files (no "(2)")
    # Jun 25 2025: "(2)" files + later M1/M2/M3 chunks + standalone T10
    # -----------------------------------------------------------------------
    print("\n" + "#"*70)
    print("# BEL INVERTER / actual-failed-charges")
    print("#"*70)

    may_2025 = [p for p in glob_dir(FAILED_DIR, 'truklog_*.log')
                if '(' not in os.path.basename(p)]

    jun_2025 = (
        glob_dir(FAILED_DIR, 'truklog_M0_T* (2).log')
        + glob_dir(FAILED_DIR, 'truklog_M0_T10.log')
        + glob_dir(FAILED_DIR, 'truklog_M1_T1*.log')
        + glob_dir(FAILED_DIR, 'truklog_M2_T1*.log')
        + glob_dir(FAILED_DIR, 'truklog_M2_T2*.log')
        + glob_dir(FAILED_DIR, 'truklog_M3_T2*.log')
    )
    jun_2025 = list(set(jun_2025))

    for label, paths in [('May20_2025_actualfailed', may_2025),
                          ('Jun25_2025_actualfailed', jun_2025)]:
        paths = [p for p in paths if os.path.exists(p) and os.path.getsize(p) > 0]
        if not paths:
            print(f"\n  [SKIP {label} — no files found]")
            continue
        print(f"\n  [{label}: {len(paths)} file(s)]", file=sys.stderr)
        analyze_session(paths, label)

    # -----------------------------------------------------------------------
    # full charge then fail (Aug 22 2025)
    # -----------------------------------------------------------------------
    print("\n" + "#"*70)
    print("# logs/full charge then fail.log  (Aug 22 2025)")
    print("#"*70)
    fctf = os.path.join(LOGS_DIR, 'full charge then fail.log')
    if os.path.exists(fctf):
        mb = os.path.getsize(fctf) // 1024 // 1024
        print(f"\n  [full charge then fail: {mb} MB single file]", file=sys.stderr)
        analyze_session(fctf, 'full_charge_then_fail_Aug22_2025')
    else:
        print(f"\n  [SKIP — not found: {fctf}]")

    if args.output:
        content = buf.getvalue()
        sys.stdout = sys.__stdout__
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Report written to: {args.output}")


if __name__ == '__main__':
    main()
