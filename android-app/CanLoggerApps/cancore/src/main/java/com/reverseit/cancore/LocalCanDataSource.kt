package com.reverseit.cancore

import android.util.Log
import com.reverseit.cancore.SubscriptionManifest.Aggregation
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val TAG = "LocalCanDataSource"

/** Silence threshold for bus_lost detection (protocol §5 default). */
private const val BUS_LOST_THRESHOLD_MS = 5_000L
private const val BUS_LOST_POLL_MS = 1_000L

/**
 * In-process [CanDataSource] -- taps the logger's [CanPipelineManager]
 * frame stream and applies the same identify/decode/aggregate logic the
 * remote protocol does, without any network round-trip.
 *
 * Used by `:vtrux` to drive the embedded live display on the logger
 * phone itself. The Phase 6 Android server-side protocol will share the
 * same [BusIdentityResolver] and [SignalAggregator] primitives.
 */
class LocalCanDataSource(
    private val rawFrames: SharedFlow<CanFrame>,
    private val identities: List<BusIdentity>,
) : CanDataSource {

    private val _status = MutableStateFlow<DataSourceStatus>(DataSourceStatus.Idle)
    override val status: StateFlow<DataSourceStatus> = _status.asStateFlow()

    override fun open(
        dbcs: Map<String, String>,
        manifest: SubscriptionManifest,
    ): Flow<DecodedSignalFrame> = callbackFlow {
        _status.value = DataSourceStatus.Connecting

        // Parse the per-bus DBCs once.
        val parsed: Map<String, Dbc> = try {
            dbcs.mapValues { (_, text) -> DbcParser.parse(text) }
        } catch (e: Exception) {
            Log.w(TAG, "DBC parse failed: ${e.message}", e)
            _status.value = DataSourceStatus.Failed("DBC parse: ${e.message}")
            close(null)
            return@callbackFlow
        }

        // Build the aggregator table: (busName, msgId, signalName) -> aggregator.
        // We hold one aggregator per subscribed signal, plus per-subscription
        // window-end bookkeeping.
        val subStates = manifest.subscriptions.map { sub ->
            val msg = parsed[sub.bus]?.messages?.get(sub.messageId)
            val activeSignals = when {
                sub.signals == null -> msg?.signals?.map { it.name } ?: emptyList()
                else -> sub.signals
            }
            SubState(
                sub = sub,
                signalNames = activeSignals,
                windowMs = (1000.0 / sub.rateHz).toLong().coerceAtLeast(1L),
                aggregators = activeSignals.associateWith {
                    SignalAggregator(sub.aggregation, decimateN = 1)
                }.toMutableMap(),
            )
        }

        val resolver = BusIdentityResolver(identities)
        val identifiedBuses = HashSet<String>()
        val pendingBuses = manifest.subscriptions.map { it.bus }.toMutableSet()
        val subscribedBuses = pendingBuses.toSet()
        val lastFrameMsByBus = HashMap<String, Long>()
        _status.value = DataSourceStatus.Handshaking(
            activeSubscriptions = manifest.subscriptions.size,
            pendingBuses = pendingBuses.toList().sorted(),
        )

        // Bus-lost watchdog (protocol §5): an identified bus that goes silent
        // for >5s gets its resolver assignment dropped so a fresh busIndex
        // (e.g. re-enumerated USB dongle after truck power-cycle) can claim
        // it on subsequent frames.
        val watchdogJob = launch {
            while (isActive) {
                delay(BUS_LOST_POLL_MS)
                val nowMs = System.currentTimeMillis()
                val toLose = identifiedBuses.filter { bus ->
                    val last = lastFrameMsByBus[bus] ?: return@filter false
                    nowMs - last > BUS_LOST_THRESHOLD_MS
                }
                for (bus in toLose) {
                    identifiedBuses -= bus
                    if (bus in subscribedBuses) pendingBuses += bus
                    resolver.forget(bus)
                    lastFrameMsByBus.remove(bus)
                    Log.i(TAG, "bus_lost: $bus (silent >${BUS_LOST_THRESHOLD_MS}ms)")
                    _status.value = if (identifiedBuses.isEmpty()) {
                        DataSourceStatus.Handshaking(
                            activeSubscriptions = manifest.subscriptions.size,
                            pendingBuses = pendingBuses.toList().sorted(),
                        )
                    } else {
                        DataSourceStatus.Streaming(identifiedBuses.toList())
                    }
                }
            }
        }

        val job = rawFrames
            .onEach { frame ->
                val busName = resolver.observe(frame) ?: return@onEach
                lastFrameMsByBus[busName] = System.currentTimeMillis()
                if (busName !in identifiedBuses) {
                    identifiedBuses += busName
                    pendingBuses -= busName
                    _status.value = DataSourceStatus.Streaming(identifiedBuses.toList())
                }
                val db = parsed[busName] ?: return@onEach
                val msg = db.messages[frame.id] ?: return@onEach
                val decoded = try {
                    DbcDecoder.decode(msg, frame.data)
                } catch (e: Exception) {
                    return@onEach
                }

                val nowMs = frame.timestampMs
                val matchingSubs = subStates.filter {
                    it.sub.bus == busName && it.sub.messageId == frame.id
                }
                for (s in matchingSubs) {
                    val tRel = nowMs - s.startMs.also {
                        if (s.startMs == 0L) s.startMs = nowMs
                    }
                    for (signalName in s.signalNames) {
                        val v = decoded[signalName] ?: continue
                        s.aggregators[signalName]?.update(v)
                    }
                    if (s.sub.aggregation == Aggregation.DECIMATE) {
                        // We treat decimate as "emit every N frames" based on
                        // the per-signal aggregator counter; if any aggregator
                        // is due, flush the whole subscription.
                        if (s.aggregators.values.any { it.decimateDue() }) {
                            emit(s, nowMs / 1000.0, this@callbackFlow::trySend)
                        }
                        continue
                    }
                    if (nowMs - s.lastEmitMs >= s.windowMs) {
                        emit(s, nowMs / 1000.0, this@callbackFlow::trySend)
                        s.lastEmitMs = nowMs
                    }
                }
            }
            .launchIn(this)

        awaitClose {
            job.cancel()
            watchdogJob.cancel()
            // Do not overwrite Failed; only clean closes set Idle here.
            if (_status.value is DataSourceStatus.Streaming ||
                _status.value is DataSourceStatus.Handshaking ||
                _status.value is DataSourceStatus.Connecting) {
                _status.value = DataSourceStatus.Idle
            }
        }
    }

    override fun close() {
        _status.value = DataSourceStatus.Idle
    }

    private fun emit(
        s: SubState,
        timestampSec: Double,
        send: (DecodedSignalFrame) -> Any,
    ) {
        val signals = LinkedHashMap<String, Double>(s.signalNames.size)
        for (name in s.signalNames) {
            val v = s.aggregators[name]?.flush() ?: continue
            signals[name] = v
        }
        if (signals.isEmpty()) return
        send(
            DecodedSignalFrame(
                bus = s.sub.bus,
                messageId = s.sub.messageId,
                timestamp = timestampSec,
                signals = signals,
            )
        )
    }

    private class SubState(
        val sub: SubscriptionManifest.Subscription,
        val signalNames: List<String>,
        val windowMs: Long,
        val aggregators: MutableMap<String, SignalAggregator>,
    ) {
        var startMs: Long = 0L
        var lastEmitMs: Long = 0L
    }
}
