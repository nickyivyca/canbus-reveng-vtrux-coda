# DLCM SecurityAccess — where the seed/key lives

Scope: the DLCM UDS **SecurityAccess** (seed/key) handshake — which bus it is on,
which module terminates it, and where the key algorithm lives in firmware. This
is a **separate concern** from the torque/CAL reverse engineering in
`coda-dlcm-decompile-notes.md`; that file remains the reference for the DLCM code
structure, SH-4 details, the Ghidra project (`dlcm_analysis`), bootloader/HAL
layering, and the CAL torque tables. Cross-reference it for anything about how
the binary is laid out or disassembled.

*Last updated: 2026-09-24*

---

## 1. The handshake is on D CAN, terminated by the DLCM (gateway passes it through)

**Question:** does the GWM (gateway) handle SecurityAccess for the DLCM, or does
it forward the diagnostic session to the DLCM on D CAN and let the DLCM do it?

**Answer: the DLCM does it, on its own bus.** The GWM is a transparent bridge for
the `0x7E0`/`0x7E8` ISO-TP frames between the J1962 Diag CAN and D CAN.

### Evidence

The Omitec-side flash captures (`coda_dlcm_flash6.log`, `flash5.log`) are
**Diag-CAN-only** — every frame is a diagnostic ID (`0x7E0`, `0x7E8`, `0x710`,
`0x718`, `0x7DF`, `0x734`, `0x758`, `0x7ED`, `0x591`, `0x592`, `0x603`), with no
normal vehicle broadcasts. They can't show which internal bus the DLCM is on.

An **Android 2-bus capture recorded the D CAN side during the same flash**, found
by timestamp correlation:
- `coda_dlcm_flash6.log` internal start: **2026-04-26 15:13:13** (BUSMASTER header).
- Android session `coda_20260426_151050_T0..T11` (5-minute chunks, 15:10:50 →
  16:10:50) fully covers it. Copied to `dcan_flash_capture/` (see its README).

Channel mapping from anchor IDs (per `../../README.md`):
- **Channel 1 = B CAN** — carries `0x381` (BMS), shared IDs; **no** D CAN
  exclusives, **no** diagnostic traffic.
- **Channel 2 = D CAN** — carries the D CAN exclusives `0x308`/`0x312`/`0x325`
  **and** the entire diagnostic flash session.

Per-(ID, channel) counts across the 12 chunks:

| ID | ch1 (B CAN) | ch2 (D CAN) | meaning |
|----|-------------|-------------|---------|
| `0x7E0` (tester req) | 0 | **286,281** | matches flash6 exactly |
| `0x7E8` (DLCM resp) | 0 | **15,593** | matches flash6 exactly |
| `0x308`/`0x312`/`0x325` | 0 | ~166k each | D CAN exclusives |
| `0x381` (BMS) | 3,433 | 0 | B CAN anchor |

The **SecurityAccess frames themselves are on channel 2 (D CAN)**:

```
Rx 2 0x7E0  02 27 01                  requestSeed
Rx 2 0x7E8  06 67 01 7C 87 6E 19 55   seed = 7c876e19
Rx 2 0x7E0  06 27 02 27 26 96 6F 00   sendKey = 2726966f
Rx 2 0x7E8  02 67 02                  access granted
```

And the DLCM's **own broadcast `0x212` stops during the flash** on D CAN (T0
pre-flash: 15,000 frames → T6 mid-flash: **0**) — the DLCM is the module in
bootloader mode, and it is the node answering `0x7E8` on its own bus.

**Conclusions (confirmed):**
- The `0x7E0`/`0x7E8` diagnostic session physically traverses **D CAN**.
- The **DLCM** generates the seed and validates the key — it is the endpoint.
- The **GWM does not compute or check the key**; it only bridges the frames
  (consistent with the interposer/proxy design, which passes `0x27`/`0x67`
  through untouched — see `coda-dlcm-decompile-notes.md`).

Extraction: `artifacts/out_of_band_traffic.py` (flash6 ID inventory), plus the
`awk`/`grep` channel-mapping over `dcan_flash_capture/`.

---

## 1e. Levels 01/02 PROVEN ON THE CAR (2026-09-20)

The last unproven link to a laptop-driven flash is closed. Every unlock before this was
level 03/04 in an extended session; level 01/02 lives behind a different subfunction in
the **programming session (0x02)** and had never been exercised on this vehicle.

Run by `artifacts/dlcm_unlock_probe.py` (D CAN, Innomaker gs_usb, car in READY, parked).
Logs: `artifacts/unlock_probe_L3.log`, `artifacts/unlock_probe_L1.log`.

| Level | Session response | Seed | Our key | ECU |
|---|---|---|---|---|
| 3 (smoke test) | `500300321388` | `df57aa23` | `4b0c52ef` | `6704` **accepted** |
| **1 (flash-time)** | `500200640bb8` | `b9b3dab6` | `60bdba49` | `6702` **accepted** |

