# DLCM DTCs — how they are stored, set, and which are visible on the bus

Investigation 2026-09-23/24/25, against `coda_dlcm_prog.bin` / `coda_dlcm_cal.bin`
under `tricore:LE:32:default` (Ghidra project `dlcm_tricore`).

**Question that started it:** a post-flash DTC read on 2026-09-23 returned seven DLCM
codes, and the in-car session needed to know whether `P3115`
("System safety critical disable Drive Line Control Module fault level 2") could have been
caused by the gradient-limiter CAL edit. That is answered — it cannot, structurally — and
the work generalised into a map of the whole DLCM fault subsystem.

**Everything below was reviewed in conversation before being written here.** Claims whose
role is inferred rather than demonstrated are labelled **hypothesis** inline; those are
recorded as hypotheses, not findings.

---

## 1. The three DEM tables

The DLCM's fault handling is an AUTOSAR-style DEM: one reporter, one static config table
per event, one RAM status record per event, and a separate table mapping events to SAE
codes. Found by call census (`ghidra/scripts/DlcmCallCensus.java`), on the reasoning that
the event reporter must be among the most-called functions in the image and must take a
small constant event id at nearly every call site.

| Table | Address | Layout |
|---|---|---|
| Event reporter | `FUN_8007F6C8` | `(eventId, testResult, enable, clearGate, debounceSel)`; `if (eventId > 0x7F) return` |
| Per-event RAM status | `0xD000727E` (`a0-0x1D82`) | 6 B/event: `[0]` debounce counter, `[1]` status bits |
| Per-event CAL config | `0xA0023FB4` (CAL off `0x3FB4`) | 8 B/event, 128 events |
| Event -> DTC | `0xA002451E` (CAL off `0x451E`) | 6 B/event, 128 events |

`a0 = 0xD0009000` throughout (small-data base, per the Architecture section of
`coda-dlcm-decompile-notes.md`).

### 1a. Event -> DTC table, `0xA002451E`

**All 128 records decode to valid DLCM SAE codes: 0 mismatches, 0 blanks**, scored against
the 104 DLCM rows of `coda-diagnostics/coda_dtc_list.csv`. That is what establishes the
table; it was found by brute-forcing stride and field offsets and maximising DLCM-list
matches, rather than by eye — this firmware has already produced two wrong table readings
that looked structurally plausible (see the boxed warning in
`dlcm-security-access.md` §1b).

Record is 6 bytes with the DTC high and low bytes two apart. **Caveat:** four candidate
phases score 128/128 because they are shifts of the same data; the record origin is not
yet pinned from the indexing code. The **event -> DTC mapping is identical across all four**,
so the map is safe to use; the exact field offsets within the record are not settled.

Several DTCs map from more than one event — the firmware has multiple independent monitors
that report the same customer-visible code. Codes seen on this car:

| DTC | Event id(s) | Debounce (`b0`) per event |
|---|---|---|
| `C0044` Brake switch fault open | 8 | 100 |
| `C2100` Key Interlock Solenoid | 24, 25 | 100, 100 |
| `P0A05` Coolant Pump Loss | 36 | 100 |
| `P3103` BMS exited HV while running | 42 | 100 |
| `U0110` Lost Comms with MCM | 86, 87, 88, 89 | 253, 253, 253, 100 |
| `P3114` / `P3115` / `P3116` safety critical disable | 125 / 126 / 127 | 0 / 0 / 0 |

### 1b. Per-event CAL config, `0xA0023FB4`

| Byte | Meaning |
|---|---|
| `b0` | Primary debounce threshold. **`0xFF` = event disabled** — the reporter then forces status `0x10` (notCompletedSinceClear) and returns. |
| `b1` | Secondary threshold. 100 for every event except id 89 (250). **Hypothesis:** a second debounce limit; not demonstrated. |
| `b2` | `0x10` for all 128 events. Read as `b2 & 1`, which is therefore always 0. |
| `b3` | `0`, `1` or `2`. **Role unknown.** It is *not* established to be the P3114/P3115/P3116 fault-level selector — that selector is the reason code in §2, and `b3` was checked against it and does not correspond. |

15 events are disabled (`b0 = 0xFF`): ids 10, 11, 12, 13, 15, 18, 23, 26, 29, 35, 40, 72,
102, 103, 107.

`P3114`/`P3115`/`P3116` are the only events with `b0 = 0`; every other event is
100/200/250/253/255. **What threshold 0 does to the state machine is not established** —
the debounce logic has several paths and they were not all walked. It is recorded here only
as "these three are configured unlike anything else".

### 1c. Helpers

- `FUN_8007FAD8(eventId)` — sets a bit in a 128-bit "newly confirmed" bitmap at
  `0xD0006B54` (`a0-0x24AC`).
- `FUN_8007F9A6(eventId)` — returns whether status bit `0x08` (confirmed) is set.
- `FUN_80082EAA` — **not** a fault reporter despite having 199 callers and 2093 call sites.
  It is the safety trap / panic handler, called on every failed redundancy check. Its call
  count is why it topped the census; it takes no event id.

---

## 2. P3115 is a roll-up with no detection of its own

**This is the answer to the question that started the investigation.**

Across all 118 call sites of `FUN_8007F6C8`, the constant event ids stop at **124**. Ids
125, 126 and 127 are never reported by any monitor. `P3115` is set in exactly one place,
`FUN_8005ABAC`:

```c
ok = (mode != 2)                                          // mode from FUN_8008C766
  && (u16 @0xD001086A == (u16 @0xD001086C ^ 0xFFFF))      // value + inverted copy
  && (u8  @0xD001086E == (u8  @0xD001086F ^ 0xFF));
if (ok && code != 0 && code < 0x11)
    report(code == 4 || code == 0xD || code == 0x10 ? 127 /*P3116*/
                                                   : 126 /*P3115*/, failed = 1);
```

So `P3115` means "an internal safety-disable reason code in 1..16 is currently non-zero",
with reasons 4, 13 and 16 diverted to `P3116`. Note the failure mode of the integrity
guard: if the value and its inverted copy disagree the reason is forced to 0 and **nothing
is reported**, so corruption suppresses the DTC rather than setting it.

`P3115` is **not** a roll-up of other DTCs. `C0044`, `P0A05`, `C2100` and `U0110` are DEM
events that write the DEM status array; the 16 reason flags are a separate mechanism that
never consults DEM status. None of the codes seen on the car on 2026-09-23 fed `P3115`.

### 2a. The reason code

Published by `FUN_8005688C` from an internal pair (`0xD0008634` / `0xD000863A` inverted,
plus `0xD0008642` / `0xD0008652`) into the pair `FUN_8005ABAC` reads. `FUN_8005592A` is a
redundancy-checked copier in the other direction. Assigned by **`FUN_800561E0`**, a flat
priority if/else chain — first flag that reads 1 wins:

| Reason | Flag | -> DTC | | Reason | Flag | -> DTC |
|---|---|---|---|---|---|---|
| 1 | `0xD000834F` | P3115 | | 9 | `0xD00085CA` | P3115 |
| 2 | `0xD000834D` | P3115 | | 10 | `0xD0008554` | P3115 |
| 3 | `0xD000874F` | P3115 | | 11 | `0xD0008555` | P3115 |
| 4 | `0xD000874C` | **P3116** | | 12 | `0xD000868A` | P3115 |
| 5 | `0xD00085A4` | P3115 | | 13 | `0xD000868B` | **P3116** |
| 6 | `0xD00083EC` | P3115 | | 14 | `0xD000868C` | P3115 |
| 7 | `0xD00083ED` | P3115 | | 15 | `0xD000868D` | P3115 |
| 8 | `0xD00083EE` | P3115 | | 16 | `0xD000868E` | **P3116** |

Every flag is stored with an inverted copy and every read is integrity-checked; a mismatch
calls `FUN_80082EAA`. **What each flag individually means is not known** — only where each
is written.

### 2b. Which function writes each reason flag

Recorded 2026-10-03 because it existed only in `~/ghidra-projects/dlcm_export/safety_flags.txt`,
which is machine-local and does not sync. Produced by
`DlcmA0RefScan.java <out> cb1,cb3,a5c,c14,c13,c12,a36,aac,aab,976,975,974,973,972` and a
second run with `8b1,8b4` for reasons 3 and 4, then filtered per exact offset. This is a
reference measurement, not an interpretation.

