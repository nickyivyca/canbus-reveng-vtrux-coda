package com.reverseit.tpms

import java.io.BufferedReader
import java.io.File

/**
 * The per-log wheel-ratio computation behind every TPMS drive row: a port of `extract_one` in
 * `projects/coda/notes/artifacts/tpms_wheel_ratio_trend.py`, which produced the corpus the detector
 * was validated on. The Python is the reference; **diff behaviour against it, not against this
 * comment.** `WheelRatioParityTest` does exactly that on real captures.
 *
 * Kept numerically faithful rather than idiomatic, down to numpy's semantics where they matter:
 * `np.interp` on repeated abscissae, `np.gradient`'s one-sided ends, `round()` half-to-even for the
 * steady window length, and population standard deviation. Each is marked where it is used.
 *
 * **One deliberate difference, agreed with the algorithm session 2026-09-24:** the app computes a
 * row per 5-minute log segment, not per session, and centres steering on the running median of
 * the *session so far* (supplied by the caller) rather than on the row's own median -- a 5-minute
 * stretch of winding road can misplace its own median badly. The Python's whole-session centring
 * is reproduced by [extractSession] for the parity test only.
 *
 * Decoding is hand-rolled from byte positions, as in the Python, whose `check_decode` verifies
 * those positions against `cantools` on real frames. The parity test inherits that check: it
 * compares against the Python on the same logs, byte for byte.
 */
object WheelRatioExtractor {

    const val ID_STEER = 0x080
    const val ID_MCM = 0x1C0
    const val ID_FRONT = 0x200
    const val ID_REAR = 0x208

    /**
     * A wheel word whose 14-bit value is all ones is a dead channel, not a speed (spec section 1:
     * the DLCM's own invalid-value test is `0x3FFF`; the parts car's RR reads it in 12,534 of
     * 12,539 frames). The whole frame is dropped. Independent of the `SubFrameID` gate, because the
     * fault flag and the stuck channel are separate signals. Never fired on this car, so it does
     * not move parity with the Python, which lacks it.
     */
    const val STUCK = 0x3FFF

    /** `0x200` SubFrameID `ABSFault`: the parts car sends it in every frame, with RR dead behind it. */
    const val ESC_FAULT_SUBFRAME = 0x14

    const val VOID_ESC_FAULT = "esc_fault"
    const val VOID_WHEEL_STUCK = "wheel_stuck"

    /**
     * Ids sent on D CAN and **never** rebroadcast by the gateway: bus identity comes from these and
     * from nothing else (spec section 1, "Bus identity comes from anchors"). Every id the ratios read
     * (`0x200`, `0x208`, `0x080`, `0x1C0`) is rebroadcast onto B CAN, so counting their frames cannot
     * tell the buses apart -- which is what the withdrawn `dominantBus` did, on margins of one frame
     * or a tie. `0x300` is deliberately absent: D-only in every capture, but the DBC has a different
     * C CAN message on that id, and an anchor must be unique on every bus that could be logged.
     */
    val D_CAN_ANCHORS = setOf(0x308, 0x312, 0x325, 0x330, 0x580)

    /** Distinct anchor ids a channel needs to count as D CAN -- and a rival to count as ambiguity. */
    const val MIN_ANCHORS = 2

    /** The ids the ratios read; the D CAN channel must carry all four. */
    val SIGNAL_IDS = setOf(ID_FRONT, ID_REAR, ID_STEER, ID_MCM)

    /** Why a capture yielded no D CAN rows: see [selectDCan]. Stored in the drive row's `reject`. */
    const val REJECT_NO_D_CAN = "no_d_can"
    const val REJECT_AMBIGUOUS = "d_can_ambiguous"
    const val REJECT_INCOMPLETE = "d_can_incomplete"

    /** A rejected capture: a stable [code] for code to match, and [why] for a person. */
    class BusRejection(val code: String, val why: String) {
        override fun toString() = "$code: $why"
    }

    /**
     * Which channel is D CAN, from anchor evidence alone -- `select_d_can` in
     * `tpms_wheel_ratio_trend.py`. Returns the channel, or null and the reason. Three tests, each for
     * a case that has been seen:
     *  1. the winner needs [MIN_ANCHORS] **distinct** anchor ids, so one frame cannot decide;
     *  2. a rival needs [MIN_ANCHORS] distinct ids too before it counts as ambiguity -- stray single
     *     frames with implausible ids do occur, and presence alone would let one reject a good capture;
     *  3. the winner must carry all of [SIGNAL_IDS], so a D-CAN-looking channel missing what we came
     *     for is refused rather than yielding an empty row.
     * [signalIds] null skips test 3 (the live path, which cannot know until the segment ends).
     */
    fun selectDCan(
        anchorIds: Map<Int, Set<Int>>,
        signalIds: Map<Int, Set<Int>>?,
    ): Pair<Int?, BusRejection?> {
        val live = anchorIds.filterValues { it.size >= MIN_ANCHORS }
        if (live.isEmpty()) {
            val seen = anchorIds.filterValues { it.isNotEmpty() }.mapValues { it.value.size }
            return null to BusRejection(REJECT_NO_D_CAN,
                "no channel carries $MIN_ANCHORS distinct D CAN anchors (saw ${if (seen.isEmpty()) "none" else seen})")
        }
        if (live.size > 1) {
            return null to BusRejection(REJECT_AMBIGUOUS,
                "D CAN anchors on ${live.size} channels (" +
                    live.entries.sortedBy { it.key }.joinToString { (b, ids) ->
                        "$b: " + ids.sorted().joinToString("/") { "0x%X".format(it) } } +
                    ") -- the evidence does not separate")
        }
        val bus = live.keys.single()
        if (signalIds != null) {
            val missing = SIGNAL_IDS - signalIds[bus].orEmpty()
            if (missing.isNotEmpty()) {
                return null to BusRejection(REJECT_INCOMPLETE,
                    "channel $bus is D CAN but carries no " + missing.sorted().joinToString("/") { "0x%X".format(it) })
            }
        }
        return bus to null
    }

