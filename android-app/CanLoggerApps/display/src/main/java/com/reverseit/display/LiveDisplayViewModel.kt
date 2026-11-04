package com.reverseit.display

import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.reverseit.cancore.CanDataSource
import com.reverseit.cancore.DataSourceStatus
import com.reverseit.cancore.DecodedSignalFrame
import com.reverseit.cancore.SubscriptionManifest
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

/**
 * Bridge between a [CanDataSource] and the live-display Compose screen.
 *
 * Exposes the most-recent value for each signal as a flat
 * `Map<signalName, Double>`. The screen looks up signals by name. This
 * keeps the rebuild of any single gauge cheap (the StateFlow emits a new
 * map on every frame; consumers debounce via `collectAsState`).
 *
 * For the rare case where two messages on different buses carry the same
 * signal name, last-write-wins. The first-draft Vtrux manifest does not
 * have that collision -- the rich 4-bit `bcm_mainc_stat` is on 0x440 and
 * we don't subscribe to the 2-bit one on 0x410.
 *
 * A value stays in the map after its message stops arriving, so
 * [signalSeenAtMs] records when each signal last arrived, on [clockMs]
 * (`SystemClock.elapsedRealtime`), for readouts that must go stale
 * (`GenInhibitStatus`).
 */
class LiveDisplayViewModel(
    private val dataSource: CanDataSource,
    val clockMs: () -> Long = { SystemClock.elapsedRealtime() },
) : ViewModel() {

    val status: StateFlow<DataSourceStatus> get() = dataSource.status

    private val _signalValues = MutableStateFlow<Map<String, Double>>(emptyMap())
    val signalValues: StateFlow<Map<String, Double>> = _signalValues.asStateFlow()

    private val _signalSeenAtMs = MutableStateFlow<Map<String, Long>>(emptyMap())
    val signalSeenAtMs: StateFlow<Map<String, Long>> = _signalSeenAtMs.asStateFlow()

    /** name -> display unit (parsed from DBC SG_ "<unit>" tokens). */
    private val units: MutableMap<String, String> = HashMap()

    private var streamJob: Job? = null

    fun unitOf(name: String): String = units[name] ?: ""

    fun setUnits(units: Map<String, String>) {
        this.units.clear()
        this.units.putAll(units)
    }

    fun start(dbcs: Map<String, String>, manifest: SubscriptionManifest) {
        stop()
        streamJob = dataSource.open(dbcs, manifest)
            .onEach { frame -> consume(frame) }
            .catch { /* status flow surfaces failures */ }
            .launchIn(viewModelScope)
    }

    fun stop() {
        streamJob?.cancel()
        streamJob = null
        dataSource.close()
    }

    override fun onCleared() {
        stop()
        super.onCleared()
    }

    private fun consume(frame: DecodedSignalFrame) {
        if (frame.signals.isEmpty()) return
        val now = clockMs()
        val next = HashMap(_signalValues.value)
        val seen = HashMap(_signalSeenAtMs.value)
        for ((name, value) in frame.signals) {
            next[name] = value
            seen[name] = now
        }
        _signalSeenAtMs.value = seen
        _signalValues.value = next
    }
}
