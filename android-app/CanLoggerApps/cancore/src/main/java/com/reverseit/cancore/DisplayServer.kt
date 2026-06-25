package com.reverseit.cancore

import android.util.Log
import com.reverseit.cancore.SubscriptionManifest.Aggregation
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.java_websocket.WebSocket
import org.java_websocket.drafts.Draft
import org.java_websocket.exceptions.InvalidDataException
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.handshake.ServerHandshakeBuilder
import org.java_websocket.server.WebSocketServer
import org.json.JSONArray
import org.json.JSONObject
import java.net.InetSocketAddress

private const val TAG = "DisplayServer"
private const val ENDPOINT_PATH = "/stream"
private val PROTOCOL_VERSIONS = intArrayOf(1)
private val SUPPORTED_WIRE_FORMATS = arrayOf("json")
private val SUPPORTED_AGGREGATIONS = arrayOf("decimate", "latest", "min", "max", "mean")

/**
 * Silence threshold (protocol §5 default). An identified bus that produces
 * no frames for this long is declared `bus_lost`, its resolver assignment
 * is dropped, and frame emission is gated until it re-identifies on
 * whatever fresh `busIndex` is now carrying the bus (e.g. after a truck
 * power-cycle re-enumerates the USB dongles).
 */
private const val BUS_LOST_THRESHOLD_MS = 5_000L
private const val BUS_LOST_POLL_MS = 1_000L

/**
 * WebSocket server implementing the CAN Display Protocol v1 (see
 * `android-app/notes/protocols/can-display-protocol.md`).
 *
 * Endpoint: `ws://<host>:<port>/stream`
 * Auth: `Authorization: Bearer <token>` (matches [LogFileServer]).
 *
 * Single-client semantics with takeover (protocol §10): the most recent
 * authenticated connection wins. The previous client is closed with
 * `error { code: "superseded", fatal: true }`.
 *
 * Composition over inheritance: the underlying [WebSocketServer] is a private
 * field, mirroring how [LogFileServer] hides NanoHTTPD. Consumer modules of
 * `:cancore` (`:vtrux`, `:companion`) do not need Java-WebSocket on their
 * compile classpath.
 */
class DisplayServer(
    port: Int,
    private val token: String,
    private val rawFrames: SharedFlow<CanFrame>,
    private val identities: List<BusIdentity>,
) {

    companion object {
        const val DEFAULT_PORT = 9878
        const val SERVER_NAME = "vtrux-logger"
        const val SERVER_VERSION = "0.1.0"
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val activeLock = Any()
    private var activeSession: ClientSession? = null

    private val server = object : WebSocketServer(InetSocketAddress(port)) {

        init {
            // Reuse the port immediately on restart; without this Android keeps the
            // bind in TIME_WAIT after the process is replaced (debug install -> rerun)
            // and the next start() throws "Address already in use".
            isReuseAddr = true
        }

        override fun onWebsocketHandshakeReceivedAsServer(
            conn: WebSocket,
            draft: Draft,
            request: ClientHandshake,
        ): ServerHandshakeBuilder {
            val path = request.resourceDescriptor
            if (path != ENDPOINT_PATH) {
                Log.w(TAG, "rejecting handshake: path='$path' (expected '$ENDPOINT_PATH')")
                throw InvalidDataException(404, "not found")
            }
            val authHeader = request.getFieldValue("Authorization")
            if (authHeader != "Bearer $token") {
                Log.w(TAG, "rejecting handshake: bad/missing Authorization header")
                throw InvalidDataException(401, "unauthorized")
            }
            return super.onWebsocketHandshakeReceivedAsServer(conn, draft, request)
        }

        override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
            Log.i(TAG, "client connected: ${conn.remoteSocketAddress}")
            val newSession = ClientSession(conn, rawFrames, identities, scope)
            val oldSession = synchronized(activeLock) {
                val prev = activeSession
                activeSession = newSession
                prev
            }
            if (oldSession != null) {
                Log.i(TAG, "superseding existing session ${oldSession.conn.remoteSocketAddress}")
                oldSession.supersede()
            }
            newSession.sendHello()
        }

        override fun onClose(conn: WebSocket, code: Int, reason: String, remote: Boolean) {
            Log.i(TAG, "client disconnected: code=$code remote=$remote reason='$reason'")
            synchronized(activeLock) {
                val s = activeSession
                if (s != null && s.conn === conn) {
                    s.shutdown()
                    activeSession = null
                }
            }
        }

        override fun onMessage(conn: WebSocket, message: String) {
            val s = synchronized(activeLock) { activeSession }
            if (s != null && s.conn === conn) {
                s.onMessage(message)
            }
        }

        override fun onError(conn: WebSocket?, ex: Exception) {
            Log.e(TAG, "ws error on ${conn?.remoteSocketAddress}: ${ex.message}", ex)
        }

        override fun onStart() {
            Log.i(TAG, "listening on $address")
            connectionLostTimeout = 30
        }
    }

    fun start() {
        server.start()
    }

    fun stop(timeoutMs: Int = 1_000) {
        try {
            server.stop(timeoutMs)
        } catch (e: InterruptedException) {
            Log.w(TAG, "stop interrupted: ${e.message}")
        }
        synchronized(activeLock) {
            activeSession?.shutdown()
            activeSession = null
        }
    }
}