    /** True if either wheel word in `d[4..5]` / `d[6..7]` reads the 14-bit all-ones value. */
    fun stuckWheel(d: IntArray): Boolean = wheel(d, 4) == STUCK || wheel(d, 6) == STUCK

    /**
     * The 14-bit wheel count at `d[i..i+1]`: the count above `0xC000`, as the DBC now decodes it
     * (spec section 1). The top two bits are always `0b11` on the wire, so this equals the raw
     * word minus `0xC000`; masking is what the Python does.
     */
    fun wheel(d: IntArray, i: Int): Int = ((d[i] shl 8) or d[i + 1]) and STUCK

    /**
     * `0x208` brake pressure for the brakes-off gate (`<= 0`). 12 bits at start 19 with
     * `BrakePressure_Valid` at bit 20 (bit 4 of `d[2]`). **An invalid reading counts as braking**,
     * encoded 1.0: the smallest value that still fails the gate, so after interpolation onto the
     * front timeline it rejects itself and barely its neighbours. The old `raw16 - 4096` read the
     * valid bit as part of the value and called an invalid frame brakes OFF. Same as the Python
     * `read_frames` from 2026-09-26.
     */
    fun brake(d: IntArray): Double {
        val valid = (d[2] shr 4) and 1
        val press = ((d[2] and 0x0F) shl 8) or d[3]
        return if (valid == 1) press.toDouble() else 1.0
    }
    const val COUNTS_PER_KMH = 17.61      // vehicle_speed_chain.py, anchored to 0x491 ODO

    // Filters -- the values in tpms_wheel_ratio_trend.py and spec section 1.
    const val MIN_KMH = 25.0
    const val MAX_STEER_DEG = 2.0
    const val STEER_DEG_PER_COUNT = 0.1   // DBC scale; its offset is wrong, hence the centring
    const val MAX_STEER_RATE = 5.0        // deg/s
    /**
     * The v24 wide torque cap (DEL, L/R and the pairs), 40 Nm. **No longer the verdict cap** -- see
     * [VERDICT_TORQUE_NM]. Still used by [Filters.V24] (kept for parity tests) and, deliberately, by
     * the GPS block's strict channel ([GpsRateAccumulator]).
     */
    const val MAX_TORQUE_NM = 40.0
    const val MAX_TORQUE_FR_NM = 20.0

    /**
     * The torque cap on every contrast since proc 3 (owner, 2026-09-26: "yes do it, don't
     * want false positives"). On the corpus it takes the 6 psi fast-path false-alarm rate from
     * 1.03 % to none and sensitivity from 0.000092 to 0.000113 per psi, at 16 drives of 188, and it
     * costs samples per drive (5019 -> 1706 on `coda_20260926_155726`).
     *
     * **Why it helps is not the obvious reason** (spec section 1, algorithm session 2026-09-26).
     * Binned by instantaneous torque, F/R rises smoothly with it -- front-wheel creep, as expected --
     * but DEL is essentially flat and L/R is inconsistent between drives. So on DEL the cap is not
     * removing slip; it works as a proxy for the car being driven hard (acceleration, load transfer,
     * cornering). Anything that replaces it should aim at that, not at torque.
     */
    const val VERDICT_TORQUE_NM = 20.0
    const val STEADY_WIN_S = 1.0
    /** Spread of the mean-of-four over the trailing 1 s. 2% since v24; DEL reads the same at 1%. */
    const val STEADY_TOL = 0.02

    /** Width of the per-band ratio sums in a row (`ratio_bands`), same as the GPS block's bands. */
    const val RATIO_BAND_KMH = 10

    /** The filter settings that differ between rule sets. */
    class Filters(
        val torqueWideNm: Double,
        val torqueFrNm: Double,
        val steadyTol: Double,
        /** Centre on the > [FAST_CENTRE_KMH] samples (v24) or on all steering frames (before). */
        val fastCentre: Boolean,
    ) {
        companion object {
            val V24 = Filters(MAX_TORQUE_NM, MAX_TORQUE_FR_NM, STEADY_TOL, fastCentre = true)

            /**
             * Proc 3's filters: [VERDICT_TORQUE_NM] on every contrast, 2 %
             * steadiness, fast centre. F/R is unchanged from [V24] (it was already at 20 Nm). The
             * rest of proc 3, D CAN pinning, is in [readFrames] ([selectDCan]), for every filter set.
             */
            val PROC3 = Filters(VERDICT_TORQUE_NM, VERDICT_TORQUE_NM, STEADY_TOL, fastCentre = true)

            /**
             * Build 23 and the corpus tool `tpms_wheel_ratio_trend.py` as published. Kept for the
             * parity test against that tool, whose constants were measured under these filters.
             */
            val LEGACY = Filters(20.0, 20.0, 0.01, fastCentre = false)
        }
    }

    /**
     * The steering centre is estimated from samples above this speed only (spec section 1, owner
     * approved 2026-09-26): at highway speed the car is nearly always going straight, while low-speed
     * manoeuvring with the wheel turned can drag an all-samples median tens of degrees off -- the
     * recovered `coda_20260924_004341` went from 617 samples to none that way. Strictly greater,
     * on the extractor's own four-wheel-mean kmh, over the wheel-sample grid.
     */
    const val FAST_CENTRE_KMH = 60.0

    /** Fast samples needed before the fast centre is used; below it the all-samples median is. */
    const val FAST_CENTRE_MIN = 200

    const val CENTRE_SRC_FAST = "fast"
    const val CENTRE_SRC_ALL = "all"

    /** The Python drops a *session* below this; the app keeps every row (see [Result]). */
    const val PY_MIN_SAMPLES = 300

    /** Ratio names as they appear in the drive row and in the prototype's `contrasts()`. */
    val RATIO_NAMES = listOf("DEL", "FR", "LR_", "LFRF", "LRRR")

