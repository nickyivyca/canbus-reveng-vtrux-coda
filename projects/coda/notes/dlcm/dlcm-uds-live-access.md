# DLCM live UDS access — what the ECU will tell us unlocked

Scope: what the Coda DLCM serves over UDS **without any SecurityAccess**, established
in a single bench session at the car on **2026-09-19** (`the bench PC`, Innomaker
gs_usb dongle, D CAN and OBD). Two services matter: `0x23 ReadMemoryByAddress`
and `0x22 ReadDataByIdentifier`.

This file is the reference for the **live access channel**. For the CAL/PROG code
structure see `coda-dlcm-decompile-notes.md`; for the seed/key handshake see
`dlcm-security-access.md`; for the torque limiter itself see
`dlcm-torque-limiter-code-trace.md`.

*Last updated: 2026-09-19*

---

## 1. Headline

- **`0x23` is implemented and UNLOCKED in the default session.** No SecurityAccess
  was performed at any point in this session. The plan's expectation that the
  service would be security-gated was wrong.
- **It is address-allow-listed to exactly one window: `0x80000000`–`0x80001DFF`**
  (0x1E00 = 7680 bytes). Every other address tested returns `NRC 0x31
  requestOutOfRange`. The window is **inside the bootloader region**.
- **`0x22` answers 74 DIDs unlocked** — against the 11 the Omitec polls in normal
  mode. Six further DIDs return `NRC 0x33 securityAccessDenied`.
- Several DIDs are **live internal telemetry**, and four have been identified to
  their exact DBC encodings.

---

## 2. `0x23 ReadMemoryByAddress`

### 2.1 Support and gating

| Property | Result |
|---|---|
| Service dispatched? | **Yes** — truncated request `23 14` returns `NRC 0x13` (length), never `0x11` |
| Security gated? | **No** — never once returned `NRC 0x33` |
| Session dependence | **None** — default (`0x01`) and extended (`0x03`) allow-lists are byte-identical |
| Accepted format IDs | `0x14` (4-addr/1-size), `0x24` (4/2), `0x44` (4/4) all parse |
| Max read per request | **>= 64 bytes** (1/2/4/8/16/32/64 all succeed) |
| Readable window | **`0x80000000`–`0x80001DFF`**, boundary bisected exactly |

**Note on the plan's example frame.** `dlcm_ram_read_mapping.md` gives
`23 14 D9 04 7B 5C 00 10`, which is malformed: in ISO 14229 the format
identifier's high nibble is the *memorySize* length, so `0x14` declares a
**one-byte** size. The correct 4-byte-address/2-byte-size identifier is `0x24`.

### 2.2 The allow-list is a single window, confirmed exhaustively

The first extent search only walked upward from `0x80000000` and stopped at the
first refusal, so by construction it could only find the first window. A full
region scan (`dlcm_region_scan.py`) closed that gap: fine 256-byte grid over the
whole bootloader region, coarse grids over PROG, the uncached flash alias, D0/D9
RAM, on-chip SRAM and the SH peripheral window, plus every pointer harvested from
the window itself.

**Result: 31 readable probe points, all inside `0x80000000`–`0x80001DFF`. No
second region exists.** Specifically refused: `0x80002090`, `0x80008911`,
`0x8000A000`, `0x80021528` / `0x80021B64` (the CAL V-curves), `0x80040C38`,
`0x80040000`, `0xD9047B5C`, `0xD9057B5C`, `0xD0006BEC`, `0x7F0F0880`,
`0xA0021528`, `0x00000000`, `0xFFFF8000`.

### 2.3 What is in the window

Dumped three times, byte-identical each time, so the region is static, not live.
Archived as `artifacts/dlcm_window_80000000.bin` (+ `_verify.bin`). 7680 bytes,
only 7% non-zero, in 18 populated runs.

It is the **diagnostic identification data segment**: the DID payload strings
live here (`1111CI31` at `0x80000880` is F183; `A2C3814910000` + `AK2108010000`
at `0x80001400` are F192/F191), plus part numbers at `0x80000B10`/`0x80000C00`.

A descriptor table sits at `0x80000120`: seven records, stride `0x20`, each
`{flags=0x006DF402, ptr}` with the pointers stepping by exactly **13 bytes** into
a string pool at `0x80002090` — 13 being F192's length. The pool itself is just
past the window edge and unreadable.

### 2.4 Two RSA-1024 public keys

At **`0x80000524`** and **`0x80000638`**, each a length-prefixed 128-byte modulus
followed by `01 00 00 00 01 00 01 00` — exponent **65537**. Both moduli are
1022-bit.

