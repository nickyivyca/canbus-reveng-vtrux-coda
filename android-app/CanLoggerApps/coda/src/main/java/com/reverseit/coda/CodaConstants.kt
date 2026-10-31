package com.reverseit.coda

object CodaConstants {
    const val VEHICLE_NAME = "coda"
    const val BITRATE_KBPS = 500

    // --- CAN IDs (B CAN unless noted) ---
    const val ID_BATT_POWERMODE    = 0x378  // B0[7:4]=HVPowermode nibble
    const val ID_MCM_TELEMETRY     = 0x1C0  // D CAN, gateway-passed to B CAN
    const val ID_HVAC_STATUS       = 0x276  // B0=PTC kW, B1=ACCM kW, B7=BattFanPWM
    const val ID_BMS_HV_BATT_TEMP  = 0x390  // B0=FrontInletTemp, B1=RearInletTemp, B3=ReturnTempDrv
    const val ID_HVAC_AIR_STATE    = 0x391  // B4=ReturnAirTemp, B5=EvapAirOffTemp
    const val ID_BMS_BATT_STATUS   = 0x383  // B0-B1 BE uint16 SoC x10
    const val ID_BMS_DRIVING_RANGE = 0x2C1  // B1=ExpRange, B3=MaxRange (raw bytes)
    const val ID_BMS_THERMAL       = 0x382  // B0=AvgCellTemp (raw-128 degC)
    const val ID_DCDC_STATUS1      = 0x1D5  // B3=Voltage14V raw, B6=Current14V raw

    // --- Page 2 (specs screen) IDs ---
    const val ID_BMS_DRIVE_LIMITS  = 0x275  // B0=DischargeLimit, B1=ChargeLimit, B2-3=PackCurrent, B4-5=PackVoltage
    const val ID_BMS_VMIN_VMAX     = 0x381  // B0-1=avg mV, B2-3=max mV, B4-5=min mV, B6=VmaxId, B7=VminId
    const val ID_BMS_FAULT_STATUS  = 0x270  // B0 = fault byte (see COLD_FAULT_B0)
    const val ID_GWM_VEH_FAULTS    = 0x271  // B0[1:0] = VehicleFaultLampReq
    const val ID_MCM_THERMAL       = 0x241  // D CAN, gateway-passed. Drivetrain temps, byte roles unconfirmed
    const val ID_AC_COMPRESSOR_CMD = 0x410  // B7 = max_pwr_consumption (commanded ceiling)
    const val ID_AC_COMPRESSOR_STS = 0x439  // B0=status, B1=speed, B2=power
    const val ID_CMS_INPUT         = 0x27B  // CMS AC input:  B0-1=V, B2-3=I
    const val ID_CMM_INPUT         = 0x27D  // CMM AC input:  B0-1=V, B2-3=I
    const val ID_CMS_OUTPUT        = 0x27C  // CMS HV output: B0-1=V, B2-3=I
    const val ID_CMM_OUTPUT        = 0x279  // CMM HV output: B0-1=V, B2-3=I
    const val ID_CMS_TEMPS         = 0x27A  // CMS: B0-1=Case, B2-3=PFC, B4-5=HV1, B6-7=HV2
    const val ID_BMS_CHARGER_CMD   = 0x050  // B5-6 = EVSEMaxCurrent (J1772 pilot, charge-only)

    /**
     * B CAN anchor IDs, used to pick the right bus when replaying a multi-bus log.
     * Channel numbers depend on dongle insertion order and are never stable across
     * capture sessions, so the bus must be identified by its content.
     */
    /**
     * Logical name for B CAN in [com.reverseit.cancore.BusIdentityResolver].
     *
     * The app is on B CAN via OBD pins 2/3, and that is also the bus the IPK reads the TPMS
     * telltale from -- `0x600` originates on D CAN at the RCU and reaches B CAN as a gateway
     * pass-through, so injecting on B CAN puts the frame directly at its consumer.
     */
    const val BUS_B_CAN = "b_can"

    val B_CAN_ANCHOR_IDS = setOf(
        ID_BMS_BATT_STATUS, ID_BATT_POWERMODE, ID_BMS_VMIN_VMAX,
        ID_BMS_DRIVE_LIMITS, ID_BMS_THERMAL, ID_DCDC_STATUS1,
    )