Both keys were computed by us from the recovered 48-round LFSR (`../../tools/flash_sim/seedkey.py`,
self-test 13/13). The level-3 run was deliberately done **first**, as a smoke test of the
identical code path, so that a level-1 failure could not be confused with a toolchain,
bus or dongle fault. That ordering is worth repeating for any future first-time probe.

Session parameters differ: extended `0x03` returns P2 = `0x0032`/`0x1388` (50 ms/5000 ms),
programming `0x02` returns `0x0064`/`0x0BB8` (100 ms/3000 ms).

**Programming session 0x02 did not disturb the running application** -- `0x212` continued
broadcasting normally throughout. Consistent with the 2026-07-21 capture, in which the
DLCM's broadcast stops 36 ms after the ERASE rather than at session entry. This is an
observation about *this probe*, which never erases or downloads; it is **not** a claim
that session 0x02 is inert in general.

## 1a. CORRECTION: the DLCM also has SecurityAccess levels 03/04, in the EXTENDED session (2026-09-19)

Sections 2 and 3 below were written believing the DLCM had only levels 01/02, validated by
the bootloader during a flash. **Both beliefs are wrong.** Evidence: the Omitec's
`Enable Backdoor` function, captured on D CAN in
`dcan_uds_capture_20260919/coda_20260919_182618_T0.log` at t=22.17-22.35 s
(moved out of `CANLogs/CodaLogs/` 2026-09-20 -- see that folder's README).

```
10 01              -> 50 01 00 32 13 88
10 03              -> 50 03 00 32 13 88     EXTENDED session
27 03              -> 67 03 19 56 27 BC     seed, LEVEL 3
27 04 05 24 E7 59  -> 67 04                 key ACCEPTED, access granted
2E FD 05 01        -> 6E FD 05              WriteDataByIdentifier FD05 = 0x01, succeeded
10 01              -> 50 01 00 32 13 88     back to default (unlock released)
```

### Why this matters

**a. Levels 03/04 exist on the DLCM.** Section 2's "level 0x01 / 0x02 -- distinct from BMS
(`0x03/0x04`) and gateway (`0x03/0x04`)" is disproven; the DLCM answers `27 03`/`27 04` too.

**b. It unlocks in the extended session -- no programming session, no erase.** Every
previously known security path ran through a flash sequence that destroys the application
36 ms after the erase command (section 3a). This one does not touch the flash at all and is
safe to repeat on a running vehicle.

**c. The APPLICATION validates it, so the algorithm is in PROG -- which we have.** The
DLCM's own `0x212` broadcast runs continuously at 10 ms cadence straight through the whole
exchange (**max inter-frame gap 21 ms** across t=21.0-23.5 s, 250 frames), so no reset
occurred and the bootloader was never running. Section 3's conclusion therefore does **not**
hold for levels 03/04. Section 3 itself named the escape hatch: *"a jump-table dispatch (SID
used as an index, no `CMP/EQ`) would not show in this scan."* That is evidently what
`coda_dlcm_prog.bin` uses.

This is the most tractable position the seed/key problem has been in: the binary is in hand,
the Ghidra project exists, and there is a known-good pair to validate any candidate
implementation against.

**d. `FD05` is the backdoor flag and is writable.** The exhaustive DID sweep
(`dlcm-uds-live-access.md` section 3.1) found `FD05` returning `NRC 0x33` on *read*; it sits
behind level 3. `0x2E` writes are accepted once unlocked.

**e. Enabling the backdoor changed nothing observable to an independent tester.** A full
`0x23` + gated-DID re-probe immediately afterwards found zero newly readable addresses, an
identical window boundary, and all six DIDs still `NRC 0x33`. The Omitec dropped to default
session 23 ms after the write, releasing the unlock, and `FD05=01` does not by itself widen
`0x23`.

### Level 03/04 seed/key pair

| Session | Level | Validated by | Seed | Key | seed XOR key |
|---|---|---|---|---|---|
| backdoor 20260919 | **03/04** | **application (extended session)** | `195627BC` | `0524E759` | `1C72C0E5` |

**SOLVED 2026-09-19 -- see section 1c.** The speculation that once stood here, that 03/04
must be a *different* algorithm from 01/02, is **disproven**: it is one algorithm with two
per-level constants.

**Harvesting more pairs is nearly free:** each press of `Enable Backdoor` triggers a fresh
`27 03` seed and the Omitec's computed key, the Android logger captures it automatically,
and there is no erase risk.

---

## 1b. The UDS service dispatch table in PROG (2026-09-19, CORRECTED)

Section 3's scan looked for `CMP/EQ #SID,R0` and found none, concluding PROG had no UDS
handler. The dispatch is in fact a **table**, at **`0x80041250`**, adjacent to the DID
descriptor tables at `0x80040C38` / `0x80041174`.

