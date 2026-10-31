"""Census of VCM outages (0x400 heartbeat gaps) across the June 2026 Android sessions.

Purpose: decide whether the 2026-06-18 00:21:26 VCM silence (which caused the AC 10 01
EPO) looks like the owner pulling the Via-side 12V fuses to reset a fault -- something
that was being done around the smog-test work -- or a spontaneous VCM failure. A
deliberate fuse pull should appear as a VCM outage with the truck stationary; if such
outages exist, their signature (0x053 FAILURE first? GENE e-stop flag? abrupt?) can be
compared with the trip's.

Input: per-file extracts made with
  grep -HE " 0x(400|53|54|3E9|1F1|592|410) |START DATE AND TIME" <log>
(one extract file per log chunk, in a directory given as argv[1]).

For each chunk:
  * PT channel = the channel carrying DLC-8 0x410
  * every 0x400 gap > 0.3 s (plus leading/trailing absence while 0x410 is present)
    -> time, gap length, BMS awake during gap?, speed just before, 0x053 states in the
       1.5 s before, GENE e-stop flag before, key state (0x592 bit4, GM 0x1F1 run/crank)
       before and at revival, bcm_epo transition after, first 0x400 B0 at revival
  * every 0x592 IgnitionKeyState 1->0: how long 0x400 keeps going afterwards (normal
    key-off behaviour of the VCM)

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/vcm_outage_census.py <extract_dir> > projects/vtrux/notes/artifacts/vcm_outage_census.txt
"""
import sys
sys.path.insert(0, ".")

import glob
import os
import re
from collections import defaultdict

OPSTATE = {0: "INIT", 1: "STBY", 2: "ACTIVATION", 3: "DEACTIVATION", 4: "OPERATIONAL", 5: "FAILURE", 6: "SHTDWN", 7: "WAIT4COOLING", 8: "PWR_OFF_RDY"}
LINE = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s*(.*)$")
HDR = re.compile(r"START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+):(\d+)")


def chunk_key(path):
    m = re.search(r"(vtrux_\d{8}_\d{6})_T(\d+)", path)
    return (m.group(1), int(m.group(2))) if m else (path, 0)


def load(path):
    frames = []
    hdr = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            _, _, rest = raw.partition(".log:")
            if not rest:
                rest = raw
            if rest.startswith("***"):
                m = HDR.search(rest)
                if m and hdr is None:
                    d, mo, y, hh, mm, ss, ms = (int(x) for x in m.groups())
                    hdr = hh * 3600 + mm * 60 + ss + ms / 1000.0
                continue
            m = LINE.match(rest)
            if not m:
                continue
            hh, mm, ss, tk, ch, idh, dlc, data = m.groups()
            t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
            try:
                b = bytes(int(x, 16) for x in data.split()[: int(dlc)])
            except ValueError:
                continue
            frames.append((t, int(ch), int(idh, 16), b))
    return hdr, frames


def hms(sec):
    sec = sec % 86400
    return "%02d:%02d:%06.3f" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def last_before(lst, t, lo=-1e9):
    r = None
    for tt, v in lst:
        if tt > t:
            break
        if tt >= lo:
            r = (tt, v)
    return r


def first_after(lst, t, hi=1e9):
    for tt, v in lst:
        if tt >= t:
            return (tt, v) if tt <= hi else None
    return None


