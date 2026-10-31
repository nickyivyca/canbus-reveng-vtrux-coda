package com.reverseit.tpms

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.math.BigDecimal
import java.math.RoundingMode
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Turns each closed CAN log segment into one TPMS drive row (spec section 4: "one drive row per
 * CAN log closed", so the TPMS file is 1:1 with the logs beside it).
 *
 * The row is computed by **re-reading the closed log**, not from the live frame stream, so the
 * input is byte-for-byte what the Python reference reads and the parity test is meaningful. A
 * 5-minute segment is ~37 MB; parsing it takes ~0.4 s on a desktop JVM, a few seconds on the head
 * unit, on this class's own thread.
 *
 * **Steering is centred on the session so far.** [SteeringCentre] accumulates every segment of the
 * current session in order. If a segment arrives out of sequence -- the process restarted
 * mid-session, or [catchUp] is filling a gap -- the earlier segments are re-read to rebuild it,
 * so a row's centre never depends on whether the app happened to be running for the whole drive.
 * Each row records the centre used and the sample count behind it.
 *
 * Every segment gets a row, including ones with no qualifying samples (n = 0, ratios null): the
 * sample floor is a detector setting and may change (spec section 4).
 *
 * `temps` carries the [WheelRatioExtractor.TEMP_CHANNELS] medians. Like the ratios, they are
 * regenerable from the logs. **The `gps` block is not** -- it comes from [GpsRateAccumulator] via
 * [gpsFor], exists only for segments that closed while the app was running with GPS on, and is null
 * otherwise (including every catch-up row).
 */
class DriveRowProducer(
    private val logDir: File,
    private val sink: (JSONObject) -> Unit,
    private val recordedLogs: () -> Set<String>,
    private val activeSegment: () -> String?,
    /**
     * The segment's GPS block, or null when GPS was not running: the live close's block (taken, so
     * it is used once), else the best one the store's per-minute partial rows saved.
     */
    private val gpsFor: (String) -> JSONObject? = { null },
    /** The active epoch's SET time (epoch ms), or null before the first calibration. See [catchUp]. */
    private val epochSetAtMs: () -> Long? = { null },
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "tpms-rows").apply { isDaemon = true; priority = Thread.MIN_PRIORITY }
    },
    /** Message, and the failure if any. Injectable so JVM tests need no Android logger. */
    private val log: (String, Throwable?) -> Unit = { m, e ->
        if (e == null) TpmsLog.d(TAG, m) else TpmsLog.e(TAG, m, e)
    },
) {

    // Touched only on the executor thread.
    private var sessionKey: String? = null
    private var centre = SteeringCentre()
    private var fast = FastSteeringCentre()
    private var nextIndex = 0
    private val processed = HashSet<String>()

    /** A log segment has closed (from [SegmentWatcher]). Returns immediately. */
    fun onSegmentClosed(file: File) {
        executor.execute { guarded(file.name) { process(file) } }
    }

    /**
     * Produce rows for segments that closed while the process was not running -- including the
     * common case of the head unit powering down before the last segment's row was written.
     *
     * Bounded on purpose: only segments **newer than the newest one already recorded** are
     * considered, so a first install does not backfill months of logs into the precalibration
     * file, and a log that was deliberately never recorded is not resurrected.
     *
     * **When nothing is recorded yet but an epoch exists**, the bound is the epoch's SET time
     * instead: segments last written at or after it. Without this, an epoch whose first segments
     * all ended without a live close (power cut, process killed) never got a row until some later
     * segment happened to close live -- build 23's first day in the car. Last-modified is the
     * segment's close (or last write) time on the same clock as the SET.
     */
    fun catchUp() {
        executor.execute {
            guarded("catch-up") {
                val recorded = recordedLogs()
                processed.addAll(recorded)
                val newest = recorded.mapNotNull { SegmentName.parse(it) }.maxOrNull()
                val since = if (newest == null) epochSetAtMs() ?: return@guarded else null
                val active = activeSegment()
                val todo = (logDir.listFiles { f -> f.isFile && f.name.endsWith(".log") } ?: emptyArray())
                    .mapNotNull { f -> SegmentName.parse(f.name)?.let { it to f } }
                    .filter { (seg, f) -> f.name != active && f.name !in processed &&
                        (if (newest != null) seg > newest else f.lastModified() >= since!!) }
                    .sortedBy { it.first }
                if (todo.isNotEmpty()) {
                    log("catch-up: ${todo.size} segment(s) after " +
                        (newest?.name ?: "SET at ${since}ms"), null)
                }
                todo.forEach { (_, f) -> process(f) }
            }
        }
    }

    private fun process(file: File) {
        if (!processed.add(file.name)) return
        val seg = SegmentName.parse(file.name) ?: return
        val frames = WheelRatioExtractor.readFrames(file)
        if (seg.session != sessionKey || seg.index != nextIndex) rebuildCentre(seg)
        addToCentres(frames)
        nextIndex = seg.index + 1
        val (c, src) = centreSoFar()
        val res = WheelRatioExtractor.extractSegment(frames, c)
        sink(driveRow(file.name, frames.startTs ?: seg.sessionTs, res, centre.n,
            WheelRatioExtractor.temperatures(frames), gpsFor(file.name), frames.voidReasons,
            centreSrc = src, steerNFast = fast.n, reject = frames.busRejection))
        log("${file.name}: n=${res.n}" +
            frames.voidReasons.let { if (it.isEmpty()) "" else " VOID $it" } +
            (frames.busRejection?.let { " REJECTED $it" } ?: ""), null)
    }

    /** Re-read this session's earlier segments so the centre covers the whole session so far. */
    private fun rebuildCentre(seg: SegmentName) {
        sessionKey = seg.session
        centre = SteeringCentre()
        fast = FastSteeringCentre()
        for (i in 0 until seg.index) {
            val f = File(logDir, "${seg.session}_T$i.log")
            if (!f.isFile) continue                     // pruned or never written; use what exists
            addToCentres(WheelRatioExtractor.readFrames(f))
        }
    }

    private fun addToCentres(frames: WheelRatioExtractor.Frames) {
        frames.steer.forEach { centre.add(it.a.toInt()) }
        fast.add(WheelRatioExtractor.fastSteerRaw(frames))
    }

    /**
     * The centre for this session so far, and where it came from: the fast-sample median once there
     * are [WheelRatioExtractor.FAST_CENTRE_MIN] of them, else the all-samples median. The fallback
     * reproduces the old behaviour and is acceptable only because the row is tagged (spec section 1).
     */
    private fun centreSoFar(): Pair<Double?, String?> =
        if (fast.n >= WheelRatioExtractor.FAST_CENTRE_MIN) fast.median() to WheelRatioExtractor.CENTRE_SRC_FAST
        else centre.median()?.let { it to WheelRatioExtractor.CENTRE_SRC_ALL } ?: (null to null)

    private inline fun guarded(what: String, block: () -> Unit) {
        try {
            block()
        } catch (e: Throwable) {
            log("drive row failed ($what)", e)
        }
    }

    /** `coda_20260618_195906_T3.log`, ordered by session then numeric segment index. */
    data class SegmentName(val session: String, val index: Int, val name: String) : Comparable<SegmentName> {
        /** The session start from the name, as `YYYYMMDDTHHMMSS` -- used when a log has no header. */
        val sessionTs: String get() = session.substringAfter('_').replace('_', 'T')

        override fun compareTo(other: SegmentName) =
            compareValuesBy(this, other, { it.session }, { it.index })

        companion object {
            private val RE = Regex("""^([a-z]+_\d{8}_\d{6})_T(\d+)\.log$""")
            fun parse(name: String): SegmentName? =
                RE.matchEntire(name)?.let { SegmentName(it.groupValues[1], it.groupValues[2].toInt(), name) }
        }
    }

    companion object {
        private const val TAG = "TpmsRows"
        private const val WHEEL_HZ = 100.0

        /**
         * Which processing produced a row's numbers -- filters and decode -- as distinct from
         * `schema`, which is the record layout: a new field bumps `schema`, a change that moves DEL
         * bumps `proc`. 1 = build 23 (20 Nm, 1 %, all-samples centre); 2 = v24 (40/20 Nm, 2 %, fast
         * centre); **3 = 20 Nm on every contrast, 2 %, fast centre, D CAN pinned by anchors**
         * ([WheelRatioExtractor.Filters.PROC3], [WheelRatioExtractor.selectDCan]). Proc is a claim
         * about rules, not a build: build 29 tagged rows 3 without the D CAN pinning, and could keep
         * the number only because it was never installed (spec section 4, 2026-09-27). **An untagged
         * row is resolved by structure, not by default** (spec section 4): `ratios.DEL.n` present
         * means 2, else 1.
         *
         * Proc 3 rows share the epoch with proc 1 and 2 rows (algorithm session ruling, 2026-09-26):
         * measured on the live epoch's own drives, the 40 -> 20 Nm change moves DEL by -0.000066,
         * about 0.25-0.5 psi on LF and RF. Diluted if the baseline is still learning; a small fixed
         * bias if it has frozen, removed at the next real inflation's SET. The detector does not
         * read `proc` yet.
         */
        const val PROC = 3

        /**
         * The per-minute checkpoint of a segment still open (spec section 4): the GPS block so far
         * and nothing CAN-derived -- `n` 0, `ratios` null. The open log is deliberately not
         * re-parsed; the CAN half is regenerable from the log, the GPS block is not. The store marks
         * it `partial`, and a completed row for the same log always supersedes it.
         */
        fun partialRow(log: String, ts: String, gps: JSONObject?): JSONObject = JSONObject()
            .put("type", TpmsEpochStore.DRIVE)
            .put("schema", TpmsEpochStore.SCHEMA)
            .put("proc", PROC)
            .put("partial", true)
            .put("ts", ts)
            .put("log", log)
            .put("n", 0)
            .put("ratios", JSONObject.NULL)
            .put("gps", gps ?: JSONObject.NULL)
            .put("void", JSONObject.NULL)

        /**
         * One drive row, in the prototype's `drive_record` shape plus the two steering fields agreed
         * with the algorithm session. Ratios are stored dimensionless (spec invariant 2).
         */
        fun driveRow(
            log: String, ts: String, res: WheelRatioExtractor.Result, steerN: Long,
            temps: Map<String, WheelRatioExtractor.TempStat> = emptyMap(),
            gps: JSONObject? = null,
            void: List<String> = emptyList(),
            centreSrc: String? = null,
            steerNFast: Long = 0,
            reject: WheelRatioExtractor.BusRejection? = null,
        ): JSONObject {
            // Each ratio carries its own n: F/R's is smaller (its stricter torque cap), and a count
            // to be inferred from which cap applies is a count someone will misread.
            val ratios: Any = if (res.n == 0) JSONObject.NULL else JSONObject().apply {
                res.ratios.forEach { (k, r) ->
                    put(k, JSONObject()
                        .put("mean", if (r.n > 0) r.mean else JSONObject.NULL)
                        .put("sd", if (r.n > 0) r.sd else JSONObject.NULL)
                        .put("n", r.n))
                }
            }
            return JSONObject()
                .put("type", TpmsEpochStore.DRIVE)
                .put("schema", TpmsEpochStore.SCHEMA)
                .put("proc", PROC)
                .put("partial", false)
                .put("ts", ts)
                .put("log", log)
                .put("n", res.n)
                .put("dur_s", round1(res.n / WHEEL_HZ))
                .put("kmh_med", res.kmhMedian?.let { round1(it) } ?: JSONObject.NULL)
                .put("steer_centre", res.steerCentre ?: JSONObject.NULL)
                .put("steer_centre_src", centreSrc ?: JSONObject.NULL)
                .put("steer_n", steerN)
                .put("steer_n_fast", steerNFast)
                .put("ratios", ratios)
                .put("torque_abs_mean", res.torqueAbsMean ?: JSONObject.NULL)
                .put("torque_abs_sd", res.torqueAbsSd ?: JSONObject.NULL)
                // Per-band sufficient statistics, so a per-band baseline can be rebuilt from rows
                // alone; the detector stays pooled for now (spec section 4). Empty bands omitted.
                .put("band_kmh", WheelRatioExtractor.RATIO_BAND_KMH)
                .put("ratio_bands", JSONObject().apply {
                    for ((band, byRatio) in res.bands) put(band.toString(), JSONObject().apply {
                        for ((name, b) in byRatio) put(name, JSONObject()
                            .put("n", b.n).put("sum", b.sum).put("sumsq", b.sumSq))
                    })
                })
                .put("temps", JSONObject().apply {
                    temps.forEach { (k, s) ->
                        put(k, JSONObject()
                            .put("median", s.median ?: JSONObject.NULL)
                            .put("valid_frac", s.validFrac?.let { round3(it) } ?: JSONObject.NULL)
                            .put("n", s.n))
                    }
                })
                .put("gps", gps ?: JSONObject.NULL)
                // Null, or why this segment's ESC data is faulty. The ratios are still stored (for
                // analysis); the detector voids the whole session. Regenerable from the log.
                .put("void", if (void.isEmpty()) JSONObject.NULL else JSONArray(void))
                // Null, or why the capture gave no D CAN rows (WheelRatioExtractor.selectDCan).
                // Kept out of `void` deliberately: a void condemns the whole session, and a
                // segment without D CAN says nothing about the ESC's sensors.
                .put("reject", reject?.let { JSONObject().put("code", it.code).put("why", it.why) }
                    ?: JSONObject.NULL)
        }

        private fun round3(x: Double): Double = BigDecimal(x).setScale(3, RoundingMode.HALF_EVEN).toDouble()

        /** Python's `round(x, 1)`: half-to-even on the exact binary value. */
        private fun round1(x: Double): Double = BigDecimal(x).setScale(1, RoundingMode.HALF_EVEN).toDouble()
    }
}