> ### READ THIS BEFORE DECODING ANY TABLE IN THIS FIRMWARE
>
> **This firmware puts the key field AFTER the pointers, in at least two unrelated table
> formats.** Assume that layout until proven otherwise; assuming a leading key has now
> produced two separate wrong results one day apart, both of which survived initial review
> because the misread table still looked structurally plausible:
>
> | Table | Wrong assumption | Actual |
> |---|---|---|
> | UDS service dispatch, `0x80041250` | `SID` first, handler at +0x0C | handler first, then `SID` |
> | DID descriptor, `0x80040Bxx`+ | `DID` first, handler at +0x0C | record starts **0x0C before** the DID |
>
> The failure mode is identical in both: every key is paired with a **neighbouring**
> record's pointer, so the result is self-consistent, all pointers are in range and
> even-aligned, and nothing looks wrong until a value contradicts measurement. In both
> cases the tell was the same -- a record's "preceding" pointer equalling the previous
> record's "own" pointer. Check for that chain before trusting any field offset here.

**Record format: `handler pointer (little-endian)` FIRST, then `SID | flags | 00 | 00`.**

> An earlier version of this section had the field order reversed and therefore
> **misassigned every SID to the handler of the preceding record**. Corrected 2026-09-19
> after the Ghidra session flagged it; the corrected reading is verified below by evidence
> independent of the table itself.

| SID at | Handler | SID | flags | Service |
|---|---|---|---|---|
| `0x80041250` | `0x8007890A` | `10` | `11` | DiagnosticSessionControl |
| `0x80041258` | `0x80078A74` | `11` | `19` | ECUReset |
| `0x80041260` | `0x80078B10` | `14` | `18` | ClearDTC |
| `0x80041268` | `0x80078B8C` | `19` | `10` | ReadDTCInformation |
| `0x80041270` | `0x80078F10` | `22` | `10` | ReadDataByIdentifier |
| **`0x80041278`** | **`0x8007907C`** | **`27`** | **`0B`** | **SecurityAccess** |
| `0x80041280` | `0x80079490` | `28` | `19` | CommunicationControl |
| `0x80041288` | `0x800795C0` | `2E` | `02` | WriteDataByIdentifier |
| `0x80041290` | `0x800795F0` | `31` | `0B` | RoutineControl |
| `0x80041298` | `0x80079940` | `3E` | `19` | TesterPresent |
| `0x800412A0` | `0x80079978` | `85` | `19` | ControlDTCSetting |
| `0x800412A8` | `0x800799F0` | `BC` | `02` | **proprietary, non-standard SID** |
| `0x800412B0` | `0x80078FCC` | `23` | `02` | ReadMemoryByAddress |

### Independent confirmation of the corrected order

NRCs `0x35` invalidKey and `0x36` exceedNumberOfAttempts exist in **no UDS service other
than SecurityAccess**. Counting their occurrences inside each handler's extent:

- `0x8007907C` (SID `27` under the corrected reading) is the **only** handler containing
  both — `0x35` x4 and `0x36` x1.
- Under the old reading, SID `27` pointed at `0x80079490`, which has `0x35` x3 and `0x36`
  x0, and which the Ghidra session identifies as CommunicationControl by its body
  (subfunctions 0/1/3, communicationType 1/2, request length exactly 3).

**Resolved: `0x23 ReadMemoryByAddress` is NOT missing.** The earlier version recorded its
absence as an open anomaly. It has an entry at `0x800412B0` -> handler `0x80078FCC`, whose
body reads an addressAndLengthFormatIdentifier and memcpys out. The `00 32 13 88` bytes
previously mistaken for the end of the table are still the P2/P2* session timing pair, one
field further along than assumed.

The `flags` byte remains **unidentified** (values `02`, `0B`, `10`, `11`, `18`, `19`).
`0x27` and `0x31` share `0B`; `0x2E`, `0xBC` and `0x23` share `02`. Plausibly a
session/security mask, but that is a **hypothesis**.

`0x800799F0` (proprietary SID `0xBC`) is unexamined and worth a look -- a non-standard
service on a diagnostic ECU is where vendor functionality tends to live.

### Note on the instruction set

The DLCM is **not SH-4**. It is an **Infineon TriCore, little-endian** (established by the
Ghidra session 2026-09-19; `tricore:LE:32:default` disassembles the image cleanly). The
"529 Continental variant opcodes" and the patched SuperH4 SLEIGH were a wrong-ISA decode
being treated as obfuscation. That correction is now written up in full in
`coda-dlcm-decompile-notes.md` -> Architecture (evidence, the post-mortem of why the SH-4
conclusion looked well-supported, and what it does and does not invalidate); `ghidra/README.md`
and `tools-reference.md` carry the tooling consequences. It invalidates more than this file.

Two consequences here. First, the dispatch table above is **unaffected**: it rests only on
table bytes, all handler pointers being in range and even-aligned, and the NRC evidence.
Second, a note in the earlier version of this section about a "false lead" at `0x80055EEA`
matching `MOV #0x67,R1` is void -- there is no SH-4 instruction to match. The observation
that the bytes sit in a template repeating every 0x28 with one varying slot still stands,
and under TriCore the `40 4C` / `40 4D` / `40 4F` family that appears at handler entry
points is one 16-bit `mov.aa` opcode with differing register operands, which is exactly the
"parameterised by one nibble" pattern noted at the time.

