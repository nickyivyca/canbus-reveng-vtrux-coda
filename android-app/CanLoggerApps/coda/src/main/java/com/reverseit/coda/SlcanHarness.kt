package com.reverseit.coda

import com.reverseit.cancore.SlcanBusGroup
import java.net.InetSocketAddress
import java.net.Socket

/**
 * The emulator harness: real Coda logs replayed into the app over TCP, one SLCAN stream per bus,
 * by `tools/slcan_bridge.py --busmaster`. An AVD has no USB host, so this is the only way the
 * logger, segment rolls, drive rows, the GPS pairing and the transmitter run on real traffic
 * before the car. See `android-app/notes/plans/coda-slcan-harness-0x600.md`.
 *
 * **Off unless a system property says otherwise**, and the property can only be set over ADB:
 *
 *     adb reverse tcp:9000 tcp:9000 ; adb reverse tcp:9001 tcp:9001
 *     adb shell setprop debug.coda.slcan 9000,9001
 *     adb shell am force-stop com.reverseit.coda      (the choice is made once, at app start)
 *
 * The head unit has no ADB, so on the car the property is never set and [configuredPorts] is
 * empty: `CodaApplication` then uses `CanPipelineManager` exactly as before, with no harness
 * object constructed at all. It is not gated on `BuildConfig.DEBUG`, because the car runs debug
 * builds too.
 */
object SlcanHarness {

    const val PROPERTY = "debug.coda.slcan"

    /** The bridge, reached through `adb reverse`. */
    private const val HOST = "127.0.0.1"
    private const val CONNECT_TIMEOUT_MS = 2_000

    /**
     * Ports from [PROPERTY], one per bus in bus-index order; empty when unset or unreadable.
     * Read with `getprop` because `SystemProperties` is not public API.
     */
    fun configuredPorts(): List<Int> {
        val value = runCatching {
            val p = ProcessBuilder("getprop", PROPERTY).redirectErrorStream(true).start()
            val out = p.inputStream.bufferedReader().readText().trim()
            p.waitFor()
            out
        }.getOrDefault("")
        if (value.isEmpty()) return emptyList()
        val ports = value.split(',').map { it.trim().toIntOrNull() }
        if (ports.any { it == null || it !in 1..65535 }) {
            DebugLog.w("Harness", "$PROPERTY='$value' is not a port list; harness off")
            return emptyList()
        }
        return ports.filterNotNull()
    }

    /** A bus group dialling [ports], bus i on ports[i]. Not started. */
    fun create(ports: List<Int>): SlcanBusGroup = SlcanBusGroup(
        busCount = ports.size,
        connect = { bus ->
            val s = Socket()
            try {
                s.connect(InetSocketAddress(HOST, ports[bus]), CONNECT_TIMEOUT_MS)
                s.tcpNoDelay = true
            } catch (e: java.io.IOException) {
                s.close()
                throw e
            }
            SlcanBusGroup.Link(s.getInputStream(), s.getOutputStream()) { s.close() }
        },
        onLinkChange = { n -> DebugLog.log("Harness", "SLCAN streams connected: $n of ${ports.size}") },
    )
}
