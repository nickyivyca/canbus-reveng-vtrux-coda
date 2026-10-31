package com.reverseit.tpms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import kotlin.random.Random

/** [SteeringCentre] against a plain sorted-list median after every add, `np.median`'s definition. */
class SteeringCentreTest {

    private fun reference(xs: List<Int>): Double {
        val s = xs.sorted()
        val m = s.size / 2
        return if (s.size % 2 == 1) s[m].toDouble() else (s[m - 1] + s[m]) / 2.0
    }

    @Test
    fun `empty has no median`() = assertNull(SteeringCentre().median())

    @Test
    fun `matches the sorted median after every add`() {
        val rnd = Random(14)
        for (spread in listOf(3, 200, 65536)) {
            val c = SteeringCentre()
            val xs = ArrayList<Int>()
            repeat(3000) {
                val v = if (spread == 65536) rnd.nextInt(65536) else 20000 + rnd.nextInt(spread)
                c.add(v); xs += v
                assertEquals("spread $spread after ${xs.size}", reference(xs), c.median()!!, 0.0)
            }
            assertEquals(xs.size.toLong(), c.n)
        }
    }

    @Test
    fun `the ends of the 16-bit range`() {
        val c = SteeringCentre()
        c.add(0); assertEquals(0.0, c.median()!!, 0.0)
        c.add(0xFFFF); assertEquals(0xFFFF / 2.0, c.median()!!, 0.0)
        c.add(0xFFFF); assertEquals(0xFFFF.toDouble(), c.median()!!, 0.0)
    }
}