Tooling: `artifacts/prog_sid_dispatch_hunt.py` (+ `.out.txt`). Note its Phase 4 searches for
SH-4 encodings and is therefore meaningless; Phases 1-3 and 5 are byte/pointer analysis and
remain valid.

---

## 1c. SOLVED: the seed/key algorithm (2026-09-19)

Recovered by the Ghidra session from the SecurityAccess handler at `0x8007907C`, once the
image was disassembled as TriCore rather than SH-4.

```c
uint32_t key(uint32_t seed, uint32_t secret) {
    uint32_t v = seed ^ secret;
    for (int i = 0; i < 48; i++)
        v = (v << 1) | (((v>>4) ^ (v>>11) ^ (v>>20) ^ (v>>29)) & 1);
    return v;                       /* 32-bit; seed and key both big-endian on the wire */
}
```

A 48-round Galois-style LFSR, taps at bits 4/11/20/29, keyed by a per-level constant:

| Level | Service | Constant |
|---|---|---|
| 1 | `27 01` / `27 02` | `0xCAF77776` |
| 3 | `27 03` / `27 04` | `0x9D89EA36` |

**One algorithm, two constants** -- not two algorithms, as section 2 and the original
section 1a both assumed.

### Verification (run independently in this session, not taken on trust)

All **13** captured pairs reproduce:

- **9/9** level-03/04 pairs harvested live on 2026-09-19 under `secret = 0x9D89EA36`
  (`artifacts/seedkey_pairs.md`).
- **3/4** historical level-01/02 pairs under `secret = 0xCAF77776` -- flash5, flash6 and
  20260721.
- The remaining one, **flash2** (`seed 86BD0760 -> key C6CCDA14`), does **not** fit the
  level-1 constant but reproduces **exactly** under the level-3 constant. A false match is
  ~2^-30, so flash2 was almost certainly a **level 03/04** session mislabelled as 01/02 in
  section 2's table. The capture would need re-checking to confirm which subfunction was
  actually used; until then treat section 2's level attribution for flash2 as **suspect**.

So: 13/13 with flash2 relabelled.

### What this enables, demonstrated on the car

With the algorithm we no longer need the Omitec. Verified live 2026-09-19
(`artifacts/dlcm_level3_unlock.py`): `10 03`, `27 03`, compute, `27 04` -> **`67 04`, our
own key accepted**. The six DIDs that return `NRC 0x33` when locked then read out:

| DID | Value | Note |
|---|---|---|
| `A10C` | `11 22 33 44` | placeholder/test pattern |
| `A10D` | `1A E4 63 BC 98 90 DB E3` | 8 bytes, high entropy |
| `A10E` | `AB 56 28 EF` | |
| `A10F` | `0D 99 F2 3A` | |
| `FD05` | `01` | the backdoor flag, set by the Omitec |
| `FD06` | `00` | same family, never written by the Omitec |

**The unlock does NOT widen `0x23`.** Fully unlocked at level 3, `0xD9047B5C`, the CAL
tables, PROG and the filter ring buffer all still return `NRC 0x31`. The
ReadMemoryByAddress allow-list is **independent of security level** -- see
`dlcm-uds-live-access.md` section 2. Route A is blocked by an address table, not by
permissions.

### `FD06`, and why it was not written

`FD06` is a structural twin of the backdoor flag: both are 1-byte DIDs, **mode 2**
(memcpy from a data pointer) rather than the `85xx` block's mode 3 (call a handler), with
adjacent RAM homes.

**CORRECTED 2026-09-19** -- the DID descriptor layout was initially read with the key at
offset 0, which shifted every field by one record:

```
  record starts 0x0C BEFORE the DID
  +0x00 data ptr | +0x04 handler A | +0x08 handler B | +0x0C DID | +0x0E len | +0x11 mode&7
  mode 2 = memcpy from data ptr ; 3 = call handler A ; 4 = call handler B
```

Correct values, verified against the binary:

| DID | record start | data ptr | mode |
|---|---|---|---|
| `FD05` | `0x80040BB4` | **`0xD00051C2`** | 2 |
| `FD06` | `0x80040BC8` | **`0xD0006C56`** | 2 |

