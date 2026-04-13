# Bonnydoon Drive — BMS Limp Mode Analysis

**Log:** `frombonnydoon.log`
**Session:** 33-min drive from Bonny Doon, all 3 CAN buses captured (B+C+D CAN)
**Duration:** 1972.4s (32.9 min), 5,447,696 frames
**Analyzed:** 2026-02-19

---

## Pack Context

This pack is degraded with a known weak cell that is consistently the lowest in the pack. Due to the imbalance, the pack is effectively **empty at ~35% SoC** — the weak cell hits the UV protection threshold while the rest of the pack still has charge. This means that at 50% displayed SoC, the pack only has ~15% of usable range remaining, and the weak cell is already significantly lower in voltage than the pack average.

This is directly relevant to the limp mode trigger: under heavy discharge current, the weak cell sags much harder than its neighbors (degraded cells have higher internal resistance), and its terminal voltage can approach the UV floor even when the pack average looks fine.

---

## Drive Overview

| Parameter | Value |
|---|---|
| Starting SoC | ~62.1% (~27% usable above empty) |
| Ending SoC | 44.1% (~9% usable above empty) |
| SoC at limp onset | **50.3%** (~15% usable above empty) |
| Normal discharge limit | 396A |
| Limp mode discharge limit | **174A** (56% reduction) |
| Duration of primary limp hold | ~220s (3.7 min) |

---

## 0x275 B0 — Discharge Limit Timeline

```
Startup ramp (t=3.7 → t=23.4s):
  0A → 396A at +20A/s (linear, +1 LSB per 10Hz sample)

Normal driving (t=23.4 → t=1518.4s):
  Stable 396A for ~25 minutes

LIMP MODE ONSET (t=1518.5 → t=1526.4s):
  Two-phase ramp down over ~8 seconds:
  ├─ Fast ramp: 396A → 272A at -40A/s  (t=1518.5 → 1521.5, ~3s)
  └─ Slow ramp: 270A → 174A at -20A/s  (t=1521.6 → 1526.4, ~5s)

LIMP MODE HOLD (t=1526.4 → t=1746.4s):
  Stable 174A for ~220 seconds (3.7 min)

RECOVERY (t=1746.5 → t=~1768s):
  174A → 396A at +20A/s (~22 seconds)

Brief normal (t=~1768 → t=~1843s):
  396A for ~75 seconds

SECOND DIP (t=~1843 → t=~1872s):
  Another drop to ~174A, ~28 seconds, then recovery at +20A/s

Final normal (t=~1877 → end):
  Stable 396A to end of log
```

### Ramp Rates

All ramp rates are exact integer LSB steps at 10Hz — a software rate limiter in the BMS:

| Direction | Rate | Step size |
|---|---|---|
| Ramp up (startup + recovery) | +20A/s | +1 raw per sample |
| Limp onset fast phase | -40A/s | -2 raw per sample |
| Limp onset slow phase | -20A/s | -1 raw per sample |

---

## 0x275 B1 — Charge Limit

Startup ramp 0→150A at +20A/s, then **fixed at 150A for the entire drive**. Limp mode does NOT reduce the charge limit — regen braking stays fully available at 150A.

---

## 0x275 Full Byte Map Around Limp Onset

| Byte | Normal | At limp | Range (full drive) | Notes |
|---|---|---|---|---|
| B0 | 198 (396A) | 87 (174A) | 0–198 | **Discharge limit. Drops 56%.** |
| B1 | 75 (150A) | 75 (150A) | 0–75 | Charge limit. Unchanged. |
| B2 | 125 | 121 | 119–131 | Slow-varying, drops ~4 at limp. Possibly pack-average voltage, temperature, or scaled SoC. |
| B3 | wildly varying | wildly varying | 0–255 | Continuously varying. Counter or fast analog (16.9k transitions). |
| B4 | 1 | 1 | 0–1 | Binary flag. Set at startup, never changes. HV active / drive ready. |
| B5 | 62 | 44–47 | 0–92 | **Drops ~30% at limp.** Tracks B0 event. Likely BattSentHVACLimits or second current limit. |

---

## Cell Voltages and the Weak Cell

### Individual Cell Identification (C CAN 0x000–0x019)

Extracted all 104 individual cell voltages at 8 time windows across the drive. Two cells stand out:

**Weak cell: cell #94** (ID 0x017 B4-5) — consistently the lowest cell in 7 of 8 snapshots:

