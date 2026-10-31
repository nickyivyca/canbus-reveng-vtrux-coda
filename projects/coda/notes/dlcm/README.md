# `projects/coda/notes/dlcm/`

The Coda's **DLCM** (Drive Line Control Module, Continental EMS9180) — the
module that turns pedal position into a motor torque request. This folder
holds its firmware images, the factory specs, every write-up of the reverse
engineering, and the tooling used to reflash it.

`artifacts/` holds internal analysis scripts, intermediate data and their
outputs, and is not published. Where these notes cite `artifacts/<script>.py`,
they are naming the script a result came from, for provenance; the script
itself is internal. Vendor functional-requirement specs and the raw capture
folders are held on the same basis.

This file is a map. Each document below is self-contained and authoritative
for its own topic; nothing here restates their findings.

---

## Start here

| if you are… | read |
|---|---|
| about to propose or flash any CAL change | **`dlcm-cal-flash-campaign.md`** — what is actually on the car, the image lineage with md5s, and the two-session verification protocol — **and `flash7-reset-mechanism.md` §7**, the rules that flash 7's fault imposes (no edit without an ECM2 twin; screen before md5) |
| working on torque behaviour | `dlcm-torque-limiter-code-trace.md` — the §10.7 gradient limiter, the creep/assist loop, and the table semantics everything else is expressed in |
| working on traction control, `0x300` or `0x312` | **`esp-torque-intervention.md`** — the ESC torque-limit interface, both directions |
| coming to the firmware cold | `coda-dlcm-decompile-notes.md` — extraction, memory layout, the CAN configuration tables, and the Ghidra environment |
| about to trace any decompiled function | **`artifacts/dlcm_symbols.csv`** — the function-to-meaning index. Look the address up BEFORE tracing it, and add a row after identifying one. Its maintenance rule is in `coda-dlcm-decompile-notes.md` → The symbol map |

## The documents