    /** One decoded frame. [a], [b], [c] are the per-ID values listed on [Frames]. */
    class Row(val t: Double, val bus: Int, val a: Double, val b: Double = 0.0, val c: Double = 0.0)

    /**
     * The four IDs read from one log, **D CAN only** ([selectDCan]; empty if D CAN could not be
     * established, and then [busRejection] says why), each sorted by time. Timestamps in seconds,
     * re-based so the first frame of these IDs or of an anchor, on any channel, is t = 0 (what
     * `parse_file` does to the ID-filtered file the Python reads).
     *
     *  - [front] `0x200`, SubFrameID 0 only: a = LF, b = RF (counts above `0xC000`). **The gate
     *    also excludes traction-control events** (they arrive as SubFrameID `0x20`; one 1.5 s burst in
     *    the whole mountain descent, algorithm session 2026-09-26) -- a side effect of a gate written
     *    for another purpose, recorded here so it survives any tidying of this filter.
     *  - [rear] `0x208`: a = LR, b = RR, c = brake (see [brake]: invalid counts as braking)
     *  - [steer] `0x080`: a = raw counts, uncentred
     *  - [torque] `0x1C0`: a = Nm
     */
    class Frames(
        val front: List<Row>,
        val rear: List<Row>,
        val steer: List<Row>,
        val torque: List<Row>,
        /** From the `START DATE AND TIME` header as `YYYYMMDDTHHMMSS`, or null if absent. */
        val startTs: String?,
        /** Frames of the [TEMP_CHANNELS] IDs, by ID. Not time-stamped: only medians are taken. */
        val temps: Map<Int, List<RawFrame>> = emptyMap(),
        /** `0x200` frames on an ESC bus carrying [ESC_FAULT_SUBFRAME]. See [voidReasons]. */
        val escFaultFrames: Long = 0,
        /** `0x200` (SubFrameID 0) or `0x208` frames on an ESC bus with a wheel word at [STUCK]. */
        val stuckWheelFrames: Long = 0,
        /**
         * Null when D CAN was established, else why not. **Not a void:** a void condemns the whole
         * session, and a segment without D CAN says nothing about the ESC's sensors -- the dongle
         * or logger lost the bus, or the car was keyed off. It yields a row with no
         * ratios, and this says why, so a missing row is explicable (spec section 8a item 5).
         */
        val busRejection: BusRejection? = null,
    ) {
        /**
         * Why this segment's TPMS data is void, or empty if it is not. **Owner's rule, 2026-09-26:
         * all TPMS data from a drive whose ESC sensors are problematic is void** -- the drive, not
         * just the flagged samples, because an intermittently failing sensor also produces frames
         * that pass every per-sample check (spec section 1, "Void the drive").
         *
         * "Problematic" is narrow on purpose. A healthy car also sends non-zero SubFrameIDs:
         * `0x1E` then `0x1C`, a fixed ~2 s + ~2 s pair when the ESC initialises at car power-up
         * (which can be well into a capture: it marks a key cycle mid-capture, spec section 1), and
         * separately `0x20`, ~1.5 s bursts that can recur within a capture. A rule keyed on
         * "SubFrameID != 0" would void every drive in the corpus and the app would sit in
         * LEARNING looking as if it were waiting for driving.
         */
        val voidReasons: List<String>
            get() = buildList {
                if (escFaultFrames > 0) add(VOID_ESC_FAULT)
                if (stuckWheelFrames > 0) add(VOID_WHEEL_STUCK)
            }
    }

    /** One frame's bus and its data bytes (as many as it carried). */
    class RawFrame(val bus: Int, val bytes: IntArray)

    /**
     * A temperature channel stored per drive row. **The list is the algorithm session's
     * (2026-09-24)**: the ambient proxy and its gate partner, a cross-check, the factory's own
     * outside-air estimate, and cabin air to flag HVAC activity. Byte positions and the
     * `(1, -128) degC` decode are from `projects/coda/CODA-B-CAN.dbc`, and
     * `DriveRowProducerTest` checks them against that file with `DbcDecoder`.
     *
     * [invalidRaw] is excluded from the median and counted against `valid_frac`. `0x80` is the
     * sentinel on every one of these. **It is also a genuine 0 degC**, which is discarded along with
     * it -- harmless in Santa Cruz, not somewhere that freezes; revisit before relying on these in
     * a cold climate. `Cell_T_avg` additionally has `0x00` (standby) and `0x33` (charge stopped),
     * per the DBC's own comment on the signal.
     *
     * Every channel also has a physical-plausibility backstop, [TEMP_MIN_C]..[TEMP_MAX_C], for
     * sentinels nobody has documented yet (`UnderHoodTemp` was all-sentinel on this car and was
     * only dropped because someone noticed).
     *
     * **The line these exclusions hold: drop values that are not measurements; never drop
     * measurements judged unrepresentative.** A sentinel is not a reading, so removing it is part
     * of decoding, and `valid_frac` records that it happened. The FrontInlet < Cell_T_avg ambient
     * gate discards real readings -- that is analysis, it is tunable, and it belongs at ingest.
     * The two are one short step apart; do not let the gate follow the sentinels into the writer.
     */
    class TempChannel(val name: String, val id: Int, val byte: Int, val invalidRaw: Set<Int>)

    val TEMP_CHANNELS = listOf(
        TempChannel("FrontInletAirTemp", 0x390, 0, setOf(0x80)),
        TempChannel("Cell_T_avg", 0x382, 0, setOf(0x80, 0x00, 0x33)),
        TempChannel("RearInletAirTemp", 0x390, 1, setOf(0x80)),
        TempChannel("OPAirTemp", 0x391, 3, setOf(0x80)),
        TempChannel("EvapAirOffTemp", 0x391, 5, setOf(0x80)),
    )
    private val TEMP_IDS = TEMP_CHANNELS.map { it.id }.toSet()
    const val TEMP_MIN_C = -40.0
    const val TEMP_MAX_C = 90.0

