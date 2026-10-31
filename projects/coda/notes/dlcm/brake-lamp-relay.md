# The DLCM's regen brake lamp relay

**Headline: the feature is fully specified, the hardware and the harness are both on
the car, the diagnostic half runs every task cycle — and the lamps do not light under
regen. The stop lamps have exactly two electrical sources and no module other than the
DLCM can reach them, so the only route to regen brake lights is `C_A3`.**
**And the factory's own DLCM DTC table says B2100 is "Not implemented at this time"
(§6), which is documentary confirmation that the command was never built.**
Observed on the car 2026-09-25 (below). What is written here is the static
analysis that was done before and alongside that observation; everything in it
survives the observation, and §6 records the one reading that the observation
bears on.

Investigation 2026-09-25, from `DLCM Functional Requirements V4_2`, the DLCM
TriCore image, and the corpus. Ghidra project `dlcm_tricore`.

---

## 1. On-car observation (ground truth)

Reported by the owner, 2026-09-25, watching the reflection of the high-mounted
lamp in glass while driving the C4c pedal map (150 Nm commanded regen at zero
pedal):

- Pressing the brake pedal: **lamp lights**, visible in the reflection.
- Lifting off into regen, including at the strongest levels: **lamp does not
  light, at any point.**

So on this car the regen path to the brake lamps is not working, whatever the
cause. The spec threshold is 30 Nm (§2), and the map commands five times that, so
this is not a case of sitting below the trip point.

## 2. What the specification says

**§6.6 Brake Lamp Relay** (flow chart transcribed at
`artifacts/dlcm_spec_image_transcriptions.md` p37):

```
RegenBrakeLampRelayCommand =
      SR-latch( set: regen_level_Nm > 30, reset: regen_level_Nm < 20 )
   OR (ManualBrakeLampRelay_FaultOpen AND BrakeSwitch)
   OR (BrakeSwitch_FaultOpen AND BrakePressure_Valid
       AND SR-latch(set: BrakePressure_bar > 5, reset: < 1))
```

**§2.2 I/O list** — the module's six static digital outputs, in the order the
Omitec live-data panel also lists them (rows 1–6), which is an independent
corroboration of the table:

| # | pin | function | I/O | type | current | drive |
|---|---|---|---|---|---|---|
| 1 | `C_A2` | Inverter Enable | Out | LS/static | 0.2 A | LowSide |
| 2 | `C_H4` | Self-Power Enable | Out | LS/static | 1 A | LowSide |
| 3 | `C_M4` | Transaxle Ignition | Out | HS/static | 1 A | HighSide |
| 4 | `B_M1` | Key Interlock Solenoid | Out | LS/static | 3 A | LowSide |
| **5** | **`C_A3`** | **Brake Light Relay** | **Out** | **LS/static** | **0.2 A** | **LowSide** |
| 6 | `C_L4` | Reverse Light | Out | HS/static | 3 A | HighSide |

and the feedback leg:

| 18 | `B_K2` | **Brake lamp diag** | In | digital, switch to +12 V | pull-down 2.74 kΩ |

**§2.1 electrical schematic** (p16): two relays in parallel on the lamp feed —
"Manual Brake Lamp Control" (coil 85 from the brake switch) and "Regen Brake Lamp
Control" (coil 85 = Self Power Enable 12 V, coil 86 = `C_A3`). Both 87 terminals
are fed from Fuse 8 FLVPDB, the same node that feeds the brake switch. `B_K2`
taps the shared lamp node, which is why §5.8 says it reads high for *either*
relay. The service manual agrees: DTC C0023's entry says "Note there are two
relays: Manual Brake relay, regen brake lamp relay."

## 2b. The production harness is fully built for it — and has only two lamp sources

From the Coda release-7 LV wiring diagrams (internal-only, sheet 18
for the relay block and sheet 59 for the wire list). `CN23` is the relay block in the
Front LV PDB; `CN43`/`CN44`/`CN45` are DLCM connectors A/B/C (wire prefixes `DCA`/`DCB`/`DCC`).

**Brake Lamp Relay 2 — the regen relay — is wired in production:**

| wire | colour/size | from | cav | to | cav | role |
|---|---|---|---|---|---|---|
| **`DCCA3`** | B/R 0.5 | `CN23` | **14** | `CN45` | **A3** | coil low side ← DLCM `C_A3` |
| `BR03` | W/B 0.5 | `S_BPG1` | R | `CN23` | 15 | coil high side (post-power-relay rail) |
| `BR02` | R/G 0.5 | `S_ABS1` | L | `CN23` | 16 | contact feed |
| `BS02B` | G 0.5 | `CN23` | 13 | `S_BS02` | R | output → lamps |

**Brake Lamp Relay 1 — the pedal relay — is cavities 9–12:** `BS02A` out (9), `ZBR1`
ground (10), `BR04` from `S_BS01` (11), `BR01` feed (12).

