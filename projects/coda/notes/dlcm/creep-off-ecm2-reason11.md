# Creep assist off vs the ECM2 creep monitor (reason 11)

`Coda drivetrain lash model` session, 2026-10-08. User-approved as written. **Provisional; simulation and
static decompile only. Nothing here is flashed, proposed for flashing, or authorised.**

The question (plan `../plans/rd_shift_jerk_sim.md` step 5, worklog §3BB.7). The R<->D candidates K1 and L2+K1
switch the creep assist off with one CAL byte, `0xA00215C0` 1 -> 0. Does that **trip** ECM2's creep monitor
(a fault, so a shutoff like flash 7), **blind** it, or neither?

Work split, agreed with the `Coda DLCM work` session on 2026-10-08:
- This session traced the creep side: the creep output into ECM2, reason 11, `a0-0xaa3`, `a0-0xaa4`, `b64`, and
  the creep ceiling's select (`b60`).
- That session owns the exact trip mechanisms, everything downstream of the slew limiter's target `b56`
  (reason 15), and `cb5`.

Addresses: a0 = 0xD0009000, a1 = 0xA0028000. Spans are ret-to-ret, never Ghidra function labels. Ghidra splits
functions at every call to the redundancy trap `0x80082EAA`, and `FUN_800507BA` (worklog §3AJ.4) is one of those
fragments. Every ECM2 variable is stored with a bit-inverted shadow and checked against it; the checks are left
out below.

## 1. Answer

**Creep-off cannot trip reason 11. With K1 the monitor can never fire. It is not blind to a creep output
that is nonzero.** (User-approved conclusion, 2026-10-08.)

- **Every fault path in reason 11 needs a nonzero creep output (§3).** K1 makes that output 0 on every tick
  (§2), so the monitor's condition is false on every tick, its debounce stays at 0, and the reason-11 flag
  never sets.
- **The monitor reads the creep output itself, not the enable byte.** If that output ever became nonzero
  despite the byte, the monitor would still see it. What it loses is only coverage of creep that can no longer
  be commanded.
- **The creep OUTPUT and the creep CEILING are different things; do not conflate them.**
  - Only the ceiling (`b60`/`b62`) can reach reason 15's bound route, through `b56`.
  - The ceiling is computed from ECM2's own speed signals, flags and CAL. It never reads the creep output
    (§5), so K1 does not change it.
  - The `Coda DLCM work` session made this conflation first, then corrected it, and checked the readers
    independently.
- **With K1, ECM2's slew-limiter target is always `b70`, ECM2's copy of the driver demand.**
  - The creep term `b64` is 0 on every tick.
  - The branch where the target becomes the ceiling (`b56 = b62`) is never selected.
  - The PROG torque request loses its creep term the same way.
  - Whether that change matters to reason 15 is for the `Coda DLCM work` session.

## 2. The creep output under K1

The creep orchestrator `0x80075FF8..0x8007605C` writes `0xD000513A` (= `a0-0x3ec6`) every tick:
`active ? (P + I >= 1 ? P + I : 0) : 0`.

- **It is never negative.** Values below 1 are written as 0 (`jlt d15,#1` at `0x80076048`).
- **The active flag `a0-0x3ec1` can't be set with the enable byte at 0.** It is
  `(0xA00215C0 != 0) && ... && a0-0x3ec2 == 0`, computed by `FUN_8007605E`.
- **So under K1 the output is 0 on every tick.**
- The K1 image differs from C4c only in that byte. L2+K1 also edits the speed limb, `0xA0021508`/`0A`.

**Direct reads of the enable byte.** `creep_enable_xref_scan.py` finds one direct read,
`FUN_8007605E @0x8007618C`, with a positive control.

**Indirect reads, through a descriptor whose arrays live in CAL.**
- `creep_enable_descriptor_check.py` resolved 93 candidate descriptors, and both positive controls were found.
- No array covers `0xA00215C0`.
- The neighbouring descriptor `0x80043FE8` ends at `0xA00215AF`, and the next one starts its axis at
  `0xA00215C4`.