| file | what it covers |
|---|---|
| `coda-dlcm-decompile-notes.md` | Firmware extraction and layout. PROG (1.8 MB container, 343 KB active) and CAL (114 KB container, 18 KB active), both plaintext. The module's own CAN RX/TX tables and the firmware-derived signal map. |
| `dlcm-torque-limiter-code-trace.md` | The torque path end to end: the §10.7 gradient limiter `FUN_80075DFA` and its four LUTs, the creep/assist subsystem, the §10.6 smoothing filter, and what `0x212` does and does not show. The longest file here and the reference for table names and units. |
| `dlcm-cal-flash-campaign.md` | The six CAL flashes of 2026-09-20..24: what went on the car, how each was verified, and the errors the process caught. PROG has never been written. |
| `pedal-map-envelope-design.md` | How the D accelerator map was rebuilt on capability envelopes (C4c, flashed 2026-09-24), the rule, the four measurements under it, and the rejected candidates. **Its §10 carries the units correction** that affects figures elsewhere. |
| `regen-limit-chain.md` | **Slimmed by the 2026-10-03 split; 140 lines.** The original question and its answer: at speed, regen is limited by **power**, nothing else. Plus the histogram artefact that nearly became a theory. Its §2/§6/§7 moved to `esp-torque-intervention.md` and its §4/§4b to `pedal-map-envelope-design.md`; the header table maps every moved section. |
| `esp-torque-intervention.md` | **The ESC torque-limit interface: `0x300` in, `0x312` out.** Both ESC limits traced from the RX accessor to the application site. **The asymmetry is the headline:** the braking side is gated on calibration alone and fires 5 times corpus-wide, going to exactly 0 for 2.5–21 s; the tractive side needs a runtime arming bit (`0x300` B4 bit 6, set in 0.0146 % of frames) and fires 34 times for 0.02–0.86 s, partially. Also: the applied limit is observable on D CAN as `0x312 TorqueFeedback` (no M CAN needed), `0x312`'s published `M_MAX`/`M_MIN` are read from *pre-ESC* magnitudes so they never carry an intervention, and `M_MIN`'s publication negates a stored magnitude. Part II preserves the superseded `regen-limit-chain.md` sections with supersession banners, including the falsified 'it is a mirror, not a wall'. |
| `next-flash-candidate-k1-b25-flat31.md` | 2026-10-13, simulation only, **not authorised for flashing**. The next candidate after C4c (plan `next_flash_from_c4c.md` step 5): creep off (K1), regen floor blend 25 % (B25), one pedal zero point 32.34 % from 0 to 31 mph (FLAT31). Results against every acceptance criterion, the candidates scored, the accepted feel changes, the rejected options and the model's limits; numbers from worklog 3BG-3BJ. |
| `candidate-criteria.md` | 2026-10-17, agreed with the user. **The criteria for new calibration candidates**: the maintained images by headline name (`0.13g-brakeblend-156nm`, `0.13g-brakeblend-156nm-nochatterfix`, `illegal-onepedal-156nm`) and their inputs, the shared gates, the optional 0.13 g gate for legal flashes, the scored goals, what is not a criterion, and the current cards. Replaces the A1-A7 and C1-C6 tables for new work. |
| `next-flash-candidate-regen13-brakeblend.md` | 2026-10-17, simulation only, **not authorised for flashing**. The candidate after K1+B25+FLAT31 (plan `../plans/next_flash_regen13_brake_blend.md` step 6): off-throttle regen capped at 0.13 g (R13P10) and the full 156.2 Nm blended in on the brake (BBSW20P256), md5 13679c3c. The rule to rebuild the bytes, the per-address change list with each ECM2 copy, results against every acceptance criterion, the user's decisions and the caveats. |
| `regen13-modelling-inputs.md` | 2026-10-14, reviewed. Car-measured inputs for the 0.13 g regen + brake-blend candidate (plan `next_flash_regen13_brake_blend.md` step 2): regen torque -> deceleration (0.0117 m/s2 per delivered Nm; driver-only 0.13 g = ~106 Nm requested, not 118.6), friction deceleration vs raw 0x208 pressure (knee to ~100 raw, then ~0.006 m/s2 per count), total decel vs pressure, early brake-press pressures, mass per drive, and why the accelerometer is not in the chain. |
| `regen13-model-screens.md` | 2026-10-14, in progress (plan `../plans/regen13_model_screens.md`, the lash session's share of `next_flash_regen13_brake_blend.md` step 5). Section 1, reviewed: the braked-stop episode sets (`stop` ~5 mph anchor, `stop_low` ~3 mph), counts by cohort, C4c coverage, recorded measures, and the 0x330 invalid burst after standstill that leaves the recorded ring undefined for ~58 % of stops. Section 2, reviewed: the plant's measured-friction option and the opt-in grade fallback for braked stops; simulated vs recorded stop speed. Section 2b, reviewed 2026-10-15: the COM receive-poll schedule (`codasim/io/comsched.py`) checked against the firmware and the logs, one defect found and fixed, cosim on the poll by default, the 0x20C arrival offset (1.5 ms; sensitivity 0.65 / 2.5 ms) and the re-runs. |
| `low-speed-clunk-and-creep-columns.md` | The D↔R clunk and the creep columns, worked together. Two clunk sources, the mechanism, the model and its limits, and the wrong-way creep assist. |
| `creep-off-ecm2-reason11.md` | 2026-10-08, provisional. Does creep assist off (`0xA00215C0` = 0, R<->D candidates K1/L2+K1) trip or blind ECM2's creep monitor (reason 11)? **No trip, and the monitor can never fire under K1**, because every fault path needs a nonzero creep output; it still reads that output. Traces the creep output into ECM2, `a0-0xaa3`, `a0-0xaa4` (hypothesis: 'creep not permitted'), `b64` and ECM2's creep ceiling `b60`/`b62`, and keeps creep OUTPUT and creep CEILING apart. Split with the `Coda DLCM work` session, which owns reason 15 and the trip mechanisms. |
| `flash7-reset-mechanism.md` | **2026-10-08. Why flash 7 reset the DLCM seven times and cut the MCM.** A pedal release at walking pace lands the raw demand inside 7a's slow band; the newly enabled three-stage filter freezes the published command; ECM2, which has no copy of the filter, keeps slewing its allowance down; the 300-count gap holds for > 5 ticks; shut-off path; the seven-reset cap is CAL `0xA0021D8C`. All seven resets are releases, the freeze is the firmware filter to within 15 counts from the bus alone, and a forward replay of the recorded throttle reproduces all seven under f7 and none under C4c. The oscillation is a sibling effect, not the cause. Closes T3. |
| `regen-stop-lamp-thresholds.md` | 2026-10-14. The regen stop-lamp thresholds: UN R13-H 5.2.22.4 (signal required above 1.3 m/s2 = 0.13 g, optional 0.7-1.3, off below 0.7), China GB 21670-2025 (same 1.3 m/s2, secondary source), the US (no threshold), what production EVs do (about 0.1 g measured by Consumer Reports; Hyundai/Kia updated to 0.13 g). 0.2 g is found only in forum posts. Plus a model estimate of the Coda's regen in g: about 0.17 g on the 12-31 mph plateau. Sources marked by how they were read. |
| `brake-lamp-relay.md` | Why regen does not light the brake lamps. The relay, the harness, the diagnostic half that runs but is calibrated off, and the factory line confirming the feature was never built. |
| `dlcm-dtcs-investigation.md` | How DTCs are stored and set, the event→DTC table, and which codes reach the bus. |
| `dlcm-security-access.md` | The UDS SecurityAccess seed/key handshake — which bus, which module, where the algorithm lives. |
| `dlcm-uds-live-access.md` | What the ECU serves over UDS with no SecurityAccess at all. |
| `dlcm-torque-flow.md` | Text re-transcription of `dlcm-torque-flow-chart.png`. The PNG is the source of truth. |
| `dlcm-second-pass-hypotheses.md` | Early investigation angles. **Largely void** — written under the SH-4 assumption; see the warning in its header. |

Plans live one level up in `../plans/` (`dlcm_reflash_7_8_clunk_and_regen_floor.md`,
`dlcm_zero_crossing_cal_proposal.md`, `dlcm_creep_and_one_pedal.md`,
`dlcm_creep_assist_dig.md`, `dlcm_ram_read_mapping.md`,
`dlcm_variant_opcode_decode.md`).

## Firmware, specs and data

| path | what |
|---|---|
| `coda_dlcm_prog.bin` | PROG image, 1.83 MB. Load base **`0x80040000`**. |
| `coda_dlcm_cal.bin` | CAL image, 114 KB, base `0xA0020000`. This is the **stock** calibration; the flashed ones are in `artifacts/cal_as_flashed_*.bin`. |
| *(reflash captures)* | **Moved to `../../logs/flash/` on 2026-10-04.** `coda_dlcm_flash6.log` — the capture the PROG and CAL images above were extracted from — and every other `coda_*_flash*.log` now live there, together with the BMS and GWM flashes, which were never DLCM captures. See `../../logs/flash/README.md`. |
| `DLCM Functional requirements_V4_2.pdf` | Factory spec, 119 pp. Fully extracted to `artifacts/dlcm_functional_requirements_full.md`. |
| `MCM_Functional_requirements_V1_2.pdf` | Motor controller spec, 16 pp; extracted alongside it. |
| `UQM-PID-20240123.csv` | UQM PID list. |
| `dlcm_flash_proxy.py` | The MITM CAL byte-patcher. **This is how the car is actually flashed** — bytes are patched in flight during an Omitec session, not uploaded as an image, so every flash needs a patch preset. |
| `../../tools/flash_sim/` | **Moved 2026-10-17** from `flash_sim/` here: the Omitec and Gateway/DLCM reflash simulators and the UDS flash stack `flash_cal.py` uses, now under `projects/coda/tools/` so they can grow to other modules. The images they read stay in this folder. |
| `cal_images/` | The maintained candidate CAL images by headline name (`0.13g-brakeblend-156nm.bin`, `0.13g-brakeblend-156nm-nochatterfix.bin`, `illegal-onepedal-156nm.bin`), simulation only, not authorised for flashing. Has its own `README.md`. |
| `artifacts/` | Scripts, extracted data, flashed and other candidate CAL images, and outputs. Has its own `README.md`. |
| `dcan_flash_capture*/`, `dcan_uds_capture_20260919/` | Raw captures of flash and UDS sessions, by date. |
| `dcan_drive_capture_20261004_f7/` | The flash-7 test **drive** captures, 2026-10-04 — vehicle traffic recorded with a NON-STOCK calibration on the car, deliberately kept outside every `influx_sync.py` root so they cannot join the stock corpus. Its README has the measured per-chunk extents and the flash boundary. |

## Folder-wide conventions and traps

These bite across documents, so they are collected here rather than in any one
of them. Each is established in the file named.

- **The ECU is an Infineon TriCore LE, not a Renesas SH-4.** Corrected
  2026-09-19. Use `tricore:LE:32:default` and the `dlcm_tricore` Ghidra
  project; the archived `dlcm_analysis` workspace and the modified SuperH4
  SLEIGH are void. `coda-dlcm-decompile-notes.md` → Architecture.
- **One internal torque count is 0.1 Nm.** The published `0x212` value is
  `internal × 0.4 + 2000`, so one unit of `raw − 2000` is **0.25 Nm**, not
  0.1. Both scales appear in scripts here and mixing them is a 2.5× error.
  `pedal-map-envelope-design.md` §10.
- **One internal speed count is 2.203 CAN motor rpm.**
- **Tables exist twice.** The accelerator and brake maps have two banks
  (`0x80044070`/`0x800409F0` and `0x80044050`/`0x800409C8`), and the limiter
  LUTs have a second record block (the V-curve at `0xA0021528` *and*
  `0xA0021B64`). **Every flash writes both**, because which copy the running
  variant reads is open. Missing one is a silent no-op, not an error.
- **D and R do not share a speed axis** — D is `[0, 640, 1024, 1536, …]`, R is
  `[0, 256, 640, 1280, …]`, so a column index means a different speed in each.
- **A CAL address stored as a pointer inside a PROG descriptor is invisible to
  a code-reference scan.** All the gradient tables are in that class, so
  "not referenced" from `artifacts/cal_code_xref.py` never means "not read".
- **An edit with no ECM2 twin is how flash 7 faulted.** The supervisor ECM2
  recomputes the torque path from the mirrored tables and compares; a filter,
  lag or table that exists only on the PROG side moves the published command
  away from ECM2's expectation, and 300 counts for 5 ticks is a module reset.
  `0xA0021545` (the 7a enable) stays 0; the whole gain table
  `0xA002148C..0xA0021499` and `0xA002149C..0xA00214A9` is off-limits. A byte
  diff that shows a change once rather than twice is the cheap screen.
  `flash7-reset-mechanism.md` §7.
- **The flash protocol is two-session:** one session proposes a change list
  from a stated rule, the other re-derives the image from the rule alone and
  compares md5. A matching md5 says the change list means what it claims; it
  is **not** permission to flash. The user is the gate, always.

## Related, outside this folder

`../low-speed-driveline-signals.md` (what the bus can and cannot resolve at
walking pace) · `../../CODA-D-CAN.dbc` (signal encoding) ·
`../../README.md` (vehicle overview, CAN topology) ·
`../../../../ghidra/README.md` (Ghidra environment and headless scripts).