**`S_BS02`, the lamp feed splice, has exactly five wires and only TWO sources:**

```
BS02A   CN23 cav 9   -> S_BS02     Brake Lamp Relay 1 output
BS02B   CN23 cav 13  -> S_BS02     Brake Lamp Relay 2 output
BS02    S_BS02       -> CNLR02 9   right-rear stop filaments (LR01 6 and 12)
BS03    S_BS02       -> IPCN03 3   CHMSL (RF07) and left-rear stops (LL27 6 and 12)
DCBK2   S_BS02       -> CN44 K2    DLCM B_K2 feedback input
```

*`BS03`'s destinations were corrected 2026-09-26 — see §2d. It is not just "the IP
inline": past `IPCN03` it forks at `IPRF28` into the high-mounted lamp and into the
left-hand rear lamps, so five filaments plus the CHMSL hang off this one splice.*

**This is a closed result and it matters: nothing but those two relays can light the
stop lamps.** No ESC, no gateway, no other module, and no CAN message. The only route to
regen brake lights on this car is making the DLCM drive `C_A3`.

`S_BS01`, the brake switch splice, likewise has three wires: `BS01` in from the switch
(`IPCN09` 8), `BR04` to Relay 1's coil, and `DCBF1` to `CN44 F1` = `B_F1`. So the switch
energises the manual relay **and** feeds the DLCM's input in parallel — the pedal path is
pure hardware and never touches the module. **A working pedal lamp therefore says nothing
about `C_A3`.**

Relay block parts (sheet 59): Relay 1 = `AA37220003`, Relays 2–5 = `AAD6616001`, snap-on
block `AD37625110`, cover `AD37626110`. Five relays are listed against six drawn
positions — see the block map in §2d, which replaces the cavity-grouping inference that
used to stand here. Identify the relay by its wire regardless: the one whose cavity 14
carries the black/red `DCCA3`.

## 2c. On-car test, and why connector C must stay mated

**Do not unplug DLCM connector C to ground `A3`.** `C_H4` on that connector is
**Self-Power Enable**, the low-side driver for the DLCM's own power relay. The module
wakes on ignition, then pulls `C_H4` low to latch its main supply; that relay's output is
the rail distributed by splice `S_BPG1` — and `BR03`, the regen relay's coil high side,
comes from `S_BPG1`. With connector C off there is no coil supply, so grounding `A3`
produces a dark lamp that means nothing.

Connector C (`CN45`) also carries `C_A2` Inverter Enable, `C_M4` Transaxle Ignition (TCM
enable), `C_L4` Reverse Light, `C_A4`/`C_K4`/`C_C3` PRND LEDs and backlight, and
`C_E3`/`C_E4` — the second PRND encoder channel, which the spec requires to agree with the
first before allowing a shift. Power, ground and both CAN buses are duplicated on A and B
and survive; everything else on C is an output. Expect a non-drivable car and a stack of
DTCs.

**Test procedure, all connectors mated:**

1. Pull Brake Lamp Relay 2 and jumper `CN23` **cavity 16 → 13** (feed to output). Lamps
   should light. Near a formality — `BR01` and `BR02` share splice `S_ABS1`, and a working
   pedal lamp already proves `S_ABS1` live — but it isolates the lamp path.
2. Re-fit the relay, key on / READY, and ground **cavity 14** (or back-probe `DCCA3`).
   This parallels the DLCM's own low-side driver, which is harmless.
   - **Lamps light** → relay, coil supply and lamps all good; the DLCM never pulls `C_A3`
     low. That is a firmware conclusion and no relay will change it.
   - **Lamps dark** → the relay itself or `BR03` is open. Swap Relay 1 and Relay 2 (both
     `AAD6616001`) and retest.

Step 2 needs the car awake — the coil's high side is the post-power-relay rail.

## 2d. Re-verified against the wiring PDF pages, 2026-09-26

Everything in §2b and §2c above was originally established from
a distilled wire-list extract (internal-only). It has now been
re-read off rendered pages of the wiring PDF itself, at 600–1200 dpi.
Crops of sheets 18 and 59 and full-page LV renders were used, held
internally. `CODA1.0 EE Schematics R09-Latest.pdf` carries the same
sheets 18 and 19 with identical text, so the two documents agree.

**`S_BS02`'s splice table, sheet 59, as printed:**

| Cav | Wire | CSA | Col | Type |
|---|---|---|---|---|
| L | `BS03` | 0.5 | G | FLRY |
| R | `BS02` | 0.85 | G | AVSS |
| R | `BS02A` | 0.5 | G | FLRY |
| R | `BS02B` | 0.5 | G | FLRY |
| R | `DCBK2` | 0.5 | G | AVSS |
| X | *(spare — blank)* | | | |

