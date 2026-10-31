package com.reverseit.tpms

import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * [WheelRatioExtractor] under the proc 3 rules ([WheelRatioExtractor.Filters.PROC3]: 20 Nm on every
 * contrast, 2 % steadiness, fast centre, **D CAN pinned by anchors**) against reference values from
 * the algorithm session's extractor, on both live-epoch sessions of 2026-09-26. The references are
 * the spec's section 8a item 3 (2026-09-27), **and they are D CAN**: a parity reference must name
 * its bus, because 5e-7 is ten times finer than the difference between the two copies, so an
 * unpinned test verifies "we picked the same one", not "we decode identically".
 *
 * Two cross-checks that need no reference: F/R was already capped at 20 Nm under v24, so on the same
 * frames proc 3's F/R must equal v24's to the last digit -- any difference is a bug in the filter
 * set, not a rule change -- and, with one cap for everything, top-level `n` equals v24's F/R n.
 *
 * Skipped unless `TPMS_CODA_LOGS` points at the `CodaLogs` folder holding the segments.
 */
class ExtractorProc3ReferenceTest {

    private class Ref(val n: Int, val del: Double, val fr: Double, val lr: Double)

    private val refs = linkedMapOf(
        "coda_20260926_155726" to linkedMapOf(
            "T0" to Ref(1275, 0.999223, 1.004553, 1.000014),
            "T1" to Ref(417, 0.999191, 1.004508, 1.000232),
            "pooled" to Ref(1701, 0.999221, 1.004541, 1.000082),
        ),
        "coda_20260926_181156" to linkedMapOf(
            "T0" to Ref(541, 0.999208, 1.004252, 1.000613),
            "T1" to Ref(3610, 0.999277, 1.004712, 1.000063),
            "T2" to Ref(0, Double.NaN, Double.NaN, Double.NaN),
            "pooled" to Ref(4298, 0.999266, 1.004661, 1.000138),
        ),
    )

    private companion object {
        const val PROC1_DEL_155726 = 0.999216
    }

    @Test
    fun `matches the algorithm session's proc 3 numbers for both live-epoch sessions`() {
        val dir = System.getenv("TPMS_CODA_LOGS")
        assumeTrue("TPMS_CODA_LOGS not set", !dir.isNullOrEmpty())
        for ((session, byPart) in refs) {
            val segs = byPart.keys.filter { it.startsWith("T") }
                .associateWith { WheelRatioExtractor.readFrames(File(dir, "${session}_$it.log")) }
            for ((part, e) in byPart) {
                val frames = if (part == "pooled") segs.values.toList() else listOf(segs.getValue(part))
                val r = WheelRatioExtractor.extractSession(frames, WheelRatioExtractor.Filters.PROC3)
                val what = "$session $part"
                val n = r?.n ?: 0
                println("%s: n %d DEL %.7f FR %.7f LR %.7f".format(what, n,
                    r?.ratios?.get("DEL")?.mean ?: Double.NaN, r?.ratios?.get("FR")?.mean ?: Double.NaN,
                    r?.ratios?.get("LR_")?.mean ?: Double.NaN))
                assertEquals("$what n", e.n, n)
                if (e.n == 0) continue
                r!!
                assertEquals("$what DEL", e.del, r.ratios.getValue("DEL").mean, 5e-7)
                assertEquals("$what FR", e.fr, r.ratios.getValue("FR").mean, 5e-7)
                assertEquals("$what LR_", e.lr, r.ratios.getValue("LR_").mean, 5e-7)
                // One cap for every contrast: F/R now sees exactly the samples DEL does.
                assertEquals("$what n FR", n, r.ratios.getValue("FR").n)
                val v24 = WheelRatioExtractor.extractSession(frames, WheelRatioExtractor.Filters.V24)!!
                assertEquals("$what n = v24 F/R n", v24.ratios.getValue("FR").n, n)
                assertEquals("$what FR = v24 FR", v24.ratios.getValue("FR").mean, r.ratios.getValue("FR").mean, 0.0)
                // Proc 1 (build 23) shares the 20 Nm cap and differs only in steadiness and the
                // centre estimator, so proc 3 must land almost on it (spec section 4 mixing table:
                // proc 1 DEL 0.999216). A regression in the steadiness or centre logic shows here.
                if (session == "coda_20260926_155726" && part == "pooled") {
                    assertEquals("$what DEL near proc 1", PROC1_DEL_155726, r.ratios.getValue("DEL").mean, 1e-5)
                }
            }
        }
    }
}
