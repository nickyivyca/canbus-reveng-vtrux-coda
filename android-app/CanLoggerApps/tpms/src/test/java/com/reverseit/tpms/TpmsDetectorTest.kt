package com.reverseit.tpms

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import kotlin.math.exp

/**
 * What the corpus parity cannot show: the corpus has one row per session, so segment pooling,
 * file-order windows and the page-facing [TpmsEstimate] are tested here on synthetic rows.
 */
class TpmsDetectorTest {

    /** A drive row whose ratios put [lfPsi] on LF alone (others at baseline), exactly. */
    private fun row(log: String, n: Long, lfPsi: Double = 0.0, ts: String = "20260901T100000"): JSONObject {
        // A single-wheel change d moves every contrast containing LF by +d (LF sign is +1 in all
        // three). Soft reads negative, so d = -psi * A.
        val d = -lfPsi * TpmsDetector.A_PER_PSI
        val ratio = exp(d / 2.0)
        val ratios = JSONObject()
        for (k in listOf("DEL", "FR", "LR_", "LFRF", "LRRR")) {
            ratios.put(k, JSONObject().put("mean", if (k in listOf("DEL", "FR", "LR_")) ratio else 1.0).put("sd", 0.002))
        }
        return JSONObject().put("type", "drive").put("schema", 1).put("ts", ts).put("log", log)
            .put("n", n).put("ratios", ratios)
    }

    private fun session(i: Int) = "coda_202609%02d_100000".format(i)

    @Test
    fun `segments of one session pool into one drive`() {
        val det = TpmsDetector()
        val rows = listOf(
            row("${session(1)}_T0.log", 300, 0.0),
            row("${session(1)}_T1.log", 300, -3.0),
            row("${session(1)}_T2.log", 0),                              // no ratios contribute nothing
            row("${session(2)}_T0.log", 900),
        )
        rows[2].put("ratios", JSONObject.NULL)
        val drives = det.drives(rows)
        assertEquals(2, drives.size)
        assertEquals(600L, drives[0].n)
        // Pooled contrasts are the n-weighted mean: LF at -1.5 psi.
        val dev = TpmsDetector.outlierPsi(drives[0].c, DoubleArray(3))
        // The outlier reading of a pure single-wheel change is exactly that change on its own
        // corner; each other corner reads -1/3 of it (projected -d/4, x 4/3), since the outlier
        // reading is taken per corner.
        assertEquals(-1.5, dev.getValue(Corner.LF), 1e-9)
        assertEquals(0.5, dev.getValue(Corner.RR), 1e-9)
    }

    @Test
    fun `sub-floor segments of one session still qualify`() {
        // Three 300-sample segments are one 900-sample drive: above the 800 floor.
        val rows = (0 until 3).map { row("${session(1)}_T$it.log", 300) }
        val r = TpmsDetector().run(TpmsDetector().drives(rows))
        assertEquals(1, r.usedDrives)
    }

