# Coda HVAC — firmware and decompile notes

Started 2026-10-26. The work ran as a gated plan of six steps, now complete; what each step
produced is in section 11 and what is still open in section 10.

## Goal

Understand the mechanism that turns on the Coda's battery conditioning, specifically how
to force it on to warm the pack to a warmer temperature than the default behaviour
targets. **Flashing is not authorised**; this work produces models and documentation.

Scope rulings by the user:
- **2026-10-26 (step 3 gate):** keep the existing control loop and change only the
  setpoint/threshold the pack is heated to. Commanding the PTC heater (H9) or overriding
  outputs is not the lever.
- **2026-10-26 (step 4 gate):** a live RAM write that is lost when the HVAC sleeps or resets
  is acceptable, and is what was wanted (section 8). Running anything on the car is the user's
  call.

Related existing notes: `../thermal-behavior-investigation.md`,
`../thermal-indicator-signals.md`, `../charging-analysis.md`,
`../module-diagnostic-ids.md` (HVAC row), `0x276 HVACStatus` and `0x391 HVACAirState` in
`../../README.md`, and the shared HV PTC heater notes under `../../../../notes/Heater/`.

## 1. The 2026-10-25 reflash and the extracted image

Sources: `flash_capture_20261025/` (the flash tool's candump, and the Android logger
chunks T0-T3, which saw the same traffic). Extraction: `artifacts/hvac_flash_extract.py`
phases p1-p3, outputs beside it. Images: `firmware_20261025/` (its README has the table).

**The image is complete.** Nine RequestDownloads — the SBL and eight program segments,
matching what the tool displayed. Every one was checked three independent ways:

| Check | Result |
|---|---|
| bytes received vs RequestDownload size, ISO-TP and block-counter continuity | 9/9 equal, 0 aborts, 0 gaps |
| tool candump vs Android logger | 9/9 byte-identical; same frame counts (`0x750` 13,149, `0x758` 805) |
| CRC-16/CCITT-FALSE of each segment vs the 2 bytes in the tool's TransferExit | 9/9 match |

Every RequestDownload used dataFormatIdentifier `0x00` (no compression or encryption
declared), and the content is not encrypted: seg1 opens with readable code bytes and
carries ASCII strings.

| Seg | RequestDownload addr | Bytes |
|---|---|---|
| 0 (SBL) | `0x002020` | 6,943 |
| 1 | `0x00C000` | 4,310 |
| 2 | `0x00EE10` | 240 |
| 3 | `0xE08800` | 1,196 |
| 4 | `0xF98000` | 15,517 |
| 5 | `0xFA8000` | 15,347 |
| 6 | `0xFB8000` | 16,080 |
| 7 | `0xFC8000` | 14,261 |
| 8 | `0xFE8000` | 16,228 |

Program total (segs 1-8): 83,179 bytes.

**Version strings in seg1:** `v1.4rev5`, `00.009.240.01`, `A0000000D01.12`,
`C0D4AICMBETA01`, `CAN 1.3`, `SoftwareFileNumber`. `v1.4rev5` is the value the module
already returned for DID `F191` (`../module-diagnostic-ids.md`).

## 2. Flash session sequence (tester `0x750`, HVAC `0x758`)

From `artifacts/hvac_flash_extract.p1.out.txt` (candump time base).

1. t = 84.0-84.1 s: ten `7F 10 33` and one `7F 11 33` from the HVAC with no physical
   request on `0x750` before them; the candump holds `0x7DF` functional frames.
2. `10 02` refused (`7F 10 33`), `10 03` accepted, SecurityAccess `27 03`/`27 04`
   succeeds, `10 02` accepted, `11 01` ECUReset.
3. After the reset: `10 02`, SecurityAccess again, then TesterPresent every ~1 s.
4. For each segment: `31 01 FF 00 44 <addr 4> <size 4>` (positive `71 01 FF 00 00`),
   `34 00 44 <addr> <size>` (positive `74 20 04 02`), TransferData in 248-byte blocks,
   `37 <CRC 2>`.
5. After the SBL: `31 01 FF 02 44 00 00 21 08 00 00 00 00`, no response in either
   capture. After the last segment: `31 01 FF 02 44 00 00 CB A5 00 00 00 00`, no
   response; a `7F 11 33` follows 21 s later; `10 01` at the end is accepted.

**SecurityAccess pairs observed (level 0x03/0x04):**

| When | Seed | Key |
|---|---|---|
| before the reset | `6E 76 07 29` | `BE 7B 58 88` |
| after the reset | `12 34 56 78` | `58 18 2F C9` |

## 3. Hypotheses (unconfirmed, recorded 2026-10-26)

Approved by the user as hypotheses, to be confirmed or disproven from the code. None of
them is evidence yet; nothing should be built on one without the check named against it.

- **H1 — the MCU is a Freescale HCS12/S12X.** Basis: seg1 opens `CF 22 00` (HC12
  `LDS #$2200`); `4A 80 00 FE` reads as a banked `CALL $8000, page $FE`; the addresses
  read as page:offset (`F9:8000` etc.) with the SBL loaded to RAM at `0x2020`.
  *Check:* plan step 1a (vector entries on decoded code, `CALL` pages inside flashed
  pages, clean decode at segment starts).
- **H2 — seg2 (`0xEE10`-`0xEEFF`) is a relocated interrupt vector table**, so the
  resident bootloader and the hardware vectors at the top of `0xC000`-`0xFFFF` were not
  sent, and the image is application-only. *Check:* do seg2's words point at function
  entries; does the application write the vector base register.
- **H3 — routine `31 01 FF 00 <addr> <size>` is erase-before-download, and
  `31 01 FF 02 <addr>` is jump/execute** (`0x2108` inside the SBL, `0xCBA5` at the
  end); the missing responses would fit the ECU handing over control. Also: **the fixed
  seed `12 34 56 78` after the reset comes from the bootloader**, which uses a constant
  seed. *Check:* the SBL's routine and SecurityAccess handlers (seg0), and whether
  `0x2108` / `0xCBA5` are code entry points.

**Status after step 1 (2026-10-26):** H1 confirmed, H2 confirmed, H3 partly supported.
Evidence in section 4.

Added at the end of step 2 (2026-10-26), approved by the user as hypotheses; evidence in
section 5:

- **H4 — the `0x215` handler has a source-level precedence bug.** The handler computes
  `B0 << ((B1 + 8) & 0xFF)` as a 16-bit value (machine code, decoded by hand from the
  bytes), which is how C compiles `B0 << 8 + B1`. Hypothesis: `(B0 << 8) + B1` was
  intended. Supporting evidence: B0:B1 is a big-endian word on the bus, vehicle speed
  (H7); the HVAC's value equals that word only when B1 = 0 and is wrong in 62 % of
  272,615 frames, so while driving it reads ~0 km/h with occasional absurd spikes
  (e.g. B0 = 27, B1 = 3 gives `0xD800`, "432 km/h"). The `0x275` handler has the same
  expression, overwritten at once by a correct `(B4 << 8) + B5`. The value feeds two
  lookups (`0x7EEF17`, `0x7F200F`) whose role is not yet known.
- **H5 — `0x276` B2[5:2] is a mode/state field separate from HVACHVDisableStatus.** The
  code packs B2 as `(RAM 0x3DF3 & 3) << 6 | (RAM 0x3E50 & 0xF) << 2 | (RAM 0x3E02 & 3)`;
  the `0x01`/`0x0D`/`0x11` values in `../thermal-behavior-investigation.md` are that
  nibble reading 0, 3 and 4.
- **H6 — through `0x390` B4-B7 the BMS gives the HVAC the cell-temperature window it
  conditions toward** (DBC: AllowedCellTempMax/Min/Diff, AllowedHumidity). Check: plan
  step 4, starting at the reader `0x7EC9C1`.
- **H7 — `0x215` B0:B1 is vehicle speed, km/h x 128, big-endian. Confirmed** (section 5.4)
  and added to `CODA-D-CAN.dbc`. Its transmitter is not shown; the ESC is suspected.

Added at the end of step 3 (2026-10-26), approved by the user; evidence in section 6:

- **H8 — I/O control (`0x2F`) and WriteDataByIdentifier (`0x2E`) are not gated by
  SecurityAccess.** A code fact, read from the dispatcher and handlers: the security level
  `0x2A06` is read only by `10 02`, `11` and `27`. `0x2F` needs the extended session and
  physical addressing (`0x750`); `0x2E` needs only physical addressing. Not tested on the car.
- **H9 — `2F 83 06 02 <v0> <v1> <mask>` sets the PTC PWM override that the heater function
  `0x7F200F` reads** (shadow `0x3BF2`, output `0x3DD0`); whether that function obeys it is
  not read. The user ruled this lever out for the goal (2026-10-26): the existing control
  loop is to be kept, and only the pack-heating setpoint/threshold changed.

Added at the end of step 4 (2026-10-26), approved by the user as hypotheses; evidence in
section 7:

