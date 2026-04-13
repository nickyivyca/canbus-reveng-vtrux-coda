package com.reverseit.coda

import com.reverseit.cancore.CanFrame
import com.reverseit.cancore.SignalDecoder
import com.reverseit.coda.CodaConstants.BATT_TEMP_DISPLAY_MAX_C
import com.reverseit.coda.CodaConstants.BATT_TEMP_DISPLAY_MIN_C
import com.reverseit.coda.CodaConstants.AUX_POWER_DISPLAY_MAX_W
import com.reverseit.coda.CodaConstants.CLIMATE_POWER_DISPLAY_MAX_KW
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_DEADBAND_NM
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_DISPLAY_MAX_NM
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_SCALE
import com.reverseit.coda.CodaConstants.MOTOR_TORQUE_ZERO_RAW

/**
 * Decodes B CAN frames into Coda display state.
 *
 * All signal IDs, byte positions, and scales come from CODA-B-CAN.dbc and coda.md.
 * Call [update] on every incoming frame (IO thread). Call [buildState] at 10 Hz (main thread).
 *
 * Thread safety: update() and buildState() may be called from different threads.
 * Each raw field is a plain Int/Float and reads/writes are individually atomic on JVM,
 * so no locking is needed for this display-only use case (a stale read of a single
 * field by one tick is acceptable).
 */
class CodaSignalDecoder : SignalDecoder {

    // 0x378 BattPowermode: B0[7:4] = HVPowermode nibble
    @Volatile private var hvPowermode: Int = 4   // default = HV On Drive

    // 0x1C0 MCM telemetry: B0-B1 LE uint16 motor torque
    @Volatile private var motorTorqueRaw: Int = MOTOR_TORQUE_ZERO_RAW

    // 0x276 HVACStatus: B0=PTC kW*10, B1=ACCM kW*10, B2=HVAC flags, B7=BattFanPWM
    @Volatile private var ptcPowerRaw:  Int = 0
    @Volatile private var accmPowerRaw: Int = 0
    @Volatile private var hvacFlags:    Int = 0   // B2: bit3=heating active, bit4=AC active
    @Volatile private var battFanPwm:   Int = 0

    // 0x390 BMS_HVBattTemp1: B0=FrontInlet, B1=RearInlet, B3=ReturnDrv (raw, T=raw-128)
    @Volatile private var frontInletRaw:  Int = 128   // 0 degC
    @Volatile private var rearInletRaw:   Int = 128
    @Volatile private var returnDrvRaw:   Int = 128

    // 0x391 HVACAirState: B4=ReturnAirTemp, B5=EvapAirOffTemp (raw, T=raw-128)
    @Volatile private var returnAirRaw:  Int = 128
    @Volatile private var evapAirOffRaw: Int = 128

    // 0x383 BMSBattStatus: B0-B1 BE uint16, SoC = raw/10 %
    @Volatile private var socRaw: Int = 0

    // 0x2C1 BMSDrivingRange: B1=ExpRange, B3=MaxRange (raw bytes)
    @Volatile private var expRangeRaw: Int = 0
    @Volatile private var maxRangeRaw: Int = 0

    // 0x382 BMSThermal: B0=AvgCellTemp (raw-128 degC)
    @Volatile private var battTempRaw: Int = 128

    // 0x1D5 DCDCStatus1: B3=Voltage14V, B6&0x7F=Current14V
    @Volatile private var voltage14vRaw:  Int = 0
    @Volatile private var current14vRaw:  Int = 0