**Readers of `0xD000513A`** (`dlcm_addr_xref.py`, full output, after the 2026-10-08 fix that recovers stores
after a call):

| site | what |
|---|---|
| `0x800545D4` | ECM2 input snapshot `0x80054274..0x800548E0`; the only ECM2-side read |
| `0x80075D0A` | the PROG request sum |
| `0x80076130`, `0x8007625A` | inside the creep block |

## 3. Reason 11 = the ECM2 creep monitor, `0x80050246..0x80050AEE`

The snapshot copies `0xD000513A` into `a0-0xa18`. Its only readers are this function (`0x800502D8`,
`0x80050894`), the snapshot's own redundancy check, and init. Read from the full-span decompile
(`artifacts/creep_monitor_span_80050246.c.txt`); the comparison is checked in the assembly at
`0x80050864..0x80050902`:

```
c    = a0-0xa18                                   /* ECM2's copy of the creep output, >= 0 */
lim  = sat16(b62 + CAL a1-0x62a4)                 /* 0xA0021D5C = 250 counts, ~25 Nm */
aa3  = (!aa4 && lim < sat16(c + b70)) || (aa4 && c != 0)
ad4  = aa3 ? ad4 + 1 : 0                          /* debounce */
aab  = ad4 > CAL a1-0x62a2                        /* 0xA0021D5E = 5 ticks; 0xD0008555 = the reason-11 flag */
b64  = !aa3 ? c : (!aa4 ? sat16(b62 - b70) : 0)   /* creep half of ECM2's slew target b56 = b70 + b64 */
```

- Both constants are identical in stock, C4c, f7 and K1.
- The reason-11 flag `aab` is read only by the safety-disable OR-chain `0x80055A3E` and `0x800561E0` (the
  shutoff path), plus init.
- `aa4` (§4) is computed from the same `b62` and `b70` in the same tick, by `FUN_80050F16`, called at
  `0x80050842` just before the compare.
  - When `aa4` = 0, its second term guarantees `b70 <= lim`. So `lim < c + b70` needs c > 0.
  - When `aa4` = 1, the condition is `c != 0`.
  - **Both branches need c != 0.**
- Within a tick, `b70` is written earlier, by reason 10 (`0x8004EEA2`). `b62` is written by `0x80050AFE`,
  called at `0x8005083E`. Neither is rewritten between the two comparisons.

## 4. `a0-0xaa4`: hypothesis "creep not permitted"

**HYPOTHESIS, user-approved as such, 2026-10-08:** `a0-0xaa4` means "creep not permitted", i.e. the creep
output must be zero. It is broader than an N/P flag; N/P is one of its three triggers.

**Structure (measured).** `FUN_80050F16`, `0x80050F16..0x8005129A`
(`artifacts/creep_monitor_span_80050F16.c.txt`):

```
aa4 = (c11 != 40 && c11 != 10)                       /* not D and not R */
   || (sat16(b62 + CAL a1-0x62a4 [250]) < b70)       /* demand alone over the creep ceiling + margin */
   || (|0xD00086E6| >= b5a)                          /* speed at or above the creep speed threshold */
b5a = Lut1dB(c11 == 10 ? 0x8004095C : 0x80040968)[a0-0xce4], then min(b5a, CAL a1-0x628a [1280]) if cb5 == 1
```

- **Callers and readers.** It is called only from reason 11. `aa4` is read only by reason 11, at
  `0x800503E0`, `0x800508C0` and `0x80050A28`, plus its writer's read-back and init. Nothing else in the
  decoded image uses it.
- **`c11` (`a0-0xc11`) takes only 5, 10, 20 and 40** in its writer `0x8004CBAC..0x8004D69A`, plus 0xFF at init.
  - That is PROG's gear encoding (`dlcm-torque-limiter-code-trace.md`, "Map selection, per gear").
  - 40 = D and 10 = R are measured there; 5 = P and 20 = N are inferred from shifter order.
  - Its transitions use `a0-0x9ee`, ECM2's snapshot of PROG's gear byte `0xD00050AE`, gated by further
    flags that have not been traced.
