package com.reverseit.coda

import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.util.Log
import androidx.core.content.ContextCompat
import com.reverseit.cancore.BuildConfig
import com.reverseit.cancore.BusIdentity
import com.reverseit.cancore.BusIdentityResolver
import com.reverseit.cancore.CanFrameSource
import com.reverseit.cancore.CanLoggingService
import com.reverseit.cancore.CanPipelineManager
import com.reverseit.cancore.CanTransmitter
import com.reverseit.cancore.FlowHealth
import com.reverseit.cancore.LogFileServer
import com.reverseit.cancore.PeriodicTransmitter
import com.reverseit.cancore.SlcanBusGroup
import com.reverseit.cancore.watched
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import com.reverseit.tpms.DriveRowProducer
import com.reverseit.tpms.WheelRatioExtractor
import com.reverseit.tpms.FileTpmsCalibrationStore
import com.reverseit.tpms.GpsRateAccumulator
import com.reverseit.tpms.HardwareReport
import com.reverseit.tpms.LampMode
import com.reverseit.tpms.TpmsLampPolicy
import com.reverseit.tpms.TpmsLampSlot
import com.reverseit.tpms.SegmentWatcher
import com.reverseit.tpms.TpmsHost
import com.reverseit.tpms.TpmsLog
import java.io.File
import org.json.JSONObject

class CodaApplication : Application(), TpmsHost {
    val pipeline = CanPipelineManager()
    private var fileServer: LogFileServer? = null

    /**
     * The emulator harness, when `debug.coda.slcan` names its ports (see [SlcanHarness]); null
     * otherwise, and always null on the car, which has no ADB to set the property. Decided once,
     * first thing in [onCreate], before anything reads [frameSource] or [transmitter].
     */
    var harness: SlcanBusGroup? = null
        private set

    /**
     * Where every consumer takes frames from: the dongles, or in an AVD the harness standing in
     * for them. With the harness off this is [pipeline] itself, so the car path is unchanged.
     */
    val frameSource: CanFrameSource get() = harness ?: pipeline

    private val canTransmitter: CanTransmitter get() = harness ?: pipeline

    /**
     * The app's only route onto a vehicle bus. See [PeriodicTransmitter] for the interlocks. One
     * slot is registered, the `0x600` TPMS lamp ([registerTpmsLamp]), and the transmitter is enabled
     * only by [CodaConstants.TPMS_LAMP_TX_ON_CAR] (true from build 31, the RCU removed) or the
     * emulator harness. The contention guard still holds the slot silent while an RCU is heard.
     */
    val transmitter by lazy {
        PeriodicTransmitter(canTransmitter, allowedIds = CodaConstants.TX_ALLOWED_IDS)
    }

    /**
     * Resolves which physical dongle is on B CAN, by watching for the B CAN anchor IDs.
     *
     * Required before anything transmits. Dongle insertion order decides physical bus indices and
     * is never stable across sessions, so a hardcoded index would eventually put a B CAN frame on
     * D CAN or on whatever else happened to be plugged in first. Pass [bCanBusIndex] to
     * [PeriodicTransmitter.register] rather than a constant.
     */
    val busResolver = BusIdentityResolver(
        listOf(
            BusIdentity(
                name = CodaConstants.BUS_B_CAN,
                // Exclusive anchors, not CodaConstants.B_CAN_ANCHOR_IDS -- three of those are
                // gateway-rebroadcast onto D CAN and so cannot tell the two buses apart. See
                // CodaConstants.B_CAN_EXCLUSIVE_IDS.
                anchorIds = CodaConstants.B_CAN_EXCLUSIVE_IDS,
            )
        )
    )

    /** Physical bus index carrying B CAN, or null while still unidentified. */
    fun bCanBusIndex(): Int? = busResolver.assignments.value[CodaConstants.BUS_B_CAN]