- **H10 — the BMS "HVAC Enable" line is a hardware wake / power enable the firmware does not
  read.** The R09 schematic wires BMS pack connector BS01 pin 24 ("HVAC Enable") to HVAC
  HV12 pin 62 ("SPBC Wake/Enable Input") and to IPK IP30 pin 16 ("HVAC Enable Input"). The
  application reads PORTB bit 0 only among the digital inputs that feed the model, and
  that bit behaves like the AC request (7.4); no read of pin 62 was found.
- **H11 — mode nibble 2 is cabin heating and 4 is AC.** **Confirmed 2026-10-28 (9.1, 9.2):**
  bit 2 = cabin heat, bit 1 = cabin cool; nibble 2 = cabin heat, 4 = cabin cool. The mode chart (7.4) builds the
  nibble from a superstate (none / `0x374E` bit 2 / bit 1) and a pair of battery flags;
  logged 0x09/0x21 (nibbles 2/8) co-occur with cabin heat and 0x11 (4) with AC.
- **H12 — mode nibble 3 (`0x276` B2 = 0x0D, the 2026-03-28 morning-drive state) is a second
  battery demand, not identified.** **Settled 2026-10-28 (9.1): pack cool demand**, centred
  on AllowedCellTempMax; the ATD0 ch9/ch10 inputs (hypothesis: battery humidity) also set it. It is `0x3753` bit 0, set when `0x3807` >= 2, the
  output of a mirrored ramp (table `0x2405` = 200/100/0) next to the heat-demand ramp.

## 4. Memory map and workspace (plan step 1, 2026-10-26)

### 4.1 H1 — S12X: confirmed

Independent checks, each of which could have failed:

- seg2 is exactly 120 words, the S12X vector table layout (plain HCS12 has 64).
- The reset code writes S12X-specific registers (below).
- The code uses `GPAGE` and the global-memory instructions `GLDAB`/`GLDX`, which only the
  S12X has.
- Every computed `JMP`/`JSR`/`CALL` target, and every switch-table target, lands in
  flashed bytes. The final build decodes 32,388 instructions with 0 decode errors.
- The 120 vector words have 8 distinct targets, all in flashed bytes.

### 4.2 H2 — seg2 is a relocated vector table: confirmed

The application reset entry (`0x7FCBA5`, local `0xCBA5`) writes IVBR (`0x0121`) = `0xEE`,
which places the vector table at `0xEE10`-`0xEEFF`, exactly seg2. It also writes MMCCTL1
(`0x13`), DIRECT (`0x11`), `0x1C`, CLKSEL (`0x39`), PLLCTL (`0x3A`) and `0x2F0`, then
`JMP 0xC000`. seg1 at `0xC000` opens `LDS #$2200` and `CALL $8000,FE`. So the image is
application-only; the resident bootloader and the hardware vectors at `0xFF10`-`0xFFFF`
were not sent.

### 4.3 H3 — routine control: partly supported

- `0xCBA5`, the address sent in the final `31 01 FF 02`, is the application reset entry:
  vector slots 117-119 (reset, COP, clock monitor) point to it.
- `0x2108`, the address sent after the SBL download, is the SBL's entry (global
  `0x0FE108`). It runs the same start-up sequence as the application and sets its own
  vector base to `0x20`: `LDD #$2001; STAB $13; CLR $11; STAA $0121; ASLA; STAA $1C;
  CLR $39; LDAB #$81; STAB $3A; LDAB #$10; STAB $02F0; JMP $21A5`.
- So `31 01 FF 02 <addr>` fits "execute at address". The erase routine (`FF 00`) and the
  fixed seed are not checked yet; that is plan step 3.

### 4.4 Address map used by the workspace

S12X local -> global, as applied by `artifacts/pack_hvac_image.py`
(`coda_hvac_map.json` has the unflashed ranges):

| Seg | Sent | Global |
|---|---|---|
| 0 (SBL) | `0x002020` | `0x0FE020` (RAM; separate program) |
| 1 | `0x00C000` | `0x7FC000`-`0x7FD0D5` |
| 2 | `0x00EE10` | `0x7FEE10`-`0x7FEEFF` |
| 3 | `0xE08800` | `0x780800`-`0x780CAB` |
| 4-7 | `0xF9`-`0xFC:8000` | `0x7E4000`, `0x7E8000`, `0x7EC000`, `0x7F0000` |
| 8 | `0xFE8000` | `0x7F8000` |

### 4.5 Ghidra project

`coda_hvac` in `~/ghidra-projects/`, stock `HCS-12X:BE:24:default`, holding both the
program image and the SBL. `bash ghidra/hvac-build.sh --force` rebuilds it from the repo
in about 4 minutes; repeat runs give identical numbers. Not archived as a zip (a deviation
from the plan): it is regenerable in one command and names live in
`artifacts/hvac_symbols.csv`.

`HvacFlowSeed.java` (report: `artifacts/hvac_flow_seed.out.txt`) reaches a fixed point in
8 rounds: 32,388 instructions, 318 functions, 0 errors, 32 switch sites with 32
decompiler jump-table overrides. Coverage of flashed bytes by instructions: 92.3%
overall; seg4 99.9%, seg5 96.8%, seg6 99.8%, seg7 99.2%, seg8 92.0%, seg1 29.1%, seg2
and seg3 0%. *Hypothesis (unchecked):* the undecoded part of seg1 (it holds the version
strings) and seg3 (`E0:8800`) are data.

Two silent stock-Ghidra pitfalls, handled in `HvacFlowSeed` and documented in
`ghidra/README.md`:

1. **Wrong-page references.** Ghidra's constant propagator assumes PPAGE = `FE` for every
   `0x8000`-`0xBFFF` reference, whatever page the code is on, and stock SLEIGH never
   follows extended `JMP`/`JSR`/`CALL`. This had seeded fake code in 14 places; 36
   references were moved to their own page. Two references from fixed-page code are
   left at page `FE`, unverified (PPAGE at run time unknown).
2. **Switch-site stack noise.** The compiler's three switch helpers take an inline table
   after the `JSR`; functions containing a switch show 2 bytes of stack error in the
   decompiler's C.

Compiler switch helpers (named in the CSV):

| Global | Name | Inline table after the `JSR` |
|---|---|---|
| `0x7FCAEF` | `SwitchWordTable` | `[N:u16][default:addr16][addr16 x N]`, selector in D |
| `0x7FCAFA` | `SwitchByteOffset` | `[N:u8][default:u8][off:u8 x N]`, target = ret + 2 + off |
| `0x7FCB0E` | `SwitchSparse` | `[max:u8][default:addr16]`, then sorted `([key:u8][addr16])` to key == max |

### 4.6 Simulator skeleton

`projects/coda/tools/hvacsim/`: S12X integer semantics (`fixedpoint.py`), the packed
image read by local address and page (`image.py`), symbols over the CSV, RAM, and 9
passing tests. One test checks every packed segment against the flash tool's own
TransferExit CRC.

## 5. CAN message table (plan step 2, 2026-10-26)

Method: every instruction dumped to TSV by `ghidra/scripts/HvacListingDump.java`
(`~/ghidra-projects/hvac_export/listing.tsv`, regenerable) and swept in Python; the
compressor IDs as raw immediates led to the transmit code. Log evidence:
`artifacts/hvac_can_log_check.py` phases p1-p7 over the 20 captures in
`projects/coda/logs/` larger than 100 kB, with the bus identified per capture by the
audited B CAN anchors `0x48A` + `0x381` (resolved in 20/20). Outputs:
`artifacts/hvac_can_log_check.out.txt` (p1-p3) and `.out.p4.txt` to `.out.p7.txt`.

### 5.1 One controller, on B CAN

Only CAN0 (`0x0140`-`0x017F`) is touched; no other MSCAN block appears in any access.
Vector slots 68/69/70 are its transmit, receive and error ISRs (`0x7FCB2D`, `0x7FCB46`,
`0x7FCB6C`), shown by the registers each touches (`CANTFLG/CANTIER`; `CANRFLG` RXF clear;
`CANRFLG` read and `0xFE` written). Slot 112 is the RTI ISR (`0x7FCBC4`).

| Function | Global | Does |
|---|---|---|
| CAN0 init | `0x7E7A63` | CANCTL1 `0x80`, filters, BTR0/1 `0x41/0x76`; called once from the main function |
| TX buffer load | `0x7E7836` | CANTBSEL, IDR0-3, data, DLC, priority |
| RX buffer read | `0x7E7966` | IDR0-3, DLC, data into the buffers named by the pointers at `0x3012`-`0x301A` |
| RX fetch | `0x7F9F4B` | calls the read; on success clears the "processed" flag `0x301E` and pushes the bus-silence deadline |
| RX dispatch | `0x7E6E4F` | 32-bit compare of the received ID against a constant chain, one handler per ID |
| TX queue | `0x7EB2EC` | takes a 16-byte descriptor (below) |
| TX service | `0x7EB12D` | sends from the one-shot queue first, else the next periodic entry whose countdown is 0 |
| CAN task | `0x7EB0C9` | TX service, RX fetch if pending, dispatch, the two timeouts; every main-loop pass |
| main | `0x7F813E` | init, then the endless loop; called by `AppStartup` (`0x7FC000`: `LDS #0x2200`, MMCCTL1 = 5, `CALL` the copy-down `0xFE:8000`, `CALL` this) |

