package com.reverseit.cancore

import android.util.Log
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory

private const val TAG = "RemoteCanDataSource"

/**
 * CAN Display Protocol v1 client. Connects to a server, performs the
 * handshake described in the protocol spec §3-§5, and surfaces decoded
 * `frame` messages on the open flow while status/error messages drive the
 * [status] StateFlow.
 *
 * Network binding hook: pass a [socketFactory] (e.g. from `Network.getSocketFactory()`)
 * to bind connections to a specific Android transport. This is required on
 * cellular-on phones where the local subnet would otherwise be routed through
 * CGNAT and time out. Phase 7 wires this from the caller; for the test
 * server use case (no cellular contention), pass null.
 */
class RemoteCanDataSource(
    private val url: String,
    private val token: String,
    private val socketFactory: SocketFactory? = null,
) : CanDataSource {

    private val _status = MutableStateFlow<DataSourceStatus>(DataSourceStatus.Idle)
    override val status: StateFlow<DataSourceStatus> = _status.asStateFlow()

    private var liveSocket: WebSocket? = null

    override fun open(dbcs: Map<String, String>, manifest: SubscriptionManifest): Flow<DecodedSignalFrame> = callbackFlow {
        _status.value = DataSourceStatus.Connecting

        val clientBuilder = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS) // 0 == infinite, required for streaming
            .pingInterval(20, TimeUnit.SECONDS)
        if (socketFactory != null) clientBuilder.socketFactory(socketFactory)
        val client = clientBuilder.build()

        val request = Request.Builder()
            .url(url)
            .addHeader("Authorization", "Bearer $token")
            .build()

        val listener = object : WebSocketListener() {
            private var sentConfig = false
            private val activeBuses = LinkedHashSet<String>()

            override fun onOpen(webSocket: WebSocket, response: Response) {
                // Server sends `hello` first; sendConfig() runs on `hello` receipt.
                Log.i(TAG, "websocket open: ${response.code}")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = try {
                    JSONObject(text)
                } catch (e: Exception) {
                    Log.w(TAG, "ignored non-JSON frame: ${text.take(120)}")
                    return
                }
                when (msg.optString("type")) {
                    "hello" -> {
                        if (!sentConfig) {
                            sentConfig = true
                            webSocket.send(buildConfig(dbcs, manifest).toString())
                        }
                    }
                    "ready" -> {
                        val pending = msg.optJSONArray("pending_buses")
                            ?.let { (0 until it.length()).map { i -> it.getString(i) } }
                            ?: emptyList()
                        val active = msg.optJSONArray("active_subscriptions")?.length() ?: 0
                        _status.value = DataSourceStatus.Handshaking(active, pending)
                    }
                    "status" -> handleStatus(msg)
                    "frame" -> handleFrame(msg)
                    "error" -> {
                        val code = msg.optString("code")
                        val detail = msg.optString("message")
                        val reason = "$code: $detail"
                        Log.w(TAG, "server error: $reason fatal=${msg.optBoolean("fatal")}")
                        _status.value = DataSourceStatus.Failed(reason)
                        if (msg.optBoolean("fatal")) webSocket.close(1000, "server error")
                    }
                }
            }

            private fun handleStatus(msg: JSONObject) {
                val kind = msg.optString("kind")
                val bus = msg.optString("bus")
                when (kind) {
                    "bus_identified" -> {
                        activeBuses += bus
                        _status.value = DataSourceStatus.Streaming(activeBuses.toList())
                    }
                    "bus_silent", "bus_lost" -> {
                        activeBuses -= bus
                        _status.value = if (activeBuses.isEmpty()) {
                            DataSourceStatus.Failed("$kind: $bus")
                        } else {
                            DataSourceStatus.Streaming(activeBuses.toList())
                        }
                    }
                }
            }

            private fun handleFrame(msg: JSONObject) {
                val bus = msg.optString("bus")
                val messageId = msg.optInt("message_id")
                val t = msg.optDouble("t", 0.0)
                val s = msg.optJSONObject("s") ?: return
                val signals = LinkedHashMap<String, Double>(s.length())
                val it = s.keys()
                while (it.hasNext()) {
                    val k = it.next()
                    signals[k] = s.optDouble(k)
                }
                if (_status.value !is DataSourceStatus.Streaming) {
                    activeBuses += bus
                    _status.value = DataSourceStatus.Streaming(activeBuses.toList())
                }
                trySend(DecodedSignalFrame(bus, messageId, t, signals))
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // Protocol v1 is JSON text only. Drop binary frames.
                Log.w(TAG, "unexpected binary frame (${bytes.size} bytes); v1 is JSON only")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val reason = buildString {
                    append(t.javaClass.simpleName)
                    if (response != null) append(" (HTTP ${response.code})")
                    val msg = t.message
                    if (!msg.isNullOrBlank()) append(": ").append(msg)
                }
                Log.w(TAG, "websocket failed: $reason")
                _status.value = DataSourceStatus.Failed(reason)
                // Close the producer cleanly. Status flow already carries the failure;
                // propagating the Throwable here would surface it as an unhandled
                // exception on the consumer's coroutine scope.
                close(null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "websocket closed: $code $reason")
                if (_status.value !is DataSourceStatus.Failed) {
                    _status.value = DataSourceStatus.Failed("closed: $reason ($code)")
                }
                close()
            }
        }

        val socket = client.newWebSocket(request, listener)
        liveSocket = socket

        awaitClose {
            socket.close(1000, "client closing")
            liveSocket = null
            client.dispatcher.executorService.shutdownNow()
            // Do NOT clobber the status here. If the flow is closing because
            // of a failure, _status is already Failed and the UI needs to see
            // it. If the consumer is closing voluntarily, the explicit close()
            // method below sets Idle.
        }
    }

    override fun close() {
        liveSocket?.close(1000, "client closing")
        liveSocket = null
        _status.value = DataSourceStatus.Idle
    }

    private fun buildConfig(dbcs: Map<String, String>, manifest: SubscriptionManifest): JSONObject {
        val subs = JSONArray()
        for (s in manifest.subscriptions) {
            val obj = JSONObject()
                .put("bus", s.bus)
                .put("message_id", s.messageId)
                .put("rate_hz", s.rateHz)
                .put("aggregation", s.aggregation.wire)
            if (s.signals == null) {
                obj.put("signals", "*")
            } else {
                obj.put("signals", JSONArray(s.signals))
            }
            subs.put(obj)
        }
        val dbcsObj = JSONObject()
        for ((bus, text) in dbcs) {
            dbcsObj.put(bus, text)
        }
        return JSONObject()
            .put("type", "config")
            .put("protocol_version", 1)
            .put("wire_format", "json")
            .put("dbcs", dbcsObj)
            .put("subscriptions", subs)
    }
}