    private val appScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    /**
     * The indirect-TPMS store, immutable fragments in `CodaLogs/tpms/` -- a subfolder of the log
     * directory, which keeps log pruning and the companion's pull-then-DELETE away from it (see
     * [CodaConstants.TPMS_DIR]). Process-lifetime so drive rows can land without a UI.
     */
    val tpmsStore by lazy { FileTpmsCalibrationStore(File(logDir(), CodaConstants.TPMS_DIR)) }

    /**
     * Turns each closed CAN log segment into one TPMS drive row. Fed by [segmentWatcher], and on
     * start catches up on segments that closed while the process was not there to see them.
     */
    val driveRows by lazy {
        DriveRowProducer(
            logDir = logDir(),
            sink = { tpmsStore.addDrive(it) },
            recordedLogs = { tpmsStore.recordedLogs() },
            activeSegment = { CanLoggingService.currentSegmentName },
            // A live close has the complete block; otherwise (kill, power cut, catch-up) the best
            // one the per-minute partial rows saved in the store.
            gpsFor = { name -> gps.take(name) ?: tpmsStore.storedGps(name) ?: legacySnapshot(name) },
            epochSetAtMs = { tpmsStore.epochSetAtMs() },
        )
    }

    /**
     * GPS speed paired with wheel speed, per log segment -- the TPMS common-mode channel. Fed CAN
     * frames below and GPS fixes by [GpsSpeedService]; speed only, never position.
     */
    override val gps = GpsRateAccumulator(currentSegment = { CanLoggingService.currentSegmentName })

    /**
     * Notices each closed log segment from the logging service's published segment name -- no hook
     * in the shared logging code. The GPS block is parked *before* the drive-row producer is handed
     * the file, so the row finds it.
     */
    private val segmentWatcher = SegmentWatcher(
        current = { CanLoggingService.currentSegmentName },
        onClosed = { name ->
            gps.closeSegment(name)
            driveRows.onSegmentClosed(File(logDir(), name))
        },
    )

