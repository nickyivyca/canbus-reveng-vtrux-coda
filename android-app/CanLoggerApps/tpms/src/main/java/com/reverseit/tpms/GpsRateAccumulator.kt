package com.reverseit.tpms

import com.reverseit.cancore.CanFrame
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject

/**
 * The GPS common-mode channel's collection side: pairs each GPS speed fix with the rear-pair wheel
 * speed at the same instant and folds the pair into per-segment, per-speed-band sums
 * (spec section 7; plan `android-app/notes/plans/coda-tpms-gps.md`, Step 1 outcome 3a-e).
 *
 * **Privacy rule (owner, 2026-09-24): no absolute position; otherwise only what GPS-TPMS needs.**
 * A fix reaches this class as the handful of numbers in [Fix] -- speed, its accuracy, altitude and
 * its accuracy, and the fix time. No latitude, no longitude, no `Location`: those never leave
 * [GpsSpeedService]'s callback. Altitude is used only to form a grade over a short baseline, and
 * only `grade^2` summed per band leaves this class. At most the last few fixes are held, for the
 * lag products; nothing like a speed or altitude series is retained.
 *
 * **Pairing is live** because holding GPS samples until the segment closes would be retaining a
 * series. Each fix is held only until wheel samples exist on both sides of it, then paired with
 * the rear-pair average over [PAIR_HALF_WINDOW_NS] either side -- a window comparable to the
 * receiver's own averaging, rather than one instantaneous wheel sample.
 *
 * **Two filter sets, kept in separate [Channel]s that share nothing but the input:**
 *  - `strict` -- the DEL filters (speed, brakes, steering, steering rate, torque, steady speed).
 *    This is the channel.
 *  - `loose` -- no steady-speed and no torque gate. **LOOSE IS FOR MEASURING THE TRADE, NOT FOR
 *    USE.** It is the only data from which the receiver's lag can be measured, because the steady
 *    gate removes the speed variation a lag would displace. Dropping the gate costs -2.5 psi of
 *    one-signed bias at 0.5 s of lag and -11 psi at 2 s (`tpms_gps_resolution.py` phase D).
 *    Scheduled for removal once the lag is measured (owner, 2026-09-24).
 *
 * **Implausible fixes are rejected before anything is summed, and counted.** A sum cannot be
 * cleaned afterwards -- one absurd fix folded into a band is permanent and cannot even be found
 * again -- so a fix whose GPS speed differs from its paired wheel speed by more than
 * [PLAUSIBLE_FRAC] is dropped as a receiver glitch (tunnel re-acquisition and the like). The gate
 * has ~20,000x the headroom of the signal: 50 psi of common mode is a 1.1 % speed difference.
 * It is deliberately **not** a gate on reported speed accuracy, which correlates with driving
 * conditions and would bias the channel. Same line as the temperature sentinels: exclude what is
 * not a measurement, count it, never exclude a measurement judged unrepresentative.
 *
 * **Elevation change, a secondary use (owner, 2026-09-24):** each block also carries an `elev`
 * part -- net altitude change, and total climb and descent -- for correcting efficiency estimates
 * for gravitational energy (`projects/coda/notes/efficiency-calculation.md` currently cancels
 * elevation only by pairing out-and-back trips). **Only changes are stored, never an altitude.**
 * The net change chains across the segments of a session (each increment is taken from the
 * previous fix, even across a segment boundary), so per-segment values sum exactly to the trip's
 * net change, and noise enters it only at the trip's two endpoints (~sqrt(2) x the per-fix
 * vertical noise).
 *
 * **Climb and descent run a [ELEV_DEADBAND_M] hysteresis on altitude averaged over
 * [ELEV_SMOOTH_NS] first -- never on raw fixes.** Raw GPS altitude noise of ~3 m per fix against a
 * 5 m deadband is a random walk: simulated on perfectly flat ground over 30 minutes it accumulates
 * ~2,200 m of false climb, and with 10 s smoothing ~0.1 m (algorithm session, 2026-09-24). 10 s at
 * 25 m/s is 250 m of road, far shorter than any real hill, so terrain survives it.
 *
 * **Only while the car is moving** ([ELEV_MIN_KMH] on the wheels, a wheel sample within
 * [ELEV_WHEEL_FRESH_NS] of the fix). Parked, the altitude *solution* wanders one way as satellite
 * geometry changes, which no deadband removes: build 23's first drive logged 10 m of climb and none
 * of descent over five parked minutes, the same size as the drive's real climb. Such fixes are
 * counted in `parked` and change nothing, and the smoothing window restarts when motion resumes.
 * The net change still telescopes across the stop, and the car did not move meanwhile.
 *
 * Two known limits, not bugs:
 * - Skipping fixes with poor vertical accuracy cannot bias the net change (it telescopes), but it
 *   does bias climb and descent **down**: a skipped stretch's up-and-down collapses into one step
 *   between good fixes (tunnels, urban canyons).
 * - Altitude is height above the WGS84 ellipsoid, not sea level. Only differences are used, but
 *   the geoid-ellipsoid separation has a gradient of order 0.1 m/km, so a 50 km leg can carry a
 *   few metres of systematic error -- the same order as the endpoint noise; not corrected.
 *
 * x is the rear-pair average in **raw counts** (above `0xC000`), y is GPS speed in **m/s**. Neither
 * is converted, so no assumed wheel scale is baked into the sums; bands are chosen on x converted
 * to km/h, because banding on the noisy y would bias the slope.
 *
 * Thread-safe: CAN frames arrive from the pipeline collector, fixes from the location looper,
 * segment closes from the logging service, and blocks are taken by the drive-row thread.
 */