    /**
     * B CAN anchors that are **exclusive** to B CAN -- never gateway-rebroadcast onto D CAN.
     *
     * Use these, not [B_CAN_ANCHOR_IDS], to identify the bus for anything that *transmits*.
     *
     * Three of the six IDs in [B_CAN_ANCHOR_IDS] -- 0x275, 0x383 and 0x1D5 -- are B CAN native but
     * gateway-rebroadcast to D CAN (`notes/driver-inputs.md`, "B CAN -> D CAN direct pass-through").
     * They therefore appear on *both* buses, and `BusIdentityResolver`'s threshold is
     * `min(3, anchorIds.size)` = 3 matches, which D CAN can clear on rebroadcast traffic alone.
     * For picking a bus to *read* from -- what `B_CAN_ANCHOR_IDS` was written for, in
     * `ReplayCanSource` -- an occasional wrong pick costs a bad replay. For picking a bus to
     * transmit on it would put a synthetic frame on the driveline bus, so the sets are kept
     * separate rather than the looser one reused.
     *
     * Every ID here is on the B CAN exclusive list in `notes/driver-inputs.md`.
     */
    val B_CAN_EXCLUSIVE_IDS = setOf(
        ID_BATT_POWERMODE,    // 0x378
        ID_BMS_VMIN_VMAX,     // 0x381
        ID_BMS_THERMAL,       // 0x382
        ID_BMS_HV_BATT_TEMP,  // 0x390
        ID_HVAC_AIR_STATE,    // 0x391
        ID_BMS_FAULT_STATUS,  // 0x270
        ID_GWM_VEH_FAULTS,    // 0x271
        ID_BMS_DRIVING_RANGE, // 0x2C1
    )

    // --- Motor torque (0x1C0) ---
    // LE uint16, zero encoded as 0x7D80 = 32128, scale = 0.1 Nm/count
    const val MOTOR_TORQUE_ZERO_RAW    = 32128
    const val MOTOR_TORQUE_SCALE       = 0.1f   // Nm per count
    const val MOTOR_TORQUE_DEADBAND_NM = 5.0f   // |torque| < this -> TorqueState.NONE

    // --- HVPowermode (0x378 B0[7:4]) ---
    const val HVPOWERMODE_CHARGE = 5  // 3 and 4 both mean driving

    // --- Temperature encoding ---
    const val TEMP_RAW_OFFSET = 128  // T_degC = raw - 128

    // --- Driving range (0x2C1, provisional scale) ---
    // Calibrated 2026-03-22: green screen shows 94/123, raw bytes ~152/199 -> scale=0.62, offset=0
    const val RANGE_SCALE  = 0.62f  // miles per count
    const val RANGE_OFFSET = 0f     // miles

    // --- DCDC aux power (0x1D5) ---
    const val VOLTAGE_14V_SCALE  = 0.078431f  // V per count (B3)
    const val CURRENT_14V_MASK   = 0x7F       // 7-bit field in B6
    const val CURRENT_14V_SCALE  = 2.0f       // A per count

    // --- HVAC power (0x276) ---
    const val POWER_KW_SCALE = 0.1f  // kW per count

    // --- Display normalization (for notch position, 0.0-1.0) ---
    // Adjust these as needed once you see the app on device.
    const val MOTOR_TORQUE_DISPLAY_MAX_NM = 200f   // ±200 Nm = full scale
    const val CLIMATE_POWER_DISPLAY_MAX_KW = 8.0f
    const val AUX_POWER_DISPLAY_MAX_W = 2000f
    // Calibrated: x44px=8C, x90px=45C on a 19-113px bar -> min=-12, max=64
    const val BATT_TEMP_DISPLAY_MIN_C = -12f
    const val BATT_TEMP_DISPLAY_MAX_C = 64f

    // --- GUI update rate ---
    const val GUI_UPDATE_HZ = 10

    // --- Page 2 scales (all from CODA-B-CAN.dbc / CODA-D-CAN.dbc) ---
    const val CELL_MV_TO_V        = 0.001f   // 0x381 is 1 mV/bit
    const val PACK_CURRENT_SCALE  = 0.1f     // 0x275 B2-3, offset applied via ZERO_RAW
    const val PACK_CURRENT_ZERO   = 32768    // raw 0x8000 == 0.0 A
    const val LIMIT_AMPS_SCALE    = 2.0f     // 0x275 B0/B1 are 2 A/count
    const val CHARGER_SCALE       = 0.03125f // 0x27x V/I/temp fields are all /32
    const val EVSE_AMPS_SCALE     = 0.1f     // 0x050 B5-6, 0.1 A/bit