    /** A channel over one segment: median of the valid readings (degC) and the valid share. */
    class TempStat(val median: Double?, val validFrac: Double?, val n: Int)

    /** One ratio over its own samples. [n] 0 means none passed (mean and sd are NaN). */
    class Ratio(val mean: Double, val sd: Double, val n: Int)

    /** One ratio within one speed band: additive over segments and drives. */
    class BandStat(var n: Int = 0, var sum: Double = 0.0, var sumSq: Double = 0.0)

    /**
     * One log's (or, in [extractSession], one session's) filtered statistics.
     *
     * [n] can be 0, and then [ratios] is empty and [kmhMedian] is null: the app stores every row,
     * because the sample floor is a detector setting that may change (spec section 4).
     */
    class Result(
        val n: Int,
        val kmhMedian: Double?,
        val ratios: Map<String, Ratio>,
        /** The steering centre applied, in raw counts. Null when the log had no steering. */
        val steerCentre: Double?,
        /** |torque| over the wide samples, mean and population sd; null without torque frames. */
        val torqueAbsMean: Double? = null,
        val torqueAbsSd: Double? = null,
        /** Band lower edge (km/h) -> ratio name -> sums, over each ratio's own samples. */
        val bands: Map<Int, Map<String, BandStat>> = emptyMap(),
    )

    // ---------------------------------------------------------------------------- reading ----

    fun readFrames(file: File): Frames = file.bufferedReader(Charsets.UTF_8).use { readFrames(it) }

    fun readFrames(reader: BufferedReader): Frames {
        val front = ArrayList<Row>()
        val rear = ArrayList<Row>()
        val steer = ArrayList<Row>()
        val torque = ArrayList<Row>()
        val temps = HashMap<Int, ArrayList<RawFrame>>()
        var startTs: String? = null
        var origin = Double.NaN
        // Fault evidence per bus. Counted only on buses that also carry 0x208: C CAN has a
        // different message on ID 0x200 whose B0 spans ~0x07-0x1B, which includes 0x14, so an
        // unscoped count would void drives on a healthy car. The bus is identified by content.
        val faultByBus = HashMap<Int, Long>()
        val stuckFrontByBus = HashMap<Int, Long>()
        var stuckRear = 0L
        val rearBuses = HashSet<Int>()
        // Bus identity evidence (selectDCan): distinct anchor ids and signal ids per channel.
        val anchorIds = HashMap<Int, HashSet<Int>>()
        val signalIds = HashMap<Int, HashSet<Int>>()
        // Token boundaries, not substrings: a segment is ~1M lines and most carry an ID this does
        // not read, so the line is never split into objects (Change 14; it allocated ~1 GB per
        // segment). Every test below is the one the substring version made, in the same order.
        val tok = Tokens(MAX_TOKENS)
        val bytes = IntArray(8)

        while (true) {
            val line = reader.readLine() ?: break
            var first = 0
            while (first < line.length && line[first].isWhitespace()) first++
            if (first == line.length) continue
            if (line.startsWith("***", first)) {
                if (startTs == null) startTs = headerStartTs(line.trim())
                continue
            }
            val nt = tok.split(line)
            if (nt < 6) continue
            val id = parseId(tok, 3)
            if (id == NONE) continue
            val idInt = id.toInt()
            if (isTempId(idInt)) {
                // Collected without touching the time origin, which must stay the first frame of
                // the four ratio IDs for parity with the Python.
                tempFrame(tok, nt)?.let { temps.getOrPut(idInt) { ArrayList() }.add(it) }
                continue
            }
            val anchor = isAnchor(idInt)
            if (!anchor && !isSignal(idInt)) continue
            if (!tok.isEither(1, "Rx", "Tx")) continue
            val busL = tok.int(2, 10)
            if (busL == NONE) continue
            val bus = busL.toInt()
            if (!tok.isEither(4, "s", "x")) continue
            val dlcL = tok.int(5, 10)
            if (dlcL == NONE) continue
            val dlc = dlcL.toInt()
            val rel = parseTimestamp(tok, 0)
            if (rel.isNaN()) continue

            // The Python re-bases on the first line of its grep-filtered file, which carries the
            // anchors as well as the four IDs: the first frame of either, whatever its length.
            if (origin.isNaN()) origin = rel
            if (anchor) {
                anchorIds.getOrPut(bus) { HashSet() }.add(idInt)
                continue
            }
            signalIds.getOrPut(bus) { HashSet() }.add(idInt)
            var t = rel - origin
            if (t < -1.0) t += 86400.0          // midnight rollover, as parse_file

            // len(d) < 8 -> skipped. d is data_tokens[:dlc].
            val have = minOf(dlc, nt - 6)
            if (have < 8) continue
            var ok = true
            for (i in 0 until 8) {
                val v = tok.int(6 + i, 16)
                if (v !in 0L..255L) { ok = false; break }
                bytes[i] = v.toInt()
            }
            if (!ok) continue
            val d = bytes
            when (idInt) {
                ID_FRONT -> when {
                    d[0] == ESC_FAULT_SUBFRAME -> faultByBus.merge(bus, 1L, Long::plus)
                    d[0] == 0 && stuckWheel(d) -> stuckFrontByBus.merge(bus, 1L, Long::plus)
                }
                ID_REAR -> {
                    rearBuses.add(bus)
                    if (stuckWheel(d)) stuckRear++
                }
            }
            when (idInt) {
                ID_FRONT -> if (d[0] == 0 && !stuckWheel(d)) front.add(
                    Row(t, bus, wheel(d, 6).toDouble(), wheel(d, 4).toDouble()))
                ID_REAR -> if (!stuckWheel(d)) rear.add(
                    Row(t, bus, wheel(d, 6).toDouble(), wheel(d, 4).toDouble(), brake(d)))
                ID_STEER -> steer.add(Row(t, bus, ((d[2] shl 8) or d[3]).toDouble()))
                ID_MCM -> torque.add(Row(t, bus, (d[0] or (d[1] shl 8)) * 0.1 - 3212.8))
            }
        }
        // D CAN only, sorted: file order is not time order in every capture (AGENTS.md).
        val (dBus, rejection) = selectDCan(anchorIds, signalIds)
        fun pinned(rows: List<Row>) =
            if (dBus == null) emptyList() else rows.filter { it.bus == dBus }.sortedBy { it.t }
        return Frames(pinned(front), pinned(rear), pinned(steer), pinned(torque), startTs, temps,
            escFaultFrames = faultByBus.filterKeys { it in rearBuses }.values.sum(),
            stuckWheelFrames = stuckRear + stuckFrontByBus.filterKeys { it in rearBuses }.values.sum(),
            busRejection = rejection)
    }

