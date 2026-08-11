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
    val B_CAN_ANCHOR_IDS = setOf(
        ID_BMS_BATT_STATUS, ID_BATT_POWERMODE, ID_BMS_VMIN_VMAX,
        ID_BMS_DRIVE_LIMITS, ID_BMS_THERMAL, ID_DCDC_STATUS1,
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

    // --- Replay (emulator / no-dongle testing) ---
    const val REPLAY_DIR = "replay"

}
