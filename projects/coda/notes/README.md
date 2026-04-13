# Coda EV — Analysis Notes

Per-session analysis write-ups from CAN bus captures.
Vehicle overview, signal inventory, and validation status all live in `../coda.md`.

## Analysis Notes

| File | Log Analyzed | Key Findings |
|------|-------------|--------------|
| `android-coda-app-notes.md` | `codadriveslowturnonwithdefroster2.log` (replay) | Phase 1 complete. Green screen overlay calibration (pixel positions, font sizes), signal calibration (batt temp -12–64°C, range formula, LPF constants), bus identification (bus 3 = B CAN), USB flow, build notes. Phases 2–3 + future scope at end of file. |
| `charging-analysis.md` | `codacharging.log` (home L2, 9.9 min) | Charger ÷32 encoding confirmed; SoC in 0x383 B0-1; gateway firewall (zero shared B/C CAN IDs); 3 event clusters (startup, conditioning, log-end artifact) |
| `chargepointcharge-analysis.md` | `chargepointcharge.log` (Chargepoint, full charge) | OV cutoff confirmed at 3,750 mV; pack imbalance quantified (79 mV resting spread); two-phase CC charge; SoC 100% declared before OV. Note: 0x382 B0 "charge stage counter" hypothesis in this file was later disproved -- B0 is Cell_T_avg temperature (T=raw-128 degC). |
| `bonnydoon-limp-analysis.md` | `frombonnydoon.log` (33 min drive, 3 buses) | Weak cell #94 identified; limp mode = dynamic UV sag protection at 174A; 0x275 B0/B1 = discharge/charge limits confirmed |
| `driving-sequence-investigation.md` | `codadriveslowturnonwithdefroster2.log` (B+C+D CAN) | Full startup sequence mapped (8 event clusters); AC compressor 0x410/0x439 confirmed; ignition state signals; HVAC signals |
| `driver-inputs.md` | Part 1: throttle/brake + PRND logs; Part 2: `driverinputpart4.log` (body electronics sweep); Part 3: brake pedal travel investigation | Part 1: throttle 0x210 B2, brake pressure 0x208 B2-B3, PRND 0x418 B0, D↔B gateway mapped. Part 2: brake switch 0x315 B0.bit0, parking brake 0x052 B0.bit2, steering angle 0x080 B2-B3, headlight mode 0x491 B3, HVAC status 0x276, seatbelts 0x3A0. Turn signals/wipers/trunk not on CAN. Part 3: No analog brake pedal travel signal on CAN. 0x312 reclassified as ESC decel/ABS (discrete stationary, analog driving). 0x315 B5 = Batt_Volt. BrakeCount (LabVIEW) = brake pressure or local ADC. |
| `codacan-capture-notes.md` | n/a (tooling) | `codacan_capture.py` development notes: init-layout algorithm, key parameters, tuning history (tab-bar false positives, BattPowermode text-field fix, x-refinement algorithm), detection results per tab, known limitations. |
| `codacan-signal-decode-notes.md` | All CODACAN validation logs | Bench setup, cowork_replay.py quick reference, phase completion summary, Phase 2 module presence map (heartbeat IDs for all modules), Phase 5 byte-sweep status per signal (DONE/PARTIAL/OPEN), open items, next steps plan, LabVIEW decompile reference (cluster->ID map, VICD findings, corrected hypotheses). |
| `thermal-behavior-investigation.md` | `coda_20260328_101624_T0/T1.log` (morning drive 415s) | Heater graphic flickering + "pack heater running" display with no audible pack fan. Cell temps flat at 14–16°C. BMSmode 0xEA (not normal 0xD2). 0x276 B2 oscillating 0x01↔0x0D at ~1Hz from t=209s. 5 open hypotheses (wrong signal labels, cold-start PTC cycle, BMSmode identity, HVAC PID misread, 0x382 validity). |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `plans/` | Analysis plan files (investigation roadmaps before execution). Empty — android-coda-app plan merged into `android-coda-app-notes.md`. |
| `artifacts/` | Generated data files (CSVs, JSONs, survey outputs, event clusters, scripts). See `artifacts/README.md` for inventory. |
| `artifacts/cowork-results/` | Structured output from Cowork-driven CODACAN validation (field inventories, ID mappings, sweep results, screenshots). See `artifacts/cowork-results/README.md`. |

LabVIEW extraction artifacts (signal inventories, cluster data) are in `../CODACAN/`.