    /**
     * Empirical ceiling of the Coda's two onboard chargers combined: 6706-6751 W
     * across four sessions (0.7 % spread). NOT a spec figure, and not checked for
     * hot-pack or high-SoC derate. Used to draw the "CAR" limit line against the
     * EVSE offer so the display shows which side is actually binding.
     */
    const val ONBOARD_CHARGER_MAX_W = 6730f

    /**
     * 0x270 B0 value that drives the RED lamp via 0x271. Cause is an internal BMS
     * diagnostic not traceable from CAN -- see projects/coda/notes/
     * driving-sequence-investigation.md. Matched as a whole byte because the
     * severity/code nibble split in the DBC is disputed and unresolved.
     */
    const val COLD_FAULT_B0 = 0x12

    /**
     * Bytes of 0x241 shown on the drivetrain thermal slider.
     *
     * UNCONFIRMED. 0x241's role is confirmed (Rotor/Stator/IGBT) but the per-byte
     * assignment is not, and analysis of a drive log found ~6 live channels in the
     * frame, not 3 (B1 and B6 are the same channel; B4 is constant zero). See
     * projects/coda/notes/artifacts/mcm_thermal_0x241_bytes.py. Markers are drawn
     * unlabeled on a unitless scale so nothing on screen claims an identity that
     * has not been established. Change this list once the VICD sweep resolves it.
     */
    val MCM_THERMAL_BYTES = listOf(0, 1, 2)

    /** 0x241 raw bytes appear to be degC with this offset (also unconfirmed). */
    const val MCM_THERMAL_OFFSET_C = -40f

    // --- Indirect TPMS ------------------------------------------------------

    /**
     * Cold inflation pressure preloaded into the four tyre boxes on the settings page.
     * Calibration normally happens right after filling, so preloading saves ~100 button presses.
     *
     * **Two sources disagree and neither is a reading of this car's doorjamb placard.** Chosen
     * value confirmed by the owner 2026-09-21 with both figures in front of him; recorded here so
     * nobody re-opens it without the same information.
     *
     * | Source | Figure | What it is |
     * |---|---|---|
     * | Factory service manual, RCU DTC repair step | **42 psi** (chosen) | "Check tires for low pressure or damage. Repair or set to 42psi" -- five occurrences in the factory manual (internal-only) |
     * | `notes/indirect-tpms-feasibility.md` section 5 | 33 psi | Used in a "25 % loss from a 33 psi placard" calculation; not cited to a placard reading |
     * | Owner's gauge, 2026-09-20 | FL 31, FR 35, LR 33, RR 33 | Measured, but mid-leak-cycle |
     *
     * What makes 42 the manual's nominal figure rather than one instruction's number is that three
     * independent thresholds elsewhere in it are exact multiples: 33.6 psi (RCU DTC low) = 0.80x,
     * 35.7 psi (IPK lamp-on, `ipk-instrument-pack-function-overview.md`) = 0.85x, and 50.4 psi
     * (RCU DTC high) = 1.20x.
     *
     * The unresolved tension is that the owner's measured tyres sit at 31-35, which against a 42
     * placard puts **three of the four** below the 33.6 psi DTC low limit -- LF 31, LR 33 and
     * RR 33 below it, RF 35 above -- and all four between 16.7 % and 26.2 % under-inflated. So a
     * live RCU would have been setting a low-pressure DTC on three corners. **Confirm against the
     * actual doorjamb placard when the car is available** -- a preloaded value is the one that
     * gets submitted unchanged.
     */
    const val DEFAULT_TIRE_PSI = 42.0f

    /**
     * Subdirectory of the log directory holding the indirect-TPMS store --
     * `<externalFilesDir>/CodaLogs/tpms/`, a folder of immutable fragments (`TpmsEpochStore`).
     *
     * **Inside the log directory so SeaDrive on the head unit sweeps it up with everything else,
     * and in a subdirectory so nothing that prunes or deletes can touch it.** Every path that
     * deletes in the log directory is non-recursive and `.log`-only:
     *
     * | | |
     * |---|---|
     * | `LogFileServer` `/files` listing | log root, `.log`, non-recursive -- what the companion pulls then DELETEs |
     * | `LogFileServer` DELETE | log-root `.log` names only; no `/` |
     * | `CanLoggingService.pruneOldLogs` | `.log` filter, non-recursive -- the 10 GB cap cannot reach it |
     * | companion "Delete local copies" | `isFile && .log`, non-recursive |
     *
     * So the retention rule the owner asked for -- rollover and sync deletion remove CAN logs only,
     * never TPMS data -- holds by construction rather than by a rule someone has to remember.
     *
     * Reading is open: since 2026-09-26 `LogFileServer`'s `/tree` lists this folder and
     * `GET /files/tpms/<name>` serves it, so the store can be read back and verified over the
     * network. That retired the old trap ("switch the primary route to the companion and TPMS
     * backup silently stops"): the files are no longer invisible to the server.
     *
     * Writing is narrow: `PUT /files/tpms/<name>.jsonl` adds a new fragment here and nowhere else,
     * create-only, so a corrected drive row can be returned to the car (it supersedes the old row
     * in the store's dedupe; nothing is replaced). The store re-reads after each one.
     */
    const val TPMS_DIR = "tpms"

