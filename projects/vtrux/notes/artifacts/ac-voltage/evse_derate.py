"""Is the Vtrux EVSE current derate a fixed percentage or a fixed subtraction?

Pairs the J1772 pilot-advertised current (0x18FFD8C0 B2 pilotDuty, I = duty% * 0.6)
against the AC current the truck actually draws (0x18FFD7C0 B6:B7, x0.05 A), per
log file, then compares the two competing models:

    drawn = k * advertised          (fixed percentage)
    drawn = advertised - c          (fixed subtraction)

Only files where the truck is actually limit-constrained are usable: during CV
taper and at the end of a charge it draws far less than the pilot allows, which
is not a derate. Those are excluded by requiring the drawn current to be stable
near its own maximum for a sustained stretch.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/ac-voltage/evse_derate.py
"""

import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")

from canre.utils.merge import detect_capture_groups

ART = "projects/vtrux/notes/artifacts/ac-voltage"
PILOT_RAW = os.path.join(ART, "raw_pilot.txt")
AC_RAW = [os.path.join(ART, "raw_primary.txt"), os.path.join(ART, "raw_android.txt")]

PILOT_RE = re.compile(
    r"^(?P<path>.+?):\d{2}:\d{2}:\d{2}:\d{4}\s+\S+\s+\d+\s+0x18FFD8C0\s+x\s+8\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})"
)
AC_RE = re.compile(
    r"^(?P<path>.+?):\d{2}:\d{2}:\d{2}:\d{4}\s+\S+\s+\d+\s+0x18FFD7C0\s+x\s+8\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})"
)

MIN_SAMPLES = 20       # Android chunks are only ~5 s (~50 frames) long
PLATEAU_FRAC = 0.98    # samples within this fraction of the group's max current
MIN_PLATEAU_N = 15     # sustained, not a transient spike

# Android captures are split into many short _T chunks (~5 s each), so a
# per-file grouping starves the sample filters and drops whole sessions --
# including the 40 A EVSE, the widest lever arm for telling the two models
# apart. canre.utils.merge.detect_capture_groups handles both the _M#_T# and
# _T# naming conventions, so use it rather than re-deriving the prefix here.


def build_session_index(paths):
    """Map each log path to its capture-session prefix."""
    index = {}
    for prefix, plist in detect_capture_groups(sorted(paths)).items():
        for p in plist:
            index[os.path.normpath(str(p))] = prefix
    return {p: index.get(os.path.normpath(p), p) for p in paths}


