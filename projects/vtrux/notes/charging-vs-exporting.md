# Vehicle Power Modes: Charging, Export, and Driving

**Purpose:** Compare startup, shutdown, and CAN behavior across all three operational modes (charging, export power, and driving) to understand mode differences, identify mode-specific indicators, and isolate failure paths.

**Context:** The truck uses a bidirectional Bel Fuse charger that can both charge the battery (grid→battery) and export power (battery→grid). Export power continued to work reliably after charging failures occurred, suggesting the issue is likely in the wiring or connections rather than the charger module itself.

---

## State Codes

### Charging Mode States
- **State 11:** Ready to charge (pre-charge)
- **State 12:** Actively charging
- **State 15:** Shutdown/fault state

### Export Power States
- **State 30:** Export ready (pre-export)
- **State 31:** Unknown (appears briefly during startup)
- **State 32:** Actively exporting power

**Key observation:** Charging and export modes use completely different state number ranges (11/12/15 vs. 30/31/32), indicating separate state machines or mode flags within the charger firmware.

---

## Startup Sequence Comparison

### Charging Startup (rainychargedebug.log, t=23.3s)

**Status flag sequence:**
```
t=23.3s:
  - auxPowerSupply: 0→1 [SET]
  - chargerEnergyFlowEnable: 0→1 [SET]
  - s2Switch: 0→1 [SET]
  - inverterAlive: 0→1 [SET]
  - buckBoostAlive: 0→1 [SET]
  - STATE: 11→12 (ready → charging)

t=23.7s:
  - FAULT: acUnderVoltage SET (transient during startup)
  - STATE: 12→15 (fault, transient)

t=24.9s:
  - STATE: 15→12 (recovery)
  - buckBoostReady: 0→1 [SET]

t=25.6s:
  - chargingInProgress: 0→1 [SET]
  - powerChargingInProgress: 0→1 [SET]
  - inverterReady: 0→1 [SET]
  - unitReady: 0→1 [SET]
```

**Voltage/current ramp:**
```
t=23.0s:  battV=0.00V    battI=0.00A     (off)
t=23.5s:  battV=391.65V  battI=0.00A     (voltage appears)
t=24.0s:  battV=391.90V  battI=-0.85A    (current starts)
t=25.5s:  battV=392.65V  battI=-2.15A    (ramping up)
t=27.0s:  battV=393.15V  battI=-14.80A   (full charge rate)
```

**Duration:** ~3.7 seconds from STATE 11→12 to full charge current

### Export Power Startup (exportpowerattempt.log, t=19.4s)

**Status flag sequence:**
```
t=19.4s:
  - auxPowerSupply: 0→1 [SET]
  - exportEnergy: 0→1 [SET]              ← Export-specific flag
  - inverterAlive: 0→1 [SET]
  - buckBoostAlive: 0→1 [SET]
  - STATE: 31→30 (unknown → export ready)

t=20.2s:
  - buckBoostReady: 0→1 [SET]

t=20.5s:
  - FAULT: acUnderVoltage SET (brief transient)
  - exporting: 0→1 [SET]                 ← Export-specific flag
  - inverterReady: 0→1 [SET]
  - unitReady: 0→1 [SET]
  - STATE: 30→32 (ready → actively exporting)
```

**Voltage/current ramp:**
```
t=19.3s:  battV=0.00V    battI=0.00A     (off)
t=19.5s:  battV=393.80V  battI=0.00A     (voltage appears)
t=20.0s:  battV=399.80V  battI=0.00A     (voltage settles)
t=20.7s:  battV=399.55V  battI=-1.05A    (brief negative current)
t=21.1s:  battV=399.10V  battI=+1.00A    (export current starts, POSITIVE)
t=21.5s:  battV=399.80V  battI=+1.20A    (stable export at ~1.3A)
```

**Duration:** ~1.2 seconds from STATE 31→30 to stable export current

---

## Shutdown Sequence Comparison

### Charging Shutdown - Failure Mode (rainychargedebug.log, t=3689s)

**Status flag sequence:**
```
t=3689.0s:
  - STATE: 12→15 (charging → shutdown)
  - shutdownSource: 0→3
  - chargingInProgress: 1→0 [CLEARED]
  - buckBoostReady: 1→0 [CLEARED]
  - unitReady: 1→0 [CLEARED]

t=3690.2s:
  - chargerEnergyFlowEnable: 1→0 [CLEARED]
  - s2Switch: 1→0 [CLEARED]
  - rewakedFromDelayedSleep: 0→1 [SET]
  - shutdownSource: 3→14
  - stateBeforeLastShutdown: 12→5

t=3691.5s:
  - auxPowerSupply: 1→0 [CLEARED]
  - inverterAlive: 1→0 [CLEARED]
  - buckBoostAlive: 1→0 [CLEARED]
```

**Current/voltage:** Instant cutoff (14.85A → 0A in <100ms)

**Duration:** ~2.5 seconds of flag transitions during shutdown

### Export Power Shutdown (exportpowerattempt.log, t=1675s)

**Status flag sequence:**
```
(session ends while in state 32, actively exporting at 1.5A)

Last telemetry:
  t=1675.1s:  battV=392.80V  battI=+1.50A  state=32

[CAN bus goes completely silent - no further messages]
```