**Bit timing:** prescaler 2, TSEG1 7, TSEG2 8: bit rate = f_osc / 32, 500 kbit/s if the
oscillator is 16 MHz. **Tick:** RTICTL = `0x49` (binary mode, 2^13 x 10 = 81,920) gives
5.12 ms at 16 MHz. The 16 MHz is inferred, not read: it is the value that makes both the
bit rate and the transmit period below match the bus.

**Acceptance filter:** CANIDAC IDAM = `10`, eight 8-bit filters, each comparing IDR0 =
ID[10:3], so each admits blocks of 8 IDs:

| Filter | IDAR / IDMR | Admits |
|---|---|---|
| 0 | `6E` / `01` | `0x370`-`0x37F` |
| 1 | `4E` / `06` | `0x240`-`0x247`, `0x250`-`0x257`, `0x260`-`0x267`, `0x270`-`0x277` |
| 2 | `70` / `00` | `0x380`-`0x387` |
| 3 | `97` / `17` | `0x400`-`0x43F`, `0x480`-`0x4BF` |
| 4 | `C8` / `22` | `0x640`-`0x647`, `0x650`-`0x657`, `0x740`-`0x747`, `0x750`-`0x757` |
| 5 | `42` / `30` | `0x210`-`0x217`, `0x290`-`0x297`, `0x310`-`0x317`, `0x390`-`0x397` |
| 6 | `0A` / `00` | `0x050`-`0x057` |
| 7 | `FB` / `00` | `0x7D8`-`0x7DF` |

Only the init writes the filter registers (no indexed access either: the only `#0x140`
immediates elsewhere are a block-copy length, 5.6).

### 5.2 Transmit

The transmit queue has exactly 8 callers: four application packers, and four in the
diagnostic transport answering on `0x758` (step 3).

Each packer fills a 16-byte descriptor at RAM `0x2FBA` and calls the queue:
`+0` queue type (1 = periodic), `+1` u16 period reload (100), `+3` u16 countdown (0),
`+5` u16 CAN ID, `+7`..`+14` B0-B7, `+15` DLC (8). Type 0 goes to a one-shot FIFO at
`0x2E80` (15 x 16 bytes); type 1 to a table at `0x2D8E` keyed by ID (15 x 16 bytes): a new
ID appends the descriptor, a known one has only its 8 data bytes refreshed.

**Period.** The RTI ISR subtracts 5 from each periodic entry's countdown per tick,
saturating at 0; the TX service sends an entry at 0 and reloads it to 100. So each message
goes out every 20 ticks (102.4 ms at 5.12 ms) plus main-loop latency. Measured (p1,
~410,000 gaps per ID): mean 104.1 ms; the README's 102.90 ms is consistent. 30 % of gaps are
99-101 ms, below the 102.4 ms floor; unexplained (logger timestamp jitter is a candidate).
The main loop refreshes the data every 20 ticks off a u8 counter (`0x25FB`) tested with
`% 20`; that counter paces data only, not frames (an 81.9 ms gap predicted from it during
the step was refuted: 7-16 of 410,000 gaps).

**Gating.** The four packers run only while bit 4 of RAM `0x3D79` is set, an output of
`0x7EC000` (860 instructions, every 4th tick via `0x7F803C`; not read yet). `0x410` is also
packed once at start-up, before interrupts are enabled.

| ID | Packer | B0 | B1 | B2 | B3 | B4 | B5 | B6 | B7 |
|---|---|---|---|---|---|---|---|---|---|
| `0x410` | `0x7E6C23` | bit0: `0x378` B1 bit1, held for 20 refreshes after it drops; bit2 or bit3: first active entry of an 89-entry status table at `0x1000` (bit3 if entry `0x55`-`0x56`) | 0 | `0x40` if `0x3E0B` = 1, else 0 | 0 | 0 | 0 | `0x2D08` if `0x3C07` = 1, else `0x3E0A` | `0x3E4F` |
| `0x276` | `0x7E6CE3` | `0x3E01` | `0x3CD1` (= `0x439` B2) | `(0x3DF3&3)<<6 \| (0x3E50&0xF)<<2 \| (0x3E02&3)` | `0x3DE8` | `0x3DE9` | `0x3DD0` | max(`0x3DCD`, `0x3DCE`) | `0x3DCF` |
| `0x391` | `0x7E6D6C` | `0x3DE7` | `0x3E09` | `0x3E06` | `0x3E05` | `0x3E08` | `0x3E07` | `0x3DFF` | `0x3DFE` |
| `0x392` | `0x7E6DBE` | `0x3E04` | `0x3DEA` | `0xFF` if `0x3E20` = 2 or `0x3E21` = 2 or `0x3E03` = 0, else `0x3E03` | `0x3E52` | `0x3E53` | `0x3DCB` | `0x3DCA` | `(0x3E54&7) \| (0x3E55&7)<<3`, bit6 = `0x3D69` bit7, bit7 = `0x3D69` bit6 |

RAM addresses are S12X local (global `0x0FE000 | (addr & 0x1FFF)`).

### 5.3 Receive

The RX ISR copies a frame into one buffer: ID at `0x2FFA` (u32), data B0-B7 at
`0x25FC`-`0x2603`. The main loop dispatches it once; every handler sets `0x301E`. Any
successful receive pushes a deadline at `0x3004` to now + 300 ticks (1.54 s); expiry sets
`0x3D2A`. `0x378` alone refreshes a second deadline at `0x3008` (+ 400 ticks, 2.05 s);
expiry sets `0x3D2B`. One buffer: a second frame arriving before the main loop runs
replaces the first.

| ID | DBC name | Handler | Bytes used -> RAM | On B CAN (of 20) |
|---|---|---|---|---|
| `0x051` | `misc_0x051` (D) | `0x7E705B` | `0x3D29` = 1 if B0 = `0x55` or `0x3CE0` = 4 (the DLCM tests the same byte for `0x00`/`0x55`) | 13 |
| `0x1D5` | DCDCStatus1 | `0x7E71A5` | B1 -> `0x3CCD`. **Never received: no filter admits it; nothing reads `0x3CCD`** | 20 |
| `0x215` | `misc_0x215` (D), now VehicleSpeed | `0x7E7284` | `B0 << ((B1+8)&0xFF)` -> `0x3CEB` (H4) | 13 |
| `0x241` | MCM_Thermal (D) | `0x7E71D2` | B5, B1, B2, B3 -> `0x3CDC`-`0x3CDF` | 12 |
| `0x274` | ChrgrSysFaultsTemp | `0x7E70B4` | B6, B7 -> `0x3CCB`, `0x3CCC` | 7 |
| `0x275` | BMSDriveLimits | `0x7E729C` | PackVoltage B4:B5 -> `0x3CF3`; BattSentHVACLimits B6 -> `0x3CCE` | 20 |
| `0x277` | CMMTempStatus | `0x7E72CE` | none (presence only) | 7 |
| `0x370` | GWM_VehicleFaults_0x370 (D) | `0x7E71F0` | B0[6:4] -> `0x3CE0` (value 4 only after 3 in a row, which also sets `0x3D29`); B0[3:0] -> `0x3CE1`; B1 bit0 -> `0x3CE2` | 20 |
| `0x378` | BattPowermode | `0x7E707B` | B0[7:4] -> `0x3CC8`; B0[3:0] -> `0x3CCA`; B1 bit1 -> `0x3D28` (drives `0x410` B0 bit0) | 20 |
| `0x382` | BMSThermal | `0x7E7260` | B0 avg, B1 max, B2 min, B3 max-ID, B4 min-ID -> `0x3CD7`, `0x3CD8`, `0x3CDA`, `0x3CD9`, `0x3CDB` | 20 |
| `0x383` | BMSBattStatus | `0x7E70A6` | B2 bit0 -> `0x3CC9` | 20 |
| `0x390` | BMS_HVBattTemp1 | `0x7E7242` | AllowedCellTempMax B4 -> `0x3CD4`, Min B5 -> `0x3CD5`, Diff B6 -> `0x3CD3`, AllowedHumidity B7 -> `0x3CD6` (H6) | 20 |
| `0x439` | AC_Compressor_Status | `0x7E71BD` | speed B1 -> `0x3CD0`, power B2 -> `0x3CD1`; `0x3CD2` = 0 | 20 |
| `0x48A` | DCDCStatus2 | `0x7E71B1` | Heat_Plate_Thermister B5 -> `0x3CCF` | 20 |
| `0x491` | IPK_Cluster | `0x7E712E` | `(B5<<24 \| B4<<16 \| B3<<8 \| B2) / 10` -> `0x2FCA`; **nothing reads it** | 20 |
| `0x643` | none | `0x7E70C6` | bit fields of B0-B3 and B5 -> `0x2FCE`-`0x2FD4` | 0 |
| `0x750`, `0x7DF` | diagnostics | `0xFE:868B` | ISO-TP (step 3) | 0 |

