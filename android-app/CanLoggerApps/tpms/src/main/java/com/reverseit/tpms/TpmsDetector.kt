package com.reverseit.tpms

import org.json.JSONObject
import kotlin.math.ln

/**
 * The indirect-TPMS detector: an epoch file's drive rows in, a [TpmsEstimate] out.
 *
 * A port of `run()` in `projects/coda/notes/artifacts/tpms_app_prototype.py`, which is the
 * executable spec (`projects/coda/notes/tpms-algorithm-spec.md` sections 1-3).
 * `TpmsDetectorParityTest` replays the prototype's corpus file under a grid of settings and
 * requires the same events, states and per-drive numbers.
 *
 * **Stateless by design.** [evaluate] replays the whole active epoch from its first row every time
 * it is called. Nothing it derives -- baseline, verdict, pending confirmation -- is kept between
 * calls or written anywhere (spec section 4, invariant 1), so every setting can be retuned against
 * an unchanged file. An epoch holds a few hundred rows a year, so a replay costs nothing.
 *
 * **One drive is one capture session, not one row.** Rows are per 5-minute log segment. They are
 * pooled by session (the log name before `_T`) before any count applies -- K, M, confirmation,
 * the sample floor. Otherwise a 40-minute drive would be eight "drives" and confirm itself. A
 * session's contrasts are the n-weighted mean of its rows' contrasts, the same weighting the
 * prototype's `pooled()` uses. On the corpus each session is one row, so this is the identity
 * there.
 *
 * **A void drive is skipped entirely** -- not learned from, not in any window, not fast-pathed. A
 * session is void if any of its rows carries a `void` reason (the ESC reported a fault or a wheel
 * word was stuck; owner's rule, spec section 1).
 *
 * **Two paths to WARN.** The slow path pools the last M drives with confirmation, for a gradual
 * leak. The fast path (owner, 2026-09-26: "if I hit a nail ... I want to know on the first drive")
 * takes the current drive alone against the baseline with no confirmation, and is re-evaluated at
 * every segment close, so a puncture can WARN during the drive it happens on. Its threshold is
 * higher because a single drive's error has a heavy tail (measured, `tpms_fastpath_falsealarm.py`).
 *
 * **Order is file order, never `ts`.** Nothing here is time-based (spec section 4): a head unit
 * with its clock behind still gets the same verdicts, only misdated.
 */
class TpmsDetector(private val s: TpmsSettings = TpmsSettings()) {

    /** A capture session, its segment rows pooled. [c] is the three contrasts, 2*ln(ratio). */
    class Drive(
        val session: String, val ts: String, val n: Long, val c: DoubleArray,
        /** Why this drive is void, or empty. */
        val void: List<String> = emptyList(),
        /** Each contrast's own sample count (F/R's is smaller from v24); rows without one use [n]. */
        val nc: LongArray = LongArray(3) { n },
    )

    /** One detector event, as the prototype's `events` list reports it. */
    data class Event(val ts: String, val kind: String, val detail: String)

    /** Per-drive output after the baseline freezes: DEL alone, and the outlier reading. */
    class Point(val ts: String, val delPsi: Double, val dev: Map<Corner, Double>)

    class Result(
        val state: TpmsState,
        val baseline: FrozenBaseline,
        val events: List<Event>,
        val history: List<Point>,
        /** Drives above the floor, and their pooled samples, so far (for the LEARNING line). */
        val usedDrives: Int,
        val learnSamples: Long,
        /** A state change seen but not yet confirmed, and how many drives have agreed. */
        val pending: TpmsState?,
        val pendingCount: Int,
        /** The void reasons of the newest drive in the file, or empty if it counted. */
        val lastVoid: List<String>,
        /** Each contrast's pooled samples in the learning pool (DEL, FR, LR_), for the LEARNING line. */
        val learnContrastN: LongArray = LongArray(3),
    )

    /**
     * Pool [rows] (one epoch's drive rows, file order) into sessions, in order of first appearance.
     * Rows with no ratios (`n` 0) carry nothing and are skipped.
     */
    fun drives(rows: List<JSONObject>): List<Drive> {
        class Acc(val ts: String) {
            var n = 0L; val nc = LongArray(3); val wc = DoubleArray(3); val void = LinkedHashSet<String>()
        }
        val acc = LinkedHashMap<String, Acc>()
        rows.forEachIndexed { i, r ->
            val key = r.optString("log").takeIf { it.isNotEmpty() }
                ?.let { TpmsEpochStore.sessionOf(it) } ?: "#row$i"
            val reasons = voidReasons(r)
            val n = r.optLong("n", 0L)
            val c = contributions(r)
            // A void row voids its session even when it has no ratios of its own.
            if (reasons.isEmpty() && (c == null || n <= 0)) return@forEachIndexed
            val a = acc.getOrPut(key) { Acc(r.optString("ts")) }
            a.void.addAll(reasons)
            if (c == null || n <= 0) return@forEachIndexed
            a.n += n
            // Each contrast is weighted by its own samples: F/R has fewer (its stricter torque cap),
            // and a segment with none contributes nothing to F/R rather than a made-up value.
            for (k in 0 until 3) { val (w, v) = c[k] ?: continue; a.nc[k] += w; a.wc[k] += w * v }
        }
        return acc.map { (k, a) ->
            Drive(k, a.ts, a.n, DoubleArray(3) { if (a.nc[it] > 0) a.wc[it] / a.nc[it] else Double.NaN },
                a.void.toList(), a.nc.copyOf())
        }
    }

