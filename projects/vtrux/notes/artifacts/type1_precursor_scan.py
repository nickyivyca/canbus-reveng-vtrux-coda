"""Is BMS alarm TYPE1 a reliable pre-trip warning, or is it common/benign?

The 2025-08-22 mystery failure raised TYPE1 exactly 10.2s before EPO with no other
signal moving. Truck 3 sat in TYPE1 as residue across two logs. This scan asks:

  - How often does TYPE1 appear across the log corpus?
  - When it appears, is it followed by EPO/TYPE3? Within how long?
  - Does it ever appear and then clear harmlessly?

Reuses the raw-text ID filter from fault_signature_compare.py so large BUSMASTER
files are cheap to scan.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/type1_precursor_scan.py
"""
import sys
sys.path.insert(0, ".")

import os
import glob

sys.path.insert(0, "projects/vtrux/notes/artifacts")
from fault_signature_compare import iter_watch, decode, MAINC_STAT_16  # noqa: E402

CANDIDATES = [
    "projects/vtrux/logs/full-charge-then-fail.log",
    "projects/vtrux/logs/truck3-logs/truck3-canlog.log",
    "projects/vtrux/logs/truck3-logs/truck3log2.log",
    "projects/vtrux/logs/truck3-logs/truck3-6_key_and_export.txt",
    "projects/vtrux/logs/vtruxisolationtest.log",
    "projects/vtrux/logs/vtruxinterlocktest.log",
    "projects/vtrux/logs/debuglog_M4_T20.log",
    "projects/vtrux/logs/generator-on-then-off.log",
    "projects/vtrux/logs/vtruxexportafterucsc.log",
    "projects/vtrux/logs/movingaroundindriveway.log",
    "projects/vtrux/logs/rainychargedebug2.log",
    "projects/vtrux/logs/canlog_20260216_212016.log",
    "projects/vtrux/logs/vtrux_mysterybox_unplug_export.log",
]


def scan(path):
    """Return list of alarm-state episodes and whether EPO followed."""
    episodes = []
    cur_alarm = None
    alarm_start = None
    epo_t = None
    prev_epo = 0
    saw_master = False
    tlast = 0.0

    for t, aid, d in iter_watch(path):
        if aid != 0x410:
            continue
        f = decode(aid, d)
        if not f:
            continue
        saw_master = True
        tlast = t
        a = f["alarm"]
        if a != cur_alarm:
            if cur_alarm is not None:
                episodes.append([cur_alarm, alarm_start, t])
            cur_alarm = a
            alarm_start = t
        if prev_epo == 0 and f["epo"] == 1 and epo_t is None:
            epo_t = t
        prev_epo = f["epo"]
    if cur_alarm is not None:
        episodes.append([cur_alarm, alarm_start, tlast])
    return episodes, epo_t, saw_master, tlast


print("=" * 104)
print("  TYPE1 PRECURSOR SCAN")
print("=" * 104)
print("  %-42s %-9s %-30s %s" % ("log", "dur", "alarm episodes (state @start-end)", "EPO"))
print("  " + "-" * 100)

summary = []
for p in CANDIDATES:
    if not os.path.exists(p):
        print("  %-42s MISSING" % os.path.basename(p))
        continue
    eps, epo_t, saw, dur = scan(p)
    name = os.path.basename(p)
    if not saw:
        print("  %-42s %-9s %s" % (name[:42], "-", "no BMS master in log"))
        continue
    etxt = " -> ".join("%s@%.0f-%.0fs" % (a, s, e) for a, s, e in eps)
    print("  %-42s %-9.1f %s" % (name[:42], dur, etxt[:30]))
    if len(etxt) > 30:
        print("  %-42s %-9s %s" % ("", "", etxt[30:]))
    print("  %-42s %-9s EPO: %s" % ("", "", ("t=%.3fs" % epo_t) if epo_t else "none"))
    # did TYPE1 lead to EPO?
    for a, s, e in eps:
        if a == "TYPE1" and epo_t is not None and s <= epo_t:
            summary.append((name, epo_t - s, s, epo_t))
    print()

print("=" * 104)
print("  TYPE1 -> EPO LEAD TIMES")
print("=" * 104)
if not summary:
    print("  none")
for name, lead, s, epo in summary:
    print("  %-44s TYPE1 at t=%9.3f  EPO at t=%9.3f   lead = %8.3fs" % (name[:44], s, epo, lead))