    private fun tempFrame(tok: Tokens, nt: Int): RawFrame? {
        if (!tok.isEither(1, "Rx", "Tx")) return null
        val bus = tok.int(2, 10)
        if (bus == NONE) return null
        val dlc = tok.int(5, 10)
        if (dlc == NONE) return null
        if (parseTimestamp(tok, 0).isNaN()) return null  // same line validity as the ratio IDs
        val have = minOf(dlc.toInt(), nt - 6, 8)
        if (have <= 0) return null
        val b = IntArray(have)
        for (i in 0 until have) {
            val v = tok.int(6 + i, 16)
            if (v !in 0L..255L) return null
            b[i] = v.toInt()
        }
        return RawFrame(bus.toInt(), b)
    }

    /**
     * Median over the **whole segment**, not the kept samples: temperature does not depend on the
     * ratio filters, so restricting it would discard data for nothing and leave n = 0 rows with no
     * temperature at all. The channel is still the one with the most frames of each ID -- the
     * count-based pick the wheel channels dropped for [selectDCan] -- because these are B CAN ids
     * and no B CAN anchor set is settled yet (an open owner decision in the implementation doc).
     *
     * No gate is evaluated here. Whether FrontInlet < Cell_T_avg makes FrontInlet a true ambient
     * reading is a *setting*, applied at ingest; storing a flag would freeze it into the archive
     * (spec section 4, invariant 1).
     */
    fun temperatures(frames: Frames): Map<String, TempStat> =
        TEMP_CHANNELS.associate { ch ->
            val all = frames.temps[ch.id].orEmpty()
            val bus = all.groupingBy { it.bus }.eachCount().entries
                .fold(null as Map.Entry<Int, Int>?) { best, e -> if (best == null || e.value > best.value) e else best }?.key
            val raws = all.filter { it.bus == bus && it.bytes.size > ch.byte }.map { it.bytes[ch.byte] }
            val valid = raws.filter { it !in ch.invalidRaw && (it - 128.0) in TEMP_MIN_C..TEMP_MAX_C }
            ch.name to TempStat(
                median = if (valid.isEmpty()) null else median(DoubleArray(valid.size) { valid[it] - 128.0 }),
                validFrac = if (raws.isEmpty()) null else valid.size.toDouble() / raws.size,
                n = raws.size,
            )
        }

    // ------------------------------------------------------------------------- extraction ----

    /**
     * One log segment, as the app computes it. [steerCentre] is the running session-so-far median
     * in raw counts (from [SteeringCentre]); null means "no steering seen", which yields n = 0.
     */
    fun extractSegment(frames: Frames, steerCentre: Double?, filters: Filters = Filters.PROC3): Result =
        extract(frames.front, frames.rear, frames.steer, frames.torque, steerCentre, filters)
            ?: Result(0, null, emptyMap(), steerCentre)

    /**
     * The Python's `extract_one` exactly: chunks laid end to end with a 10 s gap, each chunk's
     * D CAN rows (pinned per file, as `read_frames` does), steering centred on the whole session's
     * median, and the same `None` outcomes (returned as null). For the parity test; the app uses
     * [extractSegment].
     */
    fun extractSession(chunks: List<Frames>, filters: Filters = Filters.PROC3): Result? {
        val f = ArrayList<Row>(); val r = ArrayList<Row>()
        val s = ArrayList<Row>(); val q = ArrayList<Row>()
        var tOff = 0.0
        for (c in chunks) {
            val span = if (c.front.isEmpty()) 0.0 else c.front.maxOf { it.t }
            c.front.mapTo(f) { shifted(it, tOff) }
            c.rear.mapTo(r) { shifted(it, tOff) }
            c.steer.mapTo(s) { shifted(it, tOff) }
            c.torque.mapTo(q) { shifted(it, tOff) }
            tOff += span + 10.0
        }
        val front = f.sortedBy { it.t }; val rear = r.sortedBy { it.t }
        val steer = s.sortedBy { it.t }; val torque = q.sortedBy { it.t }
        if (front.size < PY_MIN_SAMPLES || rear.size < PY_MIN_SAMPLES) return null
        val fast = if (filters.fastCentre) fastSteerRaw(front, rear, steer) else DoubleArray(0)
        val centre = when {
            fast.size >= FAST_CENTRE_MIN -> median(fast)
            steer.isEmpty() -> null
            else -> median(DoubleArray(steer.size) { steer[it].a })
        }
        val res = extract(front, rear, steer, torque, centre, filters) ?: return null
        return if (res.n < PY_MIN_SAMPLES) null else res
    }

    private fun shifted(x: Row, off: Double) = Row(x.t + off, x.bus, x.a, x.b, x.c)

    /** Raw (uncentred) steering on this segment's wheel grid wherever kmh > [FAST_CENTRE_KMH]. */
    fun fastSteerRaw(frames: Frames): DoubleArray = fastSteerRaw(frames.front, frames.rear, frames.steer)

