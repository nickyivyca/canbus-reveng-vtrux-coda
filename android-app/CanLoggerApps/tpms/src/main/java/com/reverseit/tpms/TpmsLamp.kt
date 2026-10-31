package com.reverseit.tpms

import com.reverseit.cancore.PeriodicTransmitter

/**
 * The factory TPMS dash lamp, driven by replacing the RCU's `0x600` frame -- prototype.
 *
 * Why a replacement and not an override: the IPK reads the telltale from `0x600` B7 bit 5, and
 * (owner's parts-car recollection, adopted as the working assumption) lights the lamp when the
 * frame is *absent*. So with the RCU removed something must send a well-formed `0x600` every
 * ~525 ms just to hold the lamp off, and set bit 5 to warn. See
 * `projects/coda/notes/indirect-tpms-feasibility.md` §1.2, §6 and §7a.
 *
 * A useful consequence: if this app stops, the frame stops and the lamp comes on. The failure
 * direction is "warns", never "hides a warning".
 *
 * Unknown, and only answerable on the car: whether the IPK latches bit 5 or follows it live
 * (which decides whether [LampMode.FLASH] does anything), whether it times out the frame's
 * absence and after how long, and what B1-B4 mean.
 */
enum class LampMode { OFF, STEADY, FLASH }

/**
 * Which lamp each detector state asks for. Owner, 2026-09-26: "all TPMS warn states should light
 * the light. if we can make it flash when it's worse and steady when just in warn that works too.
 * the exact state machine here doesn't have to be perfect - getting the plumbing working is more
 * important." Read here as: ADVISE steady, WARN flashing, and STALE -- the baseline no longer
 * describes the tyres, which also demands action -- steady.
 */
object TpmsLampPolicy {
    fun mode(state: TpmsState): LampMode = when (state) {
        TpmsState.LEARNING, TpmsState.OK -> LampMode.OFF
        TpmsState.ADVISE, TpmsState.STALE -> LampMode.STEADY
        TpmsState.WARN -> LampMode.FLASH
    }
}

/**
 * Successive `0x600` payloads, shaped like the RCU's own. Measured on B CAN in
 * `coda_20260618_195906_T0+T1` (1,139 frames) and consistent with the DBC's `BO_ 1536` comment:
 *
 * - **B0** steps `00 -> 03 -> 10 -> 13` and repeats, one step per frame;
 * - **B1-B4** are `01 01 07 00` in every file of the corpus (all four sensors dead throughout, so
 *   what they encode is unknown -- they are copied, not understood);
 * - **B5-B6** are the RCU's awake-time counter, little-endian, one count per two frames (~1.05 s),
 *   stepping on the frames whose B0 is `03` and `13`; it restarts at 0 when the RCU does, so a
 *   counter starting at 0 here looks like an RCU that has just woken;
 * - **B7** is `0x4A`, or `0x6A` with bit 5 (`TPMS_TelltaleFault`) set -- the only two values in
 *   the corpus.
 *
 * Not thread-safe; [PeriodicTransmitter] calls the payload provider from one thread.
 */
class RcuStatusFrames(
    startCounter: Int = 0,
    /** Frames on, then frames off, while flashing. 2 at ~525 ms is about one second each. */
    private val flashHalfFrames: Int = 2,
) {
    companion object {
        private val PHASES = intArrayOf(0x00, 0x03, 0x10, 0x13)
        private val FIXED = byteArrayOf(0x01, 0x01, 0x07, 0x00)
        const val B7_BASE = 0x4A
        const val TELLTALE_BIT = 0x20
        const val DLC = 8
    }

    private val counterBase = startCounter
    private var n = 0L
    private var flashN = 0L

    /** Frames built so far. */
    val built: Long get() = n

    /** The next frame's payload with the lamp as [mode] asks. */
    fun next(mode: LampMode): ByteArray {
        val phase = PHASES[(n % 4).toInt()]
        val counter = (counterBase + ((n + 1) / 2)).toInt() and 0xFFFF
        val lit = when (mode) {
            LampMode.OFF -> false
            LampMode.STEADY -> true
            LampMode.FLASH -> (flashN++ / flashHalfFrames) % 2 == 0L
        }
        if (mode != LampMode.FLASH) flashN = 0
        n++
        return byteArrayOf(
            phase.toByte(), FIXED[0], FIXED[1], FIXED[2], FIXED[3],
            (counter and 0xFF).toByte(), (counter ushr 8).toByte(),
            (B7_BASE or if (lit) TELLTALE_BIT else 0).toByte(),
        )
    }
}

/**
 * Registers the lamp slot. One function for the app and the tests, so the tests exercise the
 * wiring the app actually uses.
 *
 * Registration alone transmits nothing: [PeriodicTransmitter.enabled] is the gate, and every
 * interlock still applies -- above all the contention guard, which suppresses the slot for as long
 * as the RCU (or the gateway's copy of it) is heard sending `0x600` on the same bus.
 */
object TpmsLampSlot {
    const val KEY = "tpms_lamp"

    fun register(
        transmitter: PeriodicTransmitter,
        id: Int,
        periodMs: Long,
        /** The bus to send on, resolved by content (B CAN); null until identified. */
        busIndex: () -> Int?,
        mode: () -> LampMode,
        frames: RcuStatusFrames = RcuStatusFrames(),
    ) {
        transmitter.register(KEY, id, periodMs, busIndex) { frames.next(mode()) }
    }
}
