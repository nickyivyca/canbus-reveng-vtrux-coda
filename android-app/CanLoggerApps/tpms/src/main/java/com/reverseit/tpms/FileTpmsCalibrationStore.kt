package com.reverseit.tpms

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * The persistent [TpmsCalibrationStore]: [TpmsEpochStore] (immutable fragments) over `CodaLogs/tpms/`, with the state
 * the settings page renders.
 *
 * Every operation runs on **one** background thread, in call order. That makes SET, UNDO and a
 * drive row landing from the logging service mutually ordered without locks, and keeps disk IO off
 * the main thread (the UI calls [set] and [undoLast] from button handlers). The flows are
 * republished from the files after each operation, so what the page shows is always what is on
 * disk, never an in-memory belief about it.
 *
 * The estimate is [TpmsDetector] replayed over the active epoch on every republish -- so after
 * each SET, UNDO, AMEND and drive row. Nothing it derives is stored.
 *
 * Process-lifetime: owned by the application, not by an activity, because drive rows arrive from
 * the logging side whether or not the UI is up.
 */
class FileTpmsCalibrationStore(dir: File, settings: TpmsSettings = TpmsSettings()) : TpmsCalibrationStore {

    private val files = TpmsEpochStore(dir, settings = settings)
    private val detector = TpmsDetector(settings)
    private val scope = CoroutineScope(
        SupervisorJob() + Executors.newSingleThreadExecutor { r ->
            Thread(r, "tpms-store").apply { isDaemon = true }
        }.asCoroutineDispatcher()
    )

    private var loggedLoad: TpmsEpochStore.LoadStats? = null

    private val _lastEntry = MutableStateFlow<TpmsCalibrationEntry?>(null)
    override val lastEntry: StateFlow<TpmsCalibrationEntry?> = _lastEntry.asStateFlow()

    private val _undoTarget = MutableStateFlow<TpmsCalibrationEntry?>(null)
    override val undoTarget: StateFlow<TpmsCalibrationEntry?> = _undoTarget.asStateFlow()

    private val _estimate = MutableStateFlow(TpmsEstimate())
    override val estimate: StateFlow<TpmsEstimate> = _estimate.asStateFlow()

    private val _storageError = MutableStateFlow<String?>(null)
    override val storageError: StateFlow<String?> = _storageError.asStateFlow()

    init {
        run("load") { }
    }

    override fun set(entry: TpmsCalibrationEntry) = run("SET") { files.set(entry) }

    override fun undoLast() = run("UNDO") { files.undo() }

    override fun amend(psi: Map<Corner, Float>, ambientC: Float) =
        run("AMEND") { files.amend(psi, ambientC) }

    /** Record a completed drive row (from the logging side) in the active epoch or precalibration. */
    fun addDrive(row: JSONObject) = run("drive row") { files.addDrive(row) }

    /**
     * The per-minute checkpoint of the open segment, as a `partial` row. Not republished: a partial
     * row carries no ratios, so the estimate cannot change, and re-running the detector every
     * minute would be work for nothing.
     */
    fun checkpoint(row: JSONObject) = run("checkpoint", republish = false) { files.checkpoint(row) }

    /**
     * Re-read the folder after something outside the store added a fragment -- the file server's
     * `PUT` of a corrected row. A full scan, so the new fragment is read whatever its name sorts
     * against the newest `_full`; queued behind any operation already running, so it is ordered
     * with the store's own writes.
     */
    fun reload() = run("reload") { files.load(fullScan = true) }

    /**
     * Every log name that already has a completed drive row. Read directly rather than on the store
     * thread: [TpmsEpochStore] is synchronized, and this only reads its index.
     */
    fun recordedLogs(): Set<String> = files.recordedLogs()

    /** The best stored GPS block for [log], for a row catch-up builds after a kill; see [TpmsEpochStore.storedGps]. */
    fun storedGps(log: String): JSONObject? = files.storedGps(log)

    /** The active epoch's SET time (same reasoning as [recordedLogs]). */
    fun epochSetAtMs(): Long? = files.current()?.calibration?.setAtMs

    /**
     * Run [op] on the store thread, then republish from disk. A failure is shown on the page rather
     * than only logged: a SET that did not reach the disk while the page looked as though it had is
     * the failure this store exists to prevent.
     */
    private fun run(what: String, republish: Boolean = true, op: () -> Unit) {
        scope.launch {
            try {
                op()
                _storageError.value = null
            } catch (e: Exception) {
                TpmsLog.e(TAG, "$what failed", e)
                _storageError.value = "$what not saved: ${e.message ?: e.javaClass.simpleName}"
            }
            if (!republish) return@launch
            try {
                publish()
            } catch (e: Exception) {
                TpmsLog.e(TAG, "reading ${files.dir} failed", e)
                _storageError.value = "Cannot read calibration files: ${e.message}"
            }
        }
    }

    private fun publish() {
        val current = files.current()
        files.lastLoad?.takeIf { it !== loggedLoad }?.let {
            loggedLoad = it
            TpmsLog.d(TAG, "store read: $it")
        }
        _lastEntry.value = current?.calibration
        _undoTarget.value = files.undoTarget()
        _estimate.value = detector.evaluate(current)
    }

    private companion object {
        const val TAG = "Tpms"
    }
}