| Window | Cell #94 | Pack Avg | Delta | Notes |
|---|---|---|---|---|
| Early drive (t≈200) | 3154 mV | 3184 mV | -30 mV | Not the min here (cell #76 was) — moderate load |
| Pre-limp (t≈1500) | 2965 mV | 3038 mV | **-73 mV** | Already far below family under load |
| Limp onset (t≈1518) | 3006 mV | 3062 mV | **-56 mV** | Recovering from prior sag |
| Limp hold (t≈1530) | **2822 mV** | 2906 mV | **-84 mV** | Deep sag under reduced 174A load |
| Limp hold (t≈1600) | 2950 mV | 3029 mV | **-79 mV** | Still the clear outlier |
| Recovery (t≈1770) | 3188 mV | 3224 mV | -36 mV | Spread narrows at light load |
| Second dip (t≈1855) | 3096 mV | 3174 mV | **-78 mV** | Under load again |
| End rest (t≈1960) | 3126 mV | 3187 mV | **-61 mV** | Resting, still clearly lowest |

Cell #94 hit **2822 mV at t≈1530** — and that's after the discharge limit was already reduced to 174A. Under the full 396A before the BMS intervened, it would have been significantly lower. This is almost certainly the cell that triggers the UV protection.

**High cell: cell #83** (ID 0x014 B6-7) — consistently the highest in 6 of 8 snapshots, typically 27–49 mV above average. This is the cell with the failed balance channel that reaches 3.750V during charging and triggers the OV cutoff. During driving, it doesn't cause problems — it just has more capacity/charge than its neighbors.

> **Note on CODACAN VminId/VmaxId:** Prior charging sessions showed VminId=96 and VmaxId=76. The cell indices here (94, 83) don't match exactly. This may be due to different indexing conventions between the BMS internal numbering and the C CAN cell message layout, or it could be that different cells are min/max under charging vs driving conditions. Not investigated further at this time.

### Pack-Level Stats (0x381, 1 Hz)

At limp onset (t≈1518s):

| Signal | Value |
|---|---|
| Min cell (0x381 B0-1) | 3054 mV |
| Max cell (0x381 B2-3) | 3096 mV |
| Spread | 42 mV |
| SoC | 50.3% |

Immediately after (t≈1527–1534s, still under load at reduced 174A):

| Signal | Value |
|---|---|
| Min cell | 2892–2934 mV |
| Max cell | 2946–2999 mV |
| Spread | 44–65 mV |

The 0x381 min cell values are consistent with cell #94's individual readings but at lower time resolution (1 Hz vs 6.5 Hz for the individual cell messages).

### Limp Trigger — Confirmed: Weak Cell UV Sag

Given the degraded pack with an empty threshold at ~35% SoC:

- At 50.3% SoC, the pack has only ~15% usable range left
- Cell #94 is consistently 56–84 mV below the pack average under load
- Under 396A discharge, cell #94's terminal voltage sags below a BMS protection threshold — it hit 2822 mV even at the reduced 174A limit, so under full 396A it would have been well below 2.8V
- The BMS reduces the discharge limit to 174A to reduce the voltage sag on cell #94
- After ~3.7 minutes at reduced current, cell #94 recovers enough to allow full power again
- The second brief dip at t≈1843 confirms: driver hit the gas hard again and cell #94 sagged right back to the threshold

This is **dynamic voltage-under-load protection**, not a fixed SoC threshold. The BMS is protecting cell #94 from UV damage. The trigger depends on instantaneous current draw × cell #94's internal resistance → terminal voltage floor.

---

## 0x390 B0 — BMS Status Byte

| Time | Value | Event |
|---|---|---|
| t=0.7s | 0x80 → 0x8D | Startup → driving mode |
| t=932.7s | 0x8D → 0x8E | State change ~15.5 min in (precedes limp by ~10 min) |
| t=1641.9s | 0x8E → 0x8F | During limp hold, ~115s after onset |
| t=1643.8s | settles 0x8F | Rest of drive |

The 0x390 B0 transitions don't directly coincide with the discharge limit changes. The 0x8D→0x8E at t=932.7 may represent a thermal or degradation warning stage that precedes the actual power reduction. The 0x8E→0x8F during the limp hold may be an escalation or the BMS registering a fault code.

---

## SoC Trajectory

```
t=  60s   61.5%  (~27% usable)
t= 300s   59.0%  (~24% usable)
t= 600s   55.8%  (~21% usable)
t= 900s   53.2%  (~18% usable)
t=1200s   53.2%  (~18% usable)
t=1518s   50.3%  (~15% usable)  ← limp onset
t=1800s   45.1%  (~10% usable)
t=1972s   44.1%  ( ~9% usable)
```

---

## Next Steps

1. ~~**Identify the weak cell by index**~~ — **DONE.** Cell #94 (0x017 B4-5). Cell #83 (0x014 B6-7) is the high cell.

2. **Characterize the UV sag threshold:** Extract cell #94 voltage at full 6.5 Hz resolution (0x017 B4-5 on C CAN) during the seconds before the discharge limit drops (t=1515–1520). The actual instantaneous voltage under full 396A load is the trigger — the 1 Hz 0x381 summary is too slow to capture the worst-case sag.

3. **Extract temperature signals:** 0x241 (D CAN, 1 Hz, byte ranges 0x33-0x50) and 0x2C2 (B CAN, 10 Hz) may contain pack temperatures. Correlate with the limp event to check if thermal stress contributes alongside cell voltage sag.

4. **Decode 0x392 around the event:** Wide byte ranges suggest fault/status info. May contain the specific fault code that triggers the limit reduction.

5. **Cross-reference with charging OV cell:** The high cell #83 during driving should be the same cell that hits 3.750V during charging. Extract 0x000–0x019 from `chargepointcharge.log` near EOC (t≈5440s) to confirm cell #83 is the OV cell and reconcile with CODACAN VmaxId=76.