An earlier version of this section gave `FD05 -> 0xD0006C56` (which is in fact `FD06`'s)
and `FD06 -> 0xD0006C52` (which belongs to neither).

What `FD06` *controls* remains **unknown**, and the earlier attempt to answer it by
searching for 32-bit literal references was **methodologically void**, not merely
inconclusive: on TriCore, addresses are built with `movh.a` + `lea` pairs and never appear
as contiguous 4-byte literals. Confirmation -- the getter targets `0xD0007FAC` (DID `8525`)
and `0xD0007FE0` (DID `8515`) are provably read by code, yet have **zero** literal
references. Use the `movh.a`/`lea` reconstruction (`ghidra` session's `cal_code_xref.py`)
for any question of this shape.

**TESTED 2026-09-19, with the user's explicit authorisation** -- the only write this
project has ever initiated toward the DLCM (`artifacts/dlcm_fd06_experiment.py`).

The prerequisite was established first: **these flags are volatile.** `FD05` read `01`
after nine Omitec writes and **`00`** after an ignition cycle, making a key cycle a proven
reset path. (`A10C`-`A10F` are *unchanged* across the cycle, so the `FDxx` flags and the
`A1xx` values are structurally different: volatile state vs. stored values.)

Result: `2E FD 06 01` was **accepted** (`6E FD 05`... `FD06` reads back `01`), and
**nothing observable changed**:

- `0x23` reachability byte-for-byte identical before and after -- `0xD9047B5C`, both CAL
  V-curve copies, PROG base, the SecurityAccess handler, the DID string pool, the window
  edge at `0x80001E00` and `FD06`'s own RAM byte all still `NRC 0x31`.
- The six level-3 DIDs unchanged apart from `FD06` itself.
- 16 DIDs that returned `NRC 0x31` in the exhaustive sweep (`FD00`-`FD0A`, `A100`/`A105`/
  `A110`/`A111`, `8503`/`8504`/`851A`/`851F`) remained unreadable.

`2E FD 06 00` was then accepted and `FD06` reads `00`, so it is reversible by write as well
as by key cycle. **The ECU is back in its stock state.**

Conclusion: `FD06` gates nothing reachable over diagnostics. It may gate behaviour rather
than diagnostic access, or be vestigial. Recorded so this is not repeated -- the useful
follow-up is the `0x2E` handler at `0x800795C0` under a correct TriCore decode, not more
poking.

---

## 1d. Level map, and the closed question of the 0x23 allow-list (2026-09-19)

### Levels the DLCM offers

| Level | Reachable from | Constant | Status |
|---|---|---|---|
| `01`/`02` | bootloader (flash) **and application** (extended session) | `0xCAF77776` | solved, verified |
| `03`/`04` | application, extended session | `0x9D89EA36` | solved, verified |
| **`7D`/`7E`** | application, extended session -- **returns a seed** | **not a constant** -- reads an out-of-bounds RAM counter, see below | **explained, not obtainable by guessing** |

**Level 01/02 is not bootloader-only.** Verified live: in the extended session on a running
car, `27 01` -> `67 01 6D5C377E`, and our computed key `654F0F32` under `0xCAF77776` was
**accepted**. So the same constant validates against both the bootloader and the
application.

**Level 01 and level 03 are equivalent from the tester's side.** Under level 1 the six
gated DIDs return byte-identical values to level 3, and `0x23` is unchanged. Whatever
distinguishes the levels, it is not diagnostic access.

**Level `7D`/`7E` exists and is new.** `27 7D` returns a seed (`67 7D 47552926`), so the
level is real and offered by the application. A candidate constant of `0x00000000` -- taken
from its position in the array at `0x800948B4`, with no matched pair behind it -- was tried
once and **rejected with `NRC 0x35 invalidKey`**. One failed attempt of a maximum of two
was consumed; testing stopped there by prior agreement. The real constant is unknown and
recovering it means decompiling the level table / key check rather than guessing.

#### Why level `7D` failed: the constants array is one-based and level `7D` underflows it

Decompiled after the fact, from `FUN_80079372` at `0x800793A0`:

```
800793A0  sha     d15,d4,#0x2        ; d15 = level_index * 4
800793A8  add     d15,#-0x4          ; d15 = level_index * 4 - 4      <-- one-based
800793AA  lea     a2,[a0]-0x4074     ; base = element [1]
800793AE  addsc.a a2,a2,d15,#0x0
800793B2  ld.w    d4,[a2]            ; secret = base[index - 1]
```

**The array holds two entries and is indexed from 1.** Element `[1]` is `0xCAF77776`
(level 1, row index 1) and element `[2]` is `0x9D89EA36` (level 3, row index 2) -- which is
exactly the mapping the 14 verified pairs confirm. Level `7D` is **row index 0** in the
level table at `0x80041220`, so it computes `base - 4` and reads the word *before* the
array, at `a0-0x4078`.

That word is not key material. Its only two accessors anywhere in the image are
`FUN_8007f654` (`ld.w d2,[a0]-0x4078; ret` -- read it) and `FUN_8007f65c`
(`*p = *p + 1` -- increment it), called from `0x8007de28`, `0x8007de38`, `0x8007eadc`,
`0x8007eaee` and `0x8007eaba` -- an unrelated subsystem, nowhere near the SecurityAccess
code. A byte-level scan for any `A0`-based instruction touching the three array slots finds
**no store to any of them**, so the constants themselves are written once by the `.data`
copy at startup and never again.

So **level `7D`'s expected key is `LFSR48(seed ^ <that counter>)`, and the counter changes
at runtime.**

This also explains the failed attempt. The flash initialiser for `a0-0x4078` *is*
`0x00000000` (at `0x800948B4`), so the guessed constant was correct at reset -- but the test
was run at the end of a long session, by which time the counter had been incremented.

- **Established:** the addressing above, the one-based indexing, and the identity of the
  two accessor functions. These are read directly off the instruction stream.
- **Hypothesis:** that this is an off-by-one bug rather than deliberate. An increment-only
  counter owned by an unrelated subsystem is a poor cryptographic constant, which is why
  the bug reading is preferred -- but intent is not established.

**Consequences for any future attempt.** A captured `7D` pair would reveal only the counter
value at that instant, not a reusable constant, so the usual "one pair solves it" shortcut
does not apply here. There is one testable prediction: if the counter is still zero at cold
boot, `secret = 0x00000000` would be accepted in the first seconds after an ignition cycle,
before whatever increments it has run. That is worth at most one attempt, from a cold start,
and it is untested. Given that levels 1 and 3 are already solved and grant identical
diagnostic access, the expected value of chasing `7D` at all is low.

### The 0x23 allow-list is HARDCODED -- do not re-chase this

Four independent negatives, each measured:

1. Security level makes no difference: fully unlocked at **level 3**, every Route A target
   still `NRC 0x31`.
2. Nor at **level 1**: same result.
3. `FD05 = 01` alone: no change (section 1a).
4. `FD06 = 01` alone: no change (section 1c).
5. **Unlocked AND `FD05 = 01` held in the same session** -- the one combination the Omitec
   never allowed anyone to test, because it always dropped to default session immediately.
   Measured 2026-09-19: `0xD9047B5C` and `0x80021528` **still `NRC 0x31`**.

The readable window `0x80000000`-`0x80001DFF` is fixed and is not unlocked by any
credential or flag available over diagnostics. See `dlcm-uds-live-access.md` section 2.

---

## 1f. The algorithm is NOT DLCM-specific — cross-module constant map (2026-09-24)

The 48-round LFSR in section 1c is the **Coda module family's** SecurityAccess algorithm,
not the DLCM's alone. Same taps (4/11/20/29), same round count, same big-endian wire
order; only the constant changes, per (module, level).

    key = LFSR48(seed XOR constant)

| Module | Diag ids | Level | Constant | Basis | Confidence |
|---|---|---|---|---|---|
| DLCM | `0x7E0`/`0x7E8` | `01`/`02` | `0xCAF77776` | read from binary | confirmed |
| DLCM | `0x7E0`/`0x7E8` | `03`/`04` | `0x9D89EA36` | read from binary | confirmed |
| BMS | `0x722`/`0x72A` | `01`/`02` | `0x3D700822` | 26 distinct captured pairs; **granted live on the car twice** | confirmed |
| BMS | `0x722`/`0x72A` | `03`/`04` | `0x2E56D6B7` | 1 pair (the 2026-04-25 flash) | **unconfirmed** |
| Gateway | `0x710`/`0x718` | `03`/`04` | `0x92A2CBF8` | literal at `0x01A58`, loaded by `ldr r3,=…` at `0x01544` in `coda_gateway.bin` | confirmed |

**31/31 captured pairs across all three modules reproduce** under this table.

### How the non-DLCM constants were recovered

By inverting the LFSR over captured seed/key pairs. The procedure's control is this file's
own data: inverting the DLCM's captured pairs recovers exactly the constants independently
read out of the DLCM binary, which is what licenses trusting it elsewhere.

**Bits 30 and 31 of any constant are unobservable, and it does not matter.** The taps are
4/11/20/29, so those two bits are shifted out before reaching any tap and cannot affect the
key. Inversion therefore returns a 4-element set differing only in them, and all four
compute identical keys — verified explicitly. The values above are usable as-is.

This is why a *single* pair can never confirm the algorithm for a new module: inversion
always yields some constant. Two distinct pairs agreeing is the real test, which is why the
BMS level 01/02 row is confirmed and its level 03/04 row is not.

### The gateway constant was found a different way

The gateway image is plaintext ARM, and ARM builds 32-bit constants in literal pools rather
than TriCore's `movh.a`/`lea` pairs, so the constant appears verbatim. Exactly one of the
four inversion candidates is present in the image, which both confirms the algorithm for
that module and resolves the two otherwise-unobservable top bits.

### Implementation

`../artifacts/coda_security_access.py` — the table above plus `security_key(seed, module,
level)`, with a regression test over every captured pair in the corpus.

Harvester and evidence: `../artifacts/harvest_seedkey_all_ecus.py`,
`../artifacts/gateway_seedkey_literal_hunt.py` (+ `_out.txt` for both).

### BMS-specific operational notes

Two findings from the 2026-09-24 live session that apply to the BMS and are recorded in
full in `../coda-bms-decompile-notes.md`:

- **`10 03` on the BMS drops the HV contactors.** Entering the extended session is a
  vehicle state change, not an observation.
- **The unlock must be atomic**: `10 03` → `27 01` → `27 02` with nothing interleaved.
  Interleaving other requests returns `7F 27 22` conditionsNotCorrect — *not* invalidKey.

---

## 2. Known seed/key pairs (bootloader-validated, level 01/02)

DLCM SecurityAccess is **level 0x01 (requestSeed) / 0x02 (sendKey)** — distinct
from BMS (`0x03/0x04`) and gateway (`0x03/0x04`). All three captured pairs come
from **programming-session** flashes, so they were validated by the **bootloader**
(see §3). Extracted by `artifacts/security_access_extract.py`.

| Session | Seed | Key | seed XOR key |
|---------|------|-----|--------------|
| flash5 | `89349739` | `3BED538A` | `B2D9C4B3` |
| flash6 | `7C876E19` | `2726966F` | `5BA1F876` |
| 20260721 | `FEED78D7` | `51D17AD2` | `AF3C0205` |

> **flash2 removed from this table 2026-09-19.** It was never a level-01/02 pair and
> `projects/coda/logs/flash/coda_dlcm_flash2.log` is not a flash. The whole log is 29 lines:
> `10 03` -> `27 03` -> `67 03 86BD0760` -> `27 04 C6CCDA14` -> `67 04` -> `2E FD 05 01`
> -> `6E FD 05` -> `10 01`. No `10 02`, no erase, no RequestDownload, no TransferData.
> That is an **Enable Backdoor session at level 03/04**, application-validated in the
> extended session -- the same sequence captured live on 2026-09-19 (section 1a), so the
> Omitec's backdoor function has been used on this vehicle before.
>
> Found because its key reproduces under the **level-3** constant and not the level-1 one
> (section 1c); the log then confirmed the subfunction directly. The pair now lives in
> `artifacts/seedkey_pairs.md` with the other level-03/04 pairs. **The file is misnamed**
> and the remaining three rows above are the only genuine bootloader-validated pairs.

A **fourth pair** was extracted 2026-09-19 from
`dcan_flash_capture_20260721/coda_20260721_202537_T11.log`.

Seeds are ECU-generated and differ every session; the XOR is not constant, so it
is not a fixed XOR/add/rotate. During the 2026-07-20 real-Omitec run against
`../../tools/flash_sim/gateway_sim.py` (which returns the fixed flash6 seed), the real Omitec
recomputed `2726966F` — confirming the algorithm is deterministic for a given
seed, but not revealing it.

---

## 2a. The bootloader's RSA keys do NOT explain the seed/key (2026-09-19)

On 2026-09-19, UDS `0x23` turned out to be **unlocked** but allow-listed to
`0x80000000`-`0x80001DFF` -- the first 7680 bytes **of the bootloader region**
this file's section 4 says we lack. Two **RSA-1024 public keys** (e = 65537,
1022-bit moduli) sit in it at `0x80000524` and `0x80000638`. Full detail:
`dlcm-uds-live-access.md` section 2.

Tested against all four seed/key pairs (`artifacts/seedkey_vs_rsa.py`):

- no constant XOR / add / sub / rotate / byteswap fits all four pairs;
- `key` is **not** any 4-byte slice of `seed^65537 mod n`, for either modulus,
  in either endianness;
- none of the 1020 distinct 32-bit constants in the window works as an
  XOR/add/mul key.

This is structural rather than bad luck: an RSA **public** key verifies
signatures, it cannot generate a 32-bit challenge response. The keys almost
certainly serve **firmware image signature verification** by the bootloader.
They also do **not** allow signing a modified image -- that needs the private
key.

So the seed/key algorithm remains unrecovered, and section 4's option 1 (dump the
bootloader) is still the direct path -- but note that `0x23` now gives us 7680
bytes of that region for free, and no more: the allow-list has exactly one
window and no second region exists (verified exhaustively).