def census(path):
    hdr, frames = load(path)
    if not frames:
        return
    sess, ci = chunk_key(path)
    t_end = frames[-1][0]
    ch410 = defaultdict(int)
    for t, ch, aid, b in frames:
        if aid == 0x410 and len(b) == 8:
            ch410[ch] += 1
    if not ch410:
        print("%s_T%d: no PT bus (no DLC-8 0x410)" % (sess, ci))
        return
    pt = max(ch410, key=ch410.get)
    f400 = [(t, b) for t, ch, aid, b in frames if ch == pt and aid == 0x400 and b]
    f410 = [(t, b) for t, ch, aid, b in frames if ch == pt and aid == 0x410 and len(b) == 8]
    f53 = [(t, OPSTATE.get(b[0] & 0xF, b[0] & 0xF)) for t, ch, aid, b in frames if ch == pt and aid == 0x53 and b]
    f54 = [(t, (b[4] >> 3) & 1) for t, ch, aid, b in frames if ch == pt and aid == 0x54 and len(b) >= 5]
    f592 = [(t, (b[0] >> 4) & 1) for t, ch, aid, b in frames if ch == pt and aid == 0x592 and b]
    f3e9 = [(t, ((b[0] & 0x7F) << 8 | b[1]) * 0.0156) for t, ch, aid, b in frames if ch != pt and aid == 0x3E9 and len(b) >= 2]
    f1f1 = [(t, (b[0] >> 3) & 1) for t, ch, aid, b in frames if ch != pt and aid == 0x1F1 and b]
    epo = [(t, (b[0] >> 1) & 1) for t, b in f410]

    events = []
    if f400:
        if f410 and f400[0][0] - f410[0][0] > 0.3:
            events.append(("lead", f410[0][0], f400[0][0] - f410[0][0]))
        for (t0, _), (t1, _) in zip(f400, f400[1:]):
            if t1 - t0 > 0.3:
                events.append(("gap", t0, t1 - t0))
        if t_end - f400[-1][0] > 0.3:
            events.append(("tail", f400[-1][0], t_end - f400[-1][0]))
    elif f410:
        events.append(("none", f410[0][0], t_end - f410[0][0]))

    for kind, t0, g in events:
        t1 = t0 + g
        awake = any(t0 + 0.1 < t < t1 - 0.1 for t, _ in f410)
        n410 = sum(1 for t, _ in f410 if t0 < t < t1)
        sp = last_before(f3e9, t0)
        states = []
        for t, s in f53:
            if t0 - 1.5 <= t <= t0 and (not states or states[-1] != s):
                states.append(s)
        est = [v for t, v in f54 if t0 - 1.5 <= t <= t0]
        key_b = last_before(f592, t0)
        key_a = first_after(f592, t1 - 0.05, t1 + 5)
        run_b = last_before(f1f1, t0)
        run_a = last_before(f1f1, t1)
        e_after = None
        prev = None
        for t, v in epo:
            if t0 - 0.05 <= t <= t1 + 0.5 and prev == 0 and v == 1:
                e_after = t - t0
                break
            if t >= t0 - 0.05:
                prev = v
        b0_after = first_after(f400, t1 - 0.001, t1 + 1)
        absr = hms(hdr + t0) if hdr is not None else "?"
        print("%s_T%d  %-4s t=%8.3f (%s)  silent %6.2f s  BMS-awake=%s(%d x0x410)  speed=%s km/h  0x53[-1.5s]=%s  gene_estop[-1.5s]=%s  key592 before=%s after=%s  GM_run before=%s at-revival=%s  bcm_epo0->1 after=%s  0x400@revival=%s"
              % (sess, ci, kind, t0, absr, g, awake, n410,
                 ("%.0f" % sp[1]) if sp else "-",
                 ">".join(states) if states else "-",
                 ("%d..%d" % (min(est), max(est))) if est else "-",
                 key_b[1] if key_b else "-", key_a[1] if key_a else "-",
                 run_b[1] if run_b else "-", run_a[1] if run_a else "-",
                 ("%+.3f" % e_after) if e_after is not None else "-",
                 ("0x%02X" % b0_after[1][0]) if b0_after else "-"))

    prev = None
    for t, v in f592:
        if prev == 1 and v == 0:
            l400 = last_before(f400, t + 120)
            after = (l400[0] - t) if l400 else None
            n = sum(1 for tt, _ in f400 if t < tt <= t + 120)
            print("%s_T%d  keyoff(0x592 1->0) t=%8.3f (%s)  0x400 continues for %s s (%d frames in next 120 s)  BMS 0x410 frames next 120 s: %d"
                  % (sess, ci, t, hms(hdr + t) if hdr is not None else "?", ("%.1f" % after) if after is not None else "-", n,
                     sum(1 for tt, _ in f410 if t < tt <= t + 120)))
        prev = v


paths = sorted(glob.glob(os.path.join(sys.argv[1], "*.txt")), key=chunk_key)
for p in paths:
    census(p)
print("CENSUS DONE (%d chunks)" % len(paths))