Five functions touch nearly every flag and are the **redundancy copiers / initialisers**,
not detectors: `FUN_80055AA0`, `FUN_80055C92`, `FUN_80055EC4`, `FUN_80055FD0`,
`FUN_8005D1B4` (plus `FUN_800561E0` itself, and the per-subsystem publishers
`FUN_8005ACF0`, `FUN_8005B470`, `FUN_8005BD40`, `FUN_8005C628`, `FUN_8005C99C`).
Subtracting those leaves, for each flag, the functions **unique** to it:

| Reason | Flag | Unique writer(s) — **candidate detectors (hypothesis)** |
|---|---|---|
| 1 | `0xD000834F` | `FUN_8004673A` |
| 2 | `0xD000834D` | `FUN_8004722E` |
| 3 | `0xD000874F` | `FUN_80058AE2` |
| 4 | `0xD000874C` | `FUN_8005A450` |
| 5 | `0xD00085A4` | `FUN_8005277E`, `FUN_80052BD6` |
| 6 | `0xD00083EC` | `FUN_80049B6C`, `FUN_80049B86` |
| 7 | `0xD00083ED` | `FUN_8004B446`, `FUN_8004B612` |
| 8 | `0xD00083EE` | `FUN_8004D6AA` |
| 9 | `0xD00085CA` | `FUN_80053B28`, `FUN_80053C8A` |
| 10 | `0xD0008554` | `FUN_8004EEA2`, `FUN_8004F016` |
| 11 | `0xD0008555` | `FUN_80050246`, `FUN_80050980` |
| 12 | `0xD000868A` | `FUN_80056C20`, `FUN_80056DC2` |
| 13 | `0xD000868B` | `FUN_8005777A` |
| 14 | `0xD000868C` | `FUN_80056C20` |
| 15 | `0xD000868D` | `FUN_80057CDE` |
| 16 | `0xD000868E` | `FUN_80057CDE` |

**Hypothesis:** the unique writer of a flag is its detector, and the shared ones only copy
and integrity-check it. **Confirmed for reasons 1, 2, 3 and 4** by decompiling them
(§2d). Still unverified for reasons 5-16, though they were found by the same method and
`FUN_8006F110` (the `C0044` detector, §3) has the same shape.

An earlier revision of this section said reasons 3 and 4 had no writer because Ghidra
renders them as absolute `DAT_d000874f` / `DAT_d000874c` and the A0 scanner was therefore
blind to them. **That explanation was wrong.** The offsets for those two flags
(`a0-0x8B1` and `a0-0x8B4`) were simply never passed to the scanner — the list above covers
14 of the 16 flags and omits exactly those two. Passing `8b1,8b4` finds the writers at once.
Both flags *are* also reachable absolutely, because the copier band addresses them through a
second base `a15 = 0xD0010000` (`a15-0x78B1` is the same byte as `a0-0x8B1`), which is why
only the copiers appeared in an absolute-reference scan. See §10 for the scanner trap this
exposed.

All of the above lie in `0x80046000`-`0x8005D000` and root in `FUN_800463B8` /
`FUN_80046484` — which is what §2c's exclusion of the torque path rests on.

### 2c. The gradient limiter cannot set P3115

Every one of the 16 flags was traced to its writers. They all lie in
**`0x80046000`-`0x8005D000`** and root in one supervisor tree (`FUN_800463B8` /
`FUN_80046484`). The §11.7 gradient limiter is `FUN_80075DFA` at `0x80075xxx`
(`dlcm-torque-limiter-code-trace.md`). **No writer of any safety flag is anywhere in the
torque path, and no torque-rate or requested-vs-delivered plausibility monitor feeds this
chain.**

This is a structural result, so it is stronger than the behavioural evidence and
independent of it: `P3115` also did not return after a clear plus a full drive cycle on the
FLOOR40 calibration (`artifacts/dtcs_after_drive2_20260923.log`). Raising the gradient
tables cannot reach `P3115`, and neither can the planned negative-side edit.

`P3114` (event 125) is **never set by `FUN_8005ABAC`**. Unexplained; open.

### 2d. What the reason-flag detectors actually do

Reasons 1, 2, 3 and 4 were decompiled 2026-10-03. Raw output is machine-local in
`~/ghidra-projects/dlcm_export/reason_detectors_12.txt` and `reason34_detectors.txt`; the
load-bearing content is reproduced here. All four confirm the §2b hypothesis that the
unique writer is the detector.

**All four share one idiom**, which matters because it makes the remaining twelve cheap to
read:

1. every protected variable is held as a value **plus its ones-complement mirror**, and is
   checked against that mirror on each use; a mismatch calls `FUN_80082EAA` (the safety
   trap, §1c) and does not return.
2. a fault condition is evaluated from the checked inputs.
3. a **symmetric up/down debounce counter** is incremented while the condition holds and
   decremented while it does not, saturating at a CAL maximum and at zero.
4. the flag is set to 1 only at the counter maximum and cleared to 0 only at zero —
   **in between it is left unchanged**. This is hysteresis, not a threshold: the flag
   latches, and healing costs the full count.
5. the body is bracketed by a **control-flow sequence token** at `0xD0006BD8`, written and
   compared against PROG constants at entry and exit (`DAT_80040a7a`..`7d` for reason 1,
   `DAT_80040a91`..`9d` for reason 2), so a skipped or re-ordered call is detectable.

`FUN_8006F110`, the `C0044` detector (§3), has this same shape, so the idiom is used across
the module and is not specific to the safety chain.

#### Reason 1 — `FUN_8004673A`

A **difference comparator between two redundant signals**, each s16 with its own mirror:

| Address | Mirror | Role |
|---|---|---|
| `0xD000830A` | `0xD0008324` | signal A, s16 |
| `0xD0008316` | `0xD0008328` | signal B, s16 |
| `0xD0008334` | `0xD0008336` | debounce counter, u16 |
| `0xD000834F` | `0xD0008350` | the reason-1 flag |

It computes `mag = |satS16(A - B)|` (saturating, with `-0x8000` mapped to `0x7FFF`), then
`mag > threshold` drives the counter up and `mag <= threshold` drives it down.

##### Where A and B come from

Traced 2026-10-04. `FUN_80046484` is the capture function that fills the ECM2 monitor-input
block, and it is where both operands are written:

| Monitor input | Written from | I/O channel |
|---|---|---|
| `a0-0xcf8` | `FUN_8007C680()` | 7 |
| **`a0-0xcf6` = signal A** | **`FUN_8007C68C()`** | **10** |
| `a0-0xcf2` | `FUN_8007C6C4()` | 12 |
| `a0-0xcf4` | `FUN_8007C6B6()` | 13 |
| **`a0-0xcea` = signal B** | **`(uint)*(byte *)(a0-0x1a70) * 0x80`** | none — see below |

**Signal A is the accelerator pedal's channel-2 raw ADC value (confirmed).** I/O channel 10
is the channel whose CAL span is `0xA00212B2` = 2881 (low) / `0xA00212B0` = 14076 (high),
identified in `plans/dlcm_reflash_7_8_clunk_and_regen_floor.md` as APP channel 2; channel 7
is APP channel 1, span `0xA00212AA` = 5565 / `0xA00212A8` = 29134. So the units of the 3274
threshold are **channel-2 ADC counts**, i.e. 29.2% of that channel's 11,195-count span.

Signal B is **not** read from an I/O channel. It is a single byte at `0xD0007590`
(`a0-0x1a70`) multiplied by 128, captured into the monitor block by `FUN_80069D24` (which is
the only other consumer of that byte besides reason 1 itself). The 128 multiply makes one
count of the byte worth 1.14% of channel 2's span.

##### The byte arrives over an inter-node serial link, on the receive side

All of the following is measured, not inferred:

