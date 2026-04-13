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

}