These are in the bootloader region, which is consistent with the bootloader
performing **firmware signature verification**. Note what this does *not* give
us: a public key verifies signatures, it cannot generate them, so it neither
breaks the seed/key handshake (see `dlcm-security-access.md` §2a) nor allows
signing our own firmware image.

### 2.5 Consequence for Route A

**Route A as planned cannot proceed.** Every address the pointer walk needs is
refused, and no session change or address form widens the allow-list. The
remaining untested branch is the programming session — see
`dlcm-security-access.md` §3a.

---

## 3. `0x22 ReadDataByIdentifier`

### 3.1 Inventory

Exhaustive sweep of all 65536 DIDs in the default session
(`artifacts/dlcm_did_sweep_full.txt`, ~11 min):

| Outcome | Count |
|---|---|
| Positive response | **74** |
| `NRC 0x31 requestOutOfRange` | 65456 |
| **`NRC 0x33 securityAccessDenied`** | **6** — `A10C`, `A10D`, `A10E`, `A10F`, `FD05`, `FD06` |

Those six are the **only** security gating found anywhere in this session; `0x23`
never gated once. Blocks: `65xx` (6), `81xx` (2), `85xx` (48), `A1xx` (6),
`F1xx` (11, the Omitec's set), `FD02`.

### 3.2 Identified signals — confirmed by exact encoding match

Correlated against `CODA-D-CAN.dbc` signals decoded live from `0x1C0`
(`MCM_CoreTelemetry`) and `0x210`, captured on the same dongle in parallel with
the DID polling. Fitted slope/intercept land on the DBC encodings exactly, which
is what makes these confirmations rather than correlations — the four reference
signals have *different* encodings, so matching one identifies the quantity.

| DID | Signal | r | Fitted slope / intercept | DBC encoding | Residual |
|---|---|---|---|---|---|
| `8513` | **HV_Current** | +0.960 | 10.39 / 32127.4 | `A*10 + 32128` | — |
| `8514` | **Motor_Speed** | **+1.000** | **2.0000 / 32128.0** | `rpm*2 + 32128` | exact |
| `8515` | **Torque** | +0.999 | **9.968 / 32127.4** | `Nm*10 + 32128` | **1.0 Nm** |
| `8516` | **HV_Voltage** | — | identity test: mean delta **0.2 counts** | `V*10 + 32128` | 0.36 V |

`8513`–`8516` are consecutive DIDs, and the Omitec panel lists
`AccurateCurrent, AccurateSpeed, AccurateTorque, AccurateVoltage` as consecutive
rows 38–41. The two orderings agree, which independently corroborates the
mapping.

### 3.3 Accelerator group

Five consecutive DIDs `8505`–`8509` track `ThottlePedalPos` with r = 0.992–0.999,
matching the panel's five consecutive rows 33–37 (`Accel 1 (volts)`,
`Accel 2 (volts)`, `Accel 1 (%)`, `Accel 2 (%)`, `Accel-evaluated`).

Structural evidence: `8505/8506` hold a ratio of **1.977** across the whole range
— the 2:1 relationship typical of dual redundant pedal sensors — and `8508`/`8509`
are bit-identical at all times. Fitted `8507` slope is **100.3 per %**, i.e.
0.01% resolution.

### 3.4 HYPOTHESIS — torque limiter bounds at `850C` / `850D`

**Not confirmed. Flagged for review before being treated as fact.**

Decoding every static 2-byte DID in the DBC torque encoding produces exactly one
striking pair:

```
850C = 0xBC00 = 48128  ->  (48128 - 32128) / 10 = +1600.0 Nm
850D = 0x3F00 = 16128  ->  (16128 - 32128) / 10 = -1600.0 Nm
                                     mean = 32128.0 -- exactly the torque zero
```

Perfectly symmetric about the torque zero point, at round +/-1600.0 Nm. The
Omitec panel lists `high_bound` (row 55) and `low_bound` (row 56) as consecutive
entries immediately after `TorqueDesired` (row 54).

Reading: `850C`/`850D` are the **live torque limiter bounds**, currently parked
at their unlimited defaults because nothing was limiting during the capture.

Why this matters: if correct, the limiter's *output* is directly observable at
runtime, unlocked, with no reflash and no RAM read — which is what Route A was
trying to reach indirectly through the CAL tables.

**Test that would settle it:** drive through the conditions where the V-curve
actually clamps (the near-zero-crossing region characterised in
`dlcm-torque-limiter-code-trace.md`) while polling `850C`/`850D`. If they move
off +/-1600 and track the clamp, the hypothesis is confirmed.