class GpsRateAccumulator(
    /** The log segment currently being written, or null when not logging. */
    private val currentSegment: () -> String?,
) {

    /**
     * One fix, already stripped to what the channel needs. [tNanos] is the fix time in the
     * `System.nanoTime()` domain (the same as [CanFrame.elapsedNanos]).
     */
    class Fix(
        val tNanos: Long,
        val speedMps: Float?,
        val speedAccMps: Float?,
        val altitudeM: Double?,
        val verticalAccM: Float?,
    )

    /** What page 3 shows during GPS bringup. */
    data class Status(
        val state: State = State.OFF,
        val fixesLastMinute: Int = 0,
        val speedAccMps: Float? = null,
        val satellitesUsed: Int? = null,
        /** GPS speed / wheel speed in [REF_BAND_KMH], strict, over this session; see [refBandRho]. */
        val refBandRho: Double? = null,
        val refBandN: Int = 0,
    )

    enum class State { NO_PERMISSION, NO_RECEIVER, PROVIDER_OFF, OFF, SEARCHING, FIXING }

    private val _status = MutableStateFlow(Status())
    val status: StateFlow<Status> = _status.asStateFlow()

    // ------------------------------------------------------------------ live wheel state ----

    private class Sample(val t: Long, val rear: Double, val strict: Boolean, val loose: Boolean)

    private val samples = ArrayDeque<Sample>()          // last SAMPLE_KEEP_NS
    private val steadyWin = ArrayDeque<Pair<Long, Double>>()   // mean-of-four, last 1 s
    private val steerHist = ArrayDeque<Pair<Long, Double>>()   // degrees, last 0.3 s
    private val anchorIds = HashMap<Int, HashSet<Int>>()        // bus -> D CAN anchor ids, this segment
    private var dBus: Int? = null                               // see onAnchor
    private var lr = Double.NaN; private var rr = Double.NaN
    private var brake = Double.NaN; private var steerRaw = Double.NaN; private var torque = Double.NaN
    private var centre = SteeringCentre()
    private var fastCentre = SteeringCentre()          // raw counts on the wheel grid above 60 km/h
    private var sessionKey: String? = null
    private var lastAlt: Double? = null        // session-scoped: net change chains across segments
    private var refAlt: Double? = null         // hysteresis reference for climb/descent
    private val altWin = ArrayDeque<Pair<Long, Double>>()   // last ELEV_SMOOTH_NS, session-scoped
    private var lastWheelT = Long.MIN_VALUE; private var lastWheelKmh = Double.NaN

    // ---------------------------------------------------------------------- collection ----

    private inner class Pending(val fix: Fix, val bucket: Bucket)
    private val pending = ArrayDeque<Pending>()

    private var active = false
    private var current: Bucket? = null
    private val done = LinkedHashMap<String, Bucket>()
    private val fixTimes = ArrayDeque<Long>()           // for fixes-per-minute only
    private var refSumX = 0.0; private var refSumY = 0.0; private var refN = 0

    /** The GPS service is running (permission granted, updates requested). */
    fun setActive(on: Boolean) = synchronized(this) {
        active = on
        if (!on) _status.value = _status.value.copy(state = State.OFF)
    }

    fun setState(state: State) = synchronized(this) { _status.value = _status.value.copy(state = state) }

    fun setSatellites(used: Int) = synchronized(this) { _status.value = _status.value.copy(satellitesUsed = used) }

    /** Feed every pipeline frame; only the four wheel-channel IDs and the D CAN anchors are used. */
    fun observe(frame: CanFrame) {
        val id = frame.id
        if (WheelRatioExtractor.isAnchor(id)) {
            if (!frame.isTx) synchronized(this) { onAnchor(id, frame.busIndex) }
            return
        }
        if (id != WheelRatioExtractor.ID_FRONT && id != WheelRatioExtractor.ID_REAR &&
            id != WheelRatioExtractor.ID_STEER && id != WheelRatioExtractor.ID_MCM) return
        if (frame.dlc < 8 || frame.isTx) return
        synchronized(this) {
            if (frame.busIndex != dBus) return
            val d = IntArray(8) { frame.data[it].toInt() and 0xFF }
            when (id) {
                WheelRatioExtractor.ID_REAR -> if (WheelRatioExtractor.stuckWheel(d)) {
                    lr = Double.NaN; rr = Double.NaN       // dead channel: no rear speed until it recovers
                } else {
                    lr = WheelRatioExtractor.wheel(d, 6).toDouble()
                    rr = WheelRatioExtractor.wheel(d, 4).toDouble()
                    brake = WheelRatioExtractor.brake(d)
                }
                WheelRatioExtractor.ID_STEER -> {
                    val raw = (d[2] shl 8) or d[3]
                    steerRaw = raw.toDouble()
                    centre.add(raw)
                }
                WheelRatioExtractor.ID_MCM -> torque = (d[0] or (d[1] shl 8)) * 0.1 - 3212.8
                WheelRatioExtractor.ID_FRONT -> if (d[0] == 0 && !WheelRatioExtractor.stuckWheel(d)) {
                    val lf = WheelRatioExtractor.wheel(d, 6).toDouble()
                    val rf = WheelRatioExtractor.wheel(d, 4).toDouble()
                    addSample(frame.elapsedNanos, lf, rf)
                }
            }
        }
    }

    /** A fix from the location callback. */
    fun onFix(fix: Fix) = synchronized(this) {
        fixTimes.addLast(fix.tNanos)
        while (fixTimes.isNotEmpty() && fix.tNanos - fixTimes.first() > 60_000_000_000L) fixTimes.removeFirst()
        _status.value = _status.value.copy(
            state = State.FIXING, fixesLastMinute = fixTimes.size, speedAccMps = fix.speedAccMps)

        val bucket = bucketForNow() ?: return@synchronized     // not logging: nothing to attribute to
        bucket.fixes++
        trackElevation(bucket.elev, fix)
        if (fix.speedAccMps != null) {
            bucket.sumSpeedAcc += fix.speedAccMps
            bucket.sumSpeedAccSq += fix.speedAccMps.toDouble() * fix.speedAccMps
            bucket.nSpeedAcc++
        }
        if (fix.speedMps == null) { bucket.noSpeed++; return@synchronized }
        pending.addLast(Pending(fix, bucket))
        while (pending.size > MAX_PENDING) { pending.removeFirst().bucket.unpaired++ }
        drainPending()
    }

    /**
     * The logging service closed [name]. Called by [SegmentWatcher] before the drive-row producer
     * is handed the file, so the block is ready when the row is built. When GPS is running but produced
     * nothing for this segment, the block still exists (with `fixes: 0`), which distinguishes
     * "no fix" from "GPS off" (a null block).
     */
    fun closeSegment(name: String) = synchronized(this) {
        resetBus()
        val cur = current
        if (cur != null && cur.name == name) {
            park(cur)
            current = null
        } else if (active && name !in done) {
            park(Bucket(name))
        }
    }

    /** The GPS block for a closed segment, or null if GPS was not running. Removes it. */
    fun take(name: String): JSONObject? = synchronized(this) { done.remove(name)?.toJson() }

    /**
     * The block for the segment being written right now, as it stands, with `source: "snapshot"`;
     * null when nothing is open. Written every minute as the segment's `partial` row in the TPMS
     * store ([TpmsEpochStore.checkpoint]) so a segment that ends in a kill or a power cut -- the last
     * one of most drives, since the head unit loses power at key-off -- still gets its GPS block
     * from catch-up, missing at most the time since the last checkpoint.
     */
    fun snapshot(): Pair<String, JSONObject>? = synchronized(this) {
        val cur = current ?: return null
        if (cur.name != currentSegment()) return null
        cur.name to cur.toJson().put("source", SOURCE_SNAPSHOT)
    }

    // ------------------------------------------------------------------------ internals ----

    /**
     * D CAN, identified live by [WheelRatioExtractor.selectDCan]'s anchor rule, per segment as the
     * extractor does per file. It replaces `onDominantBus`, which asked per frame whether the frame's
     * bus was *currently* ahead on count: with two near-equal rebroadcast copies the lead changed
     * hands thousands of times a segment and it read an interleaved mixture of both (spec section 1).
     * The anchors stream at 100 Hz, so identification takes a few tens of ms at each segment start.
     *
     * A rival channel reaching [WheelRatioExtractor.MIN_ANCHORS] makes it ambiguous and stops
     * collection until the next segment -- refusing, not choosing. The extractor's third test (all
     * four signal ids on the winner) cannot be decided live; a missing id simply yields no samples.
     */
    private fun onAnchor(id: Int, bus: Int) {
        if (anchorIds.getOrPut(bus) { HashSet() }.add(id)) dBus = WheelRatioExtractor.selectDCan(anchorIds, null).first
    }

    /** The channel read as D CAN this segment, or null while undecided or ambiguous. */
    val dCanBus: Int? get() = synchronized(this) { dBus }

    /** New segment: bus identity is re-established from its own anchors, as for its row. */
    private fun resetBus() {
        anchorIds.clear()
        dBus = null
    }

    private fun bucketForNow(): Bucket? {
        val name = currentSegment() ?: return null
        val session = DriveRowProducer.SegmentName.parse(name)?.session ?: name
        if (session != sessionKey) {
            // New session: the steering centre is "session so far", and the reference-band
            // display restarts with it.
            sessionKey = session
            centre = SteeringCentre()
            fastCentre = SteeringCentre()
            lastAlt = null; refAlt = null; altWin.clear()
            refSumX = 0.0; refSumY = 0.0; refN = 0
        }
        val cur = current
        if (cur != null && cur.name == name) return cur
        cur?.let { park(it) }                           // segment changed without a close
        return Bucket(name).also { current = it }
    }

    private fun trackElevation(e: Elevation, fix: Fix) {
        val alt = fix.altitudeM ?: return
        val moving = lastWheelT != Long.MIN_VALUE &&
            Math.abs(fix.tNanos - lastWheelT) <= ELEV_WHEEL_FRESH_NS && lastWheelKmh >= ELEV_MIN_KMH
        if (!moving) { e.parked++; altWin.clear(); return }
        val vAcc = fix.verticalAccM
        if (vAcc != null && vAcc > ELEV_MAX_VACC_M) { e.lowAcc++; return }
        e.n++
        if (vAcc != null) { e.sumVacc += vAcc; e.nVacc++ }
        lastAlt?.let { e.dh += alt - it }
        lastAlt = alt

        altWin.addLast(fix.tNanos to alt)
        while (fix.tNanos - altWin.first().first > ELEV_SMOOTH_NS) altWin.removeFirst()
        // Only once the window is nearly full: a short window is not smoothed enough.
        if (fix.tNanos - altWin.first().first < ELEV_SMOOTH_NS * 8 / 10) return
        val smooth = altWin.sumOf { it.second } / altWin.size
        val ref = refAlt
        when {
            ref == null -> refAlt = smooth
            smooth - ref >= ELEV_DEADBAND_M -> { e.climb += smooth - ref; refAlt = smooth }
            ref - smooth >= ELEV_DEADBAND_M -> { e.descent += ref - smooth; refAlt = smooth }
        }
    }

    private fun park(b: Bucket) {
        done[b.name] = b
        while (done.size > MAX_DONE) done.remove(done.keys.first())
    }

    private fun addSample(t: Long, lf: Double, rf: Double) {
        if (lr.isNaN()) return
        val mean = (lf + rf + lr + rr) / 4.0
        val kmh = mean / WheelRatioExtractor.COUNTS_PER_KMH
        lastWheelT = t; lastWheelKmh = kmh
        if (steerRaw.isNaN()) return

        // As the drive rows: the fast-sample centre once there are enough, else all samples.
        if (kmh > WheelRatioExtractor.FAST_CENTRE_KMH) fastCentre.add(steerRaw.toInt())
        val c = (if (fastCentre.n >= WheelRatioExtractor.FAST_CENTRE_MIN) fastCentre.median() else centre.median())
            ?: return
        val deg = (steerRaw - c) * WheelRatioExtractor.STEER_DEG_PER_COUNT
        steerHist.addLast(t to deg)
        while (steerHist.size > 1 && t - steerHist.first().first > STEER_RATE_BASE_NS) steerHist.removeFirst()
        val (t0, deg0) = steerHist.first()
        val rate = if (t > t0) Math.abs(deg - deg0) / ((t - t0) / 1e9) else 0.0

        steadyWin.addLast(t to mean)
        while (t - steadyWin.first().first > STEADY_WIN_NS) steadyWin.removeFirst()
        val full = t - steadyWin.first().first >= STEADY_WIN_NS * 95 / 100
        var hi = Double.NEGATIVE_INFINITY; var lo = Double.POSITIVE_INFINITY
        for ((_, v) in steadyWin) { if (v > hi) hi = v; if (v < lo) lo = v }
        val steady = full && lo > 0 && (hi - lo) / maxOf(lo, 1.0) < WheelRatioExtractor.STEADY_TOL

        val base = kmh > WheelRatioExtractor.MIN_KMH &&
            !brake.isNaN() && brake <= 0.0 &&
            Math.abs(deg) < WheelRatioExtractor.MAX_STEER_DEG &&
            rate < WheelRatioExtractor.MAX_STEER_RATE
        // 40 Nm, not the verdict's 20, deliberately (algorithm session ruling, 2026-09-26): the block
        // pairs GPS against the undriven REAR pair, so front-wheel creep does not enter it; it is
        // collect-only; and strict vs loose exists to measure the filter trade, which a narrower
        // strict channel would degrade. If the rear pair does turn out torque-correlated, 40 Nm
        // data can still show it.
        val torqueOk = torque.isNaN() || Math.abs(torque) < WheelRatioExtractor.MAX_TORQUE_NM
        samples.addLast(Sample(t, (lr + rr) / 2.0, base && torqueOk && steady, base))
        while (t - samples.first().t > SAMPLE_KEEP_NS) samples.removeFirst()
        drainPending()
    }

    /** Pair every held fix whose window is now covered by wheel samples. */
    private fun drainPending() {
        val newest = samples.lastOrNull()?.t ?: return
        while (pending.isNotEmpty()) {
            val p = pending.first()
            val tf = p.fix.tNanos
            // Not covered yet. A fix the wheel stream never reaches (the stream stopped) is pushed
            // out by MAX_PENDING and counted as unpaired.
            if (newest < tf + PAIR_HALF_WINDOW_NS) return
            pending.removeFirst()
            val w = samples.filter { it.t >= tf - PAIR_HALF_WINDOW_NS && it.t <= tf + PAIR_HALF_WINDOW_NS }
            if (w.isEmpty()) { p.bucket.unpaired++; continue }
            val x = w.sumOf { it.rear } / w.size
            val y = p.fix.speedMps!!.toDouble()
            val xKmh = x / WheelRatioExtractor.COUNTS_PER_KMH
            if (xKmh > WheelRatioExtractor.MIN_KMH && Math.abs(y / (xKmh / 3.6) - 1.0) > PLAUSIBLE_FRAC) {
                p.bucket.implausible++
                p.bucket.strict.add(tf, x, y, false, null, null)   // breaks the lag chains
                p.bucket.loose.add(tf, x, y, false, null, null)
                continue
            }
            val grade = p.bucket.grade.update(tf, y, p.fix.altitudeM, p.fix.verticalAccM)
            val strict = w.all { it.strict }
            val loose = w.all { it.loose }
            val acc = p.fix.speedAccMps?.toDouble()
            p.bucket.strict.add(tf, x, y, strict, grade, acc)
            p.bucket.loose.add(tf, x, y, loose, grade, acc)
            if (strict) addToRefBand(x, y)
        }
    }

    private fun addToRefBand(x: Double, y: Double) {
        val kmh = x / WheelRatioExtractor.COUNTS_PER_KMH
        if (kmh < REF_BAND_KMH.first || kmh >= REF_BAND_KMH.last) return
        refSumX += x; refSumY += y; refN++
        _status.value = _status.value.copy(refBandRho = refBandRho(refSumX, refSumY), refBandN = refN)
    }

    // ---------------------------------------------------------------- per-segment state ----

    /** Grade over a ~10 s baseline, from altitude change over distance travelled (GPS speed x dt). */
    private class Grade {
        private class Point(val t: Long, val alt: Double, val vAcc: Float?, val dist: Double)
        private val hist = ArrayDeque<Point>()
        private var dist = 0.0
        private var lastT = Long.MIN_VALUE

        /** Returns (g^2, its altitude-noise term) or null when no baseline is available. */
        fun update(t: Long, speed: Double, alt: Double?, vAcc: Float?): Pair<Double, Double>? {
            if (lastT != Long.MIN_VALUE && t > lastT) dist += speed * ((t - lastT) / 1e9)
            lastT = t
            if (alt == null) return null
            hist.addLast(Point(t, alt, vAcc, dist))
            while (hist.size > 1 && t - hist.first().t > GRADE_BASE_MAX_NS) hist.removeFirst()
            val a = hist.first()
            if (t - a.t < GRADE_BASE_MIN_NS) return null
            val d = dist - a.dist
            if (d < GRADE_MIN_DIST_M) return null
            val g = (alt - a.alt) / d
            // Altitude noise inflates E[g^2] by (s1^2 + s2^2) / d^2; carried so it can be
            // subtracted at ingest instead of silently over-correcting.
            val noise = if (vAcc != null && a.vAcc != null) (vAcc * vAcc + a.vAcc * a.vAcc) / (d * d) else Double.NaN
            return g * g to noise
        }
    }

    /** One filter set's sums. `strict` and `loose` are separate instances and share no state. */
    private class Channel {
        class Band {
            var n = 0L; var sx = 0.0; var sy = 0.0; var sxy = 0.0; var sxx = 0.0; var syy = 0.0
            var ng = 0L; var sg2 = 0.0; var ngNoise = 0L; var sg2Noise = 0.0
            var nAcc = 0L; var sAcc = 0.0
        }
        val bands = java.util.TreeMap<Int, Band>()
        var gpsS = 0.0
        private class Kept(val t: Long, val x: Double, val y: Double)
        private val recent = ArrayDeque<Kept>()        // last LAGS kept fixes, consecutive only
        val lagN = LongArray(LAGS + 1)
        val lagYY = DoubleArray(LAGS + 1); val lagXX = DoubleArray(LAGS + 1)
        val lagYX = DoubleArray(LAGS + 1); val lagXY = DoubleArray(LAGS + 1)

        fun add(t: Long, x: Double, y: Double, kept: Boolean, grade: Pair<Double, Double>?, speedAcc: Double?) {
            if (!kept) { recent.clear(); return }
            val prev = recent.lastOrNull()
            if (prev != null && t - prev.t > MAX_FIX_GAP_NS) recent.clear()
            gpsS += if (prev != null && t - prev.t <= MAX_FIX_GAP_NS) (t - prev.t) / 1e9 else 1.0

            val key = ((x / WheelRatioExtractor.COUNTS_PER_KMH) / BAND_KMH).toInt() * BAND_KMH
            val b = bands.getOrPut(key) { Band() }
            b.n++; b.sx += x; b.sy += y; b.sxy += x * y; b.sxx += x * x; b.syy += y * y
            if (speedAcc != null) { b.nAcc++; b.sAcc += speedAcc }
            if (grade != null) {
                b.ng++; b.sg2 += grade.first
                if (!grade.second.isNaN()) { b.ngNoise++; b.sg2Noise += grade.second }
            }

            // Lag products: this fix against the l-th previous consecutive kept fix. Both cross
            // terms, because cross-covariance is not symmetric in lag.
            recent.addLast(Kept(t, x, y))
            while (recent.size > LAGS + 1) recent.removeFirst()
            for (l in 0..LAGS) {
                if (recent.size <= l) break
                val o = recent[recent.size - 1 - l]
                lagN[l]++
                lagYY[l] += y * o.y; lagXX[l] += x * o.x
                lagYX[l] += y * o.x; lagXY[l] += x * o.y
            }
        }

        fun toJson(): JSONObject = JSONObject()
            .put("gps_s", round3(gpsS))
            .put("bands", JSONObject().apply {
                for ((k, b) in bands) put(k.toString(), JSONObject()
                    .put("N", b.n).put("sum_x", b.sx).put("sum_y", b.sy).put("sum_xy", b.sxy)
                    .put("sum_xx", b.sxx).put("sum_yy", b.syy)
                    .put("n_g", b.ng).put("sum_g2", b.sg2)
                    .put("n_g_noise", b.ngNoise).put("sum_g2_noise", b.sg2Noise)
                    .put("n_speed_acc", b.nAcc).put("sum_speed_acc", b.sAcc))
            })
            .put("lags", JSONObject()
                .put("N", JSONArray(lagN.toList())).put("yy", JSONArray(lagYY.toList()))
                .put("xx", JSONArray(lagXX.toList())).put("yx", JSONArray(lagYX.toList()))
                .put("xy", JSONArray(lagXY.toList())))
    }

    /** Per-segment elevation change. Changes only -- no altitude is ever stored. */
    private class Elevation {
        var dh = 0.0; var climb = 0.0; var descent = 0.0
        var n = 0L; var lowAcc = 0L; var parked = 0L; var sumVacc = 0.0; var nVacc = 0L

        fun toJson(): JSONObject = JSONObject()
            .put("dh_m", round3(dh)).put("climb_m", round3(climb)).put("descent_m", round3(descent))
            .put("deadband_m", ELEV_DEADBAND_M)
            .put("n", n).put("low_acc", lowAcc).put("parked", parked)
            .put("sum_vacc", sumVacc).put("n_vacc", nVacc)
    }

    private class Bucket(val name: String) {
        var fixes = 0L; var noSpeed = 0L; var unpaired = 0L; var implausible = 0L
        var sumSpeedAcc = 0.0; var sumSpeedAccSq = 0.0; var nSpeedAcc = 0L
        val strict = Channel()
        val loose = Channel()
        val grade = Grade()
        val elev = Elevation()

        // Schema 2 from v24: `strict` uses the v24 filters (40 Nm, 2%), so its sums are not
        // poolable with schema 1's (spec section 7). It deliberately stayed at 40 Nm when the verdict
        // cap went to 20 (proc 3): see the torque gate in addSample.
        fun toJson(): JSONObject = JSONObject()
            .put("schema", 2)
            .put("source", SOURCE_CLOSE)
            .put("x", "rear_counts")
            .put("y", "gps_mps")
            .put("band_kmh", BAND_KMH)
            .put("fixes", fixes).put("no_speed", noSpeed).put("unpaired", unpaired)
            .put("implausible", implausible)
            .put("sum_speed_acc", sumSpeedAcc).put("sum_speed_acc_sq", sumSpeedAccSq)
            .put("n_speed_acc", nSpeedAcc)
            .put("strict", strict.toJson())
            .put("loose", loose.toJson())
            .put("elev", elev.toJson())
    }

    companion object {
        const val BAND_KMH = 10

        /**
         * Furthest a fix's own timestamp may sit from its arrival before it is distrusted. A real
         * receiver delivers within a second or two; this is far outside that and far inside the
         * failure it guards against.
         */
        const val MAX_FIX_CLOCK_SKEW_NS = 10_000_000_000L

        /**
         * A fix's time in the `System.nanoTime()` domain that CAN frames are stamped in.
         *
         * [fixElapsedNs] is `Location.elapsedRealtimeNanos`, which counts deep sleep where nanoTime
         * does not; the offset between the two clocks is taken fresh at arrival ([elapsedNowNs],
         * [nanoNowNs]), so nothing accumulates across a sleep.
         *
         * **A fix time more than [MAX_FIX_CLOCK_SKEW_NS] from its arrival is replaced by the arrival
         * time**, and the second value says so. Found 2026-09-26 in the emulator harness: the AVD's
         * GNSS stamps injected fixes with time since 1970 instead of since boot (20,723 days against
         * 28 minutes of uptime), so every fix sat decades in the future, never lined up with a wheel
         * sample and was counted unpaired -- silently. The car's receiver does not do this (its rows
         * pair 297-300 of 300 fixes), but nothing guarantees it keeps not doing it.
         */
        fun fixTimeNanos(fixElapsedNs: Long, elapsedNowNs: Long, nanoNowNs: Long): Pair<Long, Boolean> {
            val bad = Math.abs(elapsedNowNs - fixElapsedNs) > MAX_FIX_CLOCK_SKEW_NS
            val t = if (bad) elapsedNowNs else fixElapsedNs
            return (t - (elapsedNowNs - nanoNowNs)) to bad
        }

        /** `source` of a block: complete at a live segment close, or a periodic snapshot. */
        const val SOURCE_CLOSE = "close"
        const val SOURCE_SNAPSHOT = "snapshot"

        /** Climb/descent hysteresis, applied to smoothed altitude. Net change uses no deadband. */
        const val ELEV_DEADBAND_M = 5.0

        /** Altitude averaging window ahead of the climb/descent hysteresis. */
        const val ELEV_SMOOTH_NS = 10_000_000_000L

        /**
         * Fixes reporting worse vertical accuracy are skipped for elevation (counted in `low_acc`).
         * This cannot bias the net change: it telescopes, so a skipped fix's change is picked up
         * by the next one.
         */
        const val ELEV_MAX_VACC_M = 20.0f

        /** Elevation counts only above this wheel speed, so a parked car's GPS wander is not climb. */
        const val ELEV_MIN_KMH = 5.0
        private const val ELEV_WHEEL_FRESH_NS = 2_000_000_000L

        /** A fix whose GPS speed is off its paired wheel speed by more than this is a glitch. */
        const val PLAUSIBLE_FRAC = 0.20
        const val LAGS = 3

        /** The band page 3 shows GPS/wheel for during bringup (owner-proposed 70-80, easy to change). */
        val REF_BAND_KMH = 70..80

        private const val PAIR_HALF_WINDOW_NS = 500_000_000L
        private const val SAMPLE_KEEP_NS = 5_000_000_000L
        private const val STEADY_WIN_NS = 1_000_000_000L
        private const val STEER_RATE_BASE_NS = 100_000_000L
        private const val MAX_FIX_GAP_NS = 1_500_000_000L
        private const val MAX_PENDING = 8
        private const val MAX_DONE = 16
        private const val GRADE_BASE_MIN_NS = 8_000_000_000L
        private const val GRADE_BASE_MAX_NS = 12_000_000_000L
        private const val GRADE_MIN_DIST_M = 50.0

        /**
         * GPS speed over wheel speed as a dimensionless ratio, for display only: wheel counts are
         * converted with the assumed [WheelRatioExtractor.COUNTS_PER_KMH], which is exactly the
         * scale the channel exists to check, so this reads ~1 when the assumed scale is right.
         */
        fun refBandRho(sumX: Double, sumY: Double): Double =
            sumY / (sumX / WheelRatioExtractor.COUNTS_PER_KMH / 3.6)

        private fun round3(x: Double) = Math.round(x * 1000.0) / 1000.0
    }
}