    private fun fastSteerRaw(front: List<Row>, rear: List<Row>, steer: List<Row>): DoubleArray {
        if (front.isEmpty() || rear.isEmpty() || steer.isEmpty()) return DoubleArray(0)
        val t = DoubleArray(front.size) { front[it].t }
        val lr = interp(t, rear) { it.a }
        val rr = interp(t, rear) { it.b }
        val sa = interp(t, steer) { it.a }
        val out = DoubleArrayBuilder()
        for (i in t.indices) {
            val kmh = (front[i].a + front[i].b + lr[i] + rr[i]) / 4.0 / COUNTS_PER_KMH
            if (kmh > FAST_CENTRE_KMH) out.add(sa[i])
        }
        return out.toArray()
    }

    /** extract_one from D CAN rows onward. Null wherever the Python returns None. */
    private fun extract(
        front: List<Row>, rear: List<Row>, steer: List<Row>, torque: List<Row>, centre: Double?,
        f: Filters,
    ): Result? {
        if (front.isEmpty() || rear.isEmpty() || steer.isEmpty() || centre == null) return null
        val n = front.size
        if (n < 2) return null                            // np.gradient needs two points
        val t = DoubleArray(n) { front[it].t }
        val lf = DoubleArray(n) { front[it].a }
        val rf = DoubleArray(n) { front[it].b }

        val lr = interp(t, rear) { it.a }
        val rr = interp(t, rear) { it.b }
        val bp = interp(t, rear) { it.c }
        val sa = interp(t, steer) { (it.a - centre) * STEER_DEG_PER_COUNT }
        val tq = if (torque.isEmpty()) null else interp(t, torque) { it.a }

        val meanSpd = DoubleArray(n) { (lf[it] + rf[it] + lr[it] + rr[it]) / 4.0 }
        val kmh = DoubleArray(n) { meanSpd[it] / COUNTS_PER_KMH }

        val dt = gradient(t)
        val dsa = gradient(sa)

        val medDt = if (n > 10) median(DoubleArray(n - 1) { t[it + 1] - t[it] }) else 0.005
        // int(round(x)) in Python 3 is round-half-to-even; Math.rint is the same.
        val w = maxOf(2, Math.rint(STEADY_WIN_S / maxOf(medDt, 1e-6)).toInt())
        if (w > n) return null                            // _rolling_extreme returns None
        val steady = steadyMask(meanSpd, w, f.steadyTol)

        val keep = BooleanArray(n) { i ->
            kmh[i] > MIN_KMH &&
                bp[i] <= 0.0 &&
                Math.abs(sa[i]) < MAX_STEER_DEG &&
                (tq == null || Math.abs(tq[i]) < f.torqueWideNm) &&
                Math.abs(dsa[i] / maxOf(dt[i], 1e-6)) < MAX_STEER_RATE &&
                steady[i]
        }
        val idx = (0 until n).filter { keep[it] }
        if (idx.isEmpty()) return Result(0, null, emptyMap(), centre)
        // F/R's stricter cap: a subset of the wide samples, so one pass decides both.
        val idxFr = idx.filter { tq == null || Math.abs(tq[it]) < f.torqueFrNm }

        val ratios = LinkedHashMap<String, Ratio>()
        val bands = java.util.TreeMap<Int, LinkedHashMap<String, BandStat>>()
        fun put(name: String, use: List<Int>, num: (Int) -> Double, den: (Int) -> Double) {
            if (use.isEmpty()) { ratios[name] = Ratio(Double.NaN, Double.NaN, 0); return }
            val r = DoubleArray(use.size) { k -> num(use[k]) / den(use[k]) }
            ratios[name] = Ratio(r.average(), populationSd(r), use.size)
            for ((k, i) in use.withIndex()) {
                val band = (kmh[i] / RATIO_BAND_KMH).toInt() * RATIO_BAND_KMH
                val b = bands.getOrPut(band) { LinkedHashMap() }.getOrPut(name) { BandStat() }
                b.n++; b.sum += r[k]; b.sumSq += r[k] * r[k]
            }
        }
        put("DEL", idx, { lf[it] + rr[it] }, { rf[it] + lr[it] })
        put("FR", idxFr, { lf[it] + rf[it] }, { lr[it] + rr[it] })
        put("LR_", idx, { lf[it] + lr[it] }, { rf[it] + rr[it] })
        put("LFRF", idx, { lf[it] }, { rf[it] })
        put("LRRR", idx, { lr[it] }, { rr[it] })
        val absTq = tq?.let { q -> DoubleArray(idx.size) { Math.abs(q[idx[it]]) } }
        return Result(idx.size, median(DoubleArray(idx.size) { kmh[idx[it]] }), ratios, centre,
            torqueAbsMean = absTq?.average(), torqueAbsSd = absTq?.let { populationSd(it) }, bands = bands)
    }

    // ------------------------------------------------------------------ numpy equivalents ----

    /** `np.interp(t, xp, fp)` with xp ascending (ties allowed), clamped at both ends. */
    private inline fun interp(t: DoubleArray, rows: List<Row>, value: (Row) -> Double): DoubleArray {
        val m = rows.size
        val xp = DoubleArray(m) { rows[it].t }
        val fp = DoubleArray(m) { value(rows[it]) }
        return DoubleArray(t.size) { interpAt(t[it], xp, fp) }
    }