- `FUN_8005FFF2` fills the six bytes at `a0-0x1a74 .. a0-0x1a6f` from the **indexed signal
  pool** (§7's mechanism): `FUN_80064574(dst, 0x2000, 1)` then
  `FUN_80064574(dst+2, 0x2080, 5)`, then narrows the six u16 slots to bytes.
- The pool's static configuration is the argument of `FUN_8008E484`, at PROG `0x80042E4C`.
  Walking it (`artifacts/sigB_pool_record.py`) gives two banks; bank 1 (`0x80042E24`,
  node 1) has three records, and record 1 is **slots 1..6, six 8-bit elements** — exactly
  the read above. Ids `0x2000`, `0x2080` and `0x2085` all resolve consistently with the
  firmware's literal call arguments.
- **The pool keeps separate transmit and receive arrays for the same id.**
  `FUN_8008E3DC` performs *two* `FUN_8008EEE4(nElem << 1, 4)` allocations, storing them at
  `desc+0x10` and `desc+0x14`. `FUN_80064520` (write) uses `desc+0x10`; `FUN_80064574`
  (read) uses `desc+0x14`.
- Which of the two is incoming is settled by the ISR. `FUN_800640F6` passes `desc+0x10` to
  `FUN_80064758` and `desc+0x14` to `FUN_80064796`, which write translated addresses to
  `0xF0003C90 + ch*4` and `0xF0003C94 + ch*4` — a DMA source/destination register pair.
  **`desc+0x14`, the array reason 1's byte is read from, is the destination: the receive
  side.**

So the byte is produced by the device on the far end of the link, and the producing code is
not in this image.

##### Integrity layout of the received block

| Byte | Address | Protection |
|---|---|---|
| b0 | `0xD000758C` | mode code; compared against the protected state enum (below) |
| b1 | `0xD000758D` | odd parity, checked by `FUN_8005FDFA` -> `FUN_8008FD6E` |
| b2 | `0xD000758E` | odd parity, checked by `FUN_8005FDFA` |
| b3 | `0xD000758F` | none; unused by any traced reader |
| **b4** | **`0xD0007590`** | **none — signal B's source** |
| b5 | `0xD0007591` | `b0^b1^b2^b3^b4`, checked by `FUN_8005FDD8` |

b4 is covered by the block XOR but is the **only payload byte with no parity bit of its
own**, which is what a raw measurement needing its full 8 bits of range would look like.

`0xD0006BE5` (`a0-0x241b`) is the protected state enum b0 is checked against: legal values
`{0x3B, 0x92, 0xAD, 0xC7, 0xF1}`, **all five of odd parity**, so it is a Hamming-protected
mode variable; `0x3B` is the degraded value. ~19 functions consult it. `FUN_80068E68` does
the comparison and reports `1`, `2`, `3` or `0x17` on mismatch, with up/down counters at
`a0+0x784e` / `a0+0x784f` (+2 / -1, cap 6).

**Trap, recorded because it is convincing and wrong.** `FUN_80082DE0`'s arguments `1`, `2`,
`3` look like DEM event ids, and events 1-3 are `P0120`/`P0121` *accelerator pedal* faults —
apparently decisive confirmation of the pedal reading. `FUN_80082DE0` is **not** the DEM
reporter (`FUN_8007F6C8`). It masks its argument `& 0x1f`, forces `a0-0x241b` to `0x3B`,
bumps a saturating counter at `a0+0x784a` and stores the masked code at `a0+0x784c` with a
mirror. Those are subsystem-local codes in a different namespace. Event 23 is also one of
the 15 disabled events (§1b), which would have been a second inconsistency.

**`FUN_8005FE16` describes the transmit side, not signal B.** It masks the staging bytes at
`a0-0x1a7a+1..+4` per mode variant (`0x3B`: `&0x7f, &0x4f, 0, 0`; `0x92`: `&0x7f, &0x0f,
&0x78`, then `b4 = ~b3`; `0xAD`: `&0x7f`, passthrough, `0`, `0`; `0xC7`: `&0xe0, 0`,
passthrough, passthrough), sets odd parity, packs five u16 plus an XOR and calls
`FUN_80064520(local, 0x2080, 6)` / `FUN_800645C8(0x2080)` — all into `desc+0x10`. Its
`b4 = ~b3` is a property of what the DLCM *sends*, and says nothing about the byte it
receives. `FUN_80084E0C` writes an all-zero default (PROG `0x800444EC`, verified zero) with
staging code `0xF1` — a clear/disable path.

##### Hypothesis: b4 carries accelerator-pedal channel 1, scaled

**This is a hypothesis, not a traced assignment** — the code that produces b4 is on the far
side of the link.

The argument is that reason 1 is ungated and demonstrably does not trip in normal driving
(§2c: `P3115` did not return after a clear plus a full drive cycle), so
`|ch2_raw - b4*128| <= 3274` must hold across the entire pedal travel. That is a strong
constraint, and `artifacts/sigB_pool_record.py` phase 3 tests the candidates against the
CAL spans:

| candidate for b4 | worst `|A-B|` over travel | verdict |
|---|---|---|
| `ch1_raw >> 8` | 468 | fits, 7.0x margin |
| `ch2_raw >> 7` | 127 | fits, 25.8x margin |
| `ch1_raw >> 7` | 14980 | **trips** at 100% pedal |
| constant 0 (record zeroed / link dead) | 14076 | **trips** at 100% pedal |

`ch1_raw >> 8` works because channel 1's slope is about twice channel 2's (ratio 1.932 at
the low end, 2.070 at the high end), so a shift of 8 followed by the `*128` multiply is a
divide-by-two that lands the value back in channel 2's domain. The residual is flat across
travel: 193 counts at 0% pedal, 98 at 50%, 388 at 100%. §5.5 of
`artifacts/dlcm_functional_requirements_full.md` says the pedal "has two separate position
sensors with **different slopes**" and that the DLCM checks each "not plausible with the
other signal", which is the check this would be.

`ch2_raw >> 7` fits the arithmetic with a larger margin but is rejected on architectural
grounds, not numeric ones: it would compare a channel against a quantized copy of itself,
which is not a redundancy check.

**So reason 1 is, hypothetically, the ECM2 accelerator-pedal two-channel plausibility
monitor** — channel 2 measured locally against channel 1 delivered as one byte over the
inter-node link, consistent with §13.4.9's "ECM2 takes its CAN signals prior to any scaling
from ECM1" and with APP being named as an ECM2 input in §13.5.

Deliberately **not** asserted: the identity of the link peripheral. Its node registers sit
at `0xF0100100 + node*0x100` while this image's CAN driver uses message objects at
`0xF010C000`, and the offsets do not fit a node-register map that could be named without
guessing.

#### Reason 2 — `FUN_8004722E`

Not a difference check. Three **pairs** of flags are tested, each of the form
`(validated == 0 && raw != 0)`, and the results combined:

| Pair | "validated" | mirror | "raw" | mirror |
|---|---|---|---|---|
| A | `0xD0008347` | `0xD0008354` | `0xD0008345` | `0xD0008352` |
| B | `0xD0008348` | `0xD0008355` | `0xD0008346` | `0xD0008353` |
| C | `0xD000834A` | `0xD0008357` | `0xD0008344` | `0xD0008351` |

Pairs A and B are evaluated first and their **negated** OR is stored as an intermediate
"consistent" byte at `0xD0008349` (mirror `0xD0008356`). `FUN_80047558` and `FUN_800476E2`
are then called — they are what produce pair C. The final fault condition is
`C_disagrees || consistent == 0`, which reduces to the OR of all three pairs. Debounce
counter at `0xD0008338` (mirror `0xD000833A`); flag at `0xD000834D` (mirror `0xD000834E`).

The block is laid out as raw conditions `0xD0008344`-`0xD000834A`, then the debounced
outputs and their mirrors in `0xD000834B`-`0xD0008350` (reasons 2 and 1 at `0xD000834D` and
`0xD000834F`), then the mirrors of the raw conditions at `0xD0008351`-`0xD0008357` — i.e.
raw flag + `0xD`. Note that the reason flags themselves use *adjacent* mirrors while the raw
conditions use a `+0xD` stride, so these are two different arrays sharing one span.

#### Reasons 3 and 4 — `FUN_80058AE2` and `FUN_8005A450`

Structurally different from 1 and 2. The debounce counters sit **upstream** inside these
functions, and the final flag assignment is a boolean AND/OR against module state rather
than a counter comparison:

- **Reason 3** (`FUN_80058AE2`, 3208 bytes) — upstream debounced fault at `0xD0008758`
  (mirror `0xD0008773`), then
  `flag3 = (fault && 0xD0008619 == 0) || (fault && 0xD0008610 != 0)`.
- **Reason 4** (`FUN_8005A450`, 590 bytes) — upstream counter at `0xD0008738` compared
  against a CAL threshold of 100 to produce a fault at `0xD000875D` (mirror `0xD0008779`),
  then `flag4 = fault && (0xD0008610 != 0 || 0xD0008618 == 0)`.

**Hypothesis (not verified):** `0xD0008610`, `0xD0008618` and `0xD0008619` are a shared
mode or state gate — both detectors consult the same bytes, neither writes them, and all
three carry mirrors (`0xD0008621`, `0xD0008629`, `0xD000862A`). Open — see §11.

Two writers in the scan output are **not** detectors:

- `FUN_8005D524` and `FUN_8005D68C` write **0** to these flags along with a dozen other
  flags and counters in sequence. They are initialisers.
- `FUN_8005A69E` is **not a distinct function**. `FUN_8005A450` has size 590 and therefore
  ends exactly at `0x8005A69E`; both decompile to identical tails with the same labels,
  the same CAL operand and the same sequence token, and the writes at `0x8005A828` /
  `0x8005A838` lie past `FUN_8005A450`'s recorded body end. This is precisely the
  `DlcmFixOrphanCode` caveat in `ghidra/README.md` — Ghidra's recorded body can be shorter
  than the code the function executes, so a jump destination inside it becomes a spurious
  entry.

#### Calibration constants

`a1 = 0xA0028000` (`coda-dlcm-decompile-notes.md` Architecture), so every `[a1]`-relative
operand in these functions resolves into the CAL image. Read directly from
`coda_dlcm_cal.bin`:

| CAL address | Operand | Value | Role |
|---|---|---|---|
| `0xA0021C7C` | `a1-0x6384` | 3274 | reason-1 difference threshold (s16) |
| `0xA0021C7E` | `a1-0x6382` | 50 | reason-1 debounce maximum |
| `0xA0021C90` | `a1-0x6370` | 2 | reason-2 debounce maximum |
| `0xA0021CC2` | `a1-0x633E` | 100 | reason-4 upstream counter threshold |

Reason 3 additionally reads `a1-0x6388`/`0x6386` (200, 5) and `a1-0x635A`..`0x6352`
(18000, 3, 3, 3, 3); reason 4 also reads `a1-0x6344`..`0x6340` (654, 600, 1470). Their roles
were not traced.

3274 is in channel-2 ADC counts (signal A's units), per the
identification above.

**These counts are why the monitor task period matters.** 50 counts is a real latch delay
and 2 counts is near-immediate, but neither converts to seconds until the period is known
(§11).

---

## 3. C0044 — a brake-switch vs brake-pressure rationality check

`FUN_8006F110` is the brake-switch input handler. It is both the sole writer of the
limiter's brake selector and the detector for `C0044`:

```c
brkSw        = FUN_8007C55A()                     -> 0xD0006831   // limiter selector
pressAboveThr= (valid @0xD000683B != 0) && (press @0xD000681C > 160)   // 160 = CAL 0xA00212BC
brakeApplied = pressAboveThr || brkSw             -> 0xD0006830
C0044_failed = pressAboveThr && (brkSw == 0)
report(8 /*C0044*/, C0044_failed)
```

The brake pressure and its validity come from `FUN_8006ED3C`, which also reports event 109
(`U0415` "Invalid BrakePressureFilter Signal") when `pressValid` is false;
`pressValid = pressSigOk && (inhibit == 0) && (press != 0xFFF)`.

**The same predicate has two uses:** it is the `C0044` set condition *and* it decides which
falling-side limb the gradient limiter takes (brake-pressure table `0xA00214C0` when
pressure is valid and above threshold, otherwise the `BrkSwOn`/`BrkSwOff` constants
`0xA0021540`/`0xA002153E` selected by the raw switch).

### 3a. Reproduced from the bus, and it fires

Signals: `0x208 ESC_BrakePressure` (ESC -> DLCM) and `0x315 DLCMStatus.Brake_SW`
(a DLCM transmit frame, so it is the DLCM's own view). `0x212 DLCM_TorqueRequest.BrakeSW`
is an equivalent second copy; the two agree in 69,615/69,689 forward-filled frames and give
identical episode analysis.

**Duration matters, sample count does not.** The switch leads hydraulic pressure by about
40 ms (`CM_ SG_ 789 Brake_SW`), so on *every* brake release the switch opens while pressure
is still decaying above 160. The instantaneous predicate is therefore briefly true on
essentially every brake application — 114 of 232 `d_can` sessions show it — which is an
artifact, not a fault, and is exactly what the event's debounce of 100 exists to reject.

Corpus sweep over all 232 Coda `d_can` sessions (InfluxDB):

| Measure | Result |
|---|---|
| Sessions with the instantaneous predicate | 114 / 232 |
| Episodes >= 1 s | 118 across 75 sessions |
| Episodes >= 5 s | **19 across 16 sessions** |
| Longest | **29.7 s**, session `coda_20260823_161102`, peak pressure 276 |

Validated against raw frames rather than trusted from InfluxDB alone: that episode is
**29.81 s at t=92.07** in `../../CANLogs/CodaLogs/coda_20260823_161102_T2.log`, with a
7.79 s episode in the same chunk. So `C0044` has genuinely been setting on this car,
intermittently, over months — consistent with the user's description of it as a known
intermittent fault.

**Bus-split caveat, added 2026-10-03.** `0x208` and `0x212` are each present on **two
buses** (gateway rebroadcast; identical frame counts per bus), while `0x315` is on one.
The corpus sweep above is bus-scoped (`bus='d_can'` in InfluxDB) and is clean. The
**per-log phase and the raw-frame validation were not bus-split** — they read `0x208` from
whichever buses a capture contained and forward-filled the merged series, which is the
"not splitting at all is the same error" case under *Silent-failure invariants* in
`AGENTS.md`.

Re-measured rather than assumed, on `coda_20260823_161102_T2.log`:

| Input | Episodes | >= 1 s | >= 5 s | Longest |
|---|---|---|---|---|
| merged (as originally run) | 4 | 3 | 2 | 29.81 s, peak 276 |
| bus 2 only | 4 | 3 | 2 | 29.81 s, peak 276 |
| bus 3 only | 4 | 3 | 2 | 29.81 s, peak 276 |

Identical, because the two rebroadcast copies carry the same values and the predicate is
level-based rather than rate-based. **The method was wrong by the rule and the result
survives it** — but that is a measurement, not a reason to skip the split next time. A
rate-, count- or timing-based question on these ids would have been corrupted.
`brake_switch_implausibility.py` still does not filter by bus; fix it before reusing it for
anything rate-dependent.

**Caveat:** the absolute debounce time is not established. 100 counts is 100 calls of the
monitor task and the task period was not measured, so the >=1 s / >=5 s buckets are
descriptive and are **not** a claim about where `C0044` actually latches.

### 3b. Practical use for limiter measurements

For the planned negative-side flash, exclude regen events falling inside a *sustained*
episode; do not exclude the ~40 ms release transients, which occur on every stop in every
drive including clean ones. Per-event branch state:

```
valid = (B2 >> 4) & 1                    // 0x208
press = ((B2 << 8) | B3) & 0xFFF         // 0x208
sw    = B0 & 1                           // 0x315
contaminated = valid && press > 160 && sw == 0
```

---

## 4. The 0x208 brake-pressure field — refinement of a known discrepancy

`artifacts/dlcm_signal_map.out.txt` already records `0x208` B2 as "firmware mask 1F vs DBC
'BrakePressure' mask FF — DBC covers bits the firmware excludes". This investigation
resolves what those five bits are, from the two getters:

- `FUN_8008062E` = `((B2 << 8) & 0xF00) | B3` — an **explicit 12-bit mask**
- `FUN_8008061C` = `(B2 & 0x10) >> 4` — a **separate validity flag**

| Field | Position |
|---|---|
| BrakePressure value | B2 bits 3-0 + B3 — 12 bits (DBC start bit 19, length 12) |
| BrakePressure valid | B2 bit 4 (DBC start bit 20, length 1) |
| unused | B2 bits 7-5 — zero in 138,460 frames |

Confirmed on the wire: B2 takes only `0x0F` (12 frames, valid bit clear, value `0xFFF` =
the firmware's invalid sentinel) and `0x10`-`0x14` (valid bit set) across
`codadriveslowturnonwithdefroster2.log`.

This finding is now cited in `AGENTS.md` under *Filters that fail silently* as the
worked example of a scan that came back clean because its scope ("ids the DBC does not
account for") excluded by construction every message that had a DBC entry with a wrong
field width.

**Presented and pending review; the DBC has not been edited.** `SG_ BrakePressure :
23|16@0+ (1,-4096)` is a 16-bit field that swallows the validity bit into the value. The
`-4096` offset only "works" because bit 12 *is* the validity flag and is set whenever the
signal is valid, and the form cannot represent the invalid case as anything but `-1`.

Also pending review, and narrower than first claimed:
`CM_ SG_ 530 BrakeSW "Triple-redundancy: same signal at 0x315 B0.bit0 and 0x200 B1.bit0."`
The `0x315` leg is correct. The `0x200` leg is not — `BO_ 512` is multiplexed and in `m0`
byte 1 is `WheelSpeed_RollingCounter : 15|8@0+`, so that bit is the counter's LSB. The
"triple" is a double.

---

## 5. C2100 — local output-driver diagnostics, not on the bus

Both events concern output driver **channel 0x20**; the DLCM drives the key interlock
solenoid itself.

**Event 24, "Drive Electrical Fault"** (`FUN_800815BE`): reads `FUN_8007CB9E(0x20)`, which
returns a command byte and a feedback byte, compares them per bit for bits 0, 1 and 2
independently, and fails if **any** of the three mismatches. It passes debounce selector
**5**; every other monitor examined passes 1.

**Event 25, "Non Functional"** (`FUN_80077B10`):

```c
failed = (cmd != 0) && (enable @0xD00069B6 != 0) && (measured @0xD00069A2 < 2)
                                                    // 2 = PROG byte 0x80043F45
FUN_8007C5F6(cmd)   -> FUN_8007CD6E(0x20, cmd)      // drives the output
```

**Hypothesis:** `0xD00069A2` is a current or voltage feedback and the check is "commanded
on but no current flowing". The variable's role is **not** confirmed — it is written in
`FUN_80074572`, which also reports event 9 (`P2530` ignition input plausibility).

**Calibration override hook.** If CAL byte `0xA0021884` is non-zero the commanded state is
taken from `0xA0021880` instead of the computed value. Both are **0** in the current
calibration, so the override is off. This is the same class of live one-byte experiment as
the IIR enable at `0xA0021545`.

**Not traceable in logs.** Command and feedback are internal hardware I/O; neither reaches
any bus.

---

## 6. P0A05 — CAN-derived, but on the channel we do not tap

`FUN_80072B42`:

```c
enable = (inhibit @0xD0006982 == 0);
failed = FUN_8008047A();                  // bit 7 of byte 2 of RX buffer 0xD0007FB0
report(0x24 /*P0A05*/, failed, enable, 1, 1);
```

The `failed` expression as written is `feedback || inhibit`, but `enable` is
`inhibit == 0`, and the reporter skips all processing when `enable` is 0 — so the
`|| inhibit` term is inert and the effective condition is `feedback` gated by
`inhibit == 0`. The inhibit is shared with the monitors for events 92, 113 and 116
(`U0116` HVAC comms, `U0424` heater power, `U0466` A/C compressor power); its role is
**not** established.

Resolving the buffer to a CAN id, via the tables already documented in
`coda-dlcm-decompile-notes.md`:

```
FUN_8008047A reads a0-0x1050 +2 bit7
  a0-0x1050 filled by FUN_800686D8(a0-0x1050, 0x800C)      // RX accessor, handle 0x800C
    handle low byte 0x0C -> RX signal table 0x80041490 record 12 = 0c 40 05 88 01 0d 01 2c
      b5 = 0x0D -> RX message table 0x8004162C record 13 = CAN 0x20D
```

**The `b5` -> message-index step was validated independently** on brake pressure: handle
`0x8006` -> signal record 6 -> `b5 = 6` -> message record 6 = `0x208`, which matches the
DBC's `ESC_BrakePressure`.

So `P0A05` fails on **bit 7 of byte 2 of CAN `0x20D`**. But `0x20D` has **zero frames in
every log checked** (18 captures including recent multi-hour ones) and is in no DBC —
`dlcm_signal_map.out.txt` already records it as "not in any DBC (firmware bytes B1:FF
B2:FF)".

---

## 7. The RX table splits across two CAN channels

This bears on the open question left by the 2026-09-24 inventory, which voided the
Phase 23-27 Motor CAN ids and said only that "the real configured id set is the one
tabulated above" without assigning channels.

In the RX message table (`0x8004162C`, 26 x 52 B), the field at **`+0x04`** partitions the
entries cleanly:

| Mailbox field | Ids | Ever captured |
|---|---|---|
| `0x00xx`-`0x04xx` | everything else | yes (except `0x593`, `0x168`) |
| `0x20xx` / `0x21xx` | `0x209`, `0x20A`, `0x20B`, `0x20C`, `0x20D`, `0x20E`, `0x20F` | **none, ever** |

**Hypothesis (strong but not proven): the `0x20xx` mailbox group is the private Motor CAN.**
Evidence for: a clean two-way split in the firmware's own table; the whole group absent
from every capture while every other entry appears; and the group is contiguous in id
space, consistent with one peer module. The notes already establish that the MCM sits on a
private Motor CAN sub-bus not reachable from the OBD-II port. What is *not* proven is that
the second controller is that bus specifically rather than some other channel.

**Scope of the "ever captured" column:** presence was tested across whole captures
without splitting by bus, which is the correct scope for a claim of *global* absence but
means the column says "absent from every bus in these captures", not "absent from D CAN".
The captures used carried three bus numbers each (D CAN, B CAN and the C CAN cell bus by
content). What this evidence cannot distinguish is "we have never tapped the Motor CAN"
(the hypothesis) from "these messages are not transmitted on this car at all" — both
produce the same empty result. Resolving it needs the physical tap.

The two apparent exceptions do not weaken this: `coda-dlcm-decompile-notes.md` already
records `0x168` as "configured but not seen in the surveyed capture" and `0x593` as
"event-driven and not seen" — both are on the captured-channel side and are simply rare.

**Consequence.** `P0A05` and the four `U0110` monitors read from this group, so their inputs
are not observable with the current tap. Tracing them requires a physical Motor CAN
connection. It also corroborates the flash-artifact reading of `U0110`: the MCM is on the
bus that went quiet while the DLCM sat in its bootloader.

---

## 8. No DTC is broadcast live — a code exists only inside a UDS response

Traced 2026-10-04. **Question that prompted it:** the flash-7 drive
(`dcan_drive_capture_20261004_f7/`) threw a fault, the car needed a 12 V cycle to recover,
and the cycle cleared the stored code. Could a CAN capture alone have named it?

**No.** Four independent closures, all measured against the image rather than inferred from
the absence of a decoded signal.

**1. Exactly one function converts an event id into an SAE code.** `FUN_8007FCDE` reads the
event -> DTC table of §1a by *absolute* address — `*(u16 *)(eventId * 6 + 0xA0024520)` and
`*(u8 *)(eventId * 6 + 0xA002451F)`, which is `0xA002451E + 1/+2` — and writes the three
bytes through its three pointer arguments. It has exactly **two callers**, `FUN_80084540`
and `FUN_80084620`, whose own callers are only `0x80078CFA`, `0x80078E4C` and `0x80078E80`.

**2. That band is the UDS service-handler band.** Read straight out of the dispatch table at
`0x80041248` (8-byte rows, SID in byte 0 of word 0, handler in word 1):

| SID | Handler | | SID | Handler |
|---|---|---|---|---|
| `0x03` | `0x8007890A` | | `0x22` | `0x8007907C` |
| `0x10` | `0x80078A74` | | `0x27` | `0x80079490` |
| `0x11` | `0x80078B10` | | `0x28` | `0x800795C0` |
| `0x14` | `0x80078B8C` | | `0x2E` | `0x800795F0` |
| `0x19` | `0x80078F10` | | `0x31` | `0x80079940` |
| `0x3E` | `0x80079978` | | `0x85` | `0x800799F0` |

`FUN_80084620` is recognisably the ISO 14229 **`0x19 02` pager**: it walks events while
`cursor < 0x80`, emits **4 bytes per record** (the three code bytes from `FUN_8007FCDE` plus
the status byte `*(a0 + eventId*6 - 0x1D81) & 8`), stops after `0x32` records, keeps its
resume cursor at `a0-0x3E66`, and returns **1** when the sweep completed or **2** when more
remain. So a DTC code is materialised only while answering a tester.

**3. The DEM per-event status array has eight readers and none is a transmit path.**
`0xD000727E` (`a0-0x1D82`, §1) is read by the reporter `FUN_8007F6C8`, by six small
accessors (`FUN_8007F9A6`, `F9BC`, `F9D2`, `F9E4`, `FA02`, `FA6E`) and by the `0x19 02`
pager. The accessors' callers are the reporter, the individual monitors, and functions in
the UDS band — `FUN_8007F9A6` alone has 58 distinct callers-of-callers, which is every
monitor in the module asking "is my own event failed". None of them is a CAN packer.

**4. The periodic task chain contains no DEM function, and its one indirect route resolves
to the tester dispatcher.** `FUN_8007C33A` is the task body: 29 members, each bracketed by
`FUN_800609AA(0x15, token)` / `FUN_80060948(0x15)` (the control-flow sequence idiom of §2d),
and it **does** contain the CAN TX packer `FUN_80080C14`. No member is a DEM function. Its
only member in the DEM address band, `FUN_8007D1A4`, is a *generic indirect dispatcher*: it
walks a table at `a0-0x3D38`, stride `0x14`, calling the pointer at `+8` of each entry.
That is the one place a hidden periodic reader could live, so it was resolved statically —
the table is installed by `FUN_8008F760(0x800427E4)`, from the same init function
(`FUN_80089526`) that installs the signal pool of §2d, and holds **exactly two entries**:

| Entry | Callback | What it is |
|---|---|---|
| 0 | `FUN_8007C72C` | signal-pool publisher (calls `FUN_80064520` / `FUN_800645C8`) |
| 1 | `FUN_8007D1E4` | **the UDS service dispatcher** — it references every handler in the table above |

So the only periodic code that can reach a DTC code is the code that waits to be asked.

`FUN_80080C14`, the packer itself, reads only a TX staging block at `a0-0xF81 .. a0-0xFC4`
and **nothing** in the reason-flag / monitor-input block `a0-0xCA9 .. a0-0xD08`.

Two DEM API functions, `FUN_8007F424` (per-event status evaluation) and `FUN_8007F4E6`
(a DEM init), have **no callers and no literal function pointer anywhere in the image** —
unused library entries in this build.

### Bounds on the above

Three things this does *not* establish, recorded because each is the shape of filter that
fails silently:

- **The offset scan for the two CAL tables came back empty and that is not evidence.**
  `DlcmA0RefScan` for `3ae2` (`a1-0x3AE2` = the event -> DTC table) and `404c`
  (`a1-0x404C` = the per-event config) returned **zero hits**, because both are reached by
  multi-step address construction — the TriCore trap recorded in `ghidra/README.md` and
  §2d. The absolute-address route through `FUN_8007FCDE` is what actually answers the
  question; the empty offset scan answers nothing.
- **"No literal function pointer" cannot see a two-step address.** The pointer scan matches
  a little-endian word in the image, so a table whose entry is built with `movh.a` + `lea`
  would evade it. That would be unusual for a task table, but it is not excluded.
- **Ruling out `FUN_80080C14` is not ruling out every TX byte.** It reads a staging block
  that some other task member fills; the packer was cleared, not every possible upstream
  writer of that staging area.

### What a capture does carry

- **`0x271` B0 bits [1:0]** — the arbitrated lamp colour only (0 off, 1 yellow, 2 red).
  `B1-B7` are zero in all 428,827 corpus frames, so no code and no source. Measured in
  `../fault-light-investigation.md`, which is also where the **`0x370` negative** now lives:
  the one message the factory DTC master list actually calls "Vehicle Faults" has `B4`/`B5`
  — the only adjacent pair a 16-bit code could occupy — identically zero across 113,715
  frames on both buses, and what does move in it moves like power state.
- **Behavioural consequences** — torque limits (`0x312`), park request (`0x308`), PRND
  (`0x418`), and module silence. For the 2026-10-04 event the actual evidence was a
  two-stage silence cascade, not a fault field.

**Practical consequence, and it is the useful part of this negative.** `0x19` subfunctions
`04` (snapshot / freeze frame) and `06` (extended data) have never been tried on the DLCM
(§11), and the module does answer `0x19`. Snapshot records are captured **at fault time**,
so on any future run like flash 7 a `0x19 04` read taken **before** the 12 V cycle would
preserve the conditions this reset destroyed. Nothing on the bus will substitute for it.

---

## 9. Same code, different module — a trap

Three codes seen on the car exist in the DLCM event table with **different meanings** than
the module they were read from:

| Code | Seen on | DLCM meaning (event) |
|---|---|---|
| `U1074` | Gateway ("D CAN Bus Off") | Drive Line CAN Bus Off (33, 34) |
| `U0110` | Airbag | Lost Comms with MCM (86-89) |
| `U0155` | ACCompressor | Lost Comms with Instrumentation Pack (101) |

**The event table in §1a is only valid for codes read from `0x7E0`/`0x7E8`.** Looking up a
Gateway or Airbag code in it returns a confident, wrong answer.

---

## 10. Corrections made during this investigation

**`ghidra/scripts/DlcmSecurityAccess.java` carried the superseded SID-first dispatch
reading** in its comments and its `dumpDispatchTable()`, i.e. the exact error
`dlcm-security-access.md` §1b had already corrected. It caused the first decompile pass to
target the wrong three functions. Fixed 2026-09-23; the dump now reproduces the notes table
exactly. Independent confirmation of the corrected order: `0x80078F10` decompiles to "read
N 16-bit identifiers", i.e. `ReadDataByIdentifier` (SID `0x22`), which is what
handler-pointer-first predicts. The real DTC handlers are `0x80078B10` ClearDTC,
`0x80078B8C` ReadDTCInformation, `0x80079978` ControlDTCSetting — all three delegate to
callbacks in a DCM config struct (`cfg+0x10`, `cfg+0x20`, `cfg+0x1C` respectively).

**A wrong claim of mine was retracted before it reached the DBC.** An intermediate run read
`0x212 SG_ BrakeSW` at byte 2 **bit 7** and, finding it clear in 0/69,690 frames, concluded
the signal was dead and the DBC defective. That was wrong: in DBC Motorola numbering start
bit 16 is byte 2 **bit 0**; bit 7 would be start bit 23. `cantools` agrees with bit 0 in
69,690/69,690 frames. The DBC is correct as written. Caught by the in-car session
independently verifying rather than relaying.

Two lessons worth keeping, both of which cost time here:

1. **A signal reading constant-0 is indistinguishable from one decoded at the wrong
   offset**, and "the field is dead" is the more flattering explanation. Check against
   `cantools` before blaming the DBC.
2. **`DlcmA0RefScan.java` matches literal offset text, so a multi-step address defeats it.**
   `FUN_8008047A` builds its pointer as `lea a0,-0x1050` then `lea +0x2`, so a scan for
   `104e` found nothing and looked like proof of absence. Scan for the *base* as well as the
   effective address.
3. **An absent writer is usually an absent search.** §2b recorded that reasons 3 and 4 had
   no findable writer and attributed it to absolute addressing. The real cause was that
   their two offsets were never in the scan list — 14 of 16 flags were scanned and the
   explanation was invented for the gap. The orthogonal check that would have caught it
   immediately is to re-derive the offsets from the flag addresses and diff that set against
   what was actually passed.

**`DlcmVarXref.java` cannot see `a0`-relative accesses at all, and reports `writes: 0`
rather than failing.** Run on `0xD000834F` and `0xD000834D` it returned `reads: 0  writes:
0` for both — addresses whose writers had just been read in the decompiler. TriCore
small-data accesses are `[a0]`-relative, so Ghidra records no reference to the absolute
address and there is nothing for that script to find. The two scanners are **strictly
complementary**:

| Access form | `DlcmVarXref` | `DlcmA0RefScan` |
|---|---|---|
| `[a0]`/`[a1]`-relative | blind | sees it |
| absolute (`movh.a`/`lea` to a full address) | sees it | blind |

So `writes: 0` from `DlcmVarXref` is **not** evidence that nothing writes an address. This
was caught only by scoring two known-written addresses alongside the unknown ones — the
failure is otherwise indistinguishable from a true negative, per *Filters that fail
silently* in `AGENTS.md`. The caveat is now also recorded in `ghidra/README.md`.

---

## 11. Open items

### Resume here — concrete entry points

**Read this section, not a compaction summary.** Per *Session Startup* in `AGENTS.md`, a
summary records what a session did, not what the references say. Everything needed to
restart is below; nothing required lives only in a conversation.

**Machine-local state that does NOT sync, and may be gone:** every Ghidra export this
investigation produced is in `~/ghidra-projects/dlcm_export/*.txt`, and the Ghidra project
`dlcm_tricore` is in `~/ghidra-projects/`. Neither is in the repo. If they are missing,
rebuild with `bash ghidra/restore-ghidra.sh` and re-import per `tools-reference.md`
(`-processor tricore:LE:32:default -loader BinaryLoader -loader-baseAddr 0x80040000`).
Everything load-bearing from those exports has been copied into this file — §2b is the map
that was nearly lost that way.

Reasons 1-4 were decompiled 2026-10-03 and are written up in §2d; the two items that work
produced are now 1 and 2 below. The standard runner invocation is:

```
JAVA_HOME=~/jdk-25.0.4+7 ~/ghidra_12.0.4_PUBLIC/support/analyzeHeadless \
  ~/ghidra-projects dlcm_tricore -process coda_dlcm_prog.bin -noanalysis \
  -postScript DlcmSecurityAccess.java ~/ghidra-projects/dlcm_export/out.txt \
  <comma-separated hex addrs> <depth> \
  -scriptPath ~/Seafile/NotGit/reverse-it/ghidra/scripts
```

Ranked by value:

1. **Confirm reason 1's signal B on the wire.** Done as far as this image allows (§2d,
   2026-10-04): signal A is APP channel 2 raw, signal B is a received link byte, and the
   `b4 = ch1_raw >> 8` reading is a hypothesis whose producer is in the link partner. What
   would settle it is a physical tap on the `0x20xx` link (same measurement the Motor CAN
   item below needs) watching b4 of record `0x2080` against pedal position, or an ECM1-side
   image if one can be obtained.
2. **Reasons 3 and 4's gate bytes** `0xD0008610` / `0xD0008618` / `0xD0008619` (§2d) — find
   their writers (`DlcmA0RefScan.java <out> 9f0,9e8,9e7`) to confirm or refute the
   mode/state-gate hypothesis.
3. **Reasons 5-16** — the §2b writer map is unverified for these twelve. §2d gives the idiom
   to expect, so each is now a quick read rather than an investigation.
4. **`P3114`** (event 125) — nothing in `FUN_8005ABAC` sets it. Start by searching for any
   other caller of `FUN_8007F6C8` with a computed first argument; the census found exactly
   one (`FUN_8005ABAC`), so either there is a second path the census missed or event 125 is
   written into the status array directly.
5. **Monitor task period** — converts the debounce thresholds in §1b and the counts in §2d
   into real latch times, and is the one measurement blocking any quantitative claim about
   `C0044`/`P3115` timing. Find the scheduler that calls the monitor band.
6. **`P3103`** (event 42) — identify its monitor the same way `C2100`/`P0A05` were done:
   `grep 'd4=0x2A(' ` in a `DlcmCallCensus` run over `0x8007F6C8`.
7. **`brake_switch_implausibility.py` bus split** — small, self-contained, and it removes a
   known-latent defect (§3a). Add a bus filter to `collect()`.

**Do not re-derive these; they are settled and in this file:** the three DEM tables (§1),
the 128-entry event→DTC map (§1a), `P3115` as a roll-up and the exclusion of the torque
path (§2, §2c), the reason-flag writer map (§2b) and the reason 1-4 detector mechanics and
CAL constants (§2d), the `C0044` predicate and its corpus result (§3), the `0x208` field
layout (§4), `C2100` as hardware I/O (§5), `P0A05` → `0x20D` (§6), the two-channel RX split
(§7), and that **no DTC is broadcast live**, with the four closures that establish it
(§8). Also settled: `DlcmVarXref` is blind to `a0`-relative accesses (§10) — do not re-run it
on a small-data address expecting writers.


- **`P3114`** (event 125) is never set by `FUN_8005ABAC`. What sets it is unknown.
- **What each of the 16 safety-disable reason flags means.** Locations and writers known
  (§2b), mechanics known for reasons 1-4 (§2d), **semantics still not known for any** — the
  code says *how* a flag latches, not what physical quantity it is about. This is the
  remaining work for "what *would* trip `P3115`".
- **Reason 1's signal B** (§2d): the *route* is traced (received half of pool record
  `0x2080`, byte 4, the only unprotected payload byte) and signal A is confirmed as APP
  channel 2 raw, so the 3274 threshold is in channel-2 ADC counts. **What b4 physically
  carries remains a hypothesis** (`ch1_raw >> 8`), because its producer is not in this
  image. The link peripheral is also unidentified by choice — the register map did not fit
  anything nameable without guessing.
- **The reason 3/4 gate bytes** `0xD0008610` / `0xD0008618` / `0xD0008619` — the
  mode/state-gate reading is a hypothesis from two call sites only (§2d).
- **The remaining CAL operands of reasons 3 and 4** (§2d) were read but not attributed.
- **The monitor task period**, needed to convert debounce counts into real latch times.
  Now has concrete numbers waiting on it: reason 1 latches at 50 counts, reason 2 at 2
  (§2d).
- **`b3`** in the per-event CAL config (`0`/`1`/`2`) — role unknown.
- **Confirming the `0x20xx` mailbox group is the Motor CAN**, which needs a physical tap.
- **`P3103`** (event 42) — identified only; its monitor was not traced. It appeared in the
  2026-09-23 read with every status bit clear, which is itself unexplained.
- **`0x19` subfunctions other than `02`** have never been tried on the DLCM (`01` count,
  `04` snapshot, `06` extended data), though the module answers `0x19`. **Raised in priority
  by §8:** since nothing broadcasts a DTC live, a `0x19 04` snapshot read taken *before* any
  12 V cycle is the only way to preserve fault-time conditions, and the 2026-10-04 flash-7
  fault was lost exactly that way.
- The per-event **status-bit semantics** of the DEM state machine were only partly walked.
- **`brake_switch_implausibility.py` does not filter by bus.** Harmless for the level-based
  predicate it implements (measured, §3a), but it must be bus-split before being reused for
  any rate, count or inter-frame-timing question.
- **The `0x208` / `CM_ SG_ 530` DBC changes in §4 are still unedited** and still pending the
  user's decision.

---

## 12. Reproduction

Scripts in `artifacts/`:

| file | what |
|---|---|
| `dtc_event_table.py` (+ `_out.txt`) | Brute-forces the event -> DTC table layout, scored against the DLCM DTC list; dumps all 128 events joined to the per-event CAL config. This is the script that establishes §1a/§1b. |
| `dtc_code_locate.py` (+ `_out.txt`) | Searches both images for every DLCM DTC word. Mostly a negative result — the codes are not scattered as constants — and the source of the `PCBU` vs `PBCU` correction. |
| `dtc_table_hunt.py` (+ `_out.txt`) | Earlier structural scan for increasing-value tables. Superseded by `dtc_event_table.py`; kept because its false positives document what the image's other tables look like. |
| `brake_switch_implausibility.py` (+ `_out.txt`) | §3a/§3b. Phases: encoding check, per-log episode timeline, InfluxDB corpus sweep. |
| `reason1_signal_source.py` | §2d. Locates the writers of reason 1's two operands in `FUN_80046484`. Its `second_lea_disp()` BOL decoder is **known wrong** and now raises rather than returning a bogus displacement — parse Ghidra's decompiled output instead. |
| `sigB_pool_record.py` | §2d. Walks the pool's static config at PROG `0x80042E4C` to resolve ids `0x2000`/`0x2080`/`0x2085` to bank/record/element, then (phase 3) tests candidate carriers for byte b4 against the APP CAL spans. Phase 3 is arithmetic only — no target, no log. |
| `../../artifacts/fault-encoding/live_dtc_broadcast.py` (+ `.txt`) | §8's bus-side half. Phases: bus identification from the audited anchors, byte census of `0x370` and `0x271`, transition timeline for every candidate fault-bearing id. Established the `0x370` negative. |

Ghidra: §8 used `DlcmA0RefScan.java` (status-array readers), `DlcmFuncContext.java`
(caller chains) and `DlcmSecurityAccess.java` (decompiles), plus a plain image walk for the
dispatch and dispatcher tables.

`ghidra/scripts/DlcmPoolIdScan.java` (new) — lists every call site of the four
indexed-pool accessors with the literal signal id loaded into `d4`, chasing `mov d4,dN`
aliases back to the literal and printing `?` rather than skipping when no literal is found,
so a computed id cannot pass unnoticed as an absent one. Output
`~/ghidra-projects/dlcm_export/pool_ids.txt`.

`ghidra/scripts/DlcmCallCensus.java` — ranks functions by distinct caller
count and, for chosen targets, dumps every call site with the constants in `d4`/`d5`. This
is what found the reporter and the event-id space.

Standard headless invocation is in `tools-reference.md`; all runs here used
`-process coda_dlcm_prog.bin -noanalysis -postScript` against `dlcm_tricore`.

---

## 13. The 2026-10-04 flash-7 fault — reason 12, and what `P3115` actually witnessed

Added 2026-10-08, reviewed in conversation before writing, per the header rule. The
**mechanism** lives in [`flash7-reset-mechanism.md`](flash7-reset-mechanism.md); this
section records only what the fault settles on the **DTC side**, which is this file's
subject, plus one correction to an earlier claim of mine.

### 13a. Reason 12 is the candidate, and `P3115` is consistent with it — by model, not by readout

§2 established that `P3115` carries no detection of its own: it means *"an internal
safety-disable reason code in 1..16 is currently non-zero"*. §2b's table maps reason **12**
to flag `0xD000868A`, reporting as `P3115`.

The flash-7 reset mechanism is a reason-12 trip — the published command freezes while
ECM2's allowance keeps slewing down, the gap exceeds the 300-count tolerance for more than
5 ticks, and the shut-off path fires. A forward replay of the whole torque path on the
recorded drive predicts **all seven** resets to within +0.062 s, gives **0** on the same
drive with the C4c calibration, and **0** on the C4c drive, with simulated `0x212` matching
the recorded value to p90 |err| 8-17 published units every tick.

**Stated precisely, because the distinction matters here:** the module does not broadcast
which reason fired, and the flag was not read out of a faulting module. Reason 12 is
established by **agreement between a validated forward model and the observed reset times**,
and by being the only reason whose condition the mechanism satisfies. It is consistent with
the `P3115` that was recorded, but `P3115` cannot by itself distinguish reason 12 from any
other reason in 1..16 — that is what §2 means by a roll-up. Anyone wanting the flag itself
would have to read `0xD000868A` live, which needs a reproduction.

So `P3115 0x04` is a **witness that some safety-disable reason was non-zero during the f7
drive**, not an identification of which one.

### 13b. CORRECTION — the DTC absence after the 12 V reset proves nothing

`artifacts/flash7_diagnosis_worklog.md` §3AB is headed *"DTCs WERE READ AND WERE ABSENT —
which weakens the reset hypothesis"* and argues that because an ECU retains DTCs in
non-volatile memory, an empty store is meaningful evidence that **no DTC was ever set**.
**That conclusion is withdrawn.** Its premise — that nothing had cleared the store — is
false, and the four readouts in `artifacts/` establish the chronology:

| readout | when | DLCM result |
|---|---|---|
| `dtcs_postflash_f7_20261004.log` | after flashing f7, **before** the drive | `P0A05`, `C2100` — **no `P3115`** |
| `dtcs_after_f7_drive_fault_20261004.log` | after the faulting drive | **`P3115` status `0x04`**, `P0A05 0x93`, `C2100 0x93` |
| `dtcs_postclear_f7_20261004.log` | after an **explicit clear** | No DTCs |
| `dtcs_after_revert_c4c_20261004.log` | after reverting to C4c | No DTCs |

`P3115` was **absent before the f7 drive, present after it, and then deliberately
cleared**. The user's report — *"We tried reading dlcm dtcs after the 12 V reset and they
weren't there"* — is a read taken after that clear.

Two independent reasons the absence carries no information:

1. **The store was explicitly cleared**, and a log in the same folder records it.
2. **`P3115`'s status byte is `0x04` — pendingDTC only, not confirmed.** Pending DTCs
   self-clear, so they are exactly the class that an NVM-retention argument does not apply
   to. A readout reflects recent cycles, not history.

What survives from §3AB is only its two negative attempts to confirm the outages were
resets (rolling counters and the rest), which stand on their own evidence.

**The lesson for this file, since it is a repeat of a shape §10 already collects:** the
retention argument was applied to a DTC class it does not cover, and the conclusion came out
*more* interesting than the truth ("no DTC was ever set" rather than "we cleared it"). The
orthogonal check was free and was not done — list the readouts in time order and look for a
clear between them.

### 13c. §4's `0x208` reading confirmed from a third direction

§4 derived the `0x208` brake-pressure layout from the two getters. Those same getters turn
out to be the inputs to the **ECM2 down-step selector**, written at `0x8004812E`:

```
a0-0xc67 = (brake12 != 0x0FFF) && (0x208 B2 bit 4) && (*(u8*)0xD00051A2 == 0)
           value not the sentinel      validity bit        0x208 fresh
```

with the sentinel `0x0FFF` as a u16 constant at PROG `0x800408E8`. So the firmware uses the
12-bit value, the validity bit at B2 bit 4 and the freshness flag as a three-part validity
gate on one signal — which is §4's layout, now visible in a *consumer* of the fields rather
than only in the accessors.

Measured on the 2026-10-04 captures: validity bit set on 100 % of samples, sentinel never
present, `0x208` on rate throughout — so the selector is `1` in both calibrations' drives.
(The `162014_T0` capture reads 64 Hz rather than 100; that capture is a known
logger-dropout file with 20 gaps and is excluded from every quantitative result.)

**§4's two "pending review" items are now BOTH OBSOLETE, and §4's text is stale.**
Checked against `projects/coda/CODA-D-CAN.dbc` on 2026-10-08:

1. **The `BrakePressure` correction was applied.** The DBC now reads
   `SG_ BrakePressure : 19|12@0+ (1,0) [0|4095]` plus
   `SG_ BrakePressure_Valid : 20|1@0+`, which is exactly what §4 proposed, and the
   `CM_ BO_ 520` comment records the 2026-09-24 correction in full. §4's sentence
   "the DBC has not been edited" no longer holds. This section adds a third line of
   support for a change already in place.
2. **The `CM_ SG_ 530 BrakeSW` correction should be WITHDRAWN — §4 was comparing
   against a superseded DBC revision.** §4 says `BO_ 512` is multiplexed and that
   byte 1 bit 0 is therefore the LSB of a `WheelSpeed_RollingCounter : 15|8@0+`.
   The current `BO_ 512` has **no multiplexing** (no `M`/`m` markers, no
   `SG_MUL_VAL_`), and it defines `BrakeSW : 8|1@0+` — byte 1 bit 0 — with the
   rolling counter narrowed to `13|4@0+` (B1 bits 5-2) and `WheelSpeed_Parity` at
   `14|1@0+` (B1 bit 6). So B1 bit 0 is `BrakeSW`, not a counter bit.

   The wire evidence in the `CM_` corroborates the DBC and not §4: B1 bit 0 agrees
   with `0x315 Brake_SW` in **68,648 of 68,688 frames (99.94 %)**, and a counter LSB
   could not do that — it would agree about half the time. **The "triple-redundancy"
   comment is correct as written**, and §4's proposed correction to it was an
   artefact of the older layout.

This is the source-of-truth order (`DBC > vehicle overview > notes`) doing its job in
the direction that is easy to miss: the notes file was stale relative to the DBC, not
the other way round. The lesson is the same one §10 collects — re-read the
authoritative file before acting on a notes file's "pending" item, because a pending
item can be closed, applied, or invalidated without the notes file hearing about it.
