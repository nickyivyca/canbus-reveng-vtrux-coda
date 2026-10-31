package com.reverseit.tpms

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * [WheelRatioExtractor] against the Python `extract_one` on real captures.
 *
 * Needs reference values from `android-app/notes/artifacts/tpms_ratio_parity.py`; skipped unless
 * `TPMS_PARITY_JSON` points at its output. The logs are ~37 MB per 5-minute segment and live in the
 * SeaDrive `CANLogs` library, so they are not test resources.
 *
 * **Reference files made before 2026-09-27 are stale:** both sides then chose the bus by frame
 * count, and both now pin D CAN by anchors. Regenerate before running.
 *
 * Two checks:
 *  1. **Exact parity**: [WheelRatioExtractor.extractSession] reproduces `extract_one` -- same n,
 *     same ratios to floating-point summation order.
 *  2. **Per-segment rows pooled per session** (what the app writes, and how the detector will read
 *     it) against the same. Not asserted equal: the running session-so-far steering centre
 *     legitimately differs from whole-session centring. Printed, so the
 *     size of the difference is on record.
 */
class WheelRatioParityTest {

    @Test
    fun `matches extract_one on real sessions`() =
        run("TPMS_PARITY_JSON", "legacy", WheelRatioExtractor.Filters.LEGACY)

    /** The same, under the v24 rule set: the corpus tool's `--v24` path against [Filters.V24]. */
    @Test
    fun `matches extract_one on real sessions under v24`() =
        run("TPMS_PARITY_V24_JSON", "v24", WheelRatioExtractor.Filters.V24)

    private fun run(env: String, fset: String, filters: WheelRatioExtractor.Filters) {
        val path = System.getenv(env)
        assumeTrue("$env not set", !path.isNullOrEmpty())
        val expected = JSONObject(File(path!!).readText())

        for (session in expected.keys()) {
            val e = expected.getJSONObject(session)
            val paths = e.getJSONArray("paths").let { a -> List(a.length()) { File(a.getString(it)) } }
            val row = e.getJSONObject("row")
            assertEquals("$session: reference file was generated for another rule set", fset, e.optString("fset", "legacy"))

            val t0 = System.nanoTime()
            val frames = paths.map { WheelRatioExtractor.readFrames(it) }
            val readMs = (System.nanoTime() - t0) / 1e6
            frames.forEachIndexed { i, f ->
                println("  read T%d: front %d rear %d steer %d torque %d, front t %s..%s".format(i,
                    f.front.size, f.rear.size, f.steer.size, f.torque.size,
                    f.front.firstOrNull()?.t, f.front.maxOfOrNull { it.t }))
            }

            // 1. exact parity
            val res = WheelRatioExtractor.extractSession(frames, filters)
            assertNotNull("$session: Kotlin returned null where Python returned a row", res)
            res!!
            assertEquals("$session n", row.getInt("n"), res.n)
            assertEquals("$session kmh", row.getDouble("kmh"), res.kmhMedian!!, 1e-9)
            for (name in WheelRatioExtractor.RATIO_NAMES) {
                val r = res.ratios.getValue(name)
                assertEquals("$session $name mean", row.getDouble(name), r.mean, 1e-13)
                assertEquals("$session $name sd", row.getDouble(name + "_sd"), r.sd, 1e-12)
            }
            println("%s: exact parity OK, n=%d, %d segments read in %.0f ms (%.0f ms each)"
                .format(session, res.n, paths.size, readMs, readMs / paths.size))

            // 2. per-segment, pooled
            // As DriveRowProducer: session-so-far centre, from the fast samples under v24.
            val centre = SteeringCentre()
            val fast = FastSteeringCentre()
            var n = 0L
            val sum = HashMap<String, Double>()
            val sumSq = HashMap<String, Double>()
            val cnt = HashMap<String, Long>()
            frames.forEachIndexed { i, f ->
                f.steer.forEach { centre.add(it.a.toInt()) }
                if (filters.fastCentre) fast.add(WheelRatioExtractor.fastSteerRaw(f))
                val c = if (fast.n >= WheelRatioExtractor.FAST_CENTRE_MIN) fast.median() else centre.median()
                val seg = WheelRatioExtractor.extractSegment(f, c, filters)
                println("  T%d  n=%5d  centre=%.1f over %d  %s".format(i, seg.n, seg.steerCentre ?: Double.NaN,
                    centre.n, seg.ratios["DEL"]?.let { "DEL=%.9f".format(it.mean) } ?: "-"))
                println("      temps " + WheelRatioExtractor.temperatures(f).entries.joinToString { (k, v) ->
                    "%s=%s(%s of %d)".format(k, v.median, v.validFrac?.let { "%.2f".format(it) }, v.n) })
                n += seg.n
                for ((k, r) in seg.ratios) {
                    if (r.n == 0) continue
                    sum[k] = (sum[k] ?: 0.0) + r.n * r.mean
                    sumSq[k] = (sumSq[k] ?: 0.0) + r.n * (r.sd * r.sd + r.mean * r.mean)
                    cnt[k] = (cnt[k] ?: 0L) + r.n
                }
            }
            println("  pooled n=%d vs session n=%d".format(n, res.n))
            for (name in WheelRatioExtractor.RATIO_NAMES) {
                if (name !in sum) { println("  %-5s no per-segment samples".format(name)); continue }
                val mean = sum.getValue(name) / cnt.getValue(name)
                val sd = Math.sqrt(sumSq.getValue(name) / cnt.getValue(name) - mean * mean)
                println("  %-5s pooled %.9f sd %.6f | session %.9f sd %.6f | diff %+.2e"
                    .format(name, mean, sd, res.ratios.getValue(name).mean, res.ratios.getValue(name).sd,
                        mean - res.ratios.getValue(name).mean))
            }
        }
    }
}