---

## 3a. CORRECTION: the application survives the security exchange (2026-09-19)

An earlier reading in the Route A plan assumed that entering programming session
puts the DLCM in the bootloader, so that app RAM would be unavailable. **That is
wrong, and it matters for the interposer route.**

Measured from `dcan_flash_capture_20260721` T11 by timing the DLCM's own `0x212`
broadcast against the UDS sequence (`artifacts/flash_session_timeline.py`):

```
10 02           t=160.578    0x212 still broadcasting
27 01           t=160.598    0x212 still broadcasting
67 01 FEED78D7  t=160.616    0x212 still broadcasting
27 02 51D17AD2  t=160.642    0x212 still broadcasting
67 02  UNLOCKED t=160.645    0x212 still broadcasting
31 01 FF 00 02  t=160.880    ERASE
                t=160.916    last 0x212 -- app dies 36 ms AFTER the erase
```

`0x212` runs at its normal ~20 ms cadence straight through session entry and the
whole security exchange; the largest inter-frame gap anywhere in the pre-flash
chunk is 31 ms, so **no reset occurs at `10 02`**. It is the **erase** that ends
the application.

**Consequence:** if the erase is blocked -- forwarded to a shadow `gateway_sim`
instead of the real ECU, per the plan's Step 1b -- the DLCM sits in an unlocked
programming session **with the application still running and its RAM intact**.
That is exactly the state Route A needs, and it is the one remaining untested way
to widen the `0x23` allow-list.

