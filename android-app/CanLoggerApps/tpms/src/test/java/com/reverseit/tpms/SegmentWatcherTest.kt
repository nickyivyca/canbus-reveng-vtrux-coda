package com.reverseit.tpms

import org.junit.Assert.assertEquals
import org.junit.Test

class SegmentWatcherTest {
    @Test
    fun `reports the previous segment on a roll and on stop, never the live one`() {
        val names = ArrayDeque(listOf(null, "a_T0.log", "a_T0.log", "a_T1.log", null, null, "b_T0.log"))
        val closed = mutableListOf<String>()
        val w = SegmentWatcher({ names.removeFirst() }, { closed.add(it) })
        repeat(7) { w.poll() }
        assertEquals(listOf("a_T0.log", "a_T1.log"), closed)
    }
}