    /**
     * Bug 4 instrumentation, debuggable builds only (plan `tryemit-drops.md` Step 1.4): collector
     * measurements to logcat tag `TryEmit` every 2 s, and the stall hook
     * `am broadcast -a $ACTION_DEBUG_STALL --es target <collector> --ei ms <ms> -p <package>`.
     * Runs before anything subscribes, so every collector is measured. The frame-loss counts
     * themselves are on in every build: `CanLoggingService` starts the reporter (every 10 s) if
     * this has not.
     */
    private fun startFlowHealth() {
        FlowHealth.enabled = true
        FlowHealth.start({ Log.i("TryEmit", it) })
        // Exported: the broadcast comes from adb's shell uid. Android 14 requires the flag.
        ContextCompat.registerReceiver(this, object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val target = intent.getStringExtra("target") ?: return
                val ms = intent.getIntExtra("ms", 0).toLong()
                Log.i("TryEmit", "stall requested: $target ${ms}ms")
                FlowHealth.requestStall(target, ms)
            }
        }, IntentFilter(ACTION_DEBUG_STALL), ContextCompat.RECEIVER_EXPORTED)
        DebugLog.log("App", "FlowHealth instrumentation ON (debuggable build)")
    }

    /** Mirrors CanLoggingService's default log directory for "coda". */
    private fun logDir() = File(getExternalFilesDir(null), "CodaLogs")

    override fun onCreate() {
        super.onCreate()
        DebugLog.start()
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) startFlowHealth()
        SlcanHarness.configuredPorts().takeIf { it.isNotEmpty() }?.let { ports ->
            harness = SlcanHarness.create(ports).also { it.start() }
            DebugLog.log("App", "SLCAN harness ON (${SlcanHarness.PROPERTY}): buses 0..${ports.size - 1} on ports $ports")
        }
        TpmsLog.sink = { tag, msg, e -> if (e == null) DebugLog.log(tag, msg) else DebugLog.e(tag, msg, e) }

        // Local file server — companion phone pulls completed log files over the head unit's
        // hotspot. Listens on every interface; the AP interface is what the phone reaches.
        // Log dir mirrors CanLoggingService default for "coda".
        val logDir = File(getExternalFilesDir(null), "CodaLogs")
        fileServer = LogFileServer(
            dir = logDir,
            port = 9877,
            token = BuildConfig.SYNC_TOKEN,
            vehicleName = "coda",
            // PUT places corrected TPMS fragments (and nothing else); the store then re-reads.
            putDir = CodaConstants.TPMS_DIR,
            onPut = { tpmsStore.reload() },
            isActiveSegment = { name -> CanLoggingService.currentSegmentName == name }
        ).also { it.startServer() }
        DebugLog.log("App", "LogFileServer started on 9877, dir=${logDir.absolutePath}")

        // One inventory of the head unit's sensors per installed APK, into CodaLogs/diag/ so it
        // reaches Seafile (no ADB to the car). Samples sensors for a few seconds off the main thread.
        HardwareReport(this, File(logDir, CodaConstants.DIAG_DIR)).writeIfMissing()

        // Replay any crash log from the previous run before setting up the new handler
        val crashFile = File(cacheDir, "last_crash.txt")
        if (crashFile.exists()) {
            DebugLog.log("CRASH", "--- crash from previous run ---")
            crashFile.forEachLine { DebugLog.log("CRASH", it) }
            DebugLog.log("CRASH", "--- end of previous crash ---")
            crashFile.delete()
        }

        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            // Write to file first — survives process death
            try {
                val sb = StringBuilder("Thread: ${thread.name}\n")
                var t: Throwable? = throwable
                var depth = 0
                while (t != null && depth < 8) {
                    sb.append("caused by ${t.javaClass.name}: ${t.message}\n")
                    t.stackTrace.take(20).forEach { sb.append("  at $it\n") }
                    t = t.cause
                    depth++
                }
                crashFile.writeText(sb.toString())
            } catch (_: Exception) {}
            DebugLog.e("CRASH", "Uncaught on ${thread.name}", throwable)
            Thread.sleep(300)
            defaultHandler?.uncaughtException(thread, throwable)
        }

        // Feed the bus resolver and the transmitter's contention guard, and run its schedule. All
        // of it is cheap while the transmitter is disabled: the loop sleeps
        // PeriodicTransmitter.IDLE_SLEEP_MS, and observe() drops every frame whose ID is outside
        // the allowlist.
        appScope.launch {
            frameSource.frames.watched("app-observers").collect { frame ->
                busResolver.observe(frame)
                transmitter.observe(frame)
                gps.observe(frame)
            }
        }
        registerTpmsLamp()
        appScope.launch {
            transmitter.runLoop(sleep = { delay(it) })
        }
        // Which physical bus is B CAN, each time that changes -- the one fact anything that
        // transmits depends on, and otherwise invisible.
        appScope.launch {
            busResolver.assignments.collect { DebugLog.log("App", "bus identity: $it") }
        }

        driveRows.catchUp()
        segmentWatcher.start(appScope)
        appScope.launch {
            while (true) {
                delay(TPMS_CHECKPOINT_MS)
                try {
                    checkpointOpenSegment()
                } catch (e: Exception) {
                    DebugLog.e("App", "TPMS checkpoint failed", e)
                }
            }
        }

        DebugLog.log("App", "CodaApplication.onCreate complete")
    }

    /**
     * Harness only: a lamp mode forced from `debug.coda.tpms_lamp` (off / steady / flash), so each
     * mode can be exercised in the AVD without first making the detector warn. Null = the detector
     * decides. Never read on the car: only polled while [harness] is on.
     */
    @Volatile
    private var lampOverride: LampMode? = null

    /**
     * The `0x600` lamp-hold slot (prototype, plan `coda-slcan-harness-0x600.md` Step 2). Registered
     * in every build; transmitting only when [CodaConstants.TPMS_LAMP_TX_ON_CAR] is true (from
     * build 31) or the emulator harness is on. On B CAN by content,
     * at the RCU's own cadence, lamp state from the detector's current estimate.
     */
    private fun registerTpmsLamp() {
        TpmsLampSlot.register(
            transmitter,
            id = CodaConstants.ID_RCU_STATUS,
            periodMs = CodaConstants.RCU_STATUS_PERIOD_MS,
            busIndex = ::bCanBusIndex,
            mode = { lampOverride ?: TpmsLampPolicy.mode(tpmsStore.estimate.value.state) },
        )
        transmitter.enabled = CodaConstants.TPMS_LAMP_TX_ON_CAR || harness != null
        DebugLog.log("App", "TPMS lamp slot registered; transmitter " +
            if (transmitter.enabled) "ENABLED (${if (harness != null) "harness" else "TPMS_LAMP_TX_ON_CAR"})" else "disabled")
        // Slot state changes (GATED / BUS_UNRESOLVED / CONTENDED / ACTIVE ...) are the only way to
        // see from the log why the lamp is or is not being held.
        appScope.launch {
            var last: Any? = null
            while (true) {
                val state = transmitter.states()[TpmsLampSlot.KEY]
                if (state != last) {
                    DebugLog.log("App", "TPMS lamp slot: $state (sent ${transmitter.sentCounts()[TpmsLampSlot.KEY]})")
                    last = state
                }
                if (harness != null) lampOverride = readLampOverride()
                delay(LAMP_POLL_MS)
            }
        }
    }

    private fun readLampOverride(): LampMode? = runCatching {
        val p = ProcessBuilder("getprop", LAMP_OVERRIDE_PROPERTY).redirectErrorStream(true).start()
        val v = p.inputStream.bufferedReader().readText().trim()
        p.waitFor()
        LampMode.values().firstOrNull { it.name.equals(v, ignoreCase = true) }
    }.getOrNull()

    /**
     * Build 27/28 kept GPS snapshots in internal storage instead. The segment that was open when
     * this build was installed has its last snapshot there and nowhere else, so catch-up reads it
     * once. Removable once every head unit has run a fragment-store build.
     */
    private fun legacySnapshot(name: String): JSONObject? {
        val f = File(File(filesDir, "gps_snapshots"), "$name.json")
        if (!f.isFile) return null
        return runCatching { JSONObject(f.readText()) }.getOrNull().also { f.delete() }
    }

    /** The open segment's `ts`, read once from its header (the name alone gives only the session's). */
    private var checkpointTs: Pair<String, String>? = null

    /**
     * Write the open segment's partial row -- its GPS block so far -- as a store fragment (spec
     * section 4). **Unconditional** while a segment is open, GPS or not: skipping when nothing
     * changed is a filter whose failure mode is suppressing a write, silently, in the losing
     * direction. A kill or power cut then loses at most [TPMS_CHECKPOINT_MS] of GPS, and what was
     * saved is already on its way to the server rather than only on the head unit.
     */
    private fun checkpointOpenSegment() {
        val name = CanLoggingService.currentSegmentName ?: return
        val ts = checkpointTs?.takeIf { it.first == name }?.second
            ?: (WheelRatioExtractor.readStartTs(File(logDir(), name))
                ?: DriveRowProducer.SegmentName.parse(name)?.sessionTs)
                ?.also { checkpointTs = name to it }
            ?: return
        val block = gps.snapshot()?.takeIf { it.first == name }?.second
        tpmsStore.checkpoint(DriveRowProducer.partialRow(name, ts, block))
    }

    private companion object {
        /** Partial-row cadence: how much GPS a segment ending in a kill or power cut can lose. */
        const val TPMS_CHECKPOINT_MS = 60_000L

        const val LAMP_POLL_MS = 2_000L
        const val LAMP_OVERRIDE_PROPERTY = "debug.coda.tpms_lamp"

        /** Bug 4 stall hook; see [startFlowHealth]. */
        const val ACTION_DEBUG_STALL = "com.reverseit.cancore.DEBUG_STALL"
    }

    override fun onTerminate() {
        appScope.cancel()
        harness?.stop()
        pipeline.shutdown()
        super.onTerminate()
    }
}