The hardware filters also pass `0x050`, `0x052`, `0x054`, `0x210`, `0x212`, `0x240`,
`0x270`, `0x271`, `0x381`, `0x418`, `0x492` (all seen on B CAN); the dispatcher ignores
them.

### 5.4 `0x215` is vehicle speed, and the HVAC misreads it

`0x215` (D CAN, 50 Hz, DLC 7, in the DLCM's own receive table; rebroadcast to B CAN, which
is where the HVAC sees it) had been "16-bit word, scale 1/128, identity unknown".

- **B0:B1 / 128 = vehicle speed in km/h.** Integrated over time it reproduces the 0x491
  odometer distance on all four drives in the set: ratios 1.006, 1.000, 0.991, 1.000 (7.1,
  6.8, 7.1, 26.2 km), within the odometer's 0.1 km step (p6). It correlates r = 1.000 with
  every ESC wheel speed (`0x200` LF/RF, `0x208` LR/RR, cantools decode), at a constant ratio
  of 7.23-7.27 (p7). It is 0 in every stationary capture and non-zero only where the
  odometer moved (p5).
- **B2:B3 and B4:B5 are not wheel speeds**: they track each other but correlate 0.01-0.34
  with the wheels, at a ratio that changes from drive to drive. Unknown.
- **Sender not shown.** The DLCM receives it, so not the DLCM; the content comes from the
  wheel-speed data, which points at the ESC, but any module reading the ESC frames could
  compute it. The test that would settle it is the shared-clock method of the README's
  AICM/ACCM comparison, on a capture with D CAN identified by its audited anchors.
- **The HVAC reads the right bytes with the wrong arithmetic (H4).** p4: of 272,615 frames,
  the HVAC's value equals `(B0 << 8) + B1` exactly when B1 = 0 (102,538 frames, nearly all
  all-zero), and differs in the other 170,077; it is non-zero in only 10,531. B1 = 0 occurs
  only at multiples of 2 km/h. The value is read by `0x7EEF17` and `0x7F200F` as the input
  of a 3-point lookup; the RAM tables they pass (`0x2294`: `0x0000, 0x0400, 0x0800`;
  `0x228C`: `0x0500, 0x0F00, 0x1900`, i.e. 0/8/16 and 10/30/50 at 1/128) come from the
  start-up copy-down. Whether those are the breakpoints depends on the lookup helper's
  argument order, which is not read yet.

### 5.5 Discrepancies with the DBC and notes (listed for the user, 2026-10-26)

1. **`0x392` has no DBC entry**, and `../driver-inputs.md` ("ruled out 0x392 as seatbelt --
   it's OCS weight/pressure data") attributes it wrongly: the HVAC packs and sends it.
2. **`0x391` B6/B7** are written by the code (`0x3DFF`, `0x3DFE`); the DBC calls them
   inactive.
3. **`0x410` CASS_on_off and warmup_cycle_cntr_incr** are never set by this firmware; B2 is
   only ever `0x40` or 0. B0's sources are now known (5.2), their names are not.
4. **`0x491`**: the HVAC's B2-B5 reading disagrees with the DBC (Primary_ODO B0-B2, lights
   in B3). The logs side with the DBC: B4/B5 are 0 in every frame, B3 carries light bits
   (`0x33`, `0x73`), B0-B2 counts up (p3). Harmless: nothing reads the result.
