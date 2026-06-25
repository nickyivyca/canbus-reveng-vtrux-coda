package com.reverseit.cancore

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * Abstract source of decoded, post-aggregation CAN signal frames.
 *
 * Two implementations live in :cancore:
 *   - [RemoteCanDataSource] -- speaks the CAN Display Protocol v1 over
 *     WebSocket to a separate server (test server today; logger phone in
 *     Phase 6).
 *   - LocalCanDataSource (Phase 5) -- taps the in-process pipeline on the
 *     Vtrux logger phone, applying the same aggregation primitives without
 *     any network round-trip.
 *
 * The :display UI module depends only on this interface, so the same Compose
 * screen runs against either implementation.
 */
interface CanDataSource {

    /** Most recent connection / streaming status. Updates push to the UI. */
    val status: StateFlow<DataSourceStatus>

    /**
     * Open the source with the given per-bus DBCs and subscriptions.
     * `dbcs` maps each named bus referenced by [manifest] to a DBC text
     * covering at least every message_id subscribed on that bus. Returns
     * a cold Flow of frames; collecting it starts the connection (or
     * local tap). Cancelling the collection closes the source.
     *
     * For [RemoteCanDataSource], status messages from the protocol layer
     * (bus_identified, bus_silent, error) update [status]; only `frame`
     * messages enter this flow.
     */
    fun open(dbcs: Map<String, String>, manifest: SubscriptionManifest): Flow<DecodedSignalFrame>

    /** Force-close any in-flight connection / tap. Idempotent. */
    fun close()
}

/** One decoded frame from the protocol's `frame` message. */
data class DecodedSignalFrame(
    val bus: String,
    val messageId: Int,
    val timestamp: Double,
    val signals: Map<String, Double>,
)

/**
 * Client-side representation of the protocol's `config.subscriptions`
 * array. Serialised as-is into the WebSocket `config` message.
 */
data class SubscriptionManifest(
    val subscriptions: List<Subscription>,
) {
    data class Subscription(
        val bus: String,
        val messageId: Int,
        val signals: List<String>?, // null == "*" (all signals in DBC)
        val rateHz: Double,
        val aggregation: Aggregation,
    )

    enum class Aggregation(val wire: String) {
        DECIMATE("decimate"),
        LATEST("latest"),
        MIN("min"),
        MAX("max"),
        MEAN("mean");
    }
}

sealed class DataSourceStatus {
    /** Not yet opened, or closed cleanly. */
    object Idle : DataSourceStatus()
    /** TCP+WebSocket handshake in flight; waiting for `hello`. */
    object Connecting : DataSourceStatus()
    /** Server has acknowledged the manifest; flush of `frame` messages is
     *  imminent. `pendingBuses` may be non-empty while bus identification
     *  is still in progress server-side. */
    data class Handshaking(
        val activeSubscriptions: Int,
        val pendingBuses: List<String>,
    ) : DataSourceStatus()
    /** At least one frame received recently. [activeBuses] = the named
     *  buses currently emitting. */
    data class Streaming(
        val activeBuses: List<String>,
    ) : DataSourceStatus()
    /** Connection failed or was closed unexpectedly. [reason] is a short
     *  message suitable for surfacing in the UI banner. */
    data class Failed(val reason: String) : DataSourceStatus()
}
