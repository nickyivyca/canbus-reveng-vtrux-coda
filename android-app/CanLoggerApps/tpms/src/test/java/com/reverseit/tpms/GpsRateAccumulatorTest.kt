package com.reverseit.tpms

import com.reverseit.cancore.CanFrame
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GpsRateAccumulatorTest {

    private var segment: String? = "coda_20260924_100000_T0.log"
    private val acc = GpsRateAccumulator { segment }

    private val sec = 1_000_000_000L
    private var t = 10 * sec          // CAN/fix clock, nanoTime domain

    private fun frame(id: Int, vararg b: Int) = frameOn(dBus, id, *b)

    private fun frameOn(bus: Int, id: Int, vararg b: Int) = CanFrame(
        busIndex = bus, timestampMs = t / 1_000_000, id = id, isExtended = false, dlc = 8,
        data = ByteArray(8) { b.getOrElse(it) { 0 }.toByte() }, elapsedNanos = t)

    /** The channel D CAN is on, and the anchor ids [drive] sends there. */
    private var dBus = 0
    private var anchors = listOf(0x308, 0x312)

    private fun hi(v: Int) = (v shr 8) and 0xFF
    private fun lo(v: Int) = v and 0xFF

    /** Drive [seconds] at [kmh] with a fix every second at GPS speed [gpsScale] x truth. */
    private fun drive(
        seconds: Int, kmh: (Double) -> Double, gpsScale: Double = 1.0, torqueNm: Double = 0.0,
        altitude: (Double) -> Double? = { null }, speed: Boolean = true,
        /** Non-null: the gateway's copy on the other channel, rear pair at this x the truth. */
        gatewayRearScale: Double? = null,
    ) {
        val start = t
        for (k in 0 until seconds * 100) {
            val s = (t - start) / 1e9
            val counts = Math.round(kmh(s) * WheelRatioExtractor.COUNTS_PER_KMH).toInt()
            val w = 0xC000 + counts
            val tq = Math.round((torqueNm + 3212.8) / 0.1).toInt()
            anchors.forEach { acc.observe(frame(it)) }
            gatewayRearScale?.let { g ->
                val gw = 0xC000 + Math.round(counts * g).toInt()
                acc.observe(frameOn(1 - dBus, 0x208, 0, 0, 0x10, 0x00, hi(gw), lo(gw), hi(gw), lo(gw)))
                acc.observe(frameOn(1 - dBus, 0x080, 0, 0, hi(20000), lo(20000)))
                acc.observe(frameOn(1 - dBus, 0x1C0, lo(tq), hi(tq)))
                acc.observe(frameOn(1 - dBus, 0x200, 0, 0, 0, 0, hi(w), lo(w), hi(w), lo(w)))
            }
            acc.observe(frame(0x208, 0, 0, 0x10, 0x00, hi(w), lo(w), hi(w), lo(w)))
            acc.observe(frame(0x080, 0, 0, hi(20000), lo(20000)))
            acc.observe(frame(0x1C0, lo(tq), hi(tq)))
            acc.observe(frame(0x200, 0, 0, 0, 0, hi(w), lo(w), hi(w), lo(w)))
            if (k % 100 == 50) {
                acc.onFix(GpsRateAccumulator.Fix(
                    tNanos = t,
                    speedMps = if (speed) (counts / WheelRatioExtractor.COUNTS_PER_KMH / 3.6 * gpsScale).toFloat() else null,
                    speedAccMps = 0.3f, altitudeM = altitude(s), verticalAccM = 2f))
            }
            t += 10_000_000L
        }
    }

    private fun close(): JSONObject? {
        val name = segment!!
        acc.closeSegment(name)
        return acc.take(name)
    }

    @Test
    fun `steady straight driving pairs every covered fix into the strict band`() {
        acc.setActive(true)
        drive(30, { 80.0 })
        val b = close()!!
        val band = b.getJSONObject("strict").getJSONObject("bands").getJSONObject("80")
        val n = band.getLong("N")
        assertTrue("N=$n", n in 25..30)
        val counts = Math.round(80.0 * WheelRatioExtractor.COUNTS_PER_KMH).toDouble()
        assertEquals(counts, band.getDouble("sum_x") / n, 1e-9)
        assertEquals(counts / WheelRatioExtractor.COUNTS_PER_KMH / 3.6, band.getDouble("sum_y") / n, 1e-5)
        assertEquals(30, b.getLong("fixes"))
        assertEquals("rear_counts", b.getString("x"))
        assertEquals("gps_mps", b.getString("y"))
    }

    // --- bus identity: D CAN by anchors, live (spec section 1) --------------------------------

    private fun strictMeanX(b: JSONObject): Double? {
        val bands = b.getJSONObject("strict").getJSONObject("bands")
        if (bands.length() == 0) return null
        val band = bands.getJSONObject("80")
        return band.getDouble("sum_x") / band.getLong("N")
    }

    private val counts80 = Math.round(80.0 * WheelRatioExtractor.COUNTS_PER_KMH).toDouble()

    @Test
    fun `only D CAN's wheel frames are paired, not the gateway's copy`() {
        // The gateway's copy arrives first every cycle with the rear pair 3 % high. The old
        // count-based pick flipped between the two copies thousands of times a segment.
        acc.setActive(true)
        drive(30, { 80.0 }, gatewayRearScale = 1.03)
        assertEquals(counts80, strictMeanX(close()!!)!!, 1e-9)
    }

    @Test
    fun `without anchors nothing is paired, but fixes are still counted`() {
        acc.setActive(true)
        anchors = emptyList()
        drive(20, { 80.0 })
        val b = close()!!
        assertNull(strictMeanX(b))
        assertEquals(0, b.getJSONObject("loose").getJSONObject("bands").length())
        assertEquals(20, b.getLong("fixes"))
    }

    @Test
    fun `anchors on a second channel stop collection rather than choosing`() {
        acc.setActive(true)
        drive(10, { 80.0 })
        acc.observe(frameOn(1, 0x325)); acc.observe(frameOn(1, 0x330))     // a rival: ambiguous
        drive(20, { 80.0 })
        val n = close()!!.getJSONObject("strict").getJSONObject("bands").getJSONObject("80").getLong("N")
        assertTrue("N=$n", n in 8..10)                         // the first 10 s only
    }

    @Test
    fun `bus identity is re-established for each segment`() {
        acc.setActive(true)
        drive(10, { 80.0 }, gatewayRearScale = 1.03)
        close()
        segment = "coda_20260924_100000_T1.log"
        dBus = 1                                                // dongles re-enumerated
        drive(20, { 80.0 }, gatewayRearScale = 1.03)
        assertEquals(counts80, strictMeanX(close()!!)!!, 1e-9)
    }

    @Test
    fun `a speed ramp is loose but not strict`() {
        acc.setActive(true)
        drive(20, { s -> 60.0 + 4.0 * s })      // +4 km/h per second: over 2 % of speed even at 140
        val b = close()!!
        assertEquals(0, b.getJSONObject("strict").getJSONObject("bands").length())
        assertTrue(b.getJSONObject("loose").getJSONObject("bands").length() > 0)
    }

    @Test
    fun `high torque is loose but not strict, and the two channels share nothing`() {
        acc.setActive(true)
        drive(20, { 80.0 }, torqueNm = 60.0)
        val b = close()!!
        val strict = b.getJSONObject("strict")
        val loose = b.getJSONObject("loose")
        assertEquals(0, strict.getJSONObject("bands").length())
        assertEquals(0L, strict.getJSONObject("lags").getJSONArray("N").getLong(0))
        assertTrue(loose.getJSONObject("lags").getJSONArray("N").getLong(0) > 0)
    }

    @Test
    fun `lag products count consecutive kept fixes`() {
        acc.setActive(true)
        drive(30, { 80.0 })
        val lags = close()!!.getJSONObject("strict").getJSONObject("lags")
        val n = lags.getJSONArray("N")
        val n0 = n.getLong(0)
        for (l in 1..3) assertEquals(n0 - l, n.getLong(l))
        // At constant speed every product is the same, so sum / N is x*y exactly.
        assertEquals(lags.getJSONArray("yx").getDouble(2) / n.getLong(2),
            lags.getJSONArray("xy").getDouble(2) / n.getLong(2), 1e-9)
    }

    @Test
    fun `a fix far off the wheel speed is rejected and counted, never summed`() {
        acc.setActive(true)
        drive(20, { 80.0 }, gpsScale = 1.3)     // GPS 30 % fast: a glitch, not a tyre
        val b = close()!!
        assertTrue(b.getLong("implausible") >= 15)
        assertEquals(0, b.getJSONObject("strict").getJSONObject("bands").length())
        assertEquals(0, b.getJSONObject("loose").getJSONObject("bands").length())
    }

    @Test
    fun `a real common-mode scale difference passes the plausibility gate`() {
        acc.setActive(true)
        drive(20, { 80.0 }, gpsScale = 1.02)    // 2 %: ~90 psi of common mode, far beyond any tyre
        val b = close()!!
        assertEquals(0, b.getLong("implausible"))
        val band = b.getJSONObject("strict").getJSONObject("bands").getJSONObject("80")
        assertEquals(band.getLong("N"), band.getLong("n_speed_acc"))
        assertEquals(0.3, band.getDouble("sum_speed_acc") / band.getLong("n_speed_acc"), 1e-6)
    }

    @Test
    fun `fixes without speed are counted and never paired`() {
        acc.setActive(true)
        drive(10, { 80.0 }, speed = false)
        val b = close()!!
        assertEquals(10, b.getLong("no_speed"))
        assertEquals(0, b.getJSONObject("strict").getJSONObject("bands").length())
    }

    @Test
    fun `GPS off gives a null block, GPS on with no fix gives an empty one`() {
        drive(5, { 80.0 }, speed = false)       // fixes arrive but the service never went active...
        acc.closeSegment(segment!!)
        assertNotNull(acc.take(segment!!))      // ...a bucket exists because fixes arrived

        segment = "coda_20260924_100000_T1.log"
        acc.closeSegment(segment!!)
        assertNull(acc.take(segment!!))         // inactive, no fixes: GPS was off

        acc.setActive(true)
        segment = "coda_20260924_100000_T2.log"
        acc.closeSegment(segment!!)
        assertEquals(0, acc.take(segment!!)!!.getLong("fixes"))
    }

    @Test
    fun `each segment gets its own block, and take removes it`() {
        acc.setActive(true)
        drive(10, { 80.0 })
        val first = segment!!
        acc.closeSegment(first)
        segment = "coda_20260924_100000_T1.log"
        drive(10, { 80.0 })
        val second = close()!!
        val a = acc.take(first)!!
        assertTrue(a.getLong("fixes") in 9..10)
        assertTrue(second.getLong("fixes") in 9..10)
        assertNull(acc.take(first))
    }

    @Test
    fun `nothing is attributed while not logging`() {
        acc.setActive(true)
        segment = null
        drive(10, { 80.0 })
        segment = "coda_20260924_100000_T0.log"
        assertEquals(0, close()!!.getLong("fixes"))
    }

    @Test
    fun `a steady grade shows up as its square`() {
        acc.setActive(true)
        val v = Math.round(80.0 * WheelRatioExtractor.COUNTS_PER_KMH) / WheelRatioExtractor.COUNTS_PER_KMH / 3.6
        drive(40, { 80.0 }, altitude = { s -> 100.0 + 0.04 * v * s })     // 4 % climb
        val band = close()!!.getJSONObject("strict").getJSONObject("bands").getJSONObject("80")
        val ng = band.getLong("n_g")
        assertTrue(ng > 0)
        assertEquals(0.0016, band.getDouble("sum_g2") / ng, 0.0002)
        assertTrue(band.getLong("n_g_noise") == ng)
    }

    @Test
    fun `net elevation change chains exactly across segments, climb is deadbanded`() {
        acc.setActive(true)
        // 100 m -> 160 m over 60 s, with +/-1 m jitter, split over two segments.
        val jitter = { s: Double -> if (s.toInt() % 2 == 0) 1.0 else -1.0 }
        drive(30, { 80.0 }, altitude = { s -> 100.0 + s + jitter(s) })
        val a = close()!!.getJSONObject("elev")
        segment = "coda_20260924_100000_T1.log"
        drive(30, { 80.0 }, altitude = { s -> 130.0 + s + jitter(s) })
        val b = close()!!.getJSONObject("elev")
        // First fix at s=0.5 (100 + 0.5 + 1 = 101.5 m), last at s=29.5 of the second (130 + 29.5 - 1).
        assertEquals(158.5 - 101.5, a.getDouble("dh_m") + b.getDouble("dh_m"), 1e-6)
        val climb = a.getDouble("climb_m") + b.getDouble("climb_m")
        // Smoothing lags the climb by ~5 s and the last partial step stays below the deadband.
        assertTrue("climb=$climb", climb > 45.0 && climb <= 58.0)
        assertEquals(0.0, a.getDouble("descent_m") + b.getDouble("descent_m"), 0.0)
        assertEquals(30, a.getLong("n"))
    }

    @Test
    fun `altitude jitter alone produces no climb or descent`() {
        acc.setActive(true)
        drive(30, { 80.0 }, altitude = { s -> 200.0 + if (s.toInt() % 2 == 0) 2.0 else -2.0 })
        val e = close()!!.getJSONObject("elev")
        assertEquals(0.0, e.getDouble("climb_m"), 0.0)
        assertEquals(0.0, e.getDouble("descent_m"), 0.0)
        assertTrue(Math.abs(e.getDouble("dh_m")) <= 4.0)
    }

    @Test
    fun `flat road with realistic altitude noise accumulates almost no false climb`() {
        acc.setActive(true)
        val rnd = java.util.Random(42)
        // 30 minutes at 1 Hz, 3 m white noise per fix: unsmoothed, a 5 m deadband turns this into
        // kilometres of phantom climb.
        drive(1800, { 80.0 }, altitude = { 300.0 + 3.0 * rnd.nextGaussian() })
        val e = close()!!.getJSONObject("elev")
        val phantom = e.getDouble("climb_m") + e.getDouble("descent_m")
        assertTrue("phantom climb+descent = $phantom m", phantom < 20.0)
    }

    @Test
    fun `a parked car's altitude wander is not climb`() {
        acc.setActive(true)
        // Build 23's first drive: parked five minutes, the solution drifting up 10 m.
        drive(300, { 0.0 }, altitude = { s -> 100.0 + s / 30.0 })
        val e = close()!!.getJSONObject("elev")
        assertEquals(0.0, e.getDouble("climb_m"), 0.0)
        assertEquals(0.0, e.getDouble("dh_m"), 0.0)
        assertEquals(300, e.getLong("parked"))
        assertEquals(0, e.getLong("n"))
    }

    @Test
    fun `the net change telescopes across a stop, and climb resumes after it`() {
        acc.setActive(true)
        drive(30, { 80.0 }, altitude = { s -> 100.0 + s })          // 100.5 .. 129.5
        drive(60, { 0.0 }, altitude = { s -> 140.0 + s })           // parked, wandering: ignored
        drive(30, { 80.0 }, altitude = { s -> 130.0 + s })          // 130.5 .. 159.5
        val e = close()!!.getJSONObject("elev")
        assertEquals(159.5 - 100.5, e.getDouble("dh_m"), 1e-6)
        assertEquals(60, e.getLong("parked"))
        assertTrue(e.getDouble("climb_m") > 30.0)
    }

    @Test
    fun `a snapshot is the open segment's block so far, marked as a snapshot`() {
        acc.setActive(true)
        assertNull(acc.snapshot())
        drive(30, { 80.0 })
        val (name, snap) = acc.snapshot()!!
        assertEquals(segment, name)
        assertEquals(GpsRateAccumulator.SOURCE_SNAPSHOT, snap.getString("source"))
        assertEquals(30, snap.getLong("fixes"))
        drive(10, { 80.0 })
        val closed = close()!!
        assertEquals(GpsRateAccumulator.SOURCE_CLOSE, closed.getString("source"))
        assertEquals(40, closed.getLong("fixes"))
        assertNull(acc.snapshot())                                   // nothing open any more
    }

    @Test
    fun `reference-band ratio reads the GPS scale error`() {
        acc.setActive(true)
        drive(30, { 75.0 }, gpsScale = 1.01)
        val s = acc.status.value
        assertTrue(s.refBandN > 20)
        assertEquals(1.01, s.refBandRho!!, 0.001)
    }

    @Test
    fun `the block holds no position -- only the known speed-derived keys`() {
        acc.setActive(true)
        drive(30, { 80.0 }, altitude = { 100.0 })
        val allowed = setOf(
            "schema", "x", "y", "band_kmh", "fixes", "no_speed", "unpaired", "implausible",
            "sum_speed_acc", "sum_speed_acc_sq", "n_speed_acc", "strict", "loose", "gps_s", "bands", "lags", "N", "sum_x", "sum_y",
            "sum_xy", "sum_xx", "sum_yy", "n_g", "sum_g2", "n_g_noise", "sum_g2_noise",
            "yy", "xx", "yx", "xy", "n_speed_acc", "sum_speed_acc",
            "elev", "n", "dh_m", "climb_m", "descent_m", "deadband_m", "low_acc", "sum_vacc", "n_vacc",
            "source", "parked")
        fun walk(o: Any) {
            when (o) {
                is JSONObject -> o.keys().forEach { k ->
                    assertTrue("unexpected key '$k'", k in allowed || k.toIntOrNull() != null)
                    walk(o.get(k))
                }
                is JSONArray -> for (i in 0 until o.length()) walk(o.get(i))
                is String -> assertTrue("unexpected string '$o'", o in setOf("rear_counts", "gps_mps", "close"))
            }
        }
        walk(close()!!)
    }

    @Test
    fun fixTimeConvertsToNanoTimeDomain() {
        // elapsedRealtime runs 5 s ahead of nanoTime (deep sleep); the fix is 300 ms old.
        val (t, replaced) = GpsRateAccumulator.fixTimeNanos(
            fixElapsedNs = 99_700_000_000L, elapsedNowNs = 100_000_000_000L, nanoNowNs = 95_000_000_000L)
        assertEquals(94_700_000_000L, t)
        assertEquals(false, replaced)
    }

    /** The emulator's injected fixes: stamped with time since 1970 rather than since boot. */
    @Test
    fun fixTimeFarFromArrivalIsReplacedByArrival() {
        val epochNs = 1_790_000_000_000_000_000L
        val (t, replaced) = GpsRateAccumulator.fixTimeNanos(
            fixElapsedNs = epochNs, elapsedNowNs = 1_671_000_000_000L, nanoNowNs = 1_600_000_000_000L)
        assertEquals(1_600_000_000_000L, t)
        assertTrue(replaced)
    }
}