    /** Replay [drives] as the app would have reported them, drive by drive. */
    fun run(drives: List<Drive>): Result {
        var level = TpmsState.LEARNING
        var pending: TpmsState? = null
        var pendingCount = 0
        val baseline = FrozenBaseline()
        val learn = ArrayList<Drive>()
        var usedDrives = 0
        val scored = ArrayList<Drive>()            // drives after the freeze: the window's pool
        val events = ArrayList<Event>()
        val history = ArrayList<Point>()

        for (d in drives) {
            if (d.void.isNotEmpty()) continue
            if (d.n < s.minSamples) continue
            usedDrives++

            if (!baseline.isFrozen) {
                learn.add(d)
                val pooledN = learn.sumOf { it.n }
                // Not frozen while a contrast is short of its floor (the prototype would freeze
                // NaN): learning simply continues until the pool has enough F/R.
                val pool = pooled(learn, s.minNContrast)
                if (learn.size >= s.learnDrives && pooledN >= s.learnMinSamples && pool.all { it.isFinite() }) {
                    baseline.freeze(pool, learn.size)
                    level = TpmsState.OK
                    events.add(Event(d.ts, "baseline",
                        "frozen on %d drives, %d samples".format(learn.size, pooledN)))
                }
                continue
            }

            // The window holds post-freeze drives only, never the learning drives: those ARE the
            // baseline, and mixing them in pulls the first M-1 estimates toward zero.
            val base = baseline.value!!
            scored.add(d)
            val cNow = pooled(scored.takeLast(s.windowDrives), s.minNContrast)
            // All three contrasts are needed to form corners. A window clearing the wide floor can
            // still be short of F/R (its stricter torque cap); the drive stays in the window.
            if (cNow.any { !it.isFinite() }) {
                val short = RATIO_KEYS.filterIndexed { k, _ -> !cNow[k].isFinite() }
                events.add(Event(d.ts, "skip", "cleared the sample floor but %s below %d samples -- corners cannot be formed"
                    .format(short.joinToString("/"), s.minNContrast)))
                continue
            }
            val dev = outlierPsi(cNow, base)
            history.add(Point(d.ts, delPsi(cNow, base), dev))

            // An un-announced fill invalidates the baseline: stop naming corners until recalibrated.
            if (level != TpmsState.STALE) {
                val step = detectStep(history)
                if (step != null) {
                    events.add(Event(d.ts, "stale",
                        "pressures rose %+.1f psi with no calibration entered".format(step)))
                    level = TpmsState.STALE
                    pending = null; pendingCount = 0
                    continue
                }
            }
            if (level == TpmsState.STALE) continue

            // Fast path: this drive alone, no window, no confirmation.
            // This drive alone, through the same per-contrast floor as the window (spec section 3):
            // the 6 psi threshold was measured when every drive's F/R had the full sample set, so
            // it says nothing about a drive whose F/R rests on a handful of samples.
            val soloC = pooled(listOf(d), s.minNContrast)
            if (d.n >= s.fastMinSamples && level != TpmsState.WARN && soloC.all { it.isFinite() }) {
                val solo = outlierPsi(soloC, base)
                val low = solo.minByOrNull { it.value }!!
                if (low.value <= -s.fastWarnPsi) {
                    events.add(Event(d.ts, "warn",
                        "%s at %+.1f psi on this drive alone".format(low.key.name, low.value)))
                    level = TpmsState.WARN
                    pending = null; pendingCount = 0
                    continue
                }
            }

            val (want, worst) = classify(dev, level)
            if (want == level) {
                pending = null; pendingCount = 0
            } else {
                pendingCount = if (want == pending) pendingCount + 1 else 1
                pending = want
                if (pendingCount >= s.confirmDrives) {
                    val low = dev.minByOrNull { it.value }!!.key
                    events.add(Event(d.ts, want.name.lowercase(),
                        "%s at %+.1f psi".format(low.name, worst)))
                    level = want
                    pending = null; pendingCount = 0
                }
            }
        }
        return Result(level, baseline, events, history, usedDrives,
            learn.sumOf { it.n }, pending, pendingCount, drives.lastOrNull()?.void ?: emptyList(),
            LongArray(3) { k -> learn.sumOf { if (it.c[k].isFinite()) it.nc[k] else 0L } })
    }