    /**
     * Subfolder of the log directory for diagnostic reports that have to reach Seafile because
     * there is no ADB to the car (`HardwareReport`). Same reachability as [TPMS_DIR]: SeaDrive,
     * plus read-only through `LogFileServer`'s `/tree`; never pulled-and-deleted by the companion.
     * A report arriving on the server is also evidence that SeaDrive syncs subfolders.
     */
    const val DIAG_DIR = "diag"

    // Wheel-speed channels the detection method reads. See
    // projects/coda/notes/indirect-tpms-feasibility.md section 2.
    const val ID_WHEEL_FRONT = 0x200  // B0=SubFrameID; LF/RF valid ONLY when SubFrameID == 0
    const val ID_WHEEL_REAR  = 0x208  // LR, RR, BrakePressure
    const val ID_STEERING    = 0x080  // SteeringAngle -- the straightness gate
    // Torque is ID_MCM_TELEMETRY (0x1C0), already declared above.

    /** Wheel channel scale: zero = 0xC000, 0.0567 km/h per count (17.61 counts per km/h). */
    const val WHEEL_SPEED_ZERO_RAW = 0xC000
    const val WHEEL_SPEED_SCALE_KMH = 0.0567f

    /**
     * RCU status frame. B7 bit 5 is the TPMS telltale the IPK reads off B CAN (0 = OFF,
     * 1 = FAULT); B5-B6 are an RCU awake-time counter that zeroes on restart.
     */
    const val ID_RCU_STATUS = 0x600
    const val TPMS_TELLTALE_MASK = 0x20  // 0x600 B7 bit 5
    /** Measured RCU cadence for 0x600: ~1.9 Hz, gaps clustered at 0.523-0.525 s. */
    const val RCU_STATUS_PERIOD_MS = 525L

    /**
     * Every CAN ID this app is permitted to transmit, enforced by [PeriodicTransmitter] at
     * registration. Deliberately a single ID.
     *
     * 0x600 is here because an indirect TPMS that drives the factory dash lamp must transmit it
     * continuously just to hold the lamp *off* -- the IPK appears to infer the fault from the
     * frame's absence, so there is no override, only replacement. That step also requires the RCU
     * to be physically removed, and the evidence for its safety is one parts-car observation that
     * contradicts the factory manual (feasibility document section 7a). Since 2026-09-26 the TPMS
     * lamp slot is registered for this ID (`TpmsLampSlot`), but the transmitter is only enabled
     * where [TPMS_LAMP_TX_ON_CAR] or the emulator harness says so; the allowlist is the
     * wiring-time guard, not the decision.
     */
    val TX_ALLOWED_IDS = setOf(ID_RCU_STATUS)

    /**
     * **The one switch for the TPMS dash lamp on the car.** Owner, 2026-09-26: "leave it disabled
     * for now until I confirm the RCU is disconnected (it's not yet)." Turned on 2026-10-04 for
     * build 31: "build v31 with the 0x600 TX enabled. I will go pull the RCU in the car and then
     * install it."
     *
     * False: the lamp slot is registered but [PeriodicTransmitter.enabled] stays false, so nothing
     * is ever sent from the car -- only the emulator harness (`debug.coda.slcan`, ADB-only) turns
     * the transmitter on. True: the car sends `0x600` on B CAN every [RCU_STATUS_PERIOD_MS], still
     * subject to every interlock, notably the contention guard, which holds the slot silent for as
     * long as an RCU is heard on the bus.
     */
    const val TPMS_LAMP_TX_ON_CAR = true

    // --- Replay (emulator / no-dongle testing) ---
    const val REPLAY_DIR = "replay"

}
