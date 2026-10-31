package com.reverseit.tpms

import com.reverseit.cancore.CanFrame
import com.reverseit.cancore.CanTransmitter
import com.reverseit.cancore.PeriodicTransmitter
import com.reverseit.cancore.PeriodicTransmitter.SlotState
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The `0x600` lamp-hold prototype: payload shape, lamp policy, and the slot through the interlocks. */
class TpmsLampTest {

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    /**
     * The first twelve `0x600` frames on B CAN in `coda_20260618_195906_T0`, verbatim. The lamp is
     * lit throughout (B7 `0x6A`) because that car's sensors are dead.
     */
    private val real = listOf(
        "0301010700773A6A", "1001010700773A6A", "1301010700783A6A", "0001010700783A6A",
        "0301010700793A6A", "1001010700793A6A", "13010107007A3A6A", "00010107007A3A6A",
        "03010107007B3A6A", "10010107007B3A6A", "13010107007C3A6A", "00010107007C3A6A",
    ).map(::hex)

    @Test
    fun reproducesTheRcusFramesByteForByte() {
        // Start one frame early (phase 00) so the first built frame lines up with real[0] (phase 03).
        val frames = RcuStatusFrames(startCounter = 0x3A76)
        frames.next(LampMode.STEADY)
        for ((i, want) in real.withIndex()) {
            assertArrayEquals("frame $i", want, frames.next(LampMode.STEADY))
        }
    }

    @Test
    fun lampOffClearsOnlyBit5() {
        val f = RcuStatusFrames().next(LampMode.OFF)
        assertEquals(RcuStatusFrames.DLC, f.size)
        assertEquals(0x4A, f[7].toInt() and 0xFF)
        assertArrayEquals(hex("0001010700"), f.copyOf(5))
    }

    @Test
    fun counterStartsAtZeroAndWraps() {
        val fresh = RcuStatusFrames()
        val counters = (0 until 6).map { fresh.next(LampMode.OFF).let { b -> (b[5].toInt() and 0xFF) or ((b[6].toInt() and 0xFF) shl 8) } }
        assertEquals(listOf(0, 1, 1, 2, 2, 3), counters)
        val wrap = RcuStatusFrames(startCounter = 0xFFFF)
        wrap.next(LampMode.OFF)
        val b = wrap.next(LampMode.OFF)
        assertEquals(0, (b[5].toInt() and 0xFF) or ((b[6].toInt() and 0xFF) shl 8))
    }

    @Test
    fun flashTogglesBit5EveryTwoFramesAndStartsLit() {
        val frames = RcuStatusFrames()
        val lit = (0 until 8).map { frames.next(LampMode.FLASH)[7].toInt() and 0x20 != 0 }
        assertEquals(listOf(true, true, false, false, true, true, false, false), lit)
        // Leaving and re-entering FLASH starts lit again.
        frames.next(LampMode.OFF)
        assertTrue(frames.next(LampMode.FLASH)[7].toInt() and 0x20 != 0)
    }

    @Test
    fun everyWarningStateLightsTheLamp() {
        assertEquals(LampMode.OFF, TpmsLampPolicy.mode(TpmsState.LEARNING))
        assertEquals(LampMode.OFF, TpmsLampPolicy.mode(TpmsState.OK))
        assertEquals(LampMode.STEADY, TpmsLampPolicy.mode(TpmsState.ADVISE))
        assertEquals(LampMode.STEADY, TpmsLampPolicy.mode(TpmsState.STALE))
        assertEquals(LampMode.FLASH, TpmsLampPolicy.mode(TpmsState.WARN))
    }

    // ------------------------------------------------------------ through PeriodicTransmitter

    private class Recorder : CanTransmitter {
        val sent = ArrayList<Triple<Int, Int, ByteArray>>()
        override fun canTransmit(busIndex: Int) = true
        override fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean): Boolean {
            sent.add(Triple(busIndex, id, data)); return true
        }
    }

    private fun rig(mode: () -> LampMode = { LampMode.OFF }, bus: () -> Int? = { 1 }): Pair<PeriodicTransmitter, Recorder> {
        val rec = Recorder()
        val tx = PeriodicTransmitter(rec, allowedIds = setOf(0x600))
        TpmsLampSlot.register(tx, 0x600, 525, busIndex = bus, mode = mode)
        return tx to rec
    }

    private fun rcuFrame(bus: Int, t: Long) =
        CanFrame(bus, t, 0x600, false, 8, hex("0301010700773A6A"))

    @Test
    fun registeredButDisabledSendsNothing() {
        val (tx, rec) = rig()
        for (t in 0L..5_000L step 25) tx.tick(t)
        assertEquals(0, rec.sent.size)
        assertEquals(SlotState.GATED, tx.states()[TpmsLampSlot.KEY])
    }

    @Test
    fun enabledSendsOnTheResolvedBusEvery525ms() {
        var mode = LampMode.OFF
        val (tx, rec) = rig(mode = { mode })
        tx.enabled = true
        for (t in 0L until 2_100L step 25) {
            if (t == 1_050L) mode = LampMode.STEADY
            tx.tick(t)
        }
        assertEquals(4, rec.sent.size)                      // t = 0, 525, 1050, 1575
        assertTrue(rec.sent.all { it.first == 1 && it.second == 0x600 && it.third.size == 8 })
        assertEquals(listOf(0x4A, 0x4A, 0x6A, 0x6A), rec.sent.map { it.third[7].toInt() and 0xFF })
        assertEquals(listOf(0x00, 0x03, 0x10, 0x13), rec.sent.map { it.third[0].toInt() and 0xFF })
    }

    @Test
    fun waitsForTheBusToBeIdentified() {
        var bus: Int? = null
        val (tx, rec) = rig(bus = { bus })
        tx.enabled = true
        tx.tick(0)
        assertEquals(SlotState.BUS_UNRESOLVED, tx.states()[TpmsLampSlot.KEY])
        bus = 0
        tx.tick(25)
        assertEquals(1, rec.sent.size)
    }

    /**
     * RCU still fitted: its frame (the gateway's copy, on B CAN) suppresses the slot, and the slot
     * resumes only once the RCU has been silent for the whole contention window.
     */
    @Test
    fun anRcuOnTheSameBusSuppressesTheSlot() {
        val (tx, rec) = rig()
        tx.enabled = true
        for (t in 0L until 10_000L step 25) {
            if (t < 3_000L && t % 525 == 0L) tx.observe(rcuFrame(bus = 1, t = t))
            tx.tick(t)
        }
        // Last heard at t = 2625, so contended until 7625; then sends at 7625, 8150, 8675, 9200, 9725.
        assertEquals(SlotState.ACTIVE, tx.states()[TpmsLampSlot.KEY])
        assertEquals(5, rec.sent.size)
    }

    @Test
    fun anRcuFrameOnTheOtherBusDoesNotSuppress() {
        val (tx, rec) = rig()
        tx.enabled = true
        for (t in 0L until 1_100L step 25) {
            tx.observe(rcuFrame(bus = 0, t = t))   // D CAN, where the RCU itself sits
            tx.tick(t)
        }
        assertEquals(3, rec.sent.size)
    }
}
