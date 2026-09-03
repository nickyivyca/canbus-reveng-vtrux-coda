"""Time-domain micro-forensics on the five main-orig steady-state TYPE1 escalations.

All prior sweeps (m2_outlier_bytewise, type1_magnitude_compare) were VALUE-domain:
byte states at the TYPE1 instant, bytes moving during the countdown. This script works
the time domain instead, hunting for precursors the value sweeps are blind to:

  P1  micro-order: frame-by-frame change dump +/-3 s around TYPE1 and TYPE3.
      Does anything move BEFORE the alarm bits? Specifically for M2: is there any
      transition ~1.4 s before its TYPE1 (which would mean the 8.810 s outlier is a
      LATE TYPE1 BROADCAST of a universal 10.21 s timer, not a short countdown)?
  P2  TX timing: inter-frame gap statistics per BMS ID (0x400/410/420/430/440),
      baseline vs pre-window vs countdown; all anomalous gaps in the last 10 min.
      A marginal internal connection in the BMS master could perturb its own
      transmit scheduling before it perturbs any broadcast value.
  P3  fault_mon watchdog cadence (0x440 B0 bit6, pulses HIGH ~100 ms every ~1 s):
      pulse period/width regularity across the session; late/missing pulses.
  P4  balancing state (0x440 bcm_balancing B0 bit7, bcm_balancing_cnt B7):
      active at TYPE1? transitions in the 10 min before? Balancing FET switching is
      a plausible mechanical/electrical disturbance source not previously examined.
  P5  blip sweep: any byte in the watched IDs holding a value for <=3 frames,
      bracketed by >=10 stable frames of the SAME value on both sides, from charge
      start to TYPE3. The dynamics pass only covered the countdown window; this
      covers the whole session with single-frame resolution.
  P6  LSB churn: per-signal change-rate (ibat, vbat, vbus_pos, vbus_neg, lvbat,
      gfd) baseline vs final 60 s -- rising measurement noise would be the sense-
      line signature of hypothesis H4 (intermittent physical connection).

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/type1_micro_forensics.py [phases]
  e.g.  ... type1_micro_forensics.py 1 2 3      (default: all)
"""
import sys
sys.path.insert(0, ".")

import os
import re
import glob
from collections import defaultdict

import cantools

WATCH = {0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460}
BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")

ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}
MAINC16 = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]

DB = cantools.db.load_file("projects/vtrux/epri-pt-bus.dbc")
DECODABLE = {0x410, 0x420, 0x430, 0x440}
_dec_cache = {}


def dec(aid, data):
    key = (aid, data)
    v = _dec_cache.get(key)
    if v is None:
        try:
            v = DB.decode_message(aid, data, decode_choices=False)
        except Exception:
            v = {}
        _dec_cache[key] = v
    return v


def chunk_paths(patterns):
    seen = {}
    for pat in patterns:
        for p in glob.glob(pat):
            n = os.path.basename(p).lower()
            sz = os.path.getsize(p)
            if n not in seen or sz > seen[n][1]:
                seen[n] = (p, sz)
    return [v[0] for v in seen.values()]


SESSIONS = {
    "M0":   ["projects/vtrux/logs/actual-failed-charges/truklog_M0_T*.log"],
    "M1":   ["projects/vtrux/logs/actual-failed-charges/truklog_M1_T*.log"],
    "M2":   ["projects/vtrux/logs/other-logs/truklog_M2_T1[4-9].log",
             "projects/vtrux/logs/other-logs/truklog_M2_T2[0-1].log"],
    "M3":   ["projects/vtrux/logs/debuglog_M3_T*.log"],
    "0822": ["projects/vtrux/logs/full-charge-then-fail.log"],
}


def load_session(name):
    """Return time-sorted list of (t_abs, aid, data) for watched IDs."""
    frames = []
    for p in chunk_paths(SESSIONS[name]):
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line[:1] == "*":
                    continue
                m = BM_RE.match(line)
                if not m:
                    continue
                hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                aid = int(idh, 16)
                if aid not in WATCH:
                    continue
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                try:
                    data = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                frames.append((t, aid, data))
    frames.sort(key=lambda f: f[0])
    return frames


def find_escalation(frames):
    """Locate NONE->TYPE1->TYPE3 internal-fault escalation. Returns (t1, t3, t1_prev, t3_prev)."""
    prev_alarm = None
    prev_t = None
    t1 = t1_prev = None
    on_plug_at = 0
    for t, aid, data in frames:
        if aid != 0x410 or len(data) < 8:
            continue
        a = (data[1] >> 6) & 3
        plug = (data[0] >> 2) & 1
        if prev_alarm == 0 and a == 1 and plug == 1:
            t1, t1_prev, on_plug_at = t, prev_t, plug
        if t1 is not None and a == 3:
            if t - t1 < 30.0:
                return t1, t, t1_prev, prev_t
            t1 = None
        prev_alarm, prev_t = a, t
    return None


