package com.reverseit.coda

import com.reverseit.cancore.CanFrame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * Replays the 17 captures in which the old icon logic flipped directly between HEATING and
 * COOLING (`projects/coda/notes/hvac/artifacts/hvac_mode_corpus.flips.csv`, 218 flips, 217 of them
 * the battery icon with B2 unchanged) through [CodaSignalDecoder], sampling the icons after every
 * `0x276` frame, as the corpus sweep did.
 *
 * The old logic is replayed alongside, from the same frames, so the test shows it is looking at the
 * population the sweep found and not at an empty one. With the nibble mapping, an icon can change
 * only when B2 does.
 *
 * Every frame of every channel goes to the decoder, as in the app. Skipped unless
 * `TPMS_CODA_LOGS` points at the `CodaLogs` folder.
 */
class HvacModeReplayTest {

    private val captures = listOf(
        "coda_20260410_122739_T1", "coda_20260410_122739_T2", "coda_20260411_192607_T0",
        "coda_20260421_123312_T0", "coda_20260421_123312_T1", "coda_20260421_123312_T2",
        "coda_20260422_102839_T0", "coda_20260422_102839_T1", "coda_20260422_192202_T0",
        "coda_20260422_192202_T1", "coda_20260613_093051_T3", "coda_20260722_102259_T7",
        "coda_20260722_112358_T0", "coda_20260722_112358_T1", "coda_20260921_112150_T1",
        "coda_20261005_103121_T1", "coda_20261025_210254_T0",
    )

    /** The pre-2026-10-30 decoder's icons: B2 bits for the cabin, coolant temperatures for the pack. */
    private class OldLogic {
        var b2 = 0; var fan = 0; var front = 128; var rear = 128; var ret = 128
        fun update(id: Int, d: IntArray) {
            when (id) {
                0x276 -> { b2 = d[2]; fan = d[7] }
                0x390 -> { front = d[0]; rear = d[1]; ret = d[3] }
            }
        }
        fun cabin() = when {
            b2 and 0x10 != 0 -> ThermalState.COOLING
            b2 and 0x08 != 0 -> ThermalState.HEATING
            else -> ThermalState.NONE
        }
        fun battery() = when {
            fan == 0 -> ThermalState.NONE
            (front + rear) / 2.0f > ret -> ThermalState.HEATING
            else -> ThermalState.COOLING
        }
    }

    private fun isFlip(a: ThermalState, b: ThermalState) =
        a != b && a != ThermalState.NONE && b != ThermalState.NONE

    @Test
    fun `icons change only with B2, where the old logic flipped`() {
        val dir = System.getenv("TPMS_CODA_LOGS")
        assumeTrue("TPMS_CODA_LOGS not set", !dir.isNullOrEmpty())

        var oldFlips = 0; var oldFlipsB2Same = 0
        var newFlips = 0; var newChangesB2Same = 0; var samples = 0
        val b2Seen = sortedSetOf<Int>()
        for (name in captures) {
            val dec = CodaSignalDecoder()
            val old = OldLogic()
            var prev: Triple<Int, ThermalState, ThermalState>? = null
            var prevOld: Pair<ThermalState, ThermalState>? = null
            File(dir, "$name.log").bufferedReader().useLines { lines ->
                for (line in lines) {
                    val tok = line.trim().split(Regex("\\s+"))
                    if (tok.size < 6 || !tok[3].startsWith("0x") || tok[4] !in setOf("s", "x")) continue
                    val bus = tok[2].toIntOrNull() ?: continue
                    val dlc = tok[5].toIntOrNull() ?: continue
                    val id = tok[3].substring(2).toInt(16)
                    val ints = IntArray(8) { i -> tok.getOrNull(6 + i)?.toIntOrNull(16) ?: 0 }
                    dec.update(CanFrame(bus - 1, 0L, id, tok[4] == "x", dlc,
                        ByteArray(8) { ints[it].toByte() }))
                    old.update(id, ints)
                    if (id != CodaConstants.ID_HVAC_STATUS) continue

                    samples++
                    val b2 = ints[2]
                    b2Seen += b2
                    val s = dec.buildState()
                    val now = Triple(b2, s.cabinThermal, s.batteryThermal)
                    prev?.let { p ->
                        if (isFlip(p.second, now.second) || isFlip(p.third, now.third)) newFlips++
                        if (p.first == b2 && (p.second != now.second || p.third != now.third)) newChangesB2Same++
                    }
                    prev = now
                    val o = old.cabin() to old.battery()
                    prevOld?.let { p ->
                        val f = isFlip(p.first, o.first).compareTo(false) + isFlip(p.second, o.second).compareTo(false)
                        oldFlips += f
                    }
                    if (prevOld != null && old.b2 == b2 && isFlip(prevOld!!.second, o.second)) oldFlipsB2Same++
                    prevOld = o
                }
            }
        }
        println("0x276 samples %d, B2 values %s".format(samples, b2Seen.joinToString(" ") { "%02X".format(it) }))
        println("old logic: %d HEATING<->COOLING flips, %d of them the battery icon with B2 unchanged"
            .format(oldFlips, oldFlipsB2Same))
        println("nibble mapping: %d HEATING<->COOLING flips, %d icon changes with B2 unchanged"
            .format(newFlips, newChangesB2Same))

        assertTrue("old logic should reproduce the sweep's flips, got $oldFlips", oldFlips >= 200)
        assertEquals(0, newChangesB2Same)
    }
}
