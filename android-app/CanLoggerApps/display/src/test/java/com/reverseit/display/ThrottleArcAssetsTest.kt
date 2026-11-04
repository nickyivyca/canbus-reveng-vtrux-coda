package com.reverseit.display

import com.reverseit.cancore.DbcDecoder
import com.reverseit.cancore.DbcParser
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.File

/** The generator tach's green arc reads 0x0C9 APP (`notes/outstanding-changes.md` Change 9). */
class ThrottleArcAssetsTest {

    // Gradle runs JVM tests with the module directory as the working directory.
    private val assetDirs = listOf(
        "../vtrux/src/main/assets/live-display",
        "../companion/src/vtrux/assets/live-display",
    )

    @Test
    fun `both manifests subscribe APP on the OBD bus and no longer TPS`() {
        for (dir in assetDirs) {
            val text = File(dir, "manifest.json").readText()
            val subs = JSONObject(text).getJSONArray("subscriptions")
            val sub = (0 until subs.length()).map { subs.getJSONObject(it) }
                .single { it.getInt("message_id") == 0x0C9 }
            assertEquals(dir, "obd", sub.getString("bus"))
            assertEquals(dir, "Accelerator_Actual_Position", sub.getJSONArray("signals").getString(0))
            assertFalse(dir, text.contains("Throttle_Position"))
        }
    }

    @Test
    fun `the bundled OBD DBCs decode APP from 0x0C9 B4`() {
        val data = byteArrayOf(0x80.toByte(), 0x2E, 0xE0.toByte(), 0, 0x80.toByte(), 0, 0, 0)
        for (dir in assetDirs) {
            val msg = DbcParser.parse(File(dir, "dbcs/obd.dbc").readText()).messages.getValue(0x0C9)
            val app = DbcDecoder.decodeOne(msg.signalsByName.getValue("Accelerator_Actual_Position"), data)
            assertEquals(dir, 128 * 0.392157, app, 1e-6)
        }
    }
}