def fmt_bytes(d):
    return " ".join("%02X" % b for b in d)


def phase1(name, frames, t1, t3):
    print("\n--- P1 micro-order [%s]  T1=%.4f T3=%.4f gap=%.3f ---" % (name, t1, t3, t3 - t1))
    for center, label in ((t1, "TYPE1"), (t3, "TYPE3")):
        print("  around %s (t=%.4f), all watched-byte changes +/-3 s:" % (label, center))
        last = {}
        for t, aid, data in frames:
            if t < center - 20.0:
                last[aid] = data
                continue
            if t > center + 3.0:
                break
            p = last.get(aid)
            if p is not None and p != data and t >= center - 3.0:
                diffs = []
                for i in range(min(len(p), len(data))):
                    if p[i] != data[i]:
                        diffs.append("B%d %02X->%02X" % (i, p[i], data[i]))
                print("    %+8.3f  0x%03X  %s" % (t - center, aid, ", ".join(diffs)))
            last[aid] = data


def gap_stats(ts):
    if len(ts) < 3:
        return None
    gaps = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
    n = len(gaps)
    return {"n": n, "med": gaps[n // 2], "p99": gaps[int(n * 0.99)], "max": gaps[-1]}


def phase2(name, frames, t1, t3):
    print("\n--- P2 TX timing [%s] ---" % name)
    windows = [("baseline (T1-600..T1-120)", t1 - 600, t1 - 120),
               ("pre      (T1-120..T1)", t1 - 120, t1),
               ("countdown(T1..T3)", t1, t3)]
    for aid in sorted(WATCH):
        row = ["0x%03X" % aid]
        for label, a, b in windows:
            ts = [t for t, i, _ in frames if i == aid and a <= t < b]
            s = gap_stats(ts)
            row.append("n=%d med=%.1fms p99=%.1fms max=%.1fms" %
                       (s["n"], s["med"] * 1e3, s["p99"] * 1e3, s["max"] * 1e3) if s else "no data")
        print("  %s\n      base: %s\n      pre : %s\n      ctdn: %s" % tuple(row))
    print("  anomalous gaps (>2.5x baseline median) in T1-600 .. T3+2:")
    found = 0
    for aid in sorted(WATCH):
        base = [t for t, i, _ in frames if i == aid and t1 - 600 <= t < t1 - 120]
        s = gap_stats(base)
        if not s:
            continue
        thr = 2.5 * s["med"]
        ts = [t for t, i, _ in frames if i == aid and t1 - 600 <= t <= t3 + 2]
        for i in range(len(ts) - 1):
            g = ts[i + 1] - ts[i]
            if g > thr:
                print("    0x%03X  gap %.1f ms at t=%.3f (T1%+.3f)" % (aid, g * 1e3, ts[i + 1], ts[i + 1] - t1))
                found += 1
    if not found:
        print("    none")


def phase3(name, frames, t1, t3):
    print("\n--- P3 fault_mon cadence [%s] ---" % name)
    edges = []          # (t_rise, t_fall)
    rise = None
    prev = None
    for t, aid, data in frames:
        if aid != 0x440 or len(data) < 1:
            continue
        fm = (data[0] >> 6) & 1
        if prev == 0 and fm == 1:
            rise = t
        if prev == 1 and fm == 0 and rise is not None:
            edges.append((rise, t))
            rise = None
        prev = fm
    if len(edges) < 5:
        print("  <5 pulses found; fault_mon inactive or not pulsing")
        return
    periods = [(edges[i + 1][0] - edges[i][0], edges[i][0]) for i in range(len(edges) - 1)]
    ps = sorted(p for p, _ in periods)
    med = ps[len(ps) // 2]
    print("  %d pulses; period med=%.3f s  min=%.3f  max=%.3f" % (len(edges), med, ps[0], ps[-1]))
    print("  irregular periods (<0.7x or >1.3x median), with time rel to T1:")
    bad = [(p, t) for p, t in periods if p < 0.7 * med or p > 1.3 * med]
    for p, t in bad[-30:]:
        print("    period %.3f s at t=%.3f (T1%+.1f s)" % (p, t, t - t1))
    if not bad:
        print("    none -- cadence perfectly regular through the trip")
    near = [(p, t) for p, t in periods if t1 - 15 <= t <= t3]
    print("  periods in T1-15..T3: %s" % " ".join("%.2f" % p for p, _ in near))


def phase4(name, frames, t1, t3):
    print("\n--- P4 balancing [%s] ---" % name)
    events = []
    prev_bal = prev_cnt = None
    bal_at_t1 = cnt_at_t1 = None
    for t, aid, data in frames:
        if aid != 0x440 or len(data) < 8:
            continue
        bal = (data[0] >> 7) & 1
        cnt = data[7]
        if prev_bal is not None and bal != prev_bal:
            events.append((t, "balancing %d->%d" % (prev_bal, bal)))
        if prev_cnt is not None and cnt != prev_cnt:
            events.append((t, "balancing_cnt %d->%d" % (prev_cnt, cnt)))
        if t <= t1:
            bal_at_t1, cnt_at_t1 = bal, cnt
        prev_bal, prev_cnt = bal, cnt
    print("  at TYPE1: balancing=%s cnt=%s" % (bal_at_t1, cnt_at_t1))
    near = [(t, e) for t, e in events if t1 - 600 <= t <= t3 + 2]
    print("  transitions in T1-600..T3+2: %d" % len(near))
    for t, e in near[-40:]:
        print("    t=%.3f (T1%+.1f s)  %s" % (t, t - t1, e))


def phase5(name, frames, t1, t3):
    print("\n--- P5 blip sweep [%s] (session start .. T3) ---" % name)
    by_id = defaultdict(list)
    for t, aid, data in frames:
        if t <= t3 + 0.5:
            by_id[aid].append((t, data))
    nblips = 0
    for aid, seq in sorted(by_id.items()):
        if len(seq) < 30:
            continue
        nbytes = max(len(d) for _, d in seq)
        for bi in range(nbytes):
            vals = [(t, d[bi]) for t, d in seq if len(d) > bi]
            # run-length encode
            runs = []
            for t, v in vals:
                if runs and runs[-1][2] == v:
                    runs[-1][1] = t
                    runs[-1][3] += 1
                else:
                    runs.append([t, t, v, 1])
            for i in range(1, len(runs) - 1):
                a, b, c = runs[i - 1], runs[i], runs[i + 1]
                if b[3] <= 3 and a[3] >= 10 and c[3] >= 10 and a[2] == c[2]:
                    print("    0x%03X B%d: %02X -> %02X (x%d, %.0f ms) -> %02X   at t=%.3f (T1%+.1f s)  bits^ %02X"
                          % (aid, bi, a[2], b[2], b[3], (b[1] - b[0]) * 1e3 + 50, c[2],
                             b[0], b[0] - t1, a[2] ^ b[2]))
                    nblips += 1
    if not nblips:
        print("    none")


SIGWATCH = [
    (0x410, "bcm_ibat"), (0x410, "bcm_vbat"), (0x410, "bcm_gfd"),
    (0x430, "bcm_lvbat"), (0x430, "bcm_cell_vmax"), (0x430, "bcm_cell_vmin"),
    (0x440, "bcm_vbus_pos"), (0x440, "bcm_vbus_neg"), (0x440, "bcm_fgd"),
]


def phase6(name, frames, t1, t3):
    print("\n--- P6 LSB churn [%s] ---" % name)
    windows = [("baseline (T1-600..T1-60)", t1 - 600, t1 - 60),
               ("final 60s (T1-60..T1)", t1 - 60, t1)]
    for aid, sig in SIGWATCH:
        rates = []
        for label, a, b in windows:
            vals = []
            for t, i, d in frames:
                if i == aid and a <= t < b:
                    v = dec(aid, d).get(sig)
                    if v is not None:
                        vals.append(v)
            if len(vals) < 20:
                rates.append("n/a")
                continue
            ch = sum(1 for j in range(1, len(vals)) if vals[j] != vals[j - 1])
            rates.append("%.1f%% (n=%d)" % (100.0 * ch / (len(vals) - 1), len(vals)))
        print("  %-24s base=%-16s final60=%s" % ("0x%03X %s" % (aid, sig), rates[0], rates[1]))


def main():
    want = set(sys.argv[1:]) or {"1", "2", "3", "4", "5", "6"}
    for name in ("M0", "M1", "M2", "M3", "0822"):
        frames = load_session(name)
        print("\n" + "=" * 90)
        print("SESSION %s  (%d watched frames, files: %s)" %
              (name, len(frames), ", ".join(os.path.basename(p) for p in chunk_paths(SESSIONS[name]))))
        print("=" * 90)
        esc = find_escalation(frames)
        if not esc:
            print("  NO internal-fault escalation found -- check session assembly")
            continue
        t1, t3, t1p, t3p = esc
        print("  TYPE1 frame at %.4f (prev frame %.4f)  TYPE3 at %.4f (prev %.4f)" % (t1, t1p, t3, t3p))
        print("  gap frame-to-frame = %.3f s;  bounds [%.3f .. %.3f]" %
              (t3 - t1, t3p - t1, t3 - (t1p if t1p else t1)))
        if "1" in want:
            phase1(name, frames, t1, t3)
        if "2" in want:
            phase2(name, frames, t1, t3)
        if "3" in want:
            phase3(name, frames, t1, t3)
        if "4" in want:
            phase4(name, frames, t1, t3)
        if "5" in want:
            phase5(name, frames, t1, t3)
        if "6" in want:
            phase6(name, frames, t1, t3)


if __name__ == "__main__":
    main()