**It requires the interposer hardware.** With a single dongle we can observe the
erase but cannot suppress it, and the unlocked-but-idle window is only **0.23 s**
(flash6) / **0.235 s** (20260721) -- measured, two independent captures. There is
**no human confirmation step** between `67 02` and the erase; the 5.4 s pause in
the capture sits before `10 02`, while the ECU is still locked.

---

## 3. The algorithm is in the BOOTLOADER, not PROG

During a flash the DLCM runs its **bootloader** (PROG is being erased/rewritten),
so the flash-time SecurityAccess is handled by the bootloader — which lives
**below PROG base `0x80040000`** (the `0x8003Fxxx` HAL/bootloader calls are
documented in `coda-dlcm-decompile-notes.md`) and is **not** in our extracted
binaries (`coda_dlcm_prog.bin` = `0x80040000+`; `coda_dlcm_cal.bin` = data only).

Confirmed by scanning `coda_dlcm_prog.bin` for the UDS service-dispatch signature
`CMP/EQ #SID,R0` (SH-4 big-endian, opcode `0x88ii`). Tool:
`artifacts/security_access_hunt.py`.

| UDS service | `CMP/EQ #SID` hits in PROG |
|-------------|---------------------------|
| 0x22 ReadDataByIdentifier | 0 |
| **0x27 SecurityAccess** | **0** |
| 0x31 RoutineControl | 0 |
| 0x34 RequestDownload | 0 |
| 0x36 TransferData | 0 |
| 0x37 RequestTransferExit | 0 |
| 0x3E TesterPresent | 0 |
| SecurityAccess NRCs (0x35/0x36/0x37/0x33) | 0 each |

