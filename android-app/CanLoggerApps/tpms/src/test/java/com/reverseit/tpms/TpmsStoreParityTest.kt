package com.reverseit.tpms

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * Drives [TpmsEpochStore] over a real store folder for `android-app/notes/artifacts/tpms_fragment_parity.py`,
 * which runs the prototype's `FragmentStore` over the same input and compares. Skipped unless
 * `TPMS_PARITY_DIR` names a work folder holding `in/` (a copy of `CodaLogs/tpms/`) and `row.json`
 * (one drive row to add). Writes `kotlin_read.json` (the active epoch as read) and `kotlin_store/`
 * (the folder after adding the row: the migration's first `_full`).
 */
class TpmsStoreParityTest {

    @Test
    fun `dump the store as read and after one added row`() {
        val work = System.getenv("TPMS_PARITY_DIR")?.let(::File)
        assumeTrue("TPMS_PARITY_DIR not set", work != null)
        val out = File(work, "kotlin_store").apply { deleteRecursively(); mkdirs() }
        File(work, "in").listFiles()!!.forEach { it.copyTo(File(out, it.name)) }

        val st = TpmsEpochStore(out)
        val cur = st.current()!!
        File(work, "kotlin_read.json").writeText(JSONObject()
            .put("key", cur.key)
            .put("psi", JSONObject().apply { Corner.entries.forEach { put(it.name, cur.calibration.psi(it).toDouble()) } })
            .put("temp_c", cur.calibration.ambientC.toDouble())
            .put("rows", JSONArray(cur.drives))
            .put("skipped", cur.skippedLines)
            .toString(1))
        st.addDrive(JSONObject(File(work, "row.json").readText()))
    }
}
