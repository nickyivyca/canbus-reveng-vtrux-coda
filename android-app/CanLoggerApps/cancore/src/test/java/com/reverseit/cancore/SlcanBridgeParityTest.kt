package com.reverseit.cancore

import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * The emulator harness's cross-language seam: what `tools/slcan_bridge.py --busmaster` puts on
 * each bus's stream decodes, in Kotlin, to exactly the frames the Python side parsed from the log.
 *
 * Needs a dump from the bridge's selftest, which writes each bus's stream and the frames it was
 * built from:
 *
 *     py -3.11 tools/slcan_bridge.py --busmaster <T0.log> <T1.log> --vehicle coda --selftest --dump <dir>
 *
 * then `SLCAN_BRIDGE_DUMP=<dir>`. Skipped without it. Gradle does not treat the variable as a test
 * input, so run `:cancore:cleanTestDebugUnitTest` first after changing it.
 *
 * Decoded with [SlcanSource] -- the reader [SlcanBusGroup] runs per stream -- rather than through
 * the group, whose flow drops frames a slow collector cannot keep up with; an unpaced file read
 * is far faster than any collector, and that would test the buffer instead of the decode.
 */
class SlcanBridgeParityTest {

    @Test
    fun bridgeStreamsDecodeToTheParsedLog() {
        val dir = System.getenv("SLCAN_BRIDGE_DUMP")?.let(::File)
        assumeTrue("SLCAN_BRIDGE_DUMP not set", dir != null && dir.isDirectory)
        val streams = dir!!.listFiles { f -> f.name.endsWith(".slcan") }!!.sortedBy { it.name }
        assumeTrue("no .slcan streams in $dir", streams.isNotEmpty())

        for (stream in streams) {
            val bus = stream.name.removePrefix("bus").substringBefore('_').toInt()
            val expected = File(dir, stream.name.removeSuffix(".slcan") + ".expected").bufferedReader()
            var n = 0L
            var mismatch: String? = null
            val source = SlcanSource(bus, clock = { 0L }) { f ->
                val line = expected.readLine()
                val got = "%X %d %d %s".format(f.id, if (f.isExtended) 1 else 0, f.dlc,
                    f.data.copyOf(f.dlc).joinToString("") { "%02X".format(it) })
                if (mismatch == null && got != line) mismatch = "frame $n: expected '$line', got '$got'"
                if (f.busIndex != bus && mismatch == null) mismatch = "frame $n on bus ${f.busIndex}"
                n++
            }
            stream.inputStream().use { source.pump(it) }
            assertEquals(stream.name, null, mismatch)
            assertEquals("${stream.name}: frames left over in the expected list", null, expected.readLine())
            assertEquals("${stream.name}: malformed", 0L, source.stats.malformed)
            println("${stream.name}: $n frames identical")
            expected.close()
        }
    }
}
