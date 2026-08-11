package com.reverseit.coda

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.reverseit.cancore.CanFrame
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel for the Coda display pages.
 *
 * Subscribes to a [Flow] of [CanFrame] on an IO coroutine to keep the decoder fed.
 * The source is deliberately just a Flow rather than a `CanPipelineManager`, so the
 * same ViewModel runs against live USB frames or a `ReplayCanSource` -- the latter
 * being the only way to exercise the UI on an emulator, which has no USB host
 * passthrough.
 *
 * Ticks at [CodaConstants.GUI_UPDATE_HZ] on the main thread to push display state to
 * the UI. Ticker is active only while the Activity is in the foreground (controlled
 * by [setForeground]).
 */
class CodaViewModel : ViewModel() {

    private val decoder = CodaSignalDecoder()

    private val _displayState = MutableStateFlow(GreenScreenState())
    val displayState: StateFlow<GreenScreenState> = _displayState.asStateFlow()

    private val _specsState = MutableStateFlow(SpecsState())
    val specsState: StateFlow<SpecsState> = _specsState.asStateFlow()

    private var inForeground = false
    private var attached = false

    // Low-pass filter state for motor torque and aux power.
    // α = dt / (τ + dt) where τ=1s, dt=1/GUI_UPDATE_HZ.
    private val lpfAlpha = run {
        val dt = 1f / CodaConstants.GUI_UPDATE_HZ
        dt / (1f + dt)
    }
    private var filteredMotorNm      = 0f
    private var filteredClimatePowerKw = 0f
    private var filteredAuxPowerW    = 0f

    /**
     * Start consuming [frames] and driving the display state.
     *
     * Safe to call more than once across Activity recreation; only the first call
     * starts the collector and the ticker.
     */
    fun attach(frames: Flow<CanFrame>) {
        if (attached) return
        attached = true

        // Collect frames on IO and feed the decoder
        viewModelScope.launch(Dispatchers.IO) {
            frames.collect { frame ->
                decoder.update(frame)
            }
        }

        // Tick at GUI_UPDATE_HZ on main -- only push state when in foreground
        viewModelScope.launch(Dispatchers.Main) {
            val intervalMs = 1000L / CodaConstants.GUI_UPDATE_HZ
            while (true) {
                delay(intervalMs)
                if (inForeground) {
                    val raw = decoder.buildState()
                    filteredMotorNm        += lpfAlpha * (raw.motorTorqueNm   - filteredMotorNm)
                    filteredClimatePowerKw += lpfAlpha * (raw.climatePowerKw  - filteredClimatePowerKw)
                    filteredAuxPowerW      += lpfAlpha * (raw.auxPowerW       - filteredAuxPowerW)
                    _displayState.value = raw.copy(
                        motorTorqueNm  = filteredMotorNm,
                        climatePowerKw = filteredClimatePowerKw,
                        auxPowerW      = filteredAuxPowerW,
                    )
                    // Page-2 DC-DC gauge shows the same aux-power quantity as the
                    // green screen (0x1D5 V x I). Reuse the already-updated
                    // low-pass value so it does not visibly step -- 0x1D5 current
                    // is 2 A/count, ~28 W per step at 14 V.
                    _specsState.value = decoder.buildSpecsState().copy(
                        dcdcW = filteredAuxPowerW.toDouble(),
                    )
                }
            }
        }
    }

    fun setForeground(active: Boolean) {
        inForeground = active
    }
}