**Theory:** Export shutdown is **instant power-off with NO CAN messaging**. The charger (and likely entire vehicle 12V system) cuts power immediately, causing the CAN logger to lose power mid-session.

**Key observation:** Export mode has **no graceful shutdown sequence** - it just powers off completely, taking the entire CAN bus down with it. This is fundamentally different from charging mode which sends shutdown messages over ~2.5 seconds.

---

## Common Startup Elements

### Similarities

1. **auxPowerSupply always SET first** - internal power initialization
2. **inverterAlive & buckBoostAlive SET together** - both sections power up
3. **buckBoostReady SET before current flows** - DC-DC converter ready
4. **acUnderVoltage transient during startup** - both modes see brief AC voltage fault during initial grid sync
5. **inverterReady & unitReady SET when operation begins** - final "ready" flags
6. **Battery voltage appears before current flows** - contactors close first, then power transfer begins

### Differences

1. **Mode-specific flags:**
   - Charging: `chargerEnergyFlowEnable`, `chargingInProgress`, `powerChargingInProgress`
   - Export: `exportEnergy`, `exporting`

2. **State number ranges:**
   - Charging: 11, 12, 15
   - Export: 30, 31, 32

3. **s2Switch flag:**
   - Charging: `s2Switch` SET (EVSE safety switch - required for charging per J1772)
   - Export: `s2Switch` NOT used (export doesn't use EVSE handshake)

4. **Startup time:**
   - Charging: ~3.7 seconds to full current
   - Export: ~1.2 seconds to stable current
   - (Export is faster, likely because no EVSE handshake required)

5. **Current direction:**
   - Charging: Negative current (-14.8A into battery)
   - Export: Positive current (+1.3A out of battery)

6. **Shutdown behavior:**
   - Charging: Graceful shutdown with CAN messages over ~2.5 seconds
   - Export: **Instant power-off, CAN bus goes completely silent**

---

## Key Findings

### 1. Export Power Works Reliably

**Evidence:**
- exportpowerattempt.log shows 27.9 minutes (1675s) of stable export at ~1.3-1.5A
- No faults, no shutdowns, clean operation throughout
- Voltage stable at 392-400V
- This occurred AFTER the charging failures

**Implication:** The **charger inverter and buck-boost sections are functional**. The hardware can successfully:
- Synchronize to grid
- Control power flow bidirectionally
- Maintain stable voltage regulation
- Operate inverter section (required for both charging and export)

### 2. Export Shutdown is Instant Power-Off

**Evidence:**
- Session ends abruptly at t=1675.1s while still in state 32 (exporting)
- Last message shows battI=+1.50A (actively exporting)
- CAN bus goes completely silent - no shutdown messages
- No flag transitions, no state changes, no graceful ramp-down

**Theory:** When export mode ends, the system **cuts 12V power immediately**, taking down:
- The CAN logger (why logging stops)
- Possibly the entire vehicle 12V bus
- All CAN messaging capability

**This is fundamentally different from charging mode** which keeps 12V power active during graceful shutdown and sends status updates over ~2.5 seconds.

## Shutdown Behavior Comparison (All Modes)

| Mode | Shutdown Type | CAN Activity | Key Observation |
|------|---------------|--------------|-----------------|
| **Charging** | Graceful | Status flags clear over ~2.5s | Charger sends shutdown messages, vehicle stays on |
| **Export** | **Instant power-off** | **CAN goes completely silent** | **12V power cut immediately** |
| **Driving** | Graceful | Normal CAN traffic continues for ~6s | HV powers down first, 12V follows |

## Mode Detection from CAN Data

```
IF Bel_charger_present (0x18FFD4C0 messages) THEN
    IF charger_state in [11, 12, 15] AND s2Switch == 1 THEN
        MODE = CHARGING
    ELIF charger_state in [30, 31, 32] AND exporting == 1 THEN
        MODE = EXPORTING
    END IF
ELSE
    MODE = DRIVING or ACCESSORY (use BMS presence / PT bus activity to distinguish)
END IF
```

---

## Appendix: Status Flag Reference

### Common Flags (Both Modes)
- `auxPowerSupply` - Internal 12V/5V power rails active
- `inverterAlive` - Inverter section powered
- `buckBoostAlive` - Buck-boost DC-DC section powered
- `buckBoostReady` - Buck-boost converter ready for power transfer
- `inverterReady` - Inverter ready for operation
- `unitReady` - Overall system ready

### Charging-Specific Flags
- `chargerEnergyFlowEnable` - Enable flag for charging mode
- `chargingInProgress` - Active charging happening
- `powerChargingInProgress` - Power transfer active during charging
- `s2Switch` - EVSE safety switch (J1772 proximity detection)

### Export-Specific Flags
- `exportEnergy` - Enable flag for export mode
- `exporting` - Active power export happening

### Fault/Shutdown Flags
- `shutdownSource` - Numeric code indicating reason for shutdown
- `stateBeforeLastShutdown` - Previous state before fault
- `rewakedFromDelayedSleep` - System restarted after shutdown