    /** The estimate the settings page shows for [contents] (the active epoch), or before one. */
    fun evaluate(contents: TpmsEpochStore.Contents?, nowMs: Long = System.currentTimeMillis()): TpmsEstimate {
        if (contents == null) {
            return TpmsEstimate(detail = "Not calibrated: inflate all four to 42 psi, then SET")
        }
        val r = run(drives(contents.drives))
        val last = r.history.lastOrNull()
        val corners = if (r.state == TpmsState.STALE || last == null) emptyMap()
        else last.dev.mapValues { TpmsCornerEstimate(deltaPsi = it.value.toFloat()) }
        val detail = when (r.state) {
            // A contrast short of its floor holds learning open indefinitely (town-only driving
            // rarely gives F/R samples under its 20 Nm cap), so say which, rather than stall silently.
            TpmsState.LEARNING -> "%d of %d drives, %d of %d samples".format(
                r.usedDrives, s.learnDrives, r.learnSamples, s.learnMinSamples) +
                RATIO_KEYS.indices.filter { r.usedDrives > 0 && r.learnContrastN[it] < s.minNContrast }
                    .joinToString("") { k ->
                        ", %s %d of %d - needs steady highway".format(
                            LABELS[k], r.learnContrastN[k], s.minNContrast)
                    }
            TpmsState.STALE -> r.events.lastOrNull { it.kind == "stale" }?.let { "${it.ts.take(8)}: ${it.detail}" }
            else -> when {
                last == null -> "Baseline set; waiting for the next qualifying drive"
                r.pending != null -> "%s pending, %d of %d drives".format(
                    r.pending.name, r.pendingCount, s.confirmDrives)
                else -> "Last %d drives, latest %s".format(
                    minOf(s.windowDrives, r.usedDrives), last.ts.take(8))
            }
        }
        // A void last drive must not look like "no qualifying driving".
        val voidNote = r.lastVoid.takeIf { it.isNotEmpty() }?.let { reasons ->
            "Last drive void: " + reasons.joinToString(", ") {
                when (it) {
                    WheelRatioExtractor.VOID_ESC_FAULT -> "ABS/ESC fault"
                    WheelRatioExtractor.VOID_WHEEL_STUCK -> "wheel sensor dead"
                    else -> it
                }
            }
        }
        val line = listOfNotNull(voidNote, detail).joinToString(". ").ifEmpty { null }
        return TpmsEstimate(corners = corners, state = r.state, detail = line, updatedAtMs = nowMs)
    }

    // ------------------------------------------------------------------------ algorithm ----

    private fun classify(dev: Map<Corner, Double>, level: TpmsState): Pair<TpmsState, Double> {
        val worst = dev.values.min()
        val want = when (level) {
            TpmsState.WARN -> when {
                worst <= -s.warnClearPsi -> TpmsState.WARN
                worst <= -s.adviseClearPsi -> TpmsState.ADVISE
                else -> TpmsState.OK
            }
            TpmsState.ADVISE -> when {
                worst <= -s.warnPsi -> TpmsState.WARN
                worst <= -s.adviseClearPsi -> TpmsState.ADVISE
                else -> TpmsState.OK
            }
            else -> when {
                worst <= -s.warnPsi -> TpmsState.WARN
                worst <= -s.advisePsi -> TpmsState.ADVISE
                else -> TpmsState.OK
            }
        }
        return want to worst
    }

    /** Run on DEL, never the worst corner, which can change identity across the very step. */
    private fun detectStep(h: List<Point>): Double? {
        val k = s.stepWindow
        if (h.size < 2 * k) return null
        val before = h.subList(h.size - 2 * k, h.size - k).map { it.delPsi }.average()
        val after = h.subList(h.size - k, h.size).map { it.delPsi }.average()
        return (after - before).takeIf { it >= s.stepPsi }
    }