    fun interpAt(x: Double, xp: DoubleArray, fp: DoubleArray): Double {
        val m = xp.size
        if (x > xp[m - 1]) return fp[m - 1]
        if (x < xp[0]) return fp[0]
        // j with xp[j] <= x < xp[j+1]: the last index whose abscissa is <= x.
        var lo = 0; var hi = m                          // upper bound search
        while (lo < hi) { val mid = (lo + hi) ushr 1; if (xp[mid] <= x) lo = mid + 1 else hi = mid }
        val j = lo - 1
        if (j >= m - 1) return fp[m - 1]
        if (xp[j] == x) return fp[j]
        val slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])
        var r = slope * (x - xp[j]) + fp[j]
        if (r.isNaN()) {
            r = slope * (x - xp[j + 1]) + fp[j + 1]
            if (r.isNaN() && fp[j] == fp[j + 1]) r = fp[j]
        }
        return r
    }

    /** `np.gradient` for unit spacing: central differences inside, one-sided at the two ends. */
    fun gradient(a: DoubleArray): DoubleArray {
        val n = a.size
        return DoubleArray(n) { i ->
            when (i) {
                0 -> a[1] - a[0]
                n - 1 -> a[n - 1] - a[n - 2]
                else -> (a[i + 1] - a[i - 1]) / 2.0
            }
        }
    }

    /** `np.median`: the middle value, or the mean of the two middle values. */
    fun median(a: DoubleArray): Double {
        val s = a.copyOf().also { it.sort() }
        val m = s.size / 2
        return if (s.size % 2 == 1) s[m] else (s[m - 1] + s[m]) / 2.0
    }

    /** `np.std` (ddof = 0). */
    private fun populationSd(a: DoubleArray): Double {
        val mean = a.average()
        var acc = 0.0
        for (v in a) { val d = v - mean; acc += d * d }
        return Math.sqrt(acc / a.size)
    }

    /**
     * The steady-speed test over a trailing window of [w] **samples** (not seconds -- the window is
     * a sample count, which is why it straddles a chunk boundary in the Python and a segment
     * boundary here in the same way). Entries before the first full window are false.
     */
    private fun steadyMask(v: DoubleArray, w: Int, tol: Double): BooleanArray {
        val n = v.size
        val out = BooleanArray(n)
        val maxQ = ArrayDeque<Int>(); val minQ = ArrayDeque<Int>()
        for (i in 0 until n) {
            while (maxQ.isNotEmpty() && v[maxQ.last()] <= v[i]) maxQ.removeLast()
            maxQ.addLast(i)
            while (minQ.isNotEmpty() && v[minQ.last()] >= v[i]) minQ.removeLast()
            minQ.addLast(i)
            if (maxQ.first() <= i - w) maxQ.removeFirst()
            if (minQ.first() <= i - w) minQ.removeFirst()
            if (i >= w - 1) {
                val hi = v[maxQ.first()]; val lo = v[minQ.first()]
                out[i] = lo > 0 && (hi - lo) / maxOf(lo, 1.0) < tol
            }
        }
        return out
    }

    // ------------------------------------------------------------------------- line parsing ----

    private const val MAX_TOKENS = 16

    /** "No value" from the [Tokens] parsers: outside the range of any Int they return. */
    private const val NONE = Long.MIN_VALUE

    /** [D_CAN_ANCHORS] membership as a `when` on an Int, not `in` on a Set<Int>: no boxing per frame. */
    fun isAnchor(id: Int) = when (id) { 0x308, 0x312, 0x325, 0x330, 0x580 -> true; else -> false }
    // The same for the other two sets.
    private fun isSignal(id: Int) = id == ID_FRONT || id == ID_REAR || id == ID_STEER || id == ID_MCM
    private fun isTempId(id: Int) = id == 0x390 || id == 0x382 || id == 0x391

    init {
        // The `when` lists above must stay the sets they replace.
        check((0..0x7FF).filter { isAnchor(it) }.toSet() == D_CAN_ANCHORS)
        check((0..0x7FF).filter { isSignal(it) }.toSet() == SIGNAL_IDS)
        check((0..0x7FF).filter { isTempId(it) }.toSet() == TEMP_IDS)
    }

    /**
     * A line's whitespace-separated tokens as offsets into it: the old `tokenize`, which made a
     * substring of every token, without the substrings. At most [max] tokens, as before.
     */
    private class Tokens(max: Int) {
        lateinit var line: String
        val start = IntArray(max)
        val end = IntArray(max)

        fun split(s: String): Int {
            line = s
            var n = 0; var i = 0; val len = s.length
            while (i < len && n < start.size) {
                while (i < len && s[i].isWhitespace()) i++
                if (i >= len) break
                start[n] = i
                while (i < len && !s[i].isWhitespace()) i++
                end[n++] = i
            }
            return n
        }

        /** Token [k] equals [a] or [b], ignoring case (`String.equals(other, true)`). */
        fun isEither(k: Int, a: String, b: String): Boolean {
            val len = end[k] - start[k]
            return (len == a.length && line.regionMatches(start[k], a, 0, len, true)) ||
                (len == b.length && line.regionMatches(start[k], b, 0, len, true))
        }

        /** Token [k] as `String.toIntOrNull(radix)` would read it, or [NONE]. */
        fun int(k: Int, radix: Int): Long = intOf(line, start[k], end[k], radix)
    }

    /**
     * `String.toIntOrNull(radix)` over `s[from until to]`, returning [NONE] for null. A port of the
     * Kotlin standard library's own implementation, so a leading sign, non-ASCII digits and
     * overflow are accepted or refused exactly as before.
     */
    private fun intOf(s: String, from: Int, to: Int, radix: Int): Long {
        val length = to - from
        if (length == 0) return NONE
        val start: Int; val negative: Boolean; val limit: Int
        val firstChar = s[from]
        if (firstChar < '0') {
            if (length == 1) return NONE
            start = from + 1
            when (firstChar) {
                '-' -> { negative = true; limit = Int.MIN_VALUE }
                '+' -> { negative = false; limit = -Int.MAX_VALUE }
                else -> return NONE
            }
        } else {
            start = from; negative = false; limit = -Int.MAX_VALUE
        }
        val limitForMaxRadix = (-Int.MAX_VALUE) / 36
        var limitBeforeMul = limitForMaxRadix
        var result = 0
        for (i in start until to) {
            val digit = Character.digit(s[i].code, radix)
            if (digit < 0) return NONE
            if (result < limitBeforeMul) {
                if (limitBeforeMul == limitForMaxRadix) {
                    limitBeforeMul = limit / radix
                    if (result < limitBeforeMul) return NONE
                } else {
                    return NONE
                }
            }
            result *= radix
            if (result < limit + digit) return NONE
            result -= digit
        }
        return (if (negative) result else -result).toLong()
    }

    /** `0x<hex>` as the old `parseId`: more than two characters, `0x` or `0X`, then the hex. */
    private fun parseId(tok: Tokens, k: Int): Long {
        val s = tok.line; val a = tok.start[k]; val b = tok.end[k]
        if (b - a <= 2 || s[a] != '0' || (s[a + 1] != 'x' && s[a + 1] != 'X')) return NONE
        return intOf(s, a + 2, b, 16)
    }

    /**
     * `HH:MM:SS:TTTT` -> seconds, TTTT in 10 kHz ticks, or NaN. Evaluated in the Python's order so
     * the doubles match bit for bit.
     *
     * **Digits only, as `canre`'s `\d{1,2}:\d{2}:\d{2}:\d{4}`.** `CanLoggingService` writes frames
     * received just before a segment roll with a *negative* tick field (`00:00:00:-160`), which is
     * still four characters. The Python parser rejects those lines, and so -- for parity -- does
     * this; accepting them moved n by 6 on a real session and shifted every file's time origin.
     */
    private fun parseTimestamp(tok: Tokens, k: Int): Double {
        val s = tok.line; val a = tok.start[k]; val b = tok.end[k]
        // The three colons, as `split(':')` into exactly four parts.
        var c0 = -1; var c1 = -1; var c2 = -1
        for (i in a until b) if (s[i] == ':') when {
            c0 < 0 -> c0 = i
            c1 < 0 -> c1 = i
            c2 < 0 -> c2 = i
            else -> return Double.NaN
        }
        if (c2 < 0) return Double.NaN
        if (c0 - a !in 1..2 || c1 - c0 - 1 != 2 || c2 - c1 - 1 != 2 || b - c2 - 1 != 4) return Double.NaN
        for (i in a until b) if (i != c0 && i != c1 && i != c2 && !s[i].isDigit()) return Double.NaN
        val h = intOf(s, a, c0, 10)
        val m = intOf(s, c0 + 1, c1, 10)
        val sec = intOf(s, c1 + 1, c2, 10)
        val ticks = intOf(s, c2 + 1, b, 10)
        if (h == NONE || m == NONE || sec == NONE || ticks == NONE) return Double.NaN
        return h.toInt() * 3600.0 + m.toInt() * 60.0 + sec.toInt() + ticks.toInt() * 0.0001
    }

    private val START_RE = Regex("""^\*\*\*START DATE AND TIME\s+(\d{2}):(\d{2}):(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})""",
        RegexOption.IGNORE_CASE)

    /**
     * A log's `START DATE AND TIME` as `YYYYMMDDTHHMMSS`, from its header only -- for a segment still
     * being written, whose frames are not read. Null if the header has no such line (yet).
     */
    fun readStartTs(file: File, maxLines: Int = 40): String? = try {
        file.bufferedReader(Charsets.UTF_8).use { r ->
            generateSequence { r.readLine() }.take(maxLines).firstNotNullOfOrNull { headerStartTs(it) }
        }
    } catch (_: java.io.IOException) {
        null
    }

    /** `***START DATE AND TIME 18:06:2026 19:59:06:701***` -> `20260618T195906`. */
    private fun headerStartTs(line: String): String? {
        val g = START_RE.find(line)?.groupValues ?: return null
        return "%s%s%sT%02d%s%s".format(g[3], g[2], g[1], g[4].toInt(), g[5], g[6])
    }
}