5. **`0x1D5`** has a handler but cannot pass the hardware filter.
6. **`0x215`** (H7) was resolved, and `CODA-D-CAN.dbc` now carries `VehicleSpeed`
   (2026-10-26, with the user's approval).
7. `../driver-inputs.md` labels `0x215` "TCM signal"; that predates the 2026-09-24
   invalidation of the TCM.ParkLock candidate and is not supported.

### 5.6 Leads for step 4 (not findings)

- `0x390`'s window is read by `0x7EC9C1`; `0x7ED333` sets start-up defaults for the same
  RAM.
- Transmit gating, `0x410` B2's compressor flag source `0x3E0B` and much else are outputs of
  `0x7EC000`, which looks like generated control code (outputs as stack-local bit flags).
- `0x7EBA93` / `0x7EBAD1` block-copy `0x140` bytes from global `0x13:FC10` to `0x10B2` and
  `0x1332` (and `+0x280`); possibly calibration copied into RAM.
- The start-up copy-down list at `0xCD01` (7 entries, `0x0FE209` + 708 bytes being the
  largest) holds the initial RAM tables, the lookup tables of 5.4 included.

### 5.7 Method notes

- `canre.parsers.parse_file` returns a **generator**; `canre/parsers/parsers.md` said
  `list[CANFrame]` in its `BaseParser` section (corrected 2026-10-26, with a
  single-pass warning added; `arb_id` was already listed there only as a wrong name). The first p1/p2 run consumed the generator in the bus check and
  reported every ID absent; it was caught because the anchor `0x48A` itself came back
  absent. The scratchpad now takes `list(...)` and refuses a resolved bus with no anchor
  frames.

## 6. Diagnostics (plan step 3, 2026-10-26)

Ghidra rebuilt first: 54 symbol rows applied, 0 bad addresses (the RAM rows included).
Function names below are the ones added to `artifacts/hvac_symbols.csv` at this write-out.

### 6.1 Request path

- `IsoTpRx` (`0x7F868B`), called from `CanRxDispatch` for `0x750`/`0x7DF`, switches on the
  PCI nibble (single, first, consecutive, flow control) and assembles the request at
  `0x3035` (SID) on; `0x3036` holds the low byte of the request length. A complete request
  sets `0x2A1F`, and the same function then calls the dispatcher.
- `UdsDispatch` (`0x7F88BB`): the SID goes to `0x2FED`, the NRC to `0x2FF9`, the received
  ID is at `0x2FEA`. Services `0x2E`-`0x31` go through a 4-entry jump table, the rest
  through the sparse switch helper `0x7FCB0E` (table at `0x7F88F7`).
- The tail (`0x7F8C0E`): for functional requests (`0x7DF`) NRCs `0x11`, `0x13` and `0x31` are
  suppressed, others are sent. This is why the flash capture shows `7F 10 33` answers to
  `0x7DF` requests (section 2). `UdsSendNegative` (`0x7F9B70`) answers on `0x758`.
- Every accepted service restarts software timer 2 to 5000 (`0x7F9FC7`). Timers live at
  `0x363A` (6 bytes each) and count down 5 per RTI tick (`RtiIsr`), so 5000 is ~5.1 s
  real time at the 5.12 ms tick.
- **No download services** (`0x34`/`0x36`/`0x37`) in the application: programming runs in
  the bootloader.

### 6.2 Service table

| SID | Gate in the dispatcher / handler | Handler |
|---|---|---|
| `10` | length 2. Sub 01 default, 02 programming (NRC `0x33` unless `0x2A06` = 2, i.e. level 03/04 unlocked), 03 extended (starts timer 2) | `0x7F8C68` |
| `11` | length 2; only sub 01, needs `0x2A06` = 1 or 2 (NRC `0x33`); writes 1 to register `0x003C` (COPCTL); a watchdog reset is suspected, not verified | `0x7F8D21` |
| `27` | physical only, session 0x2210 = 2 | `0x7F8D93` (6.3) |
| `28` | session default or extended; length 3; comm type 1 or 2. Sub 00 sets `0x2211` = 1 (TX on), sub 01 clears it | `0x7F90E2` |
| `3E` | length 2, sub 00 | `0x7F91C1` |
| `85` | **never succeeds**: the dispatcher requires `0x3036` (length) = 2 with NRC `0x11` (the NRC every other service uses for a session check, so `0x2210` was probably meant), the handler requires length 3 (NRC `0x13`) | `0x7F9219` |
| `22` | length 3 (one DID) | `0x7F92A3` (6.4) |
| `2E` | physical only; **no session or security check** | `0x7F93A7` (6.4) |
| `2F` | extended session (NRC `0x22`), physical only; **no security check** | `0x7F947F` (6.5) |
| `31` | physical only, length >= 4; no session or security check | `0x7F99CE` start, `0x7F9A40` stop, `0x7F9AB2` results (6.6) |
| `14` | session default or extended, length 4, group `FF FF FF` only | `0x7F97CE` -> `0x7EB734` |
| `19` | session default or extended, length 2-6 by sub | `0x7F982F` (6.7) |
| `17` | same handler as `19`, but requires length byte 0: unreachable short of a 256-byte request | `0x7F982F` |

Session byte `0x2210`: 0 default, 1 programming, 2 extended. Every handler resets it when it
equals 3, but nothing sets 3 (dead code). Session timeout (`UdsSessionTimeout`, `0x7F9F07`,
from the main loop): when timer 2 expires outside the default session, the session returns
to default, `0x2211`/`0x2212` (TX on, DTC setting on) are set, the port overrides
`0x2F74`-`0x2F7B` cleared and `0x7E4B7E` clears the DID override flags `0x3BF5`+. **`10 01`
does not clear the overrides.**

### 6.3 SecurityAccess

- Sub 01/02 and 03/04. Seed request: if the level is already unlocked the seed is zero,
  else four bytes from `UdsRand` (`0x7F846F`, a Park-Miller style generator, constant
  `0x1F31D`), stored at `0x2A24` (01) / `0x2A20` (03). Key: length 6, compared byte by byte;
  success sets `0x2A06` = 1 or 2; failure is NRC `0x35`. **No attempt counter or delay.**
- `0x2A06` is written only on success and never cleared by a session change or the
  timeout, so a level stays unlocked until reset.
- `SeedToKey` (`0x7E5853`): `s = seed ^ C`, then 48 rounds of
  `s = (s << 1) | (bit29 ^ bit20 ^ bit11 ^ bit4)` (32-bit). `C` = `0x4F7B7C79` for 03/04,
  `0xF0EF3607` for 01/02. **Reproduces both captured pairs** (`6E760729 -> BE7B5888`,
  `12345678 -> 58182FC9`); `hvacsim/seedkey.py` with `tests/test_seedkey.py`. The second
  pair was answered after the reset with the fixed seed `12345678`: the bootloader uses the
  same constant (supports H3's seed clause).
- The capture's sequence matches the code: `10 02` refused (`7F 10 33`) until `27 03/04`,
  then accepted; `11 01` accepted after the unlock.

### 6.4 Data identifiers (`0x22` / `0x2E`)

Routing by DID range:

| DID | Read (`0x22`) | Write (`0x2E`) |
|---|---|---|
| `0x8300`-`0x8FFF`, `0xF000`-`0xFFFE` | `0x7E4E84` via the DID table | NRC `0x12` |
| `0xE100`-`0xE1FE` | 4 bytes of RAM at `0x2214 + 4*(DID-0xE100)` | **writes those 4 bytes**, bounded to `0x2214`-`0x2536` |
| `0xE300`-`0xE331` | 4 bytes of RAM at `0x3C28 + 4*(DID-0xE300)` | writes them, bounded to `0x3C28`-`0x3C65` |
| `0x6300`, `0x6301` | port bytes (6.5) | - |
| other (E0xx, E2xx) | `0x7E52BC` via the E-DID table | `0x7E5506`: **written to the persistent store** (corrected at step 4, below) |

- **DID table** at `0x7FC23A` (55 rows of 24 bytes): `[DID u16][size u16]` then up to four
  `[width u8][source u16][override shadow u16]` groups (width `0x18` = a block of `size`
  bytes). Rows of interest: `8306` = `0x3D8C`, `0x3DD0` (PTC heater PWM, `0x276` B5);
  `8317` = `0x3DCD`-`0x3DCF` (`0x276` B6/B7 fan PWMs); `8308` = `0x3DCA`-`0x3DCC`;
  `8312` = `0x3E0A` (`0x410` B6, compressor target speed), `0x3D69`; `8322` = the
  `0x491` odometer buffer `0x2FCA` (11 bytes; section 5.3 found nothing else reads it);
  `F190` (17 bytes at `0x3F22`), `F187`, `F18B`, `F191`, `F192`, `F183`, `F1A0`-`F1A2`,
  `F004`-`F006` are identification.
- **E-DID table** at RAM `0x2A2C` (6 rows of 7 bytes, from the copy-down):
  `[DID u16][store offset u16][length u16][flags u8]`: `E000` (block E000-E0FE, offset
  `0x064`, 4 bytes each), `E0FF` (`0x460`, 2), `E200` (E200-E232, `0x462`, 4), `E232`
  (`0x52A`, 2), `E233` (E233-E264, `0x52C`, 4), `E265` (`0x5F4`, 2). The values are written
  through `0x7E7B3B` into the emulated-EEPROM store at global `0x13:F000 + offset + 4*n`
  (read from the address arithmetic in `0x7E5506`). Flags are `0x03` in every row and
  nothing writes them. **Corrected at step 4:** this paragraph first said bit 1 refuses
  writes, so E0xx/E2xx were read-only. That was read from a decompile, and stock Ghidra
  decodes `BRSET` inverted (`ghidra/README.md`). The machine code (`0x7E55E9`
  `BRSET flags,#2` -> write path) **writes when bit 1 is set**, so with `0x03` every
  E0xx/E2xx DID is writable over `2E`, persistently. What the store holds: E233-E264 (+ E265
  checksum) is a 200-byte block loaded at start-up into RAM `0x3E76`-`0x3F3D` by
  `0x7E699F` (flash defaults at local `0xC762` when the checksum fails), read only through
  the identification DIDs (F190 at `0x3F22`); E000/E200 were not traced. The thermal
  model reads none of it (7.5).
- **The E1xx window is RAM initialised by the copy-down** (`0x0FE209`, 708 bytes, then
  `0x0FE4D6`, 107 bytes): mixed bytes, words and lookup tables (repeating `0x461D` words look
  like breakpoints). A `2E E1nn` write changes them live; a reset restores them.
- **The E3xx window** (`0x3C28`-`0x3C65`, zero at start-up) is read by `0x7F1C7E` as
  flag/value pairs (`0x3C28`/`0x3C29` flags, `0x3C2A`/`0x3C2C` values, and so on).

### 6.5 Input/output control (`0x2F`)

- **DID-table DIDs** (length >= 4): the control parameter selects through `0x7FCAEF`:
  `00` clears the DID's override flag `0x3BF5 + row index` (and bit flags through the
  13-row table at RAM `0x2A66`), `01` reads the current value and writes it back as the
  override (freeze), `02` writes the request's value, with the mask byte that follows it
  stored as the flag, `03` NRC `0x31`. The numbering is one off from ISO 14229.
  `0x7E50E7` writes the value into the override shadows.
- The heater function `0x7F200F` copies 51 override flags (`0x3BF5`-`0x3C27`) and the
  override shadows (e.g. `0x3BF2`, the PTC PWM shadow) into its own block at `0x375E`+ /
  `0x37E9`+ each step, and writes the PTC PWM `0x3DD0`. How it applies them is not read.
- **`0x6300`** (length 12): override of the PORTB input byte (value `0x2FAE`, mask
  `0x2F74`); `0x7E58EC` merges it into `0x3C83` (bit 0 is read by `0x7F200F`).
- **`0x6301`** (length 12, 4 value bytes + 4 mask bytes): `0x7E5CF1` (main loop) writes
  `(mask & value) | (~mask & normal)` straight to the ports: PORTA <- `0x3D69` (mask
  `0x2F78`, value `0x2FB2`), PORTC <- `0x3D79` (`0x2F7A`/`0x2FB4`), PORTD <- `0x3D6A` plus
  kept bits (`0x2F7B`/`0x2FB5`). `0x3D79` bit 4 is also the CAN transmit gate (5.2). When
  `0x3C07` != 0 the ports come from `0x2C67`/`0x2C68` instead and the overrides are ignored.
  Which pin drives what is not known.

### 6.6 Routine control (`0x31`)

Table at `0x7FC024`, 8 rows `[RID u16][index u8]`: `7010`, `7011`, `FF00`, `FF01`, then four
rows of `0x0000` (so RID `0x0000` is also accepted). Start/stop/result flags at `0x3E5C`,
`0x3E64`, `0x3E6C` + index. **Only `7010` does anything**: start sets `0x2FE3`, `0x3CE9`
bit 1 and clears `0x3E74`; `0x7F1C7E` then moves a state at `0x39BD` and sets input bit
`0x374D` bit 3; `RoutineRunner` (`0x7EB618`, main loop) stops it when `0x3DF0` > 20, and
when `0x3D2C`, `0x3D32`, `0x3D38`, `0x3D3E` (bits of `0x374A`) are all 1 it marks a pass
and once calls `0x7E4B9E`, which writes to the persistent store (the `E232` row). Results:
`71 03 70 10 00`/`01`, or NRC `0x21` while the four are not all 1. The flags of `7011`,
`FF00` and `FF01` are never read: accepted, no effect in the application.

### 6.7 DTCs

89 entries: status words at `0x1000 + 2*i` (RPAGE window), records of 6 bytes in the
emulated-EEPROM store at `0x13:F800 + 6*i`. `19` sub-functions through a fourth switch
helper `0x7FCAEA` (`[offset u8 x n]`, target = table + offset, no bound) at `0x7F984D`:
01 count by mask (`0x7EB7C2`), 02 list by mask (`0x7EB805`), 03 NRC `0x12`, 04 snapshot
(`0x7EB86C`); 0A all supported (`0x7EBB9F`). `0x7EBB9F` copies each record from a stack
buffer this function never fills, while advancing a far pointer it never reads; broken
output is suspected, not verified (a live `19 0A` would show it). The DTC code list is not
read yet.

### 6.8 Tooling and the simulator

- `HvacFlowSeed` does not know the helper `0x7FCAEA` (one site), so the `19` 01/02/04
  handlers are not decoded in the project; they were read with `HvacListFrom`. Carried
  forward.
- `hvacsim/startup.py` (the copy-down), `hvacsim/seedkey.py`, tests `test_startup.py`,
  `test_seedkey.py` (both pass). `artifacts/hvac_listing_query.py` queries the listing TSV.

## 7. The decision to heat the pack (plan step 4, 2026-10-26)

User scope (step 3 gate): keep the existing control loop, change only the temperature the
pack is heated to. **Result: the HVAC decides on its own, and the temperature it heats to is
the BMS's AllowedCellTempMin (`0x390` B5), which the car always sends as 8 degC.** Heat
demand starts below that, is at its midpoint at it, and ends 2 degC above it. An HVAC
calibration byte, `0x24C9`, offsets it and is writable live over `2E E1AD`.

### 7.1 Method

- Ghidra rebuilt with the step-3 rows (106 rows, 0 bad), then again after two tooling
  fixes (7.7): 32,786 instructions, 318 functions.
- **`hvacsim/cpu.py`, an S12X instruction emulator**, runs the firmware's own code. It
  decodes the bytes itself (never Ghidra's text or p-code). Covers the opcodes of the
  thermal model's call tree and the runtime helpers; anything else raises. Check: it runs
  `SeedToKey` (`0x7E5853`) and reproduces both captured seed/key pairs and 40 random cases
  at both levels (`tests/test_cpu.py`).
- `artifacts/hvac_model_run.py` runs model init `0x7ED333`, then per tick the ADC copy
  `0x7E5910`, PORTB `0x7E58EC` and the scheduler `0x7F803C`, with inputs written where the
  CAN handlers (5.3) and ADC ISRs put them. The ADC ISRs' completion is stood in by hooks.
  Sensors are set from per-channel curves measured through the firmware (7.3).
  Nothing is sent to a car.
- `artifacts/hvac_packheat_corpus.py` sweeps `../../CANLogs/CodaLogs` (the Linux box, 12
  workers) for the `0x276` mode nibble against `0x382` cell temperatures, B CAN identified
  per capture by the audited anchors `0x48A` + `0x381`.

### 7.2 Architecture

- **The scheduler** `0x7F803C` (multirate): `0x7F1C7E` every call, `0x7F200F` (sensors in,
  actuators out) every 2nd, `0x7F37B4` every 10th, `0x7EC000`, `0x7EC8AF` and the **thermal
  model step `0x7EC9C1`** every 50th (counted in the emulator over 100 calls).
- **`0x7EC9C1` is generated model code** (Simulink/Stateflow style): it copies inputs into
  model RAM `0x37xx`-`0x38xx`, calls 37 sub-blocks (`0x7FA1D5`, `0x7ED8FD`, `0x7EE42B`,
  `0x7F18F4`, ...), and writes outputs, e.g. `0x3E50` (the `0x276` B2 mode nibble) =
  `0x37C4`. Init `0x7ED333` sets temperature inputs to `0x50` (0 degC) and CAN temperatures
  to `0x80`.
- **Temperature scales.** Model temperature bytes are (T + 40) x 2, 0.5 degC per bit: the
  CAN temperatures are converted `(raw - 88) x 2`, saturated to 0-255 (raw = T + 128 per the
  DBC). Analog sensor words are (T + 40) x 128.
- **Calibrations live only in the copy-down RAM.** The call tree of `0x7EC9C1` (38
  functions, `artifacts/hvac_calltree.py`) reads 97 calibration addresses, all in
  `0x2216`-`0x251F`, plus tables passed by address (e.g. `0x2286`, `0x2408`, `0x2421`,
  `0x246E`). No far (GPAGE) or paged-window access: **the emulated-EEPROM store plays no
  part in it.** Nothing at run time writes `0x2209`-`0x24CD` except the step counters at
  `0x2202`-`0x220E`, so these values come from flash at start-up and change only by `2E
  E1xx` (lost at reset) or by reflash.
- **The HVAC drives the battery thermal hardware itself.** Wiring model (internal-only,
  pin labels): HV12 46 Battery Fan; HV11 120/121 Battery Cooler Valve; HV11 104/112, HV12
  61 Battery/Cabin Valve; HV11 106/114/115/90 and HV12 51/56/57 the two Battery
  Fresh/Recirc actuators and feedback; HV12 113 PTC Heater; HV11 96 Heater Coolant Pump
  (Enable); HV12 23 Heater Recirc 3-Way Valve; sensors HV12 15 Battery Evap Air Off Temp,
  54/55 Battery Humidity Temp / Humidity.

### 7.3 Hardwired inputs and the BMS line (4b)

- **R09 schematic** (internal-only, pages 2, 5, 26,
  `pdftotext -layout`): circuit HV62 (R/L 0.5) runs from BS01 pin 24 "HVAC Enable" (BS01 =
  "Edge of Pack Connector", the BMS interface) via CNLR01/BSLR02 and splice S_HV62 to HV12
  pin 62 "SPBC Wake/Enable Input", and as HV62A to IPK IP30 pin 16 "HVAC Enable Input". The
  HVAC's other supplies: HV12 pin 3 IGN (from the J/B, IP11 pin 8), pins 4/5 VBat1/VBat2;
  B CAN on HV12 29/10. So **a digital line from the BMS to the HVAC exists**; H10 is about
  whether the firmware reads it.
- **Digital inputs the application uses:** PORTB (`0x0001`, through the `0x6300` override)
  -> `0x3C83`; only bit 0 is consumed, as `0x374E` bit 0 -> `0x39C3` bit 5 and the mode
  flags (7.4); and PORT T bits 5/6 in `0x7E5A0C` (timing measurements, not traced).
- **ADC:** ATD0 (16 channels) and ATD1 (8) ISRs `0x7FCCAD` / `0x7FCCD8` store results at
  `0x2D58 + 2ch` / `0x2D7C + 2ch` and set "sequence done" `0x2D55` / `0x2D78`;
  `0x7E5910` copies them to `0x2F7E` / `0x2F9E` and on to `0x3C7B`-`0x3CA0`; `0x7F200F`
  linearises them through 7-point tables on breakpoints `0x237E`. Channel -> model input,
  found by perturbing one channel at a time in the emulator: ATD0 ch2 -> `0x3722`, ch6 ->
  `0x3728`, ch10 -> `0x3724`, ch11 -> `0x3726`, ATD1 ch5 -> `0x372A`, ch6 -> `0x372C` (all
  (T+40) x 128, higher counts colder); ATD0 ch9 -> `0x37EF`, ch15 -> `0x381E`, ATD1 ch3 ->
  `0x381F` (bytes 0-200/215/148). Which pin each channel is, is not known.

### 7.4 Who decides (4a): the HVAC, from the BMS window

- **Heat demand** is computed in `0x7FA1D5` from the min cell temperature (`0x382` B2 ->
  `0x3CDA` -> `0x37D8`) and the BMS window `0x390` (B5 AllowedCellTempMin -> `0x3CD5` ->
  `0x37DB`, used once, as `(0x37DB x 2 + cal[0x24C9]) >> 1`). A 3-point ramp (breakpoints
  `0x2286` = `0x1308`/`0x1408`/`0x1509`, i.e. -2/0/+2 degC on the x128 scale; table `0x2408`
  = 0/100/200) gives the demand x; `0x3818 = ((x * (cal[0x23A1] - 50)) / 100 + 100) >> 1`
  (`0x23A1` = 130, so 50 + 0.4x), else `cal[0x2399]` = 0. **`0x3756` bit 0 = `0x3818` > 50.**
- **The mode chart** `0x7F17ED` / `0x7F18F4` writes `0x37C4` from a superstate (`0x374E`
  bit 3 off, or bit 3 on with bit 2 or bit 1) and two battery flags:

  | Superstate | `0x3756` b0 | `0x3753` b0 | neither |
  |---|---|---|---|
  | default (no bit 2/1) | 1 | 3 | 0 |
  | `0x374E` bit 2 | 5 | 8 | 2 |
  | `0x374E` bit 1 | 7 | 6 | 4 |

  `0x276` B2 = 0x05 ("pack conditioning only", `../thermal-indicator-signals.md`) is
  nibble 1: no cabin superstate, battery heat demand. H11/H12 for the others.
  `0x374E` bit 2 = (a temperature condition) AND NOT PORTB bit 0; bit 4 = bit 3 AND
  (PORTB bit 0 OR (`0x374F` bit 5/6 AND cal `0x24ED`)); bit 1 = bit 4 AND a condition.
- **Emulated sweep** (`hvac_model_run.py p2`, ambient sensors 0 degC, window as logged:
  min 8, max 45, diff 5): `0x3818` = 130 (full demand) at Tmin <= 5 degC, 109 at 7, 90 at 8,
  70 at 9, 0 (no demand, mode 0) at >= 10. Same at HVPowermode 4 and 5.
- **It follows AllowedCellTempMin 1:1** (`p3`): with AllowMin 15 the midpoint (90) is at
  15 and demand ends at 17; with AllowMin 20, at 20 and 22. **Pack heating runs until the
  coldest cell is AllowedCellTempMin + 2 degC.**
- **Actuators** (`p4`, full scheduler ticks, 1,500): with demand (Tmin 5) the PTC is on and
  the battery fan at 61; without (Tmin 20) both 0, at ambient 20 and 0 degC. The PTC was
  still 10 at the end, so it ramps; the rate was not measured.
- **HV gate** (`p6`): demand is the same at HVPowermode 0-8, but `0x3E02`
  (HVACHVDisableStatus, `0x276` B2 bits 1:0) is 2 (disabled) at HVPowermode 0-3 and 1 at
  4-8. Pack heating needs HV on (drive, charge or support).

### 7.5 The car agrees

- **What the BMS sends** (InfluxDB, all Coda B-CAN `0x390`): AllowedCellTempMax 45,
  **AllowedCellTempMin 8**, AllowedCellTempDiff raw 133 or 136, AllowedHumidity 0, in every
  point. The HVAC applies the temperature offset to Diff as well (5 or 8 degC); the DBC
  comment says Diff has no offset.
- **Corpus** (`hvac_packheat_corpus.py p1`; 1,052 captures resolved, 54 unresolved and
  skipped): the coldest cell never went below 12 degC in any capture, and **mode nibble 1
  never occurs**; nibbles 0, 2, 3, 4, 6, 8 do (`.out.txt`, `.transitions.csv`).
- **The one mode-1 capture**, `projects/coda/logs/codabatteryconditioningrunningendofdrive.log`
  (26.7 s): nibble 1 throughout, PTC 21, battery fan 175, HVPowermode 4, Chargemode 1,
  AllowedCellTempMin 8, and **min cell 9 degC** (max 13, avg 10): inside the emulated ramp
  (demand at 9 degC). `codadrivingafterchargewhenitwasconditioningpack.log` is header-only.

### 7.6 Where the threshold lives, and the levers (4c, 4d)

1. **AllowedCellTempMin, `0x390` B5, from the BMS.** Constant 8 in every capture. Raising
   it raises the heat target 1:1. Changeable at the BMS, or on the HVAC's own CAN input.
2. **HVAC calibration `0x24C9`** (copy-down RAM, value 0), the offset added to
   AllowedCellTempMin: target = AllowMin + `0x24C9` / 4 degC (signed byte). Emulated: +20
   moved the midpoint from 8 to 13 degC and the end from 10 to 15; -20 removed demand at
   5 degC. It is in DID **`E1AD`** (`0x2214 + 4 x 0xAD` = `0x24C8`-`0x24CB`: AllowMax
   offset `0x24C8` = 0, AllowMin offset `0x24C9` = 0, chart hysteresis `0x24CA` = 20,
   `0x24CB` = 20). Per section 6, `2E` needs physical addressing only (H8); the value is
   lost when the HVAC resets or sleeps. Code and emulator only; not tried on the car.
3. A flash calibration change: **FLASHING IS NOT AUTHORISED.**

Not tested: the effect of the BMS power budget `0x275` BattSentHVACLimits (`0x3CCE`, read
by `0x7EC9C1` and multiplied by pack voltage) on heating; side effects of a raised
AllowMin elsewhere in the model (`0x37DB` is read once, so `0x24C9` and AllowMin are
equivalent there). When the car is parked, whether the HVAC is woken is the BMS's decision
(the HVAC Enable line); that logic is in the BMS firmware, not read.

### 7.7 Other findings and tooling

- **`0x7FA1D5` also holds a chart that is not the heat decision**: state at `0x39D3`, flag
  `0x3758` bit 2 held only while min cell >= `0x37DF`, a 2-D lookup
  (`0x7FADF6`: table `0x246E`, inputs `0x37F0` on breakpoints `0x2421` and `0x37E3` on
  `0x248C`); `0x37F0` is ATD0 ch9 through table `0x23EC`, `0x37E3` is max cell temperature
  (or `0x37D6` from ATD0 ch10 when `0x3758` bit 3 is clear). Purpose not identified.
- **Undecoded code:** after the fixes the only flashed gap reached by fall-through is the
  start-up data; `0x7EB7C2`-`0x7EB97F` (446 bytes, starts with `LEAS`) is called by nothing
  decoded (the `19` sub-function handlers behind `0x7FCAEA`); `0x7F9863`-`0x7F9982` likewise
  (`artifacts/hvac_code_gaps.py`).
- `ghidra/README.md`: the BRSET pitfall and the `HvacFlowSeed` fall-through fix.
- Corpus sweep: 1,106 files, 30 GB; the emulator runs about 120k instructions/s, a
  scheduler tick about 0.15 s.

## 8. Live write of the pack-heat offset (plan step 5, 2026-10-26)

**Tool:** `../../tools/hvac_packheat_offset.py` (README in `../../tools/`), tests
`../../tools/test_hvac_packheat_offset.py` (14, against a fake HVAC on an in-process
python-can `virtual` bus whose RAM is the image's copy-down; each of four deliberate faults
in the script is caught). Built on `flash_sim`'s bus factory and `IsoTpEndpoint`, dongle
found as `flash_cal.py` does. Sequence: `22 E1AC` (fingerprint, must be `9C 09 0A 01`),
`22 E1AD` (bytes 0/2/3 must be `00 .. 14 14`), `2E E1AD` with byte 1 changed, `22 E1AD`
read back. **Not yet run on the car**; its first `--read` and write test H8 there.

Firmware facts found while building it (listing, 2026-10-26):

1. **An E1xx write always copies exactly 4 bytes.** `0x7E4E20` takes the count from
   `0x2A5A`, a copy-down constant 4 that no instruction writes; the dispatcher's `2E` path
   (`0x7F8AF0`) checks only that the request came on `0x750` (else NRC `0x11`), never the
   length. A shorter request writes stale request-buffer bytes, so the tool always sends
   four. (`22` does check: length 3, else NRC `0x13`.)
2. **The positive `2E` response is `6E` + DID** (3 bytes, built at `0x7F9441`, sent
   through `0x7F9B70`).
3. **No DID reports the program version.** Every identification DID in the table
   (`F190`, `F191` "v1.4rev5", `F187`, `F183`, `F18B`, `F192`, `F1A0`-`F1A2`,
   `F004`-`F006`) reads RAM `0x3E76`-`0x3F3D`, the block loaded from the persistent store
   (6.4). Hence the tool's fingerprint is `E1AC`/`E1AD` against the image, not a version DID.
4. **Lead, not a finding:** `E1AC` bytes 1-3 (`0x24C5`-`0x24C7`) are read by `0x7EC9C1`,
   the function that reads the `0x390` window. Every direct access to `0x24C4`-`0x24CB` is a
   read.

## 9. Cabin and pack mode, for the app's thermal icons (plan step 6, 2026-10-28)

**Scripts:** `artifacts/hvac_mode_run.py` (emulator: `m0` ADC/PORTB perturbation, `m1`
`0x3807` sweep, `m2` ADC -> `0x3C7B..` map, `m3` cabin x pack x ambient full-tick matrix;
`.m1/.m2/.m3.out.txt`) and `artifacts/hvac_mode_corpus.py` (`c1`, 1,052 CANLogs captures,
B CAN by `0x48A` + `0x381`; `.c1.out.txt`, `.flips.csv`). The CAN-side write-up and the
approved app mapping are in `../thermal-indicator-signals.md`.

### 9.1 The mode chart's inputs (listing + emulator)

`0x276` B2 = `(0x3DF3 & 3) << 6 | 0x37C4 << 2 | HV disable`. The chart (7.4) crosses a cabin
superstate with two pack flags:

| Pack \ cabin | none (`0x374E` bit 3 off) | heat (bit 2) | cool (bit 1) |
|---|---|---|---|
| none | 0 | 2 | 4 |
| heat (`0x3756` b0) | 1 | 5 | 7 |
| cool (`0x3753` b0) | 3 | 8 | 6 |

- **Bit 3, cabin on** = `0x3821` >= cal `0x24B4` (20) AND `0x3751` bit 0. `0x3821` comes
  from the timer captures `0x3CE3`/`0x3CE5`. Hypothesis: the cabin blower speed sense (HV12
  21/40). In `m3` it is forced by a hook at `(0xFC, 0xB013)`.
- **Bit 4, AC requested** = bit 3 AND (PORTB bit 0 OR (`0x374F` bit 6 AND cal `0x24ED` = 1)
  OR (`0x374F` bit 5 AND cal `0x24EC` = 0)). `0x374F` bit 6 = selector `0x375D` == 4, bit 5
  = `0x375D` == 3; with the calibration as flashed, only the bit-6 path is live.
  Hypothesis: PORTB bit 0 is the AC switch (HV11 102).
- **Bit 2, heat** (`0x7F3500`) = `(0x37DE + 10*hyst)/2 >= (cal 0x245A = 140 + 1)/2` AND NOT
  PORTB bit 0.
- **Bit 1, cool** (`0x7F34A2`) = bit 4 AND `max(0x37DE - 10*hyst, 0) <= cal 0x2459 = 180`.
- **Knob `0x37DE`** = `0x37DD`, a 7-point table (breakpoints `0x2352`, outputs `0x2460`,
  84..220) of ADC `0x3C7F` = ATD0 ch1 (ADC 300 -> 115, 2048 -> 144, 3800 -> 207; AC on
  shifts it lower, 144 -> 130). On CAN as `0x392` B0 (`0x3E04`). Hypothesis: the
  temperature knob feedback (HV12 19).
- **Selector `0x375D`** = table `0x2525` (4, 3, 2, 1, 0) on breakpoints `0x2374`
  (0..4000) of ADC `0x3C81` = ATD0 ch13. Hypothesis: the mode control feedback (HV12 31).
- **Pack cool demand, `0x3807`.** A mirrored ramp (table `0x2405` 200/100/0, breakpoints
  `0x2280`) centred on AllowedCellTempMax. `0x3753` bit 0 = `0x3807` >= 2. This settles
  H12: `0x3753` is pack cool. In `m1`, AllowMax 25 gives 0 at Tmax 23, 51 at 24, 100 at 25
  and 200 at 27; AllowMax 45 gives 100 at 45.
  - It is also raised by ATD0 ch10 reading hot (~35 degC and above; ch10 -> `0x3724`, 7.3).
  - It is also raised by ATD0 ch9 high (ADC >= 2800, model `0x37EF` ~182/200).
  - **Hypothesis:** ch9 = battery humidity (HV12 55) and ch10 = battery humidity
    temperature (HV12 54). That would make nibble 3 at least partly pack dehumidify.
    Neither is on CAN (`0x37EF` is not transmitted).
- **`0x3DF3`** (B2 bits 7:6): no direct writer found.
- **`m3` actuators** barely moved in 400 ticks (compressor 0, PTC 10). What each nibble
  drives is taken from the corpus.

### 9.2 The car (`c1`)

Percentages are the share of each nibble's dwell with that actuator on:

| Nibble | Dwell (s) | PTC kW | ACCM kW | PTC PWM | Radiator fan | Battery fan | Compressor target | Knob p5/p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 179,700 | 3 % | 0 % | 6 % | 2 % | 1 % | 0 % | 113/113/149 |
| 2 | 8,926 | 88 % | 25 % | 90 % | 29 % | 8 % | 25 % | 147/162/220 |
| 3 | 2,578 | 8 % | 19 % | 14 % | 100 % | 85 % | 20 % | 113/113/145 |
| 4 | 59,375 | 0 % | 98 % | 0 % | 100 % | 1 % | 98 % | 84/88/110 |
| 6 | 97 | 0 % | 97 % | 0 % | 100 % | 12 % | 98 % | 84/84/104 |
| 8 | 793 | 77 % | 17 % | 82 % | 100 % | 88 % | 17 % | 158/164/220 |

- Nibbles 1, 5 and 7 are absent from CANLogs. Nibble 1 is seen only in the primary-log
  capture of 7.5.
- B2 0x0E is nibble 3 with HV disabled; 0x02 is nibble 0 with HV disabled.
- B2 bits 7:6 = 2 appear only as 0x81/0x91, 51 s in total.
- The knob quantiles agree with 9.1: heat nibbles sit at 147-220, cool nibbles at 84-110.

**App replay** (current `CodaSignalDecoder.kt` logic, per `0x276` frame): 218 direct
HEATING <-> COOLING icon changes in 17 captures.
- 217 are the battery icon flipping while B2 stays constant: 0x0D 130, 0x01 68, 0x21 17,
  0x09 2. That icon is a coolant inlet-vs-return compare.
- The one cabin flip (0x11 -> 0x09) is a real mode change.

### 9.3 Mapping (approved 2026-10-28)

`nib = (B2 >> 2) & 0xF`:
- **Cabin:** HEATING for {2, 5, 8}, COOLING for {4, 6, 7}, else NONE.
- **Battery:** HEATING for {1, 5, 7}, COOLING for {3, 6, 8}, else NONE.

Cabin heat with the compressor running (25 % of nibble 2; presumably defrost/demist) stays
HEATING, which matches what the user has seen on the original green screen. A separate
compressor flag (`0x410` B6 > 0) is exposed for later use. The app change (6d) was made
2026-10-30 (`HvacMode.kt`); see 9.4.

### 9.4 The app change (6d, 2026-10-30)

The change is made in code. It ships in the next Coda release build together with
`android-app/notes/outstanding-changes.md` Change 14 (owner, 2026-10-30), so it is not yet on
the car.
- **`HvacMode.kt`** (new, `coda/`): `nibble`, `cabin` and `battery` per the mapping in 9.3.
  `CodaSignalDecoder.buildState()` takes both icons from it. The old pack logic (battery fan
  PWM, then `0x390` inlet vs return) and its `0x390` decode are gone.
- **`GreenScreenState.compressorOn`** = `0x410` B6 > 0 (the DBC's `target_compressor_speed`).
  It is not shown on screen.
- **`HvacModeTest.kt`** (`coda/src/test/`) covers:
  - all nine nibbles under every value of the other B2 bits;
  - the B2 values the car sends;
  - the decoder end to end.
- **`HvacModeReplayTest.kt`** is skipped unless `TPMS_CODA_LOGS` is set.
  - It replays the 17 captures in `artifacts/hvac_mode_corpus.flips.csv`: every frame of every
    channel goes through the decoder, and the icons are sampled after each `0x276` frame
    (55,074 samples; B2 values 01 02 09 0D 0E 11 21).
  - The old logic, replayed from the same frames, gives 221 HEATING<->COOLING flips. 220 of
    them are the battery icon with B2 unchanged. (The sweep counted 218 and 217, on B CAN only;
    the difference was not looked into.)
  - The nibble mapping gives 1 flip, and no icon change with B2 unchanged.
  - All `:coda`, `:cancore`, `:tpms` and `:p914` unit tests pass.

## 10. Open items

Carried forward from the steps (section 11), as of 2026-10-30:

1. **Symbol rows not yet applied.** `artifacts/hvac_symbols.csv` holds 133 rows. The Ghidra
   project was last rebuilt during step 3, which applied 54 of them (section 6). The rows added in
   steps 3 and 4 are applied by the next `bash ghidra/hvac-build.sh --force`.
2. **`HvacFlowSeed` does not parse the switch helper `0x7FCAEA`.** It occurs at one site, the
   `0x19` sub-function switch.
3. **DTCs** (6.7): the DTC code list is not read. `19 0A` output is suspected broken,
   unverified.
4. **CAN layer** (section 5):
   - No hvacsim module has been added for the CAN layer. The receive handlers and the `0x215`
     misread are the candidates.
   - The `0x215` sender is open; a clock test on a D-CAN capture would settle it.
   - The 99-101 ms gaps below the transmit floor are unexplained.
   - The discrepancies in 5.5 were listed for the user and not edited in the DBC or the other
     notes.
5. **Pack heat** (section 7):
   - The effect of BattSentHVACLimits (`0x275`, `0x3CCE`) is untested.
   - The BMS's wake logic for the hardwired HVAC Enable line is unread.
6. **Live write** (section 8): `tools/hvac_packheat_offset.py` has not been run on the car.
   Its first `--read` and write test H8.
7. **Thermal mode** (section 9):
   - Pack dehumidify via ATD0 ch9/ch10 is a hypothesis.
   - Nibbles 5 and 7 have never been observed.
   - No writer of `0x3DF3` (B2 bits 7:6) was found.
   - The 221/218 replay-count difference (9.4) was not looked into.
   - The app change ships in the next Coda release build.

## 11. Work record

| Step | Done | Findings | Record |
|---|---|---|---|
| 0. Plan and notes file | 2026-10-26 | this file | |
| 1. Workspace: Ghidra project, packed image, simulator skeleton | 2026-10-26 | section 4 | The memory map was settled first on evidence that could fail (4.1, 4.2). The Ghidra project is not archived as a zip; `bash ghidra/hvac-build.sh --force` rebuilds it from the repo. The symbol applier is the shared, program-agnostic `DlcmApplySymbols.java`. hvacsim copies codasim's patterns and does not edit its files. |
| 2. CAN message table from the code | 2026-10-26 | section 5; H4-H7 | 48 symbol rows. DBC edit approved and made: `VehicleSpeed` on `misc_0x215` in `CODA-D-CAN.dbc`. InfluxDB backfill `influx_sync --backfill-id 0x215` finished (312 sessions, exit 0, `--plan` clean). |
| 3. Diagnostic functions | 2026-10-26 | section 6; H8, H9 | 52 symbol rows. hvacsim `startup.py` (copy-down) and `seedkey.py` (SecurityAccess key, verified on both captured pairs), with tests. |
| 4. The decision to heat the pack | 2026-10-26 | section 7; H10-H12; 6.4 corrected | 26 symbol rows (133 total). hvacsim `cpu.py` (S12X emulator, `tests/test_cpu.py`). `HvacFlowSeed` keeps fall-through targets (398 instructions recovered). BRSET pitfall in `ghidra/README.md`. |
| 5. Live write of the pack-heat offset | 2026-10-28 | section 8 | `tools/hvac_packheat_offset.py` and its 14 mutation-checked tests. |
| 6. Cabin and battery thermal mode for the Android app | 6a-6c 2026-10-28, 6d 2026-10-30 | section 9; `../thermal-indicator-signals.md` | H11 confirmed, H12 settled. 6d was on hold from 2026-10-28 while another session worked in the Android app; the owner lifted the hold on 2026-10-30 (9.4). |