    companion object {
        /** Single-wheel fractional radius change per psi (spec section 1). */
        const val A_PER_PSI = 2.20e-4

        /**
         * Each corner's sign in (DEL, F/R, L/R). Keyed per corner, and the inversion is derived from
         * it, so no positional matrix can drift against a positional corner order (spec section 6).
         */
        val CONTRAST_SIGNS: Map<Corner, IntArray> = mapOf(
            Corner.LF to intArrayOf(+1, +1, +1),
            Corner.RF to intArrayOf(-1, +1, -1),
            Corner.LR to intArrayOf(-1, -1, +1),
            Corner.RR to intArrayOf(+1, -1, -1),
        )

        private val RATIO_KEYS = listOf("DEL", "FR", "LR_")
        private val LABELS = listOf("DEL", "F/R", "L/R")

        /** A row's `void` reasons: absent or null means the row counts. */
        fun voidReasons(row: JSONObject): List<String> =
            when (val v = row.opt("void")) {
                is org.json.JSONArray -> (0 until v.length()).map { v.optString(it) }.filter { it.isNotEmpty() }
                is String -> listOf(v).filter { it.isNotEmpty() }
                else -> emptyList()
            }

        /**
         * Each contrast's (sample count, value) in one row: null for a contrast with no samples of
         * its own, and null overall when the row has no usable DEL. The count is the ratio's own
         * `n` (v24 rows) or else the row's.
         */
        fun contributions(row: JSONObject): Array<Pair<Long, Double>?>? {
            val r = row.optJSONObject("ratios") ?: return null
            val rowN = row.optLong("n", 0L)
            val out = arrayOfNulls<Pair<Long, Double>>(3)
            for ((i, k) in RATIO_KEYS.withIndex()) {
                val o = r.optJSONObject(k) ?: if (i == 0) return null else continue
                val m = o.optDouble("mean", Double.NaN)
                val w = if (o.has("n")) o.optLong("n", 0L) else rowN
                if (m > 0.0 && w > 0) out[i] = w to 2.0 * ln(m) else if (i == 0) return null
            }
            return out
        }

        /** The three contrasts of one row, or null if it carries no usable ratios. */
        fun contrasts(row: JSONObject): DoubleArray? {
            val r = row.optJSONObject("ratios") ?: return null
            val out = DoubleArray(3)
            for ((i, k) in RATIO_KEYS.withIndex()) {
                val m = r.optJSONObject(k)?.optDouble("mean", Double.NaN) ?: return null
                if (!(m > 0.0)) return null
                out[i] = 2.0 * ln(m)
            }
            return out
        }

        /** Sample-count-weighted mean of the contrasts. */
        /**
         * Per-contrast sample-weighted mean, each contrast over the drives that measured it; NaN
         * for a contrast whose total weight is below [minN] (the prototype's `pooled(recs, min_n)`).
         */
        fun pooled(ds: List<Drive>, minN: Long = 0): DoubleArray = DoubleArray(3) { k ->
            var w = 0L; var sum = 0.0
            for (d in ds) if (d.c[k].isFinite() && d.nc[k] > 0) { w += d.nc[k]; sum += d.nc[k] * d.c[k] }
            if (w >= maxOf(minN, 1L)) sum / w else Double.NaN
        }

        /**
         * Per-corner deviation in psi, the **outlier** reading: the projected contrast estimate x 4/3,
         * i.e. assuming the other three are at baseline. That is what "this tyre is N psi low"
         * means, so it is what thresholds and the display use (spec section 1). A soft tyre turns
         * faster, so the sign flips to make it read negative.
         */
        fun outlierPsi(cNow: DoubleArray, cBase: DoubleArray): Map<Corner, Double> {
            val dev = Corner.entries.associateWith { corner ->
                val sg = CONTRAST_SIGNS.getValue(corner)
                val a = (0 until 3).sumOf { sg[it] * (cNow[it] - cBase[it]) } / 4.0
                -a / A_PER_PSI * 4.0 / 3.0
            }
            // Every contrast's signs sum to zero over the four corners, so the corners must too, for
            // any input, while the common mode is unknown (spec section 1). A non-zero sum means a
            // broken inversion or a flipped sign -- confident, plausible, wrong-tyre output -- so
            // it fails loudly (the store shows it on page 3) rather than rendering.
            val sum = dev.values.sum()
            check(Math.abs(sum) < 1e-6 * (1.0 + dev.values.maxOf { Math.abs(it) })) {
                "corner deviations sum to $sum psi, not 0: inversion or sign convention broken"
            }
            return dev
        }

        /** DEL alone in single-corner psi. Negative is the diagonal moving as a softening LF does. */
        fun delPsi(cNow: DoubleArray, cBase: DoubleArray): Double = -(cNow[0] - cBase[0]) / A_PER_PSI
    }
}

/**
 * Write-once holder for the learned baseline.
 *
 * A baseline that quietly re-learns from recent drives tracks the 0.051 psi/day leak and reports
 * nothing wrong for ever (spec section 2). Stating that in prose did not stop either session from
 * writing code that could break it, so a second [freeze] throws rather than being discouraged.
 */
class FrozenBaseline {
    var value: DoubleArray? = null
        get() = field?.copyOf()
        private set
    var drives: Int = 0
        private set
    val isFrozen: Boolean get() = value != null

    fun freeze(contrasts: DoubleArray, nDrives: Int) {
        check(!isFrozen) {
            "baseline re-learn attempted: a frozen baseline was assigned a second time"
        }
        value = contrasts.copyOf()
        drives = nDrives
    }
}
