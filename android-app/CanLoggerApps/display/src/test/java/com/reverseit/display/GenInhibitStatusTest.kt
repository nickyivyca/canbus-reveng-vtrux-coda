package com.reverseit.display

import com.reverseit.cancore.DbcDecoder
import com.reverseit.cancore.DbcParser
import com.reverseit.display.GenInhibitStatus.FLAGS
import com.reverseit.display.GenInhibitStatus.MODE
import com.reverseit.display.GenInhibitStatus.SCHEMA_VER
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** `notes/protocols/gen-inhibit-status-interface.md`, "The rule". */
class GenInhibitStatusTest {

    // bit5 inhibit_live + bit6 key_on, everything else clear.
    private val transmitting = (1 shl 5) or (1 shl 6)

    private fun page(schema: Int = 8, mode: Int = 3, flags: Int = transmitting) =
        mapOf(SCHEMA_VER to schema.toDouble(), MODE to mode.toDouble(), FLAGS to flags.toDouble())

    private fun seenAt(t: Long) = mapOf(SCHEMA_VER to t, MODE to t, FLAGS to t)

    @Test
    fun `mode 3 with inhibit_live and key_on and nothing else set is inhibiting`() {
        assertTrue(GenInhibitStatus.inhibiting(8, 3, transmitting))
        // bits 1-3 (bus_on, bus_ours, autoarm_build) do not take part.
        assertTrue(GenInhibitStatus.inhibiting(8, 3, transmitting or 0b1110))
    }

    @Test
    fun `each transmit term on its own blocks it`() {
        assertFalse("inhibit_live clear", GenInhibitStatus.inhibiting(8, 3, 1 shl 6))
        assertFalse("key_on clear (key-off, armed but silent)", GenInhibitStatus.inhibiting(8, 3, 1 shl 5))
        assertFalse("shutdown_suppressed", GenInhibitStatus.inhibiting(8, 3, transmitting or (1 shl 4)))
        assertFalse("abort_latched", GenInhibitStatus.inhibiting(8, 3, transmitting or (1 shl 7)))
        assertFalse("disabled", GenInhibitStatus.inhibiting(8, 3, transmitting or 1))
    }

    @Test
    fun `only mode INHIBIT counts -- PASSIVE sets inhibit_live too`() {
        for (mode in listOf(0, 1, 2, 4, 5)) {
            assertFalse("mode $mode", GenInhibitStatus.inhibiting(8, mode, transmitting))
        }
    }

    @Test
    fun `only schema 8 is accepted, older and newer are unknown`() {
        for (schema in listOf(0, 2, 3, 7, 9, 255)) {
            assertFalse("schema $schema", GenInhibitStatus.inhibiting(schema, 3, transmitting))
        }
    }

    @Test
    fun `fresh for 3 s after the page arrived, then not inhibiting`() {
        assertTrue(GenInhibitStatus.inhibiting(page(), seenAt(10_000), 10_000))
        assertTrue(GenInhibitStatus.inhibiting(page(), seenAt(10_000), 13_000))
        assertFalse(GenInhibitStatus.inhibiting(page(), seenAt(10_000), 13_001))
    }

    @Test
    fun `absent inhibitor, or any one field missing or stale, is not inhibiting`() {
        assertFalse(GenInhibitStatus.inhibiting(emptyMap(), emptyMap(), 0))
        for (name in listOf(SCHEMA_VER, MODE, FLAGS)) {
            assertFalse("$name value missing", GenInhibitStatus.inhibiting(page() - name, seenAt(0), 0))
            assertFalse("$name never seen", GenInhibitStatus.inhibiting(page(), seenAt(0) - name, 0))
            assertFalse("$name stale", GenInhibitStatus.inhibiting(page(), seenAt(5_000) + (name to 0L), 5_000))
        }
    }

    // Gradle runs JVM tests with the module directory as the working directory.
    private val assetDirs = listOf(
        "../vtrux/src/main/assets/live-display",
        "../companion/src/vtrux/assets/live-display",
    )

    @Test
    fun `the bundled DBCs decode 0x7F1 at the bytes the rule assumes`() {
        val data = byteArrayOf(8, 9, 3, 0x60, 0, 3, 0x10, 0x27)
        for (dir in assetDirs) {
            val msg = DbcParser.parse(File(dir, "dbcs/powertrain.dbc").readText()).messages.getValue(0x7F1)
            val decoded = listOf(SCHEMA_VER, MODE, FLAGS).associateWith {
                DbcDecoder.decodeOne(msg.signalsByName.getValue(it), data)
            }
            assertEquals(dir, mapOf(SCHEMA_VER to 8.0, MODE to 3.0, FLAGS to 96.0), decoded)
            assertTrue(dir, GenInhibitStatus.inhibiting(decoded, seenAt(0), 0))
        }
    }

    @Test
    fun `both manifests subscribe the three fields on the powertrain bus`() {
        for (dir in assetDirs) {
            val subs = JSONObject(File(dir, "manifest.json").readText()).getJSONArray("subscriptions")
            val sub = (0 until subs.length()).map { subs.getJSONObject(it) }
                .single { it.getInt("message_id") == 0x7F1 }
            assertEquals(dir, "powertrain", sub.getString("bus"))
            val signals = sub.getJSONArray("signals").let { a -> (0 until a.length()).map { a.getString(it) } }
            assertEquals(dir, setOf(SCHEMA_VER, MODE, FLAGS), signals.toSet())
        }
    }
}