    override fun update(frame: CanFrame) {
        val d = frame.data
        when (frame.id) {
            CodaConstants.ID_BATT_POWERMODE -> {
                if (d.size >= 1)
                    hvPowermode = (d[0].toInt() and 0xFF) ushr 4
            }
            CodaConstants.ID_MCM_TELEMETRY -> {
                if (d.size >= 2)
                    motorTorqueRaw = (d[0].toInt() and 0xFF) or ((d[1].toInt() and 0xFF) shl 8)
            }
            CodaConstants.ID_HVAC_STATUS -> {
                if (d.size >= 8) {
                    ptcPowerRaw  = d[0].toInt() and 0xFF
                    accmPowerRaw = d[1].toInt() and 0xFF
                    hvacFlags    = d[2].toInt() and 0xFF
                    battFanPwm   = d[7].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_HV_BATT_TEMP -> {
                if (d.size >= 4) {
                    frontInletRaw = d[0].toInt() and 0xFF
                    rearInletRaw  = d[1].toInt() and 0xFF
                    returnDrvRaw  = d[3].toInt() and 0xFF
                }
            }
            CodaConstants.ID_HVAC_AIR_STATE -> {
                if (d.size >= 6) {
                    returnAirRaw  = d[4].toInt() and 0xFF
                    evapAirOffRaw = d[5].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_BATT_STATUS -> {
                if (d.size >= 2)
                    socRaw = ((d[0].toInt() and 0xFF) shl 8) or (d[1].toInt() and 0xFF)
            }
            CodaConstants.ID_BMS_DRIVING_RANGE -> {
                if (d.size >= 4) {
                    expRangeRaw = d[1].toInt() and 0xFF
                    maxRangeRaw = d[3].toInt() and 0xFF
                }
            }
            CodaConstants.ID_BMS_THERMAL -> {
                if (d.size >= 1)
                    battTempRaw = d[0].toInt() and 0xFF
            }
            CodaConstants.ID_DCDC_STATUS1 -> {
                if (d.size >= 7) {
                    voltage14vRaw = d[3].toInt() and 0xFF
                    current14vRaw = d[6].toInt() and CodaConstants.CURRENT_14V_MASK
                }
            }
        }
    }

    /** Build a [GreenScreenState] from current signal values. Called at 10 Hz. */
    fun buildState(): GreenScreenState {
        val mode = if (hvPowermode == CodaConstants.HVPOWERMODE_CHARGE)
            DisplayMode.CHARGING else DisplayMode.DRIVING

        // Motor torque: decode from LE uint16 with zero at 0x7D80
        val torqueNm = (motorTorqueRaw - MOTOR_TORQUE_ZERO_RAW) * MOTOR_TORQUE_SCALE
        val motorState = when {
            torqueNm < -MOTOR_TORQUE_DEADBAND_NM -> TorqueState.NEGATIVE
            torqueNm >  MOTOR_TORQUE_DEADBAND_NM -> TorqueState.POSITIVE
            else -> TorqueState.NONE
        }

        // Battery thermal: gate on fan PWM, then compare inlet vs return temps
        val batteryThermal = if (battFanPwm == 0) {
            ThermalState.NONE
        } else {
            val inletAvg = (frontInletRaw + rearInletRaw) / 2.0f
            if (inletAvg > returnDrvRaw) ThermalState.HEATING else ThermalState.COOLING
        }

        // Cabin thermal: use discrete status bits from 0x276 B2 directly.
        // bit4=AC active, bit3=heating active. No fan gate needed — these bits are only
        // set when the respective system is actively running.
        val cabinThermal = when {
            hvacFlags and 0x10 != 0 -> ThermalState.COOLING
            hvacFlags and 0x08 != 0 -> ThermalState.HEATING
            else                    -> ThermalState.NONE
        }

        val socPct       = socRaw / 10f
        val expRangeMi   = expRangeRaw * CodaConstants.RANGE_SCALE + CodaConstants.RANGE_OFFSET
        val maxRangeMi   = maxRangeRaw * CodaConstants.RANGE_SCALE + CodaConstants.RANGE_OFFSET
        val climatePower = (ptcPowerRaw + accmPowerRaw) * CodaConstants.POWER_KW_SCALE
        val auxPowerW    = voltage14vRaw * CodaConstants.VOLTAGE_14V_SCALE *
                           current14vRaw * CodaConstants.CURRENT_14V_SCALE
        val battTempC    = (battTempRaw - CodaConstants.TEMP_RAW_OFFSET).toFloat()

        return GreenScreenState(
            mode            = mode,
            cabinThermal    = cabinThermal,
            motorTorque     = motorState,
            batteryThermal  = batteryThermal,
            socPercent      = socPct,
            expRangeMiles   = expRangeMi,
            maxRangeMiles   = maxRangeMi,
            motorTorqueNm   = torqueNm,
            climatePowerKw  = climatePower,
            auxPowerW       = auxPowerW,
            battTempC       = battTempC,
        )
    }

    // SignalDecoder bridge (for cancore generic interface)
    override fun snapshot(): Map<String, Float> {
        val s = buildState()
        return mapOf(
            "soc"     to s.socPercent,
            "exp_rng" to s.expRangeMiles,
            "max_rng" to s.maxRangeMiles,
            "torque"  to s.motorTorqueNm,
            "climate" to s.climatePowerKw,
            "aux_w"   to s.auxPowerW,
            "batt_t"  to s.battTempC,
        )
    }
}