Five wires and an empty spare row. Sheet 18 draws the same splice as a five-way node.
`S_BS01` likewise: `BR04`, `DCBF1`, `BS01`, spare blank. `S_ABS1`: `BR01`, `BR02`,
`ABS1`, `ABS2`, spare blank.

**Sheet 13 "Ext Lamps-Rear" shows where the net lands.** `BS02` → `CNLR02` 9 → the rear
splice → `LR01` 6 and 12, drawn as *RR Brake1* and *RR Brake2*. `BS03` → `IPCN03` 3 →
`IPRF28` 2, where it forks: one branch to `RF07` 1, the **High Mounted Stop Lamp**; the
other via `IPLL02` 14 to `LL27` 12 and `LL27` 6, drawn as *LR Stop1* and *LR Stop2*.
So the third lamp and the main lamps are on the same line, and there is no separate
feed for any of them. That answers the question the on-car observation raised.

**Sheet 18, the relay block (`CN23`).** Each relay is drawn as a changeover with the
contacts in the upper half and the coil in the lower. Brake Lamp Relay 2 reads: common
cav 16 (`BR02`, from `S_ABS1`), NO contact cav 13 (`BS02B`, to the lamps), coil cav 15
(`BR03`, from `S_BPG1`) and coil cav 14 (`DCCA3`, the DLCM's low side). The NC contact
is unwired. Brake Lamp Relay 1 is identical with 12 / 9 / 11 / 10.

`CN23` has **26 cavities and six drawn relay positions**; the cavity table lists 21–26
as blank.

| Pos | Cavities | Relay | Coil driven by |
|---|---|---|---|
| 1 | 1–4 | Vac Pump | Vacuum Pressure Switch (via `VP02A`) |
| 2 | 5–8 | Main Beam | — |
| 3 | 9–12 | **Brake Lamp 1** | brake switch, `BR04` |
| 4 | 13–16 | **Brake Lamp 2** | **DLCM `C_A3`, `DCCA3`** |
| 5 | 17–20 | "Relay TBD" — 2nd vac pump relay | gateway `CN46` K2 |
| 6 | 21–24 | "Relay TBD2" | *nothing — no wires, no part number* |

Five relay part numbers against six positions, and position 6 is unwired on the
drawing, so the block ships with five relays and one empty socket. Both brake lamp
relays sit inside the populated run, so **both are `AAD6616001` whichever end the
part-list numbering starts from** — as are Main Beam and Relay TBD. That gives three
identical relays on the same block to swap against for the §2c test. *Which drawn
position is called "Relay 1" is still not printed; the swap-part conclusion does not
depend on it.*

**Sheet 10 "Driveline Controls 2" names the DLCM pins in the factory's own words:**
`F1` Brake Switch Input, `K2` Brake Lamp Input, `G1` E-Brake Input, `A2` Motor Enable
Relay, **`A3` Brake Relay 2 Coil**, `H4` Self Power Enable_LS, `K1` Self Power
Enable_HS, `M2` MCM Enable_HS, `M4` Transaxle Enable. The brake switch `IP27` is drawn
as a plain SPST between `ABS2` and `BS01`, and `S_BS01` then splits to `BR04` and
`DCBF1` — confirming that the pedal path never passes through the module.

**Sheet 16 confirms §2c's warning.** The Self Power Enable relay lives in `FL09`: coil
high `BP101` at cav 43, coil low **`DCCH4` at cav 44** — that is `C_H4` on connector C —
and the switched output is `BP100`, 2.0 mm² W/B, at cav 42, which is the wire that feeds
splice `S_BPG1`. `BR03`, Brake Lamp Relay 2's coil supply, comes off `S_BPG1`. Pull
connector C and the coil supply goes with it.

The same sheet shows the **Reverse Lamp relay** in `FL09` built the same way: coil high
`DCCL4` from the DLCM, coil low `ZRL01` to ground, output `DCCL4A` → `CNLR02` 11 → the
rear reverse lamps. A DLCM pin driving a relay coil in a power distribution box is the
house style for both lamp outputs.

### The gateway and the ESC, closed from their own pinouts

**Gateway `CN46`, all 20 wires.** Three CAN pairs (`A2`/`A3` Diag, `B2`/`B3` Bat,
`C2`/`C3` Driveline), power `A1` from `FL09` 1, ground `E1`, `B1`/`C1`/`D1`/`F1`/`D2`
to IP and battery-positive splices, `E2` "Lower DRL Output", `G1`/`H1` to `CNLR01`,
`J1` "Vac Pump Switch Input", `K1` "Vac Pump Switch", and two relay-coil drives:
`F2` → `RCHS` → `CN07` 86, the **Watchdog Relay** whose NC contact feeds the BMS; and
`K2` → `RVP02` → `CN23` 19, the second vacuum-pump relay. **Not one gateway pin
appears anywhere on the stop-lamp net.**

**ESC `CN12`, sheet 3, all 19 pins drawn and named:** `VBAT (KL30_P)` 1,
`VBAT (KL30_V)` 32, `IGN` 8, `GND` 16, `Diag_K` 10, `DCAN_H`/`DCAN_L` 12/13,
`CAN2_H`/`CAN2_L` 18/19, `CLUS_GND`/`CLUS_SP` 29/22, and the four wheel-speed pairs
45/46, 36/37, 34/33, 43/42. Every pin is wired and none is a lamp output. The §9 note
that the ESC was "still worth one look" is now discharged: there is no such output to
leave unwired. Consistent with that, the Coda's own ABS DTC list
(internal-only) contains **no** brake-lamp DTC —
`C107F`/`C1080`/`C1087`/`C108F`/`C1090`/`C1091` appear only in the vehicle-wide master
catalogue, which is a superset.

**The service manual says the same thing in prose**, in its ABS overview
(internal-only):

> The Brake Switch is wired directly to the Driveline Control Module (DLCM). It is used
> for activation of Stop Lamps and Brake Transmission Shift Interlock (BTSI) among other
> plausibility checks to confirm brake pedal application. In the case of Brake Switch
> failure, these functions are also carried out by the appropriate ECUs monitoring the
> Master Cylinder Pressure information on CAN.

That is spec §6.6's third term restated, and it names the DLCM as the stop-lamp ECU.
The same page also settles the dash telltale independently: "The Hand Brake Switch is
wired directly to the DLCM which sends a command to the Gateway Module (GWM), to trigger
a command to the Instrument Pack (IPK), to illuminate the 'BRAKE' telltale" — the
gateway relays a request and owns no lamp.

### Three discrepancies found, and how each was resolved

1. **The net-walk script under-reported, and the output looked like a complete net.**
   `artifacts/brake_lamp_net_walk.py` traverses the wire list as a graph. `LL08` is a
   splice *pack* whose internal continuity the wire list never states — cavities 11, 12
   and 13 are common inside the connector — so the walk stopped at `LL08` 13 and missed
   both left-rear stop filaments. It returned 12 wires where the drawing has 14, with
   nothing in the output to mark the difference. Caught by the sheet-13 image, not by
   re-reading the code. The script now carries a `BRIDGES` table and a docstring saying a
   negative result from it must be checked against a drawing. **The conclusion is
   unchanged** — the endpoints it missed are loads, not sources.

2. **Sheet 18's "Relay TBD" symbol has its coil and contact cavity numbers
   transposed.** Read literally, cavs 18↔19 are the contacts and 17/20 the coil, which
   would make the gateway's `K2` a ground-sense input. Four independent things say
   otherwise: the wire gauges (1.25 mm² on 17/20 against 0.85 on 18/19 — contacts are
   never thinner than the coil, and the Vac Pump Relay beside it follows the normal
   pattern), the names `RBP61`/`RVP01A` mirroring `BP61`/`VP01A`, the sheet-19 pin label
   "TBD_Old CHM Enable **Output**", sheet 3 showing `VP01A` and `RVP01A` both arriving at
   the vacuum pump, and the manual's "controlled by two high-side relays … the second
   … as a failsafe by the GWM". So `K2` is a coil drive. **The brake lamp relays are not
   affected**: their assignment is pinned independently by the DLCM spec (`C_A3` is a
   low-side driver) and by `BR03` originating at `S_BPG1`.

3. **Sheet 18 draws `IG41` from `IPCN01` 3 into `CN23` cavity 4** as the Vac Pump
   Relay's coil supply, but `CN23`'s own cavity table on sheet 59 lists cavity 4 as
   blank and no `IG41` → `CN23` wire exists in the release-7 list. Vacuum circuit,
   outside this investigation's scope — recorded, not chased.

## 3. Both relevant DTCs are calibrated off

From the DTC event table in CAL at `0xA002451F`, stride 6 (decoded by
`artifacts/dtc_event_table.py`); the enable byte reads 100 for live and 255 for
disabled:

| id | addr | DTC | state |
|---|---|---|---|
| 15 | `0xA0024579` | C0023 Brake switch lamp relay circuit | **255 DISABLED** |
| 18 | `0xA002458B` | B2100 Regenerative brake lamp relay circuit | **255 DISABLED** |
| 19 | `0xA0024591` | B2101 Reverse lamp relay circuit | 100 live |

The factory diagnostic manual prints B2100's entry as "Not implemented at this
time", consistent with the calibration.

## 4. The firmware's digital I/O, mapped

**The GPIO layer is three functions.** Found by scanning for TriCore port
registers and decompiling the hits (`ghidra/scripts/DlcmBrakeLamp.java`,
`DlcmGpioMap.java`):

| helper | register | role |
|---|---|---|
| `FUN_800635b8(id, level)` | `P<n>_OMR` @ `0xF0000C04 + port*0x100` | set output pin |
| `FUN_8006358c(id)` | `P<n>_IN` @ `0xF0000C24 + …` | read input pin |
| `FUN_800637f4(id, cfg)` | `P<n>_IOCR*` @ `0xF0000C10 + …` | configure pin |

`id` packs the port in bits [7:4] and the pin in bits [3:0]. `OMR` is the atomic
set/clear register — bit `pin` sets, bit `pin+16` clears — so **nothing reaches a
connector pin without passing through `FUN_800635b8`**, which is what makes an
enumeration of its callers an enumeration of every output the firmware drives.

**`B_K2` (brake lamp diag) is P1.10**, read by `FUN_8007c562` →
`FUN_8006358c(0x1a)`.

**The output channel table.** `FUN_8007cd6e(id, state)` is a table-driven channel
driver. Its argument decomposes three ways:

```c
group = id >> 8;                 // 0 here
chan  = ((id >> 5) & 7) - 1;     // 0 here
sub   = id & 0x1F;               // index into 0xC-byte entries
```

so ids `0x20`, `0x22`, `0x27` are **sub-indices 0, 2 and 7 of one array**, not
three separate channels. The array is reached as
`FUN_8008f164(0x800427BC)` → cfg `0x8004229C` → groups `0x8004228C` →
`0x8004227C` → entries at **`0x800421BC`, stride 0xC, pin id at +6**
(`artifacts/digital_output_table.py`):

| id | sub | pin | port.pin |
|---|---|---|---|
| `0x20` | 0 | `0x52` | P5.2 |
| `0x21` | 1 | `0x53` | P5.3 |
| `0x22` | 2 | `0x25` | P2.5 |
| `0x23` | 3 | `0x0D` | P0.13 |
| `0x24` | 4 | `0x0E` | P0.14 |
| `0x25` | 5 | `0x56` | P5.6 |
| `0x26` | 6 | `0x38` | P3.8 |
| `0x27` | 7 | `0x01` | P0.1 |
| `0x28` | 8 | `0x5C` | P5.12 |
| `0x29` | 9 | `0x19` | P1.9 |

**Channel `0x20` = P5.2 is the Key Interlock Solenoid**, which is what validates
the decode: its setter `FUN_8007c5f6` is called from `FUN_80077b10`, which raises
`FUN_8007f6c8(0x19, …)` — event 25 = C2100 "Key Interlock Solenoid Drive
Electrical Fault".

**Only three of the ten channels have a named accessor**, and one of them is
asymmetric:

| id | setter | getter |
|---|---|---|
| `0x20` | `FUN_8007c5f6` | `FUN_8007c600` |
| `0x27` | `FUN_8007c616` | `FUN_8007c620` |
| **`0x22`** | **none anywhere in the image** | `FUN_8007c640` |

`FUN_8007c640` and `FUN_8007c620` have zero references. So a read-back accessor
was generated for channel `0x22` / P2.5 and no writer exists. **This is
suggestive and is not proof of anything**: the other seven channels have no
accessor at all, and TriCore P2.5 cannot be mapped to connector pin `C_A3`
without a board netlist, which is not in the repo.

### 4b. The second output layer — `FUN_8007b974` — and the complete driven-pin inventory

The channel table above is **not** the only output path. Three more reach
`FUN_800635b8`, and mapping all of them (2026-09-26, `ghidra/scripts/DlcmB974Map.java`)
closes the question of what this firmware can drive.

**`FUN_8007b974(id, level)`** is a separate table-driven layer:

```c
entry = *(int *)(*(int *)(a0 - 0x3db4) + 4) + (id >> 1) * 0x14;
pin   = *(byte *)(entry + ((id & 1) ? 5 : 4));
FUN_800635b8(pin, level);
```

so one 0x14-byte entry carries **two** pin ids and `id` packs the entry index in the
high bits with which-pin in bit 0. Installed by `FUN_80089ed4(cfg)` from
`cfg = 0x80042820`; the entry array is at **`0x80042a8c`** and has two entries:

| id | entry.pin | pin | commanded by | diagnostic accessor | DTC raised |
|---|---|---|---|---|---|
| 0 | 0.A | **P1.4** | nothing | none | — |
| 1 | 0.B | **P1.5** | nothing | none | — |
| 2 | 1.A | P2.2 | `FUN_800779d8` | `FUN_8007c656` → `FUN_80081ca6` | **none** |
| 3 | 1.B | P2.0 | `FUN_80074ac8` | `FUN_8007c65c` → `FUN_80081ba4` | event 19 = B2101 |

**The enumeration is closed, not merely empty.** `FUN_8007b974` has exactly two
calling functions — the init loop and the selector `FUN_8007c662` — and the selector
has exactly two callers, both passing a literal, with no computed-argument call site
anywhere. The selector's switch is `0→0, 2→2, 3→3, anything else → return`, so **id 1
is not even reachable through it**. P1.4 and P1.5 are written to 0 once during
`FUN_80089ed4`'s init loop and never touched again. The per-output diagnostic reader
`FUN_8007c032` is likewise called with only the literals 2 and 3.

**Id 3 = P2.0 is the Reverse Lamp, and that is now proven rather than assumed.**
`FUN_80081ba4` raises event 19 and reads its state through `FUN_8007c65c`, a
two-instruction thunk `mov d4,#0x3; j FUN_8007c032`. The structural argument agrees:
`FUN_80074ac8` is the gear-selector output task and its tail is exactly seven output
calls — four booleans into the `FUN_8007db14` table (the P/R/N/D LEDs), two 16-bit
ones (the PRND low-side and GSS backlight PWMs), and `FUN_8007c662(3, …)`. The spec
lists exactly seven outputs for that cluster, and the reverse lamp is the odd one out.

**Id 2 = P2.2 has a complete diagnostic that nothing reports.** `FUN_80081ca6` is the
same three-comparator shape as the B2101 reporter — over-current, open-load and short,
ORed into a summary flag at `a0-0x26e7` — and it simply never calls `FUN_8007f6c8`.
That is a fourth instance of "diagnostic present, reporting absent" alongside the three
in §9, and it is worth weighing against §6 for the same reason.

**Every pin this firmware can drive:**

| pin | layer | role |
|---|---|---|
| P5.2 | `cd6e` id `0x20` | Key Interlock Solenoid (C2100) |
| P0.1 | `cd6e` id `0x27` | — |
| P2.0 | `b974` id 3 | Reverse Lamp (B2101) |
| P2.2 | `b974` id 2 | unreported diagnostic |
| 4 pins | `db14` ids `0x20`/`0x21`/`0x24`/`0x25` | PRND LEDs |
| 2 channels | PWM (`FUN_8007c6f0`, `FUN_8007c70e`) | PRND low-side, GSS backlight |
| P3.9, P5.7, P5.9, P5.11, P5.14 | direct literals | written once with a fixed value from the startup module `FUN_80089526` — board-level enables, not runtime outputs |

`FUN_8007db14` is a *third* family with its own bases (`a0-0x3d34`, `a0-0x3cc8`), not
the `0x800421BC` array; its entry table was not dumped because its installer
`FUN_8008f7bc` has no direct call reference to recover a cfg literal from. All four of
its commanded ids are accounted for as the PRND LEDs.

**So eleven declared output pins are never commanded by anything**: the nine channel-table
pins with no setter (including `0x22` / P2.5, the getter-without-setter), plus `b974`
P1.4 and P1.5. `C_A3` is one of those eleven or is absent from the image entirely, and
nothing in the repo can tell them apart without a board netlist.

## 5. The feedback and diagnosis half runs, every cycle

`FUN_8006eb8c` reads `B_K2` into `a0-0x27f6` and calls `FUN_8006ec06`, which runs
three comparators and reports:

```c
FUN_8007f6c8(0x12, …)   // event 18 = B2100 Regenerative brake lamp relay circuit
FUN_8007f6c8(0x0f, …)   // event 15 = C0023 Brake switch lamp relay circuit
```

It is **live**: called from `0x8007C2E2` in the main periodic task, sharing timing
slot `0x303` with `FUN_8006f870`. Establishing that required disassembling
`0x8007C2C6`–`0x8007C339`, which no prior pass had decoded — see
`coda-dlcm-decompile-notes.md`, "Ghidra's caller lists are wrong by default on
this image".

The three comparators use only two inputs: `F` = the `B_K2` feedback
(`a0-0x27f6`) and `S` = the brake switch (`DAT_d0006831`, read by 20 functions
across the torque path including the gradient limiter `FUN_80075dfa`).

## 6. The diagnostic implements the Command = ON slice of §5.8 — HYPOTHESIS

The spec's §5.8 truth table has **three** inputs: Brake Switch, Brake Lamp
Feedback, and **DLCM Regen Relay Command**. The command appears nowhere in the
code. What is implemented is exactly the rows where the command is ON.

`FUN_8006ecbe` → "Fault: Regen Relay Failed Open" (event 18):

```c
bVar2 = ((F==0 && S==0) || (F==0 && S!=0));   // == (F == 0)
bVar4 =  (S==0 && F!=0);
if (bVar2) uVar3 = 1;    // SET
if (bVar4) uVar3 = 0;    // CLEAR
```

| S | F | C | spec | code |
|---|---|---|---|---|
| off | off | **on** | set | sets (`F==0`) ✓ |
| off | on | **on** | clear | clears (`S==0 && F!=0`) ✓ |
| on | off | **on** | set | sets (`F==0`) ✓ |
| on | on | **on** | no change | neither fires ✓ |
| — | — | off | all four "no change" | **no path exists** |

Four for four on the Command=ON rows, and every Command=OFF row absent. The same
holds for the other two: `FUN_8006ec6c` ("Either Relay Failed Closed") only ever
*clears*, on `F==0`, which is exactly the spec's four clear rows — its single set
row needs Command=OFF and is missing, so that flag **can never be set in this
build**. `FUN_8006ebbe` ("Brake Switch Relay Failed Open") only ever *sets*, on
`F==0 && S!=0`, the spec's two set rows; its clear row needs Command=OFF and is
missing.

The shape of the first line is the tell: `(S==0 && F==0) || (S!=0 && F==0)` is a
two-case expansion over `S` that reduces to `F==0`. The generator expanded the
table over its inputs and emitted both branches; the command's branches are not
there at all, which is the residue of an input folded to a constant.

**Hypothesis:** the regen relay command was tied to a constant in the model this
build was generated from, collapsing the diagnostic to its Command=ON slice. A
consequence would be that B2100 asserts whenever the lamps are off — essentially
always — which is a clean explanation for why that DTC is calibrated to 255.
**Unproven.** The alternative, that this is simply a partial implementation, fits
the same evidence. The on-car observation in §1 is consistent with both.

### The factory manual says it outright — found 2026-09-26

The DLCM DTC table in the factory manual (internal-only) gives B2100 one line
and nothing else:

> | **B2100** | Not implemented at this time |

Every neighbouring code has a full entry — fault lamp colour, set condition, impacted
components, clear condition, fault reaction. B2101 directly below it reads "Reverse
lamp relay circuit… Electrical fault present on DLCM's drive of relay coil… Reverse
relay, DLCM Connection, ground." C0023 above it reads "See table definition in DLCM
Requirements." B2100 has none of that, because there is nothing to describe.

**This is Coda's own documentation confirming, independently of the binary, that the
regenerative brake lamp relay circuit was not implemented in this build.** It does not
decide between the two readings offered above — a model input folded to a constant, or
a partial implementation — but it removes the need to treat "the feature is missing" as
an inference at all. Everything else then falls into place: the relay fitted, the
harness built, the feedback input wired and diagnosed, the command and the per-output
diagnostic both absent, and the DTC calibrated to 255 because it would otherwise assert
continuously.

## 7. Negative results worth not repeating

- **No threshold constant anywhere.** The 30/20 Nm pair does not appear as a
  compiled-in immediate in any function, in any of the six torque scalings this
  ECU uses (internal 0.1 Nm counts, whole Nm, 0.25 and 0.5 Nm/count, the
  `0x312`/`0x212` raw `Nm*4 + 2000`, and the `0x1C0`/DID raw `Nm*10 + 32128`).
  `ghidra/scripts/DlcmLatchHunt.java`.
- **In the offset-binary domain the firmware actually uses for torque
  comparisons** — confirmed by `FUN_8006b3a8` testing against `0x7d80` = 32128,
  the torque zero — `32428` (+30.0 Nm) appears exactly twice in the whole CAL and
  `32328` (+20.0 Nm) appears **zero** times. Both `32428` sites are in repeated
  parameter blocks whose companions are +10.0 and +40.0 Nm plus a debounce count:
  plausibility monitors, not hysteresis latches, and neither is in the lamp
  module. A reset threshold *derived* as set-minus-hysteresis would not appear in
  the image at all, so this does not close the question.
- **The CAL scalars holding 300/200 that are code-referenced**
  (`FUN_80047b64`, `FUN_800488c2`, `FUN_80048d94`) are debounce counters in the
  safety-monitor family — recognisable by their complement-checked variables and
  the `FUN_80082eaa()` "does not return" trap.
- **Nothing about the relay reaches CAN.** 25 recent drives, 228,389 frames of
  `0x052`: B0 only ever takes `0x04`, `0x08`, `0x0C`. Bits 0, 1, 4, 5, 6, 7 are
  dead in every frame; bit 2 is ParkingBrake and bit 3 its rough complement, and
  neither tracks torque. The DBC's "six booleans ORed together" is what the
  firmware *can* assemble; only two are exercised. `artifacts/brake_lamp_relay_hunt.py`.

## 8. Tooling produced

In `ghidra/scripts/`: `DlcmBrakeLamp.java` (peripheral-space census),
`DlcmGpioMap.java` (every pin driven or read), `DlcmDtcReporters.java` (every DTC
event id this build can raise), `DlcmLatchHunt.java`, `DlcmA1CalRefs.java`,
`DlcmA0Base.java`, `DlcmVarXref.java`, `DlcmProbeRefs.java`,
`DlcmDisasmRange.java`, `DlcmMakeFunc.java`, `DlcmFixOrphanCode.java`,
`DlcmB974Map.java` (the second output layer, §4b).

In `artifacts/`: `digital_output_table.py`, `brake_lamp_relay_hunt.py`,
`brake_lamp_const_scan.py`, `call_target_scan.py`, `brake_lamp_net_walk.py`
(walks the stop-lamp net out of the wire list; read its docstring before trusting a
negative from it — see §2d discrepancy 1).

Verification crops of the wiring PDF, held internally: `p18_brakerelays`,
`p18_tbdrelays`, `p18_watchdog`, `p59_gA`–`p59_gH` (the sheet-59 wire table),
`p59_relayblk`, `p59_sbs02`, and full-page renders `lv_p03`, `lv_p10`, `lv_p13`,
`lv_p16`, `lv_p18`, `lv_p55`.

## 9. Open questions

**The "instruct another module to light the lamps" idea is closed — negatively.** It was
worth asking whether the gateway, or the ESC, could be told over CAN to turn the stop
lamps on. It cannot, and §2b is why: `S_BS02` has exactly two sources, Brake Lamp Relay 1
(brake switch, hardware only) and Brake Lamp Relay 2 (DLCM `C_A3`). Nothing else is
electrically connected to the lamp feed. Two specific things checked and ruled out:

- **The gateway.** Its "BRAKE lamp" entries in `gwm-dtcs.md` (C220C / U0002) refer to the
  IPK's **red dash BRAKE telltale** — the ordinary parking-brake / brake-system warning
  lamp, not the stop lamps. In the LV wiring that telltale ("Brake Indicator") is fed from
  the **Brake Fluid Level Switch**, and the handbrake switch (`IP56`) runs to the DLCM's
  `B_G1` E-Brake input; the gateway only *requests* the telltale as a fault reaction, it
  does not own it. The gateway has no lamp output of any kind.
- **The ESC/ABS. Closed 2026-09-26 — see §2d.** The DTC master list carries
  C107F/C1080/C1087 "Brake Lamp Inhibit Control Circuit" and C108F/C1090/C1091 "ABS Brake
  Lamp Control Circuit", which looked promising. They are generic Bosch ESP codes that
  appear nowhere in the Coda's own ABS DTC file, and sheet 3 draws all 19 pins of the ESC
  module's `CN12`: power, ignition, ground, K-line, two CAN pairs, four wheel-speed pairs
  and the sensor-cluster pair. Every pin is wired and none is a lamp output, so there is
  nothing present-but-unwired to exploit. No second commandable path exists.

**What remains genuinely open:**

1. **Which connector pin is `C_A3` on the TriCore die** — i.e. the port/pin behind it.
   Eleven physical pins are declared in the channel table at `0x800421BC`; only P5.2 and
   P0.1 are ever written by that path. Tying any of them to `C_A3` needs a board netlist,
   which is not in the repo. Without it, "P2.5 is never written" cannot be turned into
   "`C_A3` is never driven".
2. **Whether the command exists at all.** §6 is a hypothesis, not a finding. The on-car
   test in §2c is what decides it, and it decides it in two minutes.
3. ~~**`b974` ids 0 and 1 (pins P1.4 / P1.5)**~~ — **CHASED AND CLOSED 2026-09-26, see
   §4b.** The subsystem holds exactly four pins. Id 3 = P2.0 is the Reverse Lamp (proven,
   not assumed: the B2101 reporter reads it through a thunk that passes the literal 3).
   Id 2 = P2.2 is driven by the interlock task and has a complete diagnostic that nothing
   reports. **Ids 0 and 1 are written to 0 once at init and never again** — id 0 is
   selectable but never selected, id 1 is not reachable through the selector at all, and
   neither has a diagnostic accessor. They remain candidates for `C_A3` only in the weak
   sense that nine channel-table pins are too; nothing distinguishes them.

   **The harness adds a structural argument for looking there first — HYPOTHESIS.**
   Sheet 16 (§2d) shows the Reverse Lamp output and the Brake Lamp Relay 2 output built
   identically: a DLCM pin driving a relay coil in a power distribution box, with the
   relay's contacts feeding the lamps. `C_L4` is the reverse one and its firmware channel
   is `b974` id 3. If the firmware groups its outputs the way the harness does, `C_A3`
   belongs in the same subsystem — and ids 0 and 1 are exactly the declared-but-never-
   commanded entries in it. *This is an inference from architectural symmetry, not from
   a netlist; nothing yet ties `b974` id 0 or 1 to a connector pin.*
4. **Three relay-circuit DTCs have no raiser anywhere in the image** — and §4b adds a
   fourth case of the same shape (`FUN_80081ca6`, the `b974` id 2 diagnostic, computes a
   full fault classification and never reports it). Events 16 and 17
   (P2510 / U3006, Self Power Enable) and 20 (P3100, MCM enable relay). `FUN_80081ca6`
   computes a fault flag in the shape of the reverse-lamp handler and then returns without
   reporting. So an unreported diagnostic is not unique to B2100, which weakens §6 as
   evidence — worth weighing before treating that hypothesis as strong.