def pct(vals, p):
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def main():
    # pilot duty per file
    duty_per_file = defaultdict(Counter)
    with open(PILOT_RAW, "r", errors="replace") as fh:
        for line in fh:
            mo = PILOT_RE.match(line)
            if not mo:
                continue
            duty = [int(x, 16) for x in mo.group("data").split()][2]
            if 10 <= duty <= 85:
                duty_per_file[mo.group("path")][duty] += 1

    # drawn AC current per file
    amps_per_file = defaultdict(list)
    for raw in AC_RAW:
        if not os.path.exists(raw):
            continue
        with open(raw, "r", errors="replace") as fh:
            for line in fh:
                mo = AC_RE.match(line)
                if not mo:
                    continue
                b = [int(x, 16) for x in mo.group("data").split()]
                i = (b[6] | (b[7] << 8)) * 0.05
                if 0.0 <= i <= 60.0:
                    amps_per_file[mo.group("path")].append(i)

    # Pair pilot against drawn current PER FILE, not per capture session.
    # A single capture session can span more than one EVSE: session
    # vtrux_20260714_161319 starts on a 40 A unit (duty 66) and later moves to a
    # 30 A unit (duty 49). Collapsing it hands the 30 A pilot -- which dominates
    # by sample count -- the 40 A current draw, producing a bogus negative
    # derate. Per-file keeps each pilot value next to the current it caused.
    # detect_capture_groups is still used, but only to label which session a
    # file belongs to.
    sess_of = build_session_index(set(duty_per_file) | set(amps_per_file))
    duty_by_file = duty_per_file
    amps_by_file = amps_per_file
    print("%d log files across %d capture sessions "
          "(paired per file for temporal tightness)\n"
          % (len(sess_of), len(set(sess_of.values()))))

    pairs = []
    for path, amps in amps_by_file.items():
        if path not in duty_by_file or len(amps) < MIN_SAMPLES:
            continue
        duty, _ = duty_by_file[path].most_common(1)[0]
        if len(duty_by_file[path]) > 1:
            top = duty_by_file[path].most_common(2)
            if top[1][1] > 0.2 * top[0][1]:
                continue  # pilot changed mid-session; ambiguous pairing
        adv = duty * 0.6
        imax = max(amps)
        plateau = [a for a in amps if a >= PLATEAU_FRAC * imax]
        if len(plateau) < MIN_PLATEAU_N:
            continue
        drawn = pct(sorted(plateau), 0.5)
        pairs.append((adv, drawn, len(plateau), os.path.basename(path)))

    # One representative point per advertised level: the envelope (highest
    # sustained draw seen at that level across all files). Files that were
    # tapering draw less and would bias a naive average downward.
    by_adv = defaultdict(list)
    for adv, drawn, n, name in pairs:
        by_adv[round(adv, 1)].append((drawn, n, name))

    print("=" * 92)
    print("EVSE PILOT-ADVERTISED CURRENT vs CURRENT ACTUALLY DRAWN")
    print("=" * 92)
    print("%9s %9s %9s %9s   %s" % ("advert A", "drawn A", "diff A", "ratio", "example file (n files)"))
    rowsum = []
    for adv in sorted(by_adv):
        cands = sorted(by_adv[adv], reverse=True)
        # 90th percentile of the per-file draws, not the outright max: files that
        # were tapering sit well below the limit and must not drag the estimate
        # down, but a single transient high file must not define it either.
        drawn = pct(sorted(c[0] for c in cands), 0.9)
        name = cands[0][2]
        diff = adv - drawn
        ratio = drawn / adv
        rowsum.append((adv, drawn, diff, ratio, len(cands)))
        print("%9.1f %9.1f %9.2f %9.3f   %s (%d)" % (adv, drawn, diff, ratio, name[:44], len(cands)))

    # Compare the two models over the levels where the truck was clearly limited.
    usable = [r for r in rowsum if r[0] >= 12.0]
    if len(usable) >= 3:
        xs = [r[0] for r in usable]
        ys = [r[1] for r in usable]
        n = len(xs)

        # Fit each one-parameter model by least squares over the same points, then
        # compare RMS prediction error. Comparing the scatter of the differences
        # against the scatter of the ratios directly would be meaningless -- they
        # carry different units.
        c_sub = sum(x - y for x, y in zip(xs, ys)) / n              # drawn = adv - c
        k_pct = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)  # drawn = k*adv

        def rms(pred):
            return (sum((p - y) ** 2 for p, y in zip(pred, ys)) / n) ** 0.5

        rms_sub = rms([x - c_sub for x in xs])
        rms_pct = rms([k_pct * x for x in xs])

        print("\n" + "-" * 92)
        print("MODEL COMPARISON across %d advertised levels (%.1f-%.1f A)"
              % (n, min(xs), max(xs)))
        print("-" * 92)
        print("  fixed subtraction :  drawn = advertised - %.2f A   RMS error %.2f A"
              % (c_sub, rms_sub))
        print("  fixed percentage  :  drawn = %.1f%% of advertised   RMS error %.2f A"
              % (100 * k_pct, rms_pct))
        print()
        if rms_sub < rms_pct:
            print("  -> FIXED SUBTRACTION fits better (%.2f A vs %.2f A RMS)."
                  % (rms_sub, rms_pct))
            print("     drawn ~= advertised - %.1f A" % c_sub)
        else:
            print("  -> FIXED PERCENTAGE fits better (%.2f A vs %.2f A RMS)."
                  % (rms_pct, rms_sub))
            print("     drawn ~= %.1f%% of advertised" % (100 * k_pct))

        print("\n  Predicted vs actual under each model (residual = predicted - actual):")
        print("  %9s %9s %16s %16s"
              % ("advert A", "actual A", "minus %.2f A" % c_sub, "times %.3f" % k_pct))
        for adv, drawn, _d, _r, _n in usable:
            p_sub = adv - c_sub
            p_pct = adv * k_pct
            print("  %9.1f %9.1f %16s %16s"
                  % (adv, drawn, "%.1f (%+.1f)" % (p_sub, p_sub - drawn),
                     "%.1f (%+.1f)" % (p_pct, p_pct - drawn)))

    print("\n(All qualifying file-level pairs, for reference)")
    for adv, drawn, n, name in sorted(pairs):
        print("  advert %5.1f A -> drawn %5.1f A  (diff %4.2f, ratio %.3f, n=%6d)  %s"
              % (adv, drawn, adv - drawn, drawn / adv, n, name[:50]))


if __name__ == "__main__":
    main()
