package com.reverseit.tpms

import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * The indirect-TPMS store: a folder of **immutable fragments** in `CodaLogs/tpms/`, per
 * `projects/coda/notes/tpms-algorithm-spec.md` sections 4 and 5 (schema 2, 2026-09-26).
 *
 * **Why fragments.** SeaDrive on the head unit is one-way and upload-only: it uploads a file when it
 * first sees it and ignores every later change. The append-only file per epoch this replaced was
 * frozen on the server at whatever it held first (the live one reached the library at 127 bytes).
 * A file that is complete when it appears and never changes makes "upload once" correct behaviour.
 * So every write here is a new file: built in memory, written to `<name>.tmp`, fsynced, renamed.
 * The sync and any reader see a fragment only when it is complete, and a kill leaves a `.tmp`,
 * which the `*.jsonl` listing does not match.
 *
 * **A fragment** is `tpms_<prefix>_<seq>.jsonl` and holds, in order: the epoch's `calibration`
 * record (repeated in every fragment, so any one of them is a working store on its own), every
 * `calibration_amend` and `epoch_void`, then either one completed drive row (a segment closed) or
 * the open segment's row marked `partial` (the per-minute checkpoint). A `_full` fragment carries
 * the whole epoch instead; one is written on every epoch operation, when the epoch has none yet,
 * and every [fullEveryRows] completed rows. Precalibration drives (before the first SET) use the
 * same scheme under the prefix [PRECALIBRATION_TS], with a `precalibration` first record.
 *
 * **Identity comes from content, never from file names.** An epoch is its calibration record's
 * ordering key -- `name_ts` when present, else `ts` -- so N copies of one calibration are one epoch
 * and a re-upload landing as `... (1).jsonl` is a non-event. The key is unique by construction
 * ([set] pushes it past every existing one), which is why two SETs in the same second are two
 * epochs while `ts` stays the true press time. A drive is its `log`. Fragments overlap by construction, so the reader always dedupes: a completed
 * row beats every partial, then higher `proc`, then higher `n` (completed) or `gps.fixes`
 * (partials), then later seq. **Dedupe never loses a GPS block**: when the winner has none and a
 * row it beat has one, the winner takes it, tagged `source: "partial"` -- the GPS block is the one
 * thing the CAN logs cannot regenerate.
 *
 * **Legacy files** (schema 1: `tpms_<ts>.jsonl`, one append-only file per epoch) are read as
 * fragments as they are. The first write to such an epoch is a `_full`, which carries it all to
 * the server, so installing the build is the migration.
 *
 * **The app keeps an index in memory** and reads the folder once, at first use. It does not read
 * every fragment: per prefix, canonical fragments older than the newest `_full` are skipped,
 * because that `_full` holds everything they did. Correctness is still defined by the full scan
 * ([load] with `fullScan = true`), and the bounded read falls back to it if any fragment it would
 * skip was modified after that `_full` -- i.e. was placed there by hand. Changes made to the folder
 * by anything other than this instance are seen at the next start.
 *
 * Synchronous and Android-free, so it runs under plain JVM tests. [FileTpmsCalibrationStore] puts
 * it behind the UI and moves every call off the main thread; the public methods are synchronized
 * because the drive-row thread also reads it.
 *
 * The executable reference is `FragmentStore` in
 * `projects/coda/notes/artifacts/tpms_app_prototype.py`. Diff behaviour against that, not against
 * this comment.
 */