/** A growable DoubleArray. */
class DoubleArrayBuilder {
    private var a = DoubleArray(1024)
    var size = 0
        private set

    fun add(v: Double) {
        if (size == a.size) a = a.copyOf(a.size * 2)
        a[size++] = v
    }

    fun addAll(v: DoubleArray) = v.forEach { add(it) }

    fun toArray(): DoubleArray = a.copyOf(size)
}

/**
 * Running median of the fast steering samples ([WheelRatioExtractor.fastSteerRaw]) over the session
 * so far. They are interpolated, so not integers, and are kept: an hour at 100 Hz is ~3 MB, freed
 * with the session.
 */
class FastSteeringCentre {
    private val values = DoubleArrayBuilder()
    val n: Long get() = values.size.toLong()

    fun add(v: DoubleArray) = values.addAll(v)

    fun median(): Double? = if (values.size == 0) null else WheelRatioExtractor.median(values.toArray())
}

/**
 * Running median of raw steering counts over the session so far -- the straight-ahead reference
 * for both the drive rows and the live GPS path. Exact, from a histogram of the integer raw counts,
 * so no sample is retained.
 *
 * The histogram is a Fenwick tree over the 16-bit raw range, so [add] and [median] are each ~16
 * steps. The live path asks for the median on every wheel sample (100 Hz), and the `TreeMap` walk it
 * replaced cost ~75% of that path's CPU, growing with the session (Change 14). Same values as the
 * walk: the two middle ranks, averaged.
 */
class SteeringCentre {
    private val tree = LongArray(SIZE + 1)              // 1-based; raw value v is at index v + 1
    var n = 0L
        private set

    /** [raw] is `0x080` B2..B3, so always 0..0xFFFF. */
    fun add(raw: Int) {
        require(raw in 0 until SIZE) { "steering raw $raw outside 16 bits" }
        var i = raw + 1
        while (i <= SIZE) { tree[i]++; i += i and -i }
        n++
    }

    /** `np.median` of everything added: the middle value, or the mean of the two middle. */
    fun median(): Double? {
        if (n == 0L) return null
        return (valueAt((n - 1) / 2) + valueAt(n / 2)) / 2.0
    }

    /** The value at 0-based [rank] in sorted order. */
    private fun valueAt(rank: Long): Int {
        var pos = 0
        var rem = rank
        var step = SIZE
        while (step > 0) {
            val next = pos + step
            if (next <= SIZE && tree[next] <= rem) { pos = next; rem -= tree[next] }
            step = step shr 1
        }
        return pos                                       // index pos + 1 holds value pos
    }

    private companion object {
        const val SIZE = 1 shl 16
    }
}
