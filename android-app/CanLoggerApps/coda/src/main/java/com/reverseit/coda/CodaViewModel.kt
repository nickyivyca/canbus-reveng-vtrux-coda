package com.reverseit.coda

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.reverseit.cancore.CanPipelineManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel for the Coda green screen display.
 *
 * Subscribes to [CanPipelineManager.frames] on an IO coroutine to keep the decoder fed.
 * Ticks at [CodaConstants.GUI_UPDATE_HZ] on the main thread to push display state to the UI.
 * Ticker is active only while the Activity is in the foreground (controlled by [setForeground]).
 */
class CodaViewModel : ViewModel() {

    private val decoder = CodaSignalDecoder()

    private val _displayState = MutableStateFlow(GreenScreenState())
    val displayState: StateFlow<GreenScreenState> = _displayState.asStateFlow()

    private var inForeground = false

    // Low-pass filter state for motor torque and aux power.
    // α = dt / (τ + dt) where τ=1s, dt=1/GUI_UPDATE_HZ.
    private val lpfAlpha = run {
        val dt = 1f / CodaConstants.GUI_UPDATE_HZ
        dt / (1f + dt)
    }
    private var filteredMotorNm      = 0f
    private var filteredClimatePowerKw = 0f
    private var filteredAuxPowerW    = 0f

    fun attach(pipeline: CanPipelineManager) {
        // Collect frames on IO and feed the decoder
        viewModelScope.launch(Dispatchers.IO) {
            pipeline.frames.collect { frame ->
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
                }
            }
        }
    }

    fun setForeground(active: Boolean) {
        inForeground = active
    }
}