The services every UDS dispatcher must handle are entirely absent from PROG. (A
few coincidental `CMP/EQ #0x10/#0x11/#0x19` hits exist but form no dispatch
cluster; `MOV #0x67`/`#0x27` appear only 1–2 times, not a responder pattern.)

**Conclusion (SUPERSEDED for levels 03/04 -- see section 1a):** PROG contains no
`CMP/EQ`-style UDS/SecurityAccess dispatch. It does **not** follow that PROG has no handler
at all: the 2026-09-19 backdoor capture proves the application validates a level-3 key with
the bootloader not running, so a **table/computed dispatch must exist in PROG**. The
statement below still stands for the **level 01/02 flash-time** handshake, which genuinely
is the bootloader's.
The seed generation and key-validation algorithm live in the DLCM **bootloader**
(`0x80000000`–`0x8003FFFF`), which we do not have.

**Residual uncertainty:** a jump-table dispatch (SID used as an index, no
`CMP/EQ`) would not show in this scan. But the complete absence of the download
services *and* the SecurityAccess NRCs, plus the documented bootloader/HAL
dependency, makes "handled in the bootloader" the strong reading.

---

## 4. Implications & paths to the algorithm

Reversing the seed/key from firmware now requires the **bootloader image**, not
PROG. Options, roughly in order of effort:

1. **Dump the bootloader region** (`0x80000000`–`0x8003FFFF`, ~256 KB) and
   decompile it. A normal flash never reads it; obtaining it needs either a UDS
   `ReadMemoryByAddress` that the bootloader permits (likely itself
   security-gated), or **JTAG/BDM** hardware access to the SH-4. This is the
   direct path and reuses the existing `dlcm_analysis` Ghidra project once the
   image is loaded at `0x80000000`.
2. **Decompile the Omitec tool** — it computes the key, so the algorithm (or its
   generator side) is in the Omitec software. Independent of the ECU.
3. **Cryptanalysis from more seed/key pairs** — only viable if the algorithm is
   weak; three pairs already rule out simple transforms.

Until one of these lands, `../../tools/flash_sim/omitec_sim.py` stays **simulator-only for
security** (it replays the one captured key and its seed guard aborts on any
other seed) — the real laptop-direct flash is blocked here. The **interposer/
proxy** path (real Omitec does SecurityAccess, MITM patches CAL bytes) remains
the way to apply the patch on real hardware without the algorithm.

---

## Related files

- `coda-dlcm-decompile-notes.md` — DLCM code structure, SH-4/Ghidra project,
  bootloader/HAL layering, CAL torque tables (the main RE writeup).
- `dcan_flash_capture/` — the B+D CAN Android capture proving §1 (2026-04-26, companion to `coda_dlcm_flash6.log`).
- `dcan_flash_capture_20260721/` — a second DLCM-flash Android capture (found by ISO-TP content; no BUSMASTER counterpart saved). See its README.
- `artifacts/security_access_hunt.py` — PROG UDS-dispatch scan (§3).
- `artifacts/security_access_extract.py` — seed/key pair extraction (§2).
- `artifacts/out_of_band_traffic.py` — flash6 diagnostic ID inventory (§1).
- `../../tools/flash_sim/` — the reflash simulators; `omitec_sim.py` seed guard.