class TpmsEpochStore(
    val dir: File,
    private val nowMs: () -> Long = System::currentTimeMillis,
    private val zone: TimeZone = TimeZone.getDefault(),
    private val settings: TpmsSettings = TpmsSettings(),
    private val fullEveryRows: Int = FULL_EVERY_ROWS,
) {

    /**
     * The active epoch as the detector and the page see it. [calibration] has the amends applied,
     * last one winning, with the epoch's own timestamp untouched. [drives] are the deduped winners,
     * GPS inheritance applied, ordered by `ts` then `log`.
     */
    class Contents(
        /** The epoch's identity: its calibration record's `name_ts`, else its `ts` (its ordering key). */
        val key: String,
        val calibration: TpmsCalibrationEntry,
        val drives: List<JSONObject>,
        /** Unparseable lines dropped across the whole folder read. */
        val skippedLines: Int,
    )

    /** What the last folder read did, for the debug log. */
    data class LoadStats(val listed: Int, val read: Int, val skipped: Int, val fullScan: Boolean,
                         val reason: String, val droppedLines: Int)

    // ----------------------------------------------------------------------- the index ----

    /** One row as read, with the fields dedupe ranks on pulled out once. */
    private class Row(val text: String, val log: String, val ts: String, val partial: Boolean,
                      val proc: Int, val n: Long, val fixes: Long, val seq: Int, val hasGps: Boolean) {
        fun rank(): List<Long> = listOf(if (partial) 0L else 1L, proc.toLong(), if (partial) fixes else n, seq.toLong())
    }

    private class Slot(var winner: Row, var donor: Row?)

    /** An epoch (head = its calibration) or the precalibration group (head = `precalibration`). */
    private class Group(val prefix: String, val head: String, val key: String) {
        val amends = ArrayList<String>()
        val amendSet = HashSet<String>()
        val voids = LinkedHashSet<String>()
        val rows = HashMap<String, Slot>()
        var hasFull = false
        var completedSinceFull = 0
    }

    private var loaded = false
    private val epochs = LinkedHashMap<String, Group>()
    private var precal: Group? = null
    private val voided = HashSet<String>()
    /** Highest seq seen per name prefix, and every prefix any `tpms_<ts>` name uses. */
    private val seqs = HashMap<String, Int>()
    private val prefixesOnDisk = HashSet<String>()
    private var dropped = 0
    var lastLoad: LoadStats? = null
        private set

    // ------------------------------------------------------------------------- reading ----

    /** Live epoch keys, in name-key order. Voided epochs are not epochs. */
    @Synchronized
    fun epochs(): List<String> {
        ensureLoaded()
        return liveEpochs().map { it.key }
    }

    /** The active epoch's contents, or null before the first calibration. */
    @Synchronized
    fun current(): Contents? {
        ensureLoaded()
        return liveEpochs().lastOrNull()?.let { contents(it) }
    }

    /** Drive rows recorded before any calibration, deduped. */
    @Synchronized
    fun precalibrationRows(): List<JSONObject> {
        ensureLoaded()
        return precal?.let { rowsOf(it) } ?: emptyList()
    }

    /**
     * The calibration [undo] would resume, or null when undo is unavailable.
     *
     * Unavailable when there is no earlier epoch to land on (undoing the first calibration would
     * leave no baseline, the state undo exists to rescue the owner from), and once anything has
     * been measured against the new baseline. "Measured" is a **session** reaching
     * [TpmsSettings.minSamples] with its segment rows pooled, not one row reaching it: rows are per
     * 5-minute log segment and the detector pools them by session, so three 300-sample segments of
     * one drive are a qualifying drive even though no single row is.
     */
    @Synchronized
    fun undoTarget(): TpmsCalibrationEntry? {
        ensureLoaded()
        val live = liveEpochs()
        if (live.size < 2) return null
        if (pooledSessionSamples(rowsOf(live.last())).values.any { it >= settings.minSamples }) return null
        return calibrationOf(live[live.size - 2])
    }

    /**
     * The `log` of every **completed** drive row, in any epoch or precalibration. Catch-up uses this
     * to find segments that still need a row, so a partial row must not count: a segment killed
     * mid-write has only partials, and it is exactly the one catch-up has to finish.
     */
    @Synchronized
    fun recordedLogs(): Set<String> {
        ensureLoaded()
        return allGroups().flatMapTo(HashSet()) { g -> g.rows.values.filter { !it.winner.partial }.map { it.winner.log } }
    }

    /**
     * The best GPS block stored for [log] (from its highest-ranked row that has one), tagged
     * `source: "partial"` when it came from a partial row; null if none. Lets a completed row built
     * by catch-up after a kill carry the block the per-minute checkpoints saved.
     */
    @Synchronized
    fun storedGps(log: String): JSONObject? {
        ensureLoaded()
        val donor = allGroups().mapNotNull { it.rows[log]?.donor }.maxWithOrNull(RANK) ?: return null
        val gps = JSONObject(donor.text).optJSONObject("gps") ?: return null
        if (donor.partial) gps.put("source", GPS_SOURCE_PARTIAL)
        return gps
    }

    // ------------------------------------------------------------------------- writing ----

    /**
     * Open a new epoch for [entry]. Returns the new fragment (a `_full` holding the calibration).
     *
     * **The name is an ordering key; the record's `ts` is data.** The active epoch is the one whose
     * name key sorts last, so a SET made while the clock reads earlier than the newest epoch (a head
     * unit that has not yet synced its clock, or two SETs within one second) would otherwise not
     * become active -- SET would appear to succeed and silently change nothing. So the name key is
     * pushed to one second past the newest epoch when needed, while `ts` stays the wall-clock time
     * of the press, and `name_ts` records the key when the two differ. Nothing in the detector is
     * time-based, so a wrong clock misdates rows but cannot change a verdict.
     */
    @Synchronized
    fun set(entry: TpmsCalibrationEntry): File {
        ensureLoaded()
        val clockTs = formatTs(entry.setAtMs)
        var nameTs = clockTs
        val newest = epochs.values.maxOfOrNull { it.prefix }
        if (newest != null && nameTs <= newest) nameTs = formatTs(parseTs(newest)!! + 1000L)
        while (nameTs in prefixesOnDisk || epochs.values.any { it.prefix == nameTs }) {
            nameTs = formatTs(parseTs(nameTs)!! + 1000L)
        }
        val record = JSONObject()
            .put("type", CALIBRATION)
            .put("schema", SCHEMA)
            .put("ts", clockTs)
            .put("psi", psiJson { entry.psi(it) })
            .put("temp_c", num(entry.ambientC))
            .put("note", "")
        if (nameTs != clockTs) record.put("name_ts", nameTs)
        val g = Group(nameTs, record.toString(), nameTs)
        val file = writeFragment(g, full = true)
        epochs[nameTs] = g
        voided.remove(nameTs)
        return file
    }

    /**
     * Void the active epoch and resume the previous one, with its history intact. **A tombstone,
     * not a delete**: an `epoch_void` record naming the voided calibration's `ts`, written into a
     * `_full` of the epoch it voids. A delete cannot work -- an epoch spans many fragments, and
     * fragments already uploaded cannot be recalled by a one-way sync. Returns false, changing
     * nothing, when [undoTarget] is null.
     */
    @Synchronized
    fun undo(): Boolean {
        if (undoTarget() == null) return false
        val g = liveEpochs().last()
        val rec = JSONObject()
            .put("type", EPOCH_VOID)
            .put("schema", SCHEMA)
            .put("ts", formatTs(nowMs()))
            .put("epoch", g.key)
            .toString()
        writeFragment(g, full = true, extraVoid = rec)
        g.voids.add(rec)
        voided.add(g.key)
        return true
    }

    /**
     * Correct the active epoch's recorded values. Writes a `_full` with a new `calibration_amend`
     * record carrying its own audit timestamp; the calibration record, and so the epoch's identity,
     * is never touched. Takes loose values rather than an entry so it cannot move the epoch's
     * timestamp. Returns false when there is no epoch.
     */
    @Synchronized
    fun amend(psi: Map<Corner, Float>, ambientC: Float): Boolean {
        ensureLoaded()
        val g = liveEpochs().lastOrNull() ?: return false
        val current = calibrationOf(g)
        val rec = JSONObject()
            .put("type", CALIBRATION_AMEND)
            .put("schema", SCHEMA)
            .put("ts", formatTs(nowMs()))
            .put("note", "")
            .put("psi", psiJson { psi[it] ?: current.psi(it) })
            .put("temp_c", num(ambientC))
            .toString()
        writeFragment(g, full = true, extraAmend = rec)
        if (g.amendSet.add(rec)) g.amends.add(rec)
        return true
    }

    /**
     * Record a completed drive row. It goes to the active epoch or, before the first calibration,
     * to the precalibration group. Returns the fragment written.
     *
     * Precalibration rows are kept because the drives either side of the first fill bracket a known
     * common-mode step with GPS on both sides. They are never an epoch, a baseline, a verdict or an
     * undo target: the role comes from the group's first record.
     */
    @Synchronized
    fun addDrive(row: JSONObject): File {
        ensureLoaded()
        val rec = JSONObject(row.toString()).put("partial", false)
        val g = target()
        val full = !g.hasFull || g.completedSinceFull + 1 >= fullEveryRows
        return writeFragment(g, full, extraRow = rec.toString())
    }

    /**
     * The per-minute checkpoint of the segment still open: [row] is written marked `partial`. Never
     * counts towards consolidation. Returns the fragment written.
     */
    @Synchronized
    fun checkpoint(row: JSONObject): File {
        ensureLoaded()
        val rec = JSONObject(row.toString()).put("partial", true)
        val g = target()
        return writeFragment(g, full = !g.hasFull, extraRow = rec.toString())
    }

    /**
     * (Re)read the folder. [fullScan] reads every fragment; otherwise fragments a newer `_full`
     * supersedes are skipped (see the class comment).
     */
    @Synchronized
    fun load(fullScan: Boolean = false): LoadStats {
        epochs.clear(); precal = null; voided.clear(); seqs.clear(); prefixesOnDisk.clear(); dropped = 0
        loaded = true
        val files = (dir.listFiles { f -> f.isFile && f.name.endsWith(SUFFIX) } ?: emptyArray())
            .sortedBy { it.name }
        val names = files.associateWith { Name.parse(it.name) }
        names.values.filterNotNull().forEach { n ->
            prefixesOnDisk.add(n.prefix)
            if (n.seq >= 0) seqs[n.prefix] = maxOf(seqs[n.prefix] ?: -1, n.seq)
        }
        // Newest canonical _full per prefix.
        val newestFull = HashMap<String, Pair<Int, File>>()
        names.forEach { (f, n) ->
            if (n != null && n.canonical && n.full && n.seq > (newestFull[n.prefix]?.first ?: -1)) {
                newestFull[n.prefix] = n.seq to f
            }
        }
        val skip = HashSet<File>()
        var reason = if (fullScan) "requested" else "bounded"
        if (!fullScan) {
            for ((f, n) in names) {
                if (n == null || !n.canonical) continue
                val (fs, ff) = newestFull[n.prefix] ?: continue
                if (n.seq >= fs) continue
                // Written before that _full, so it should be older on disk too. If not, it was put
                // here afterwards (by hand), and the _full does not cover it.
                if (f.lastModified() > ff.lastModified()) {
                    reason = "full scan: ${f.name} is newer than ${ff.name}"
                    skip.clear()
                    break
                }
                skip.add(f)
            }
        }
        val fullScanDone = fullScan || skip.isEmpty()
        if (!fullScan && skip.isEmpty() && reason == "bounded") reason = "bounded: nothing behind a _full to skip"
        for ((f, n) in names) {
            if (f in skip) continue
            ingest(n, readFragment(f))
        }
        // Completed rows since each group's newest _full: the consolidation counter, from disk.
        for (g in allGroups()) {
            val fs = newestFull[g.prefix]?.first
            g.hasFull = fs != null
            g.completedSinceFull = sinceFull[g.key] ?: 0
        }
        sinceFull.clear()
        return LoadStats(files.size, files.size - skip.size, skip.size, fullScanDone, reason, dropped)
            .also { lastLoad = it }
    }

    // ------------------------------------------------------------------------ internals ----

    private val sinceFull = HashMap<String, Int>()

    private fun ensureLoaded() {
        if (!loaded) load()
    }

    private fun allGroups(): List<Group> = epochs.values + listOfNotNull(precal)

    private fun liveEpochs(): List<Group> =
        epochs.values.filter { it.key !in voided }.sortedBy { it.prefix }

    private fun target(): Group = liveEpochs().lastOrNull() ?: precal ?: run {
        val head = JSONObject()
            .put("type", PRECALIBRATION)
            .put("schema", SCHEMA)
            .put("ts", formatTs(nowMs()))
            .toString()
        Group(PRECALIBRATION_TS, head, PRECALIBRATION_TS).also { precal = it }
    }

    private fun ingest(n: Name?, recs: List<JSONObject>) {
        if (recs.isEmpty()) return
        val head = recs[0]
        val seq = n?.seq ?: -1
        val g: Group = when (head.optString("type")) {
            CALIBRATION -> {
                val key = head.optString("name_ts").ifEmpty { head.optString("ts") }
                if (key.isEmpty()) return
                epochs.getOrPut(key) { Group(key, head.toString(), key) }
            }
            PRECALIBRATION -> precal ?: Group(PRECALIBRATION_TS, head.toString(), PRECALIBRATION_TS)
                .also { precal = it }
            // Anything else is not a store file. Ignored by role, never by name.
            else -> return
        }
        var completed = 0
        for (r in recs.drop(1)) {
            when (r.optString("type")) {
                CALIBRATION_AMEND -> r.toString().let { if (g.amendSet.add(it)) g.amends.add(it) }
                EPOCH_VOID -> {
                    g.voids.add(r.toString())
                    r.optString("epoch").takeIf { it.isNotEmpty() }?.let { voided.add(it) }
                }
                DRIVE -> {
                    val row = rowOf(r.toString(), r, seq) ?: continue
                    merge(g, row)
                    if (!row.partial) completed++
                }
            }
        }
        if (n != null && n.canonical && !n.full) sinceFull.merge(g.key, completed, Int::plus)
        if (n != null && n.canonical && n.full) sinceFull[g.key] = 0
    }

    private fun merge(g: Group, row: Row) {
        val slot = g.rows[row.log]
        if (slot == null) {
            g.rows[row.log] = Slot(row, row.takeIf { it.hasGps })
            return
        }
        if (RANK.compare(row, slot.winner) > 0) slot.winner = row
        if (row.hasGps && (slot.donor == null || RANK.compare(row, slot.donor!!) > 0)) slot.donor = row
    }

    /** The group's winning rows, GPS inheritance applied, ordered by `ts` then `log`. */
    private fun rowsOf(g: Group): List<JSONObject> =
        g.rows.values.sortedWith(compareBy({ it.winner.ts }, { it.winner.log })).map { materialise(it) }

    private fun materialise(s: Slot): JSONObject {
        val rec = JSONObject(s.winner.text)
        val donor = s.donor
        if (!s.winner.hasGps && donor != null) {
            val gps = JSONObject(donor.text).getJSONObject("gps")
            rec.put("gps", gps.put("source", GPS_SOURCE_PARTIAL))
        }
        return rec
    }

    private fun contents(g: Group) = Contents(g.key, calibrationOf(g), rowsOf(g), dropped)

    /** The calibration with its amends applied in `ts` order, last winning. */
    private fun calibrationOf(g: Group): TpmsCalibrationEntry {
        val head = JSONObject(g.head)
        var cal = entryOf(head, head.optString("ts"))
        for (a in g.amends.map { JSONObject(it) }.sortedBy { it.optString("ts") }) {
            cal = entryOf(a, formatTs(cal.setAtMs), fallback = cal)
        }
        return cal
    }

    /**
     * Write one fragment of [g]: tmp, fsync, rename -- never in place. A `_full` carries every
     * winning row (with [extraRow] merged in); otherwise just [extraRow]. The index is updated only
     * after the rename succeeds, so a failed write leaves it describing what is on disk.
     */
    private fun writeFragment(g: Group, full: Boolean, extraRow: String? = null,
                              extraAmend: String? = null, extraVoid: String? = null): File {
        dir.mkdirs()
        var seq = (seqs[g.prefix] ?: -1) + 1
        while (File(dir, fileName(g.prefix, seq, false)).exists() ||
            File(dir, fileName(g.prefix, seq, true)).exists()) seq++
        val name = fileName(g.prefix, seq, full)
        val newRow = extraRow?.let { t -> rowOf(t, JSONObject(t), seq) }

        val lines = ArrayList<String>()
        lines.add(g.head)
        lines.addAll(g.amends)
        extraAmend?.takeIf { it !in g.amendSet }?.let { lines.add(it) }
        lines.addAll(g.voids)
        extraVoid?.let { lines.add(it) }
        if (full) {
            // Merge into a copy, so the index is untouched until the file is safely on disk.
            val copy = Group(g.prefix, g.head, g.key)
            g.rows.forEach { (k, s) -> copy.rows[k] = Slot(s.winner, s.donor) }
            newRow?.let { merge(copy, it) }
            rowsOf(copy).forEach { lines.add(it.toString()) }
        } else if (extraRow != null) {
            lines.add(extraRow)
        }

        val target = File(dir, name)
        val tmp = File(dir, "$name.tmp")
        FileOutputStream(tmp).use { out ->
            out.write(lines.joinToString("\n", postfix = "\n").toByteArray(Charsets.UTF_8))
            out.fd.sync()
        }
        if (!tmp.renameTo(target)) {
            tmp.delete()
            throw IOException("could not rename ${tmp.name} to ${target.name}")
        }

        seqs[g.prefix] = seq
        prefixesOnDisk.add(g.prefix)
        newRow?.let { merge(g, it) }
        if (full) {
            g.hasFull = true
            g.completedSinceFull = 0
        } else if (newRow != null && !newRow.partial) {
            g.completedSinceFull++
        }
        return target
    }

    private fun rowOf(text: String, r: JSONObject, seq: Int): Row? {
        val log = r.optString("log").ifEmpty { return null }
        val gps = r.optJSONObject("gps")
        return Row(text, log, r.optString("ts"), r.optBoolean("partial", false), procOf(r),
            r.optLong("n", 0L), gps?.optLong("fixes", 0L) ?: 0L, seq, gps != null)
    }

    private fun readFragment(file: File): List<JSONObject> {
        val out = ArrayList<JSONObject>()
        try {
            file.forEachLine(Charsets.UTF_8) { raw ->
                val line = raw.trim()
                if (line.isEmpty()) return@forEachLine
                val rec = try { JSONObject(line) } catch (_: JSONException) { null }
                if (rec == null || !rec.has("type")) dropped++ else out.add(rec)
            }
        } catch (_: IOException) {
            // Unreadable: treat as absent. A reader that throws loses the whole history.
        }
        return out
    }

    private fun entryOf(rec: JSONObject, ts: String, fallback: TpmsCalibrationEntry? = null):
        TpmsCalibrationEntry {
        val psi = rec.optJSONObject("psi")
        return TpmsCalibrationEntry.of(
            psi = Corner.entries.associateWith { c ->
                psi?.takeIf { it.has(c.name) }?.getDouble(c.name)?.toFloat()
                    ?: fallback?.psi(c) ?: Float.NaN     // absent from the file: not a reading
            },
            ambientC = if (rec.has("temp_c")) rec.getDouble("temp_c").toFloat()
            else fallback?.ambientC ?: Float.NaN,
            setAtMs = parseTs(ts) ?: fallback?.setAtMs ?: 0L,
        )
    }

    private fun psiJson(value: (Corner) -> Float): JSONObject =
        JSONObject().apply { Corner.entries.forEach { put(it.name, num(value(it))) } }

    private fun formatTs(ms: Long): String =
        SimpleDateFormat(TS_PATTERN, Locale.US).apply { timeZone = zone }.format(ms)

    private fun parseTs(ts: String): Long? = try {
        SimpleDateFormat(TS_PATTERN, Locale.US).apply { timeZone = zone; isLenient = false }
            .parse(ts)?.time
    } catch (_: ParseException) {
        null
    }

    /**
     * What a file name says -- an ordering and grouping hint only. [canonical] is exactly the form
     * this class writes; anything else (a legacy `tpms_<ts>.jsonl`, a `... (1).jsonl` re-upload)
     * is always read, never skipped.
     */
    private class Name(val prefix: String, val seq: Int, val full: Boolean, val canonical: Boolean) {
        companion object {
            private val CANONICAL = Regex("""^tpms_(\d{8}T\d{6})_(\d{6})(_full)?\.jsonl$""")
            private val SEQ = Regex("""^tpms_(\d{8}T\d{6})_(\d+)""")
            private val PREFIX = Regex("""^tpms_(\d{8}T\d{6})""")

            fun parse(name: String): Name? {
                CANONICAL.matchEntire(name)?.let {
                    return Name(it.groupValues[1], it.groupValues[2].toInt(), it.groupValues[3].isNotEmpty(), true)
                }
                SEQ.find(name)?.let {
                    return Name(it.groupValues[1], it.groupValues[2].toIntOrNull() ?: -1, false, false)
                }
                return PREFIX.find(name)?.let { Name(it.groupValues[1], -1, false, false) }
            }
        }
    }

    companion object {
        const val SCHEMA = 2
        const val CALIBRATION = "calibration"
        const val CALIBRATION_AMEND = "calibration_amend"
        const val EPOCH_VOID = "epoch_void"
        const val PRECALIBRATION = "precalibration"
        const val DRIVE = "drive"
        const val GPS_SOURCE_PARTIAL = "partial"

        /**
         * A `_full` every this many completed rows (spec section 4). Chosen with the algorithm
         * session 2026-09-26 against measured row sizes: a `_full` grows with the epoch, so a
         * fixed fragment interval made the cost quadratic.
         */
        const val FULL_EVERY_ROWS = 256

        /** `YYYYMMDDTHHMMSS`, local time, for file names and every `ts` field. */
        const val TS_PATTERN = "yyyyMMdd'T'HHmmss"
        const val PREFIX = "tpms_"
        const val SUFFIX = ".jsonl"

        /** Name key of the precalibration group. Chosen only so it sorts first; roles come from content. */
        const val PRECALIBRATION_TS = "00000000T000000"

        fun fileName(prefix: String, seq: Int, full: Boolean) =
            "%s%s_%06d%s%s".format(PREFIX, prefix, seq, if (full) "_full" else "", SUFFIX)

        /** Dedupe precedence: completed over partial, then `proc`, then `n` / `gps.fixes`, then seq. */
        private val RANK: Comparator<Row> = Comparator { a, b ->
            val ra = a.rank(); val rb = b.rank()
            ra.indices.firstOrNull { ra[it] != rb[it] }?.let { ra[it].compareTo(rb[it]) } ?: 0
        }

        /**
         * Which rule set produced a row's numbers. Absence is resolved by **structure**, not by
         * default (spec section 4): `ratios.DEL.n` present means 2, because per-ratio counts arrived
         * with the v24 rules, and build 26 wrote v24 rows before the tag existed.
         */
        fun procOf(r: JSONObject): Int {
            if (r.has("proc") && !r.isNull("proc")) return r.optInt("proc", 1)
            val del = r.optJSONObject("ratios")?.optJSONObject("DEL")
            return if (del != null && del.has("n") && !del.isNull("n")) 2 else 1
        }

        /**
         * The capture session a drive row belongs to: `coda_20260322_185934_T3.log` ->
         * `coda_20260322_185934`. Rows are per log segment and pooled per session at ingest.
         * A row whose `log` does not have the segment form is its own session.
         */
        fun sessionOf(logName: String): String =
            SEGMENT_NAME.matchEntire(logName)?.groupValues?.get(1) ?: logName

        private val SEGMENT_NAME = Regex("""^(.+)_T\d+\.log$""")

        /**
         * Total `n` per session over [drives]. A void session (any row with a `void` reason)
         * pools to 0: the detector never uses it, so it has measured nothing against the baseline
         * and must not close the undo window.
         */
        fun pooledSessionSamples(drives: List<JSONObject>): Map<String, Long> {
            val out = LinkedHashMap<String, Long>()
            val void = HashSet<String>()
            drives.forEachIndexed { i, d ->
                val key = d.optString("log").takeIf { it.isNotEmpty() }?.let { sessionOf(it) }
                    ?: "#row$i"
                out[key] = (out[key] ?: 0L) + d.optLong("n", 0L)
                if (TpmsDetector.voidReasons(d).isNotEmpty()) void.add(key)
            }
            void.forEach { out[it] = 0L }
            return out
        }

        /**
         * A float as the decimal the user saw. `41.9f.toDouble()` is 41.900001525878906; going
         * through the float's own string gives 41.9, which is what was typed and what the
         * prototype writes.
         */
        private fun num(f: Float): Double = f.toString().toDouble()
    }
}