`850E` is also a torque-domain value in the same encoding (slope 10.4,
intercept 32128.9, r = 0.995 vs `Torque`) but consistently ~4% steeper than the
delivered torque — a plausible `TorqueDesired` (row 54), **unconfirmed**.

### 3.5 Lead/lag — UNRESOLVED

Whether `850E`/`8515` *lead* the broadcast torque (implying they are commands
computed upstream) is **not established**. An early apparent "+220-240 ms lead"
was an artifact of the capture tool stamping one timestamp per polling pass while
polling 62 DIDs sequentially — up to ~600 ms of skew. Per-DID timestamps were
added and a 33 Hz three-DID capture taken, but that run happened to contain no
actuation (pedal flat throughout), so the question is still open.

Re-running is cheap now that the tooling is correct: one 80 s capture with sharp
pedal transitions.

---

## 4. Omitec data panel

The Omitec exposes a 64-row DLCM live data panel. The full label list is recorded
in `artifacts/omitec_panel_labels.md`. The labels are ground truth that no amount
of correlation can supply, and several name things we care about directly:
`TorqueDesired`, `high_bound`, `low_bound`, `AccurateTorque`, `Accel-evaluated`,
`PackCurrent`, `Rotor`, `Stator`, `PRNDL_DISP`.

**The label-to-DID mapping is not yet complete.** Panel order and DID order agree
within the blocks identified above, but the DID space has gaps and the panel
skips some readable DIDs, so a constant offset does not hold globally. The clean
way to finish it is to extract the Omitec's actual DID poll sequence from an
Android-logger capture taken while the panel was open, then pair the Nth polled
DID with the Nth panel row.

**"Enable Backdoor".** The Omitec has an `Enable Backdoor` option; it was enabled
and the full `0x23` + gated-DID probe re-run. **Nothing changed** — zero newly
readable addresses, identical window boundary, all six DIDs still `NRC 0x33`. The
option therefore appears to unlock functionality inside the Omitec's own
software rather than altering ECU state.

Open possibility (untested): ECU SecurityAccess state is scoped to the diagnostic
session, not to a physical tester. If a backdoor-enabled Omitec function performs
SecurityAccess and holds the session with TesterPresent, our own `0x22` requests
on `0x7E0` may be honoured for the gated DIDs — riding along on its unlock.

---

## 5. Tooling

All in `artifacts/`. Every script is read-only toward the ECU; `dlcm_ram_probe.Probe`
enforces a service allow-list (`0x10` sessions 01/03, `0x22`, `0x23`, `0x3E`) with
an assertion before every transmit, so `0x27`/`0x31`/`0x34`/`0x36`/`0x37`/`0x11`/
`0x2E`/`0x14` cannot reach the bus.

| Script | Purpose |
|---|---|
| `dlcm_ram_probe.py` | `0x23` support probe: format matrix, existence test, sweep, extent bisect |
| `dlcm_region_scan.py` | exhaustive search for additional readable windows |
| `dlcm_full_capture.py` | window double-read + verify, exhaustive 65536-DID sweep |
| `window_80000000_analysis.py` | structure, pointer census, flash cross-reference |
| `seedkey_vs_rsa.py` | seed/key pairs vs the RSA keys and window constants |
| `flash_session_timeline.py` | UDS timeline of captured flashes, unlock-to-erase timing |
| `did_live_sample.py` | which DIDs are live vs constant |
| `did_correlate.py` | per-input DID capture |
| `did_vs_broadcast.py` | DID vs cantools-decoded broadcast signals, with lead/lag scan |
| `omitec_panel_sniff.py` | passive (never transmits) capture of Omitec panel traffic |

Data: `dlcm_window_80000000.bin`, `dlcm_did_sweep_full.txt`,
`dlcm_region_scan.out.txt`, `did_live_sample.out.txt`,
`did_vs_broadcast_drive_reverse.csv` (+ `_refs.csv`), `dlcm_did_baseline_obd.txt`,
`seedkey_vs_rsa.out.txt`, `omitec_panel_labels.md`.

---

## 6. Open items

1. **Confirm or reject the `850C`/`850D` limiter-bounds hypothesis** (§3.4) — the
   highest-value single test available, and it needs only a drive through the
   clamp region while polling two DIDs.
2. **Resolve lead/lag** on `850E`/`8515` (§3.5) — one 80 s capture.
3. **Complete the panel label -> DID mapping** from an Android-logger capture of a
   panel session (§4).
4. **The six gated DIDs** — what are `A10C`-`A10F`, `FD05`, `FD06`? The
   ride-along idea in §4 is the cheapest route.
5. **Programming-session `0x23`** — see `dlcm-security-access.md` §3a; needs the
   interposer hardware.
