import sys
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

DBC = "projects/vtrux/epri-pt-bus.dbc"
LOGDIR = "../../CANLogs/VtruxLogs"
CHUNKS = [
    "vtrux_20260617_193900_T0.log",
    "vtrux_20260617_193900_T1.log",
    "vtrux_20260617_193900_T2.log",
]

db = cantools.database.load_file(DBC)

WATCH = {
    "EPRI_BCM_Status_0410": ["bcm_ready", "bcm_epo", "bcm_mainc_stat", "bcm_chgc_stat", "bcm_alarm"],
    "EPRI_BCM_Data2_0440": ["bcm_fault_mon", "bcm_mainc_stat", "bcm_mod_ena", "bcm_balancing_cnt"],
    "EPRI_OperatingMode_0053": ["OperationState", "OperationMode"],
    "EPRI_ParkLock_055C": ["parkLockState"],
    "EPRI_HCU_Sensor_0592": ["EVSESwitchState", "ExportPowerState", "IgnitionKeyState"],
    "EPRI_HCU_DTC_065B": None,  # all signals
}

msgs = {}
id2name = {}
for name in WATCH:
    m = db.get_message_by_name(name)
    msgs[name] = m
    id2name[m.frame_id & 0x7FF] = name

soc_msg = db.get_message_by_name("EPRI_BCM_Status_0410")
soc_id11 = soc_msg.frame_id & 0x7FF

soc_track = []  # (t, soc)
last_val = {}   # (msgname, sig) -> value
transitions = []  # (t, msgname, sig, old, new)
first_t = None

def soc_at(t):
    if not soc_track:
        return None
    lo = soc_track[0][1]
    for tt, v in soc_track:
        if tt > t:
            break
        lo = v
    return lo

for fn in CHUNKS:
    for fr in parse_file(f"{LOGDIR}/{fn}", absolute=True):
        key = fr.arbitration_id & 0x7FF
        if key not in id2name:
            continue
        name = id2name[key]
        m = msgs[name]
        try:
            dec = m.decode(fr.data, decode_choices=False, allow_truncated=True)
        except Exception:
            continue
        if first_t is None:
            first_t = fr.timestamp
        if key == soc_id11 and "bcm_soc" in dec:
            soc_track.append((fr.timestamp, dec["bcm_soc"]))
        wanted = WATCH[name]
        if wanted is None:
            wanted = list(dec.keys())
        for sig in wanted:
            if sig not in dec:
                continue
            v = dec[sig]
            k = (name, sig)
            if k in last_val and last_val[k] != v:
                transitions.append((fr.timestamp, name, sig, last_val[k], v))
            last_val[k] = v

t0 = first_t
print(f"first_t set. soc samples={len(soc_track)} transitions={len(transitions)}")

# --- bcm_fault_mon blink envelope: find pulses (value==1) and detect when blinking stops ---
pulses = [t for t, name, sig, old, new in transitions
          if sig == "bcm_fault_mon" and new == 1]
print("\n=== bcm_fault_mon BLINK analysis ===")
if pulses:
    print(f"  total high-pulses: {len(pulses)}")
    print(f"  first pulse t={pulses[0]-t0:.1f}s soc={soc_at(pulses[0])}")
    print(f"  last  pulse t={pulses[-1]-t0:.1f}s soc={soc_at(pulses[-1])}")
    print("  inter-pulse gaps > 3s (blink pauses / stop):")
    for i in range(1, len(pulses)):
        gap = pulses[i] - pulses[i-1]
        if gap > 3.0:
            print(f"    gap {gap:.1f}s : last blink t={pulses[i-1]-t0:.1f}s soc={soc_at(pulses[i-1])} "
                  f"-> next t={pulses[i]-t0:.1f}s soc={soc_at(pulses[i])}")
    # blink rate over time (pulses per 30s bucket) with soc
    print("  blink rate per 30s window (window: count, soc_at_window_start):")
    import math
    end = pulses[-1] - t0
    buckets = {}
    for p in pulses:
        b = int((p - t0) // 30)
        buckets[b] = buckets.get(b, 0) + 1
    for b in sorted(buckets):
        wt = t0 + b*30
        print(f"    [{b*30:4d}-{b*30+30:4d}s] pulses={buckets[b]:3d} soc={soc_at(wt)}")

# bcm_balancing_cnt is noisy analog-ish; collapse repeated micro-toggles by reporting only signals of interest
print("\n=== NON-fault_mon discrete transitions (t, soc, signal: old->new) ===")
for t, name, sig, old, new in transitions:
    if sig in ("bcm_balancing_cnt", "bcm_fault_mon"):
        continue
    print(f"  t={t-t0:7.1f}s soc={soc_at(t)!s:>5}  {name}.{sig}: {old} -> {new}")

print("\n=== balancing_cnt transitions (summary) ===")
bc = [(t, old, new) for t, name, sig, old, new in transitions if sig == "bcm_balancing_cnt"]
if bc:
    print(f"  {len(bc)} changes; first @ t={bc[0][0]-t0:.1f}s soc={soc_at(bc[0][0])}, "
          f"last @ t={bc[-1][0]-t0:.1f}s soc={soc_at(bc[-1][0])}")
    vals = sorted(set([x[2] for x in bc]))
    print(f"  value range: {min(vals)}..{max(vals)}")

print("\n=== first observed value of each watched signal ===")
seen = {}
for (name, sig), v in last_val.items():
    pass
# re-walk for first values
firstv = {}
for fn in CHUNKS:
    for fr in parse_file(f"{LOGDIR}/{fn}", absolute=True):
        key = fr.arbitration_id & 0x7FF
        if key not in id2name:
            continue
        name = id2name[key]
        m = msgs[name]
        try:
            dec = m.decode(fr.data, decode_choices=False, allow_truncated=True)
        except Exception:
            continue
        wanted = WATCH[name] or list(dec.keys())
        for sig in wanted:
            if sig in dec and (name, sig) not in firstv:
                firstv[(name, sig)] = dec[sig]
    break  # first chunk enough for initial values
for (name, sig), v in sorted(firstv.items()):
    print(f"  {name}.{sig} initial = {v}")