/**
 * Per-connection state machine for one display client. Handles the
 * `hello`/`config`/`ready` handshake, parses DBCs and subscriptions, drives
 * bus identification, and (in Step 3) decodes + aggregates + emits frames.
 */
private class ClientSession(
    val conn: WebSocket,
    private val rawFrames: SharedFlow<CanFrame>,
    private val identities: List<BusIdentity>,
    private val scope: CoroutineScope,
) {

    private val identityNames: Set<String> = identities.map { it.name }.toSet()
    private val resolver = BusIdentityResolver(identities)

    private val identifiedBuses = HashSet<String>()
    private val pendingSubBuses = HashSet<String>()
    private val subscribedBuses = HashSet<String>()
    private val lastFrameMsByBus = HashMap<String, Long>()
    private var frameJob: Job? = null
    private var watchdogJob: Job? = null

    // Populated by handleConfig() once `config` is accepted.
    private var parsedDbcs: Map<String, Dbc> = emptyMap()
    private var subStates: List<SubState> = emptyList()
    private var streamStartMs: Long = 0L

    // Latched once the client's `config` has been accepted; further client
    // messages after this are protocol-level (keepalive / pong / reconfigure
    // in future versions). v1 ignores any post-config client traffic.
    @Volatile private var configured: Boolean = false

    fun sendHello() {
        val hello = JSONObject().apply {
            put("type", "hello")
            put("protocol_versions", JSONArray().apply {
                PROTOCOL_VERSIONS.forEach { put(it) }
            })
            put("wire_formats", JSONArray(SUPPORTED_WIRE_FORMATS.toList()))
            put("server_name", DisplayServer.SERVER_NAME)
            put("server_version", DisplayServer.SERVER_VERSION)
            put("supported_aggregations",
                JSONArray(SUPPORTED_AGGREGATIONS.toList()))
            put("supported_buses", JSONArray(identities.map { it.name }))
        }
        send(hello)
    }

    fun onMessage(text: String) {
        if (configured) {
            // v1: no client-to-server messages after config. Ignore (logged at
            // debug only to avoid log spam if a client misbehaves).
            Log.d(TAG, "ignoring post-config client message (${text.length} chars)")
            return
        }
        try {
            handleConfig(text)
        } catch (e: Exception) {
            Log.w(TAG, "config handling failed: ${e.message}", e)
            sendFatal("internal", "config handler crashed: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun handleConfig(text: String) {
        val obj = try {
            JSONObject(text)
        } catch (e: Exception) {
            sendFatal("internal", "invalid JSON: ${e.message}")
            return
        }
        if (obj.optString("type") != "config") {
            sendFatal("internal", "expected type=config, got ${obj.opt("type")}")
            return
        }
        val protocolVersion = obj.optInt("protocol_version", -1)
        if (protocolVersion !in PROTOCOL_VERSIONS) {
            sendFatal("protocol_version_mismatch",
                "client requested protocol_version=$protocolVersion")
            return
        }
        val wireFormat = obj.optString("wire_format", "json")
        if (wireFormat !in SUPPORTED_WIRE_FORMATS) {
            sendFatal("unsupported_wire_format",
                "client requested wire_format=$wireFormat")
            return
        }

        // ----- DBCs -----
        val dbcsObj = obj.optJSONObject("dbcs")
        if (dbcsObj == null || dbcsObj.length() == 0) {
            sendFatal("dbc_parse_error", "config.dbcs missing or empty")
            return
        }
        val parsedDbcs = HashMap<String, Dbc>()
        val keys = dbcsObj.keys()
        while (keys.hasNext()) {
            val busName = keys.next()
            val dbcText = dbcsObj.optString(busName, "")
            if (dbcText.isBlank()) {
                sendFatal("dbc_parse_error",
                    "config.dbcs[$busName] missing or empty")
                return
            }
            try {
                parsedDbcs[busName] = DbcParser.parse(dbcText)
            } catch (e: Exception) {
                sendFatal("dbc_parse_error", "bus '$busName': ${e.message}")
                return
            }
        }

        // ----- subscriptions -----
        val subsArr = obj.optJSONArray("subscriptions") ?: JSONArray()
        val subscriptions = ArrayList<SubscriptionManifest.Subscription>(subsArr.length())
        val active = JSONArray()
        for (i in 0 until subsArr.length()) {
            val s = subsArr.optJSONObject(i) ?: run {
                sendFatal("internal", "subscriptions[$i] is not an object")
                return
            }
            val bus = s.optString("bus", "")
            val messageId = s.optInt("message_id", -1)
            val rateHz = s.optDouble("rate_hz", -1.0)
            val aggregationStr = s.optString("aggregation", "")
            if (bus.isEmpty() || messageId < 0 || rateHz <= 0.0 || aggregationStr.isEmpty()) {
                sendFatal("internal",
                    "subscriptions[$i] missing one of bus / message_id / rate_hz / aggregation")
                return
            }
            if (bus !in identityNames) {
                sendFatal("subscription_unknown_bus",
                    "subscriptions[$i] references unknown bus '$bus'")
                return
            }
            val db = parsedDbcs[bus]
                ?: run {
                    sendFatal("subscription_missing_bus_dbc",
                        "subscriptions[$i] bus '$bus' has no entry in config.dbcs")
                    return
                }
            val msg = db.messages[messageId]
                ?: run {
                    sendFatal("internal",
                        "subscriptions[$i] message_id=$messageId not present in DBC for bus '$bus'")
                    return
                }
            // Signals: either a JSON array of names, "*" string for all, or
            // omitted entirely (defaults to all).
            val signalsRaw = s.opt("signals")
            val signalNames: List<String>? = when (signalsRaw) {
                null, JSONObject.NULL -> null
                is String -> if (signalsRaw == "*") null else listOf(signalsRaw)
                is JSONArray -> List(signalsRaw.length()) { signalsRaw.getString(it) }
                else -> {
                    sendFatal("internal",
                        "subscriptions[$i].signals must be a string or array")
                    return
                }
            }
            val resolvedSignals = signalNames ?: msg.signals.map { it.name }
            // Validate each requested signal exists in the message.
            val signalSet = msg.signals.map { it.name }.toSet()
            for (sn in resolvedSignals) {
                if (sn !in signalSet) {
                    sendFatal("subscription_unknown_signal",
                        "bus '$bus' message_id=$messageId has no signal '$sn'")
                    return
                }
            }
            val aggregation = Aggregation.values().firstOrNull { it.wire == aggregationStr }
                ?: run {
                    sendFatal("unsupported_aggregation",
                        "subscriptions[$i].aggregation='$aggregationStr' not supported")
                    return
                }
            subscriptions += SubscriptionManifest.Subscription(
                bus = bus,
                messageId = messageId,
                signals = signalNames,
                rateHz = rateHz,
                aggregation = aggregation,
            )
            active.put(JSONObject().apply {
                put("bus", bus)
                put("message_id", messageId)
                put("signals", JSONArray(resolvedSignals))
                put("rate_hz", rateHz)
            })
        }

        val subBuses = subscriptions.map { it.bus }.toSet()
        pendingSubBuses += subBuses
        subscribedBuses += subBuses

        // ----- per-subscription state -----
        this.parsedDbcs = parsedDbcs
        this.subStates = subscriptions.map { sub ->
            val msg = parsedDbcs[sub.bus]!!.messages[sub.messageId]!!
            val activeSignals = sub.signals ?: msg.signals.map { it.name }
            SubState(
                sub = sub,
                signalNames = activeSignals,
                windowMs = (1000.0 / sub.rateHz).toLong().coerceAtLeast(1L),
                aggregators = activeSignals.associateWith {
                    SignalAggregator(sub.aggregation, decimateN = 1)
                },
            )
        }

        // ----- ready -----
        send(JSONObject().apply {
            put("type", "ready")
            put("active_subscriptions", active)
            put("pending_buses", JSONArray(pendingSubBuses.toList().sorted()))
        })
        configured = true

        // ----- start frame loop (decode + aggregate + emit) -----
        frameJob = rawFrames
            .onEach { frame -> handleFrame(frame) }
            .launchIn(scope)

        // ----- bus-lost watchdog (protocol §5) -----
        watchdogJob = scope.launch {
            while (isActive) {
                delay(BUS_LOST_POLL_MS)
                checkBusLoss()
            }
        }
    }

    private fun checkBusLoss() {
        val nowMs = System.currentTimeMillis()
        // Snapshot to avoid ConcurrentModificationException; mutations happen below.
        val toLose = identifiedBuses.filter { bus ->
            val last = lastFrameMsByBus[bus] ?: return@filter false
            nowMs - last > BUS_LOST_THRESHOLD_MS
        }
        for (bus in toLose) {
            val silentSec = ((nowMs - (lastFrameMsByBus[bus] ?: nowMs)) / 1000.0)
            identifiedBuses -= bus
            if (bus in subscribedBuses) pendingSubBuses += bus
            resolver.forget(bus)
            lastFrameMsByBus.remove(bus)
            sendStatus("bus_lost", bus, "silent for %.1fs".format(silentSec))
        }
    }

    private fun handleFrame(frame: CanFrame) {
        val busName = resolver.observe(frame) ?: return
        lastFrameMsByBus[busName] = System.currentTimeMillis()
        if (busName !in identifiedBuses) {
            identifiedBuses += busName
            if (busName in pendingSubBuses) {
                pendingSubBuses -= busName
                val reason = resolver.reasons.value[busName] ?: "identified"
                sendStatus("bus_identified", busName, reason)
            }
        }
        // Hold frame emission until every subscribed bus has been identified
        // (protocol §3 "server emits frame messages only after all named
        // buses listed in the client's subscriptions have been identified
        // alive"). Status messages are still allowed during this window.
        if (pendingSubBuses.isNotEmpty()) return

        val db = parsedDbcs[busName] ?: return
        val msg = db.messages[frame.id] ?: return
        val decoded = try {
            DbcDecoder.decode(msg, frame.data)
        } catch (e: Exception) {
            return
        }

        val nowMs = frame.timestampMs
        if (streamStartMs == 0L) streamStartMs = nowMs

        for (s in subStates) {
            if (s.sub.bus != busName || s.sub.messageId != frame.id) continue
            for (signalName in s.signalNames) {
                val v = decoded[signalName] ?: continue
                s.aggregators[signalName]?.update(v)
            }
            if (s.sub.aggregation == Aggregation.DECIMATE) {
                if (s.aggregators.values.any { it.decimateDue() }) {
                    emitFrame(s, nowMs)
                }
                continue
            }
            if (nowMs - s.lastEmitMs >= s.windowMs) {
                emitFrame(s, nowMs)
                s.lastEmitMs = nowMs
            }
        }
    }

    private fun emitFrame(s: SubState, nowMs: Long) {
        val signals = JSONObject()
        for (name in s.signalNames) {
            val v = s.aggregators[name]?.flush() ?: continue
            signals.put(name, v)
        }
        if (signals.length() == 0) return
        val tSec = (nowMs - streamStartMs) / 1000.0
        send(JSONObject().apply {
            put("type", "frame")
            put("bus", s.sub.bus)
            put("message_id", s.sub.messageId)
            put("t", tSec)
            put("s", signals)
        })
    }

    fun supersede() {
        sendFatal("superseded", "replaced by new authenticated client")
        try {
            conn.close(1000, "superseded")
        } catch (_: Exception) {}
        shutdown()
    }

    fun shutdown() {
        frameJob?.cancel()
        frameJob = null
        watchdogJob?.cancel()
        watchdogJob = null
    }

    // --- send helpers ----------------------------------------------------

    private fun send(obj: JSONObject) {
        try {
            if (conn.isOpen) conn.send(obj.toString())
        } catch (e: Exception) {
            Log.w(TAG, "send failed: ${e.message}")
        }
    }

    private fun sendStatus(kind: String, bus: String, detail: String) {
        send(JSONObject().apply {
            put("type", "status")
            put("kind", kind)
            put("bus", bus)
            put("detail", detail)
        })
    }

    private fun sendFatal(code: String, message: String) {
        send(JSONObject().apply {
            put("type", "error")
            put("code", code)
            put("message", message)
            put("fatal", true)
        })
        try {
            conn.close(1011, code)
        } catch (_: Exception) {}
    }

    /** Per-subscription aggregation + window-pacing state. */
    private class SubState(
        val sub: SubscriptionManifest.Subscription,
        val signalNames: List<String>,
        val windowMs: Long,
        val aggregators: Map<String, SignalAggregator>,
    ) {
        var lastEmitMs: Long = 0L
    }
}