- **Both threshold tables are flat 1920 in stock, C4c and f7.** So in these images the axis `a0-0xce4` and
  the D/R table choice have no effect. The cap is 1280 in all three.
- **Units, a HYPOTHESIS (inferred, not measured):** `0xD00086E6` is ECM2's filtered speed × 282/256
  (`0x8005872C`), the same scaling as PROG's speed index, at 2.203 counts per CAN motor rpm.
  - 1920 ≈ 870 rpm ≈ 9 mph.
  - 1280 ≈ 580 rpm ≈ 6 mph.
- **`cb5` is traced by the `Coda DLCM work` session.** It is set by a 3-term condition with a 210 ms debounce,
  and cleared after 3.01 s.
- **It matches requirement 13.5.9** (worklog §3AJ.4): creep goes to 0 in N and P, and creep is not higher than
  the max allowed.

## 5. ECM2's creep ceiling `b60`/`b62`, `0x80050AFE..0x80050F06`

From `artifacts/creep_monitor_span_80050AFE.c.txt`:

```
b5c = (0xD00086EC == 0) ? 0x7FFF
      : sat16(CAL a1-0x6294 [1000] * 0x3439 / (PROG u8 0x80040A54 [0] * |0xD00086EC| * 7))
b5e = aa2 ? CAL a1-0x6290 [800] : Lut1dA(0x80040938)[|0xD00086E6|]
b60 = cb5 ? max(b5e, min(b5c, CAL a1-0x6292 [800])) : b5e
b62 = MathIirFirstOrderQ14(b60, A = a1-0x628e, B = a1-0x628c)    /* both 16384: pass-through, b62 == b60 */
```

- **Inputs:** `0xD00086EC`, `0xD00086E6`, `aa2`, `cb5` and CAL only. **It never reads `0xD000513A`,
  `a0-0xa18`, or any creep-block variable.**
- **The `b5e` table is ECM2's own copy of PROG's creep ceiling.**
  - x = 0, 128, 256, 512, 640, 768.
  - y = 0, 570, 1070, 2080, 3000, 3200.
  - Same values in separate CAL bytes: `0xA0021B04` here, `0xA0021584` in PROG. Identical in stock, C4c
    and f7.
- **`aa2` is reason 11's direction-window latch,** written at `0x8005081E`. It is not the same flag as reason
  15's `aad`; the `Coda DLCM work` session has tabulated the two.
- **The divisor is 0 whenever `0xD00086EC` != 0.** The PROG byte `0x80040A54` is 0, read by `ld.bu` at
  `0x80050C9A`.
  - Emulating the decompiled `dvinit`/`dvstep` steps gives `b5c` = 0. That emulation is not silicon, and the
    `Coda DLCM work` session treats the value as **unresolved**.
  - The bound: the two candidate values change `b60` only when `aa2` = 0 and |`0xD00086E6`| is below about 187
    counts.
  - The byte is in PROG, so it is the same in every image.

## 6. Caveats

- **Address scans can't see a write made through a pointer** held in a register or a structure.
- **15.4 % of the populated PROG region is not disassembled.** The `Coda DLCM work` session spot-checked it as
  constant pools and descriptor banks; that is not proven.
- **A stale `aa4` is possible in principle.** `FUN_80045640`, a context-save-area headroom check, can return
  early inside `FUN_80050F16` while passing in the caller, which would leave `aa4` stale for one tick. A fault
  needs more than 5 consecutive ticks.
- **This covers the one ECM2 monitor that reads the creep output.** Monitors that see the car drive
  differently (speed, torque, timing) are affected by any calibration change and are not covered here.

## 7. Files

- `artifacts/creep_enable_xref_scan.py`, `artifacts/creep_enable_descriptor_check.py` (+ `.out.txt`)
- `artifacts/creep_monitor_span_80050246.c.txt`, `_80050F16.c.txt`, `_80050AFE.c.txt`: raw full-span
  decompiles
- `ghidra/scripts/DlcmSpanDecompile.java` decompiles one function over a ret-to-ret span. It refuses to run on
  the shared `~/ghidra-projects`, so run it on a scratch copy of `dlcm_tricore`.