/**
 * Detector settings. **None of these is stored in the file** (spec section 4, invariant 1): they
 * are applied at ingest so each can be retuned against an unchanged archive. Values and meanings
 * are `Settings` in `tpms_app_prototype.py`. Every count is in drives (sessions, segments pooled),
 * never in time.
 */
data class TpmsSettings(
    /** K: drives that form the frozen baseline... */
    val learnDrives: Int = 3,
    /** ...or this many pooled samples, whichever comes later. */
    val learnMinSamples: Long = 2400,
    /** M: drives pooled into the current estimate. */
    val windowDrives: Int = 5,
    /** A drive (a session, segments pooled) below this many samples is stored but not used. */
    val minSamples: Int = 800,
    /**
     * Per-contrast floor on a pooled set (spec section 1, v24). F/R has its own, smaller count (the
     * 20 Nm cap); one F/R sample has sd 0.0029, so a mean of 5 is 2.9 psi of noise on a corner, past
     * the advisory. At 300 it is 0.38 psi. DEL and L/R clear it whenever the drive clears [minSamples].
     */
    val minNContrast: Long = 300,
    /** Outlier-reading thresholds, psi below baseline, and the lower levels that clear them. */
    val warnPsi: Double = 4.0,
    val advisePsi: Double = 2.5,
    val warnClearPsi: Double = 3.0,
    val adviseClearPsi: Double = 1.8,
    /** Consecutive drives that must agree before the state changes. */
    val confirmDrives: Int = 2,
    /** Un-announced fill: a rise in DEL psi of at least this between two windows of [stepWindow]. */
    val stepPsi: Double = 3.0,
    val stepWindow: Int = 3,
    /**
     * Fast path: WARN when the current drive ALONE reads this far below baseline on a corner, with
     * no window and no confirmation. 6 not 4: single-drive false alarms measured on the corpus
     * are 1.57 % at 4 psi, 0.79 % at 5, none observed at 6 (worst -5.63). Provisional; retune on
     * real data.
     */
    val fastWarnPsi: Double = 6.0,
    val fastMinSamples: Long = 800,
)