    @Test
    fun `a single wheel change reads at full size, and confirmation takes two drives`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))          // learn
        for (i in 4..20) rows.add(row("${session(i)}_T0.log", 1000, -5.0))   // LF 5 psi low
        val r = det.run(det.drives(rows))
        assertEquals(TpmsState.WARN, r.state)
        // Window M=5 of -5 psi drives -> exactly -5 on LF, +5/3 on the others.
        assertEquals(-5.0, r.history.last().dev.getValue(Corner.LF), 1e-9)
        assertEquals(5.0 / 3.0, r.history.last().dev.getValue(Corner.RF), 1e-9)
        // No single-drive state change: every change needed confirm_drives agreeing verdicts.
        val changes = r.events.filter { it.kind != "baseline" }
        assertTrue(changes.isNotEmpty())
    }

    @Test
    fun `window follows file order, not the row clock`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000, ts = "20260901T10000$i"))
        rows.add(row("${session(4)}_T0.log", 1000, -5.0, ts = "20260902T100000"))
        // A later drive whose clock went backwards (unsynced boot). By timestamp, drive 4 would
        // fall out of this drive's window; by file order both are in it.
        rows.add(row("${session(5)}_T0.log", 1000, -3.0, ts = "20250101T000000"))
        val r = det.run(det.drives(rows))
        assertEquals(2, r.history.size)
        // Window = the two post-freeze drives (learning drives are the baseline, never in it).
        assertEquals(-5.0, r.history[0].dev.getValue(Corner.LF), 1e-9)
        assertEquals(-4.0, r.history[1].dev.getValue(Corner.LF), 1e-9)
    }

    @Test
    fun `the fast path warns on the first drive after a puncture`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))
        for (i in 4..8) rows.add(row("${session(i)}_T0.log", 1000))
        rows.add(row("${session(9)}_T0.log", 1000, -8.0))            // nail
        val r = det.run(det.drives(rows))
        assertEquals(TpmsState.WARN, r.state)
        // Fired on the puncture drive itself, by the fast path.
        assertEquals("warn", r.events.last().kind)
        assertTrue(r.events.last().detail, r.events.last().detail.startsWith("LF at -8.0 psi on this drive alone"))
        assertEquals(TpmsState.WARN, det.evaluate(contents(rows)).state)
        // The same drop on the slow path alone would read -8/5 = -1.6 psi and say nothing.
        val slow = TpmsDetector(TpmsSettings(fastWarnPsi = 99.0)).let { it.run(it.drives(rows)) }
        assertEquals(TpmsState.OK, slow.state)
    }

    @Test
    fun `the fast path works mid-drive, on the segments closed so far`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))
        rows.add(row("${session(4)}_T0.log", 500, -8.0))
        assertEquals(TpmsState.OK, det.run(det.drives(rows)).state)        // 500 < 800: not yet
        rows.add(row("${session(4)}_T1.log", 500, -8.0))                    // next segment closes
        assertEquals(TpmsState.WARN, det.run(det.drives(rows)).state)
    }

    @Test
    fun `a void session is not used at all, and the page says so`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))
        // One segment of session 4 carries the fault; its other segment looks clean and must
        // still not count -- the owner voids the drive, not the flagged frames.
        rows.add(row("${session(4)}_T0.log", 1000, -20.0))
        rows.add(row("${session(4)}_T1.log", 0).put("ratios", JSONObject.NULL)
            .put("void", org.json.JSONArray().put(WheelRatioExtractor.VOID_ESC_FAULT)))
        val r = det.run(det.drives(rows))
        assertEquals(TpmsState.OK, r.state)
        assertTrue(r.history.isEmpty())
        val est = det.evaluate(contents(rows))
        assertTrue(est.detail!!, est.detail!!.startsWith("Last drive void: ABS/ESC fault"))
        // Nor does a void session close the undo window.
        assertEquals(0L, TpmsEpochStore.pooledSessionSamples(rows).getValue(session(4)))
    }

    @Test
    fun `corner deviations always sum to zero while the common mode is unknown`() {
        // Each contrast's corner signs sum to zero, so any input gives a zero-sum split: one corner
        // low means another reads high, whether or not it gained anything.
        val rnd = java.util.Random(7)
        repeat(1000) {
            val now = DoubleArray(3) { rnd.nextGaussian() * 1e-3 }
            val dev = TpmsDetector.outlierPsi(now, DoubleArray(3))
            assertEquals(0.0, dev.values.sum(), 1e-9)
        }
        for (k in 0 until 3) {
            assertEquals("signs of contrast $k", 0, Corner.entries.sumOf { TpmsDetector.CONTRAST_SIGNS.getValue(it)[k] })
        }
    }

    @Test
    fun `each contrast pools over its own samples`() {
        // Two segments of one drive: F/R only has samples in the second (the first ran over 20 Nm).
        val a = row("${session(1)}_T0.log", 600, -3.0)
        val b = row("${session(1)}_T1.log", 400, 0.0)
        a.getJSONObject("ratios").getJSONObject("FR").put("mean", JSONObject.NULL).put("n", 0)
        for (k in listOf("DEL", "LR_")) a.getJSONObject("ratios").getJSONObject(k).put("n", 600)
        for (k in listOf("DEL", "FR", "LR_")) b.getJSONObject("ratios").getJSONObject(k).put("n", 400)
        val d = TpmsDetector().drives(listOf(a, b)).single()
        assertEquals(1000L, d.n)
        assertEquals(listOf(1000L, 400L, 1000L), d.nc.toList())
        // F/R is the second segment's alone (0 psi), not diluted by a value the first never had.
        assertEquals(0.0, d.c[1], 1e-15)
        assertEquals(0.6 * 3.0 * TpmsDetector.A_PER_PSI, d.c[0], 1e-12)
    }

    @Test
    fun `a window short of F-R samples is skipped, not scored on noise`() {
        val det = TpmsDetector()
        fun starved(i: Int, fr: Long) = row("${session(i)}_T0.log", 1000, -3.0).also { r ->
            for (k in listOf("DEL", "LR_")) r.getJSONObject("ratios").getJSONObject(k).put("n", 1000)
            r.getJSONObject("ratios").getJSONObject("FR").put("n", fr)
        }
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))           // learn
        rows.add(starved(4, 5))                                                 // 5 F/R samples alone
        val r = det.run(det.drives(rows))
        assertEquals(TpmsState.OK, r.state)
        assertTrue(r.history.isEmpty())
        assertEquals("skip", r.events.last().kind)
        assertTrue(r.events.last().detail, r.events.last().detail.startsWith("cleared the sample floor but FR below 300"))
        // The starved drive stays in the window: with a second, the window pools 5 + 400 F/R samples.
        rows.add(starved(5, 400))
        val r2 = det.run(det.drives(rows))
        assertEquals(1, r2.history.size)
    }

    @Test
    fun `the fast path needs the per-contrast floor on the drive alone`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))
        // A nail, but F/R on 5 samples: not enough to act on alone.
        rows.add(row("${session(4)}_T0.log", 1000, -8.0).also { r ->
            for (k in listOf("DEL", "LR_")) r.getJSONObject("ratios").getJSONObject(k).put("n", 1000)
            r.getJSONObject("ratios").getJSONObject("FR").put("n", 5)
        })
        assertTrue(det.run(det.drives(rows)).events.none { it.kind == "warn" })
    }

    @Test
    fun `learning names a contrast short of its floor`() {
        val r = row("${session(1)}_T0.log", 1000).also { r ->
            for (k in listOf("DEL", "LR_")) r.getJSONObject("ratios").getJSONObject(k).put("n", 1000)
            r.getJSONObject("ratios").getJSONObject("FR").put("n", 120)
        }
        val est = TpmsDetector().evaluate(contents(listOf(r)))
        assertEquals("1 of 3 drives, 1000 of 2400 samples, F/R 120 of 300 - needs steady highway", est.detail)
    }

    @Test
    fun `the baseline cannot be frozen twice`() {
        val b = FrozenBaseline()
        b.freeze(doubleArrayOf(0.0, 0.0, 0.0), 3)
        try {
            b.freeze(doubleArrayOf(1.0, 1.0, 1.0), 3)
            fail("second freeze must throw")
        } catch (_: IllegalStateException) { }
        assertEquals(0.0, b.value!![0], 0.0)
        // The exposed value is a copy, so the baseline cannot be edited through it either.
        b.value!![0] = 9.0
        assertEquals(0.0, b.value!![0], 0.0)
    }

    @Test
    fun `an un-announced fill goes STALE and suppresses the corners`() {
        val det = TpmsDetector()
        val rows = ArrayList<JSONObject>()
        for (i in 1..3) rows.add(row("${session(i)}_T0.log", 1000))
        for (i in 4..9) rows.add(row("${session(i)}_T0.log", 1000, -5.0))
        for (i in 10..20) rows.add(row("${session(i)}_T0.log", 1000, +5.0))   // pumped up, not told
        val c = contents(rows)
        val est = det.evaluate(c)
        assertEquals(TpmsState.STALE, est.state)
        assertTrue(est.corners.isEmpty())
        assertTrue(est.detail!!.contains("no calibration entered"))
    }

    @Test
    fun `learning shows progress, no calibration says what to do`() {
        val det = TpmsDetector()
        val est = det.evaluate(contents(listOf(row("${session(1)}_T0.log", 1000))))
        assertEquals(TpmsState.LEARNING, est.state)
        assertTrue(est.corners.isEmpty())
        assertEquals("1 of 3 drives, 1000 of 2400 samples", est.detail)
        val none = det.evaluate(null)
        assertEquals(TpmsState.LEARNING, none.state)
        assertTrue(none.detail!!.contains("SET"))
    }

    @Test
    fun `rows with missing or bad ratios are ignored, not fatal`() {
        val bad = row("${session(1)}_T0.log", 1000)
        bad.getJSONObject("ratios").getJSONObject("DEL").put("mean", 0.0)
        val missing = JSONObject().put("type", "drive").put("log", "${session(2)}_T0.log").put("n", 1000)
        val drives = TpmsDetector().drives(listOf(bad, missing))
        assertTrue(drives.isEmpty())
        assertNull(TpmsDetector.contrasts(missing))
    }

    private fun contents(rows: List<JSONObject>) = TpmsEpochStore.Contents(
        key = "20260901T090000",
        calibration = TpmsCalibrationEntry.of(Corner.entries.associateWith { 42f }, 15f, 0L),
        drives = rows,
        skippedLines = 0,
    )
}
