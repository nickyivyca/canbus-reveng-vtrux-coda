package com.reverseit.cancore

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.BatteryManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Foreground service that writes all frames from [CanPipelineManager] to BUSMASTER log files.
 *
 * Log lifecycle is controlled by a trigger mode set via [EXTRA_TRIGGER_MODE]:
 *
 *   TRIGGER_SCREEN ("screen") — screen on/off is the ignition proxy (Coda head unit).
 *     Screen state is tracked via ACTION_SCREEN_ON/OFF broadcast receiver AND a 5-second polling
 *     fallback, because some head units resume from suspend after the broadcast has already fired
 *     (receiver misses it). The poll detects the mismatch and corrects within 5 seconds.
 *
 *   TRIGGER_POWER ("power") — VtruxApplication is the single power-state authority. It debounces
 *     POWER_CONNECTED/DISCONNECTED events, manages OTG role switching, and calls notifyPowerState()
 *     directly. The service does NOT register power event receivers in this mode. Initial state is
 *     read from BatteryManager as a fallback before the first notifyPowerState() call arrives.
 *
 * Both conditions must be true to log: pipeline != null AND trigger is active.
 *
 * Intent extras:
 *   EXTRA_VEHICLE_NAME   (String)  -- used as log filename prefix, e.g. "coda"
 *   EXTRA_BITRATE_KBPS   (Int)    -- for log header
 *   EXTRA_TRIGGER_MODE   (String)  -- "screen" (default) or "power"
 */
class CanLoggingService : Service() {

    companion object {
        private const val TAG = "CanCore"
        private const val CHANNEL_ID = "can_logging"
        const val NOTIF_ID = 1

        const val EXTRA_VEHICLE_NAME  = "vehicle_name"
        const val EXTRA_BITRATE_KBPS  = "bitrate_kbps"
        /**
         * Optional absolute path for the log directory (e.g. "/sdcard/VtruxLogs").
         * If omitted, defaults to app-specific external storage under a
         * "{VehicleName}Logs" subfolder (e.g. /sdcard/Android/data/com.reverseit.coda/files/CodaLogs/).
         */
        const val EXTRA_LOG_DIR       = "log_dir"
        /**
         * Log start/stop trigger. "screen" (default) uses screen on/off; "power" uses USB charge
         * connect/disconnect. Pass [TRIGGER_SCREEN] or [TRIGGER_POWER].
         */
        const val EXTRA_TRIGGER_MODE  = "trigger_mode"
        const val TRIGGER_SCREEN      = "screen"
        const val TRIGGER_POWER       = "power"

        private const val MAX_SEGMENT_BYTES = 50L * 1024 * 1024        // 50 MB
        private const val MAX_SEGMENT_MS    = 5L * 60 * 1000            // 5 min
        private const val MAX_TOTAL_BYTES   = 10L * 1024 * 1024 * 1024 // 10 GB
        private const val SCREEN_POLL_MS    = 5_000L                    // poll interval

        // Filename of the segment currently being written, or null when idle. Read by
        // LogFileServer to refuse GET/DELETE on the live file. Written from the IO scope
        // and read from arbitrary server threads, hence @Volatile.
        @Volatile
        var currentSegmentName: String? = null
            private set
    }

    inner class LocalBinder : Binder() {
        fun getService(): CanLoggingService = this@CanLoggingService
    }

    private val binder = LocalBinder()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var logJob: Job? = null
    private var currentWriter: BusmasterWriter? = null
    private var segmentIndex = 0
    private var segmentStartMs = 0L
    private var vehicleName = "canlog"
    private var bitrateKbps = 500
    private var logDirOverride: String? = null
    private var triggerMode = TRIGGER_SCREEN
    private var sessionTag = ""
    private var sessionReady = false
    private var triggerActive = false
    private var receiverRegistered = false

    var segmentPolicy: LogSegmentPolicy = NoOpSegmentPolicy

    private var wakeLock: PowerManager.WakeLock? = null

    // Throttle periodic notification updates to avoid Android 13+ rate-limit (5/s).
    // stopLogging() calls updateNotificationText() directly and bypasses this.
    private var lastNotifUpdateMs = 0L

    /**
     * Called by the hosting app (e.g. VtruxApplication) to set power state. In TRIGGER_POWER
     * mode, VtruxApplication is the single authority — it debounces events, manages OTG role
     * switching, then calls this to start or stop the log. Not used in TRIGGER_SCREEN mode.
     */
    fun notifyPowerState(active: Boolean) {
        if (active) onTriggerActive() else onTriggerInactive()
    }

    /**
     * Called by the hosting app when a dongle attaches or detaches. Updates the notification
     * immediately so the user can tell whether any dongle is actually online. Without this,
     * the notification stays at the last "X.X MB" value when the dongle drops and no frames
     * are flowing to trigger the normal 500-frame update.
     */
    fun notifyBusChange() {
        if (logJob?.isActive != true) return
        val count = pipeline?.activeDeviceCount() ?: 0
        val text = if (count == 0)
            "Logging | ${sessionTimeDisplay()} | seg T$segmentIndex | waiting for dongle"
        else
            "Logging | $count dongle(s) | ${sessionTimeDisplay()} | seg T$segmentIndex"
        updateNotificationText(text)
    }

    /** Set by the hosting app via binder after the service starts. Triggers logging if trigger is active. */
    var pipeline: CanPipelineManager? = null
        set(value) {
            field = value
            // Only start if not already logging. The binder is re-delivered every time
            // onDeviceReady() calls startLoggingService(), but there is no need to restart
            // the collect loop — it will pick up frames from the same pipeline object once
            // a device starts emitting again.
            if (value != null && sessionReady && triggerActive && logJob?.isActive != true) startLogging()
        }

    // --- Trigger receiver (screen on/off or power connected/disconnected) ---

    // Screen-mode only. Power-mode trigger comes via notifyPowerState() from VtruxApplication.
    private val triggerReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_ON -> {
                    Log.i(TAG, "${intent.action} -- starting new session")
                    onTriggerActive()
                }
                Intent.ACTION_SCREEN_OFF -> {
                    Log.i(TAG, "${intent.action} -- stopping log")
                    onTriggerInactive()
                }
            }
        }
    }

    private fun onTriggerActive() {
        triggerActive = true
        // If already logging, don't reset the session. This guards against the pipeline setter
        // and notifyPowerState() both calling startLogging() in the same onServiceConnected()
        // callback sequence, which would open an orphaned T0 then immediately replace it.
        if (logJob?.isActive == true) return
        sessionTag = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        segmentIndex = 0
        if (pipeline != null && sessionReady) startLogging()
    }

    private fun onTriggerInactive() {
        triggerActive = false
        stopLogging()
    }

    private fun registerTriggerReceiver() {
        // Power mode: VtruxApplication owns all power event handling and calls notifyPowerState()
        // directly — no receiver needed here.
        if (triggerMode == TRIGGER_POWER) return
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
        }
        ContextCompat.registerReceiver(this, triggerReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    private fun initTriggerState() {
        triggerActive = if (triggerMode == TRIGGER_POWER) {
            // EXTRA_PLUGGED from the sticky ACTION_BATTERY_CHANGED broadcast updates faster than
            // BatteryManager.isCharging, which waits for charge current to flow. This handles the
            // race where power connected just before the service started.
            val sticky = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val plugged = sticky?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
            plugged != 0
        } else {
            val pm = getSystemService(POWER_SERVICE) as PowerManager
            pm.isInteractive
        }
    }

    /** Screen-mode only: poll every 5s to catch missed screen-on broadcasts on head units. */
    private fun startScreenPoll() {
        scope.launch {
            val pm = getSystemService(POWER_SERVICE) as PowerManager
            while (true) {
                delay(SCREEN_POLL_MS)
                val interactive = pm.isInteractive
                if (interactive && !triggerActive) {
                    Log.w(TAG, "Screen poll: interactive but triggerActive=false -- correcting, new session")
                    onTriggerActive()
                } else if (!interactive && triggerActive) {
                    Log.w(TAG, "Screen poll: not interactive but triggerActive=true -- correcting, stopping log")
                    onTriggerInactive()
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        // Trigger mode isn't known yet (arrives in onStartCommand). Show a generic idle message.
        startForegroundCompat(buildNotification("Waiting..."))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        vehicleName    = intent?.getStringExtra(EXTRA_VEHICLE_NAME) ?: "canlog"
        bitrateKbps    = intent?.getIntExtra(EXTRA_BITRATE_KBPS, 500) ?: 500
        logDirOverride = intent?.getStringExtra(EXTRA_LOG_DIR)
        triggerMode    = intent?.getStringExtra(EXTRA_TRIGGER_MODE) ?: TRIGGER_SCREEN
        // Only reset session state on first start (sessionReady=false). On subsequent
        // onStartCommand deliveries (e.g. onDeviceReady() calling startLoggingService() again
        // while logging is already in progress) we must NOT reset sessionTag/segmentIndex,
        // as that would rename the current log segment mid-session.
        if (!sessionReady) {
            sessionTag   = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            segmentIndex = 0
            sessionReady = true
        }

        // Register receiver and read initial trigger state once per service instance.
        // (onStartCommand may fire again via START_STICKY restart; onCreate resets the flag.)
        if (!receiverRegistered) {
            registerTriggerReceiver()
            initTriggerState()
            if (triggerMode == TRIGGER_SCREEN) startScreenPoll()
            // TRIGGER_POWER: VtruxApplication calls notifyPowerState() from onServiceConnected(),
            // which will override the initTriggerState() value once the binder connects.
            receiverRegistered = true
        }

        val idleMsg = if (triggerMode == TRIGGER_POWER) "Waiting for power..." else "Waiting for screen on..."
        // Re-assert the foreground notification now that POST_NOTIFICATIONS may have been granted
        // (the onCreate call fires before the permission dialog is answered on first run).
        // If logging is already active (logJob running), preserve the detailed notification
        // rather than overwriting it with the generic "Logging..." message.
        val notifText = if (logJob?.isActive == true) {
            "Logging  |  ${sessionTimeDisplay()}  |  seg T$segmentIndex"
        } else if (triggerActive) {
            "Logging..."
        } else {
            idleMsg
        }
        startForegroundCompat(buildNotification(notifText))

        pruneOldLogs()
        // Start immediately if pipeline is already set and trigger is already active,
        // but only if not already logging — onDeviceReady() calls startLoggingService() on
        // every attach event and we must not restart a running log session.
        if (pipeline != null && triggerActive && logJob?.isActive != true) startLogging()
        return START_REDELIVER_INTENT
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onDestroy() {
        // Only unregister in TRIGGER_SCREEN mode — in TRIGGER_POWER mode the receiver
        // is never registered (VtruxApplication calls notifyPowerState() directly).
        if (receiverRegistered && triggerMode == TRIGGER_SCREEN) {
            unregisterReceiver(triggerReceiver)
        }
        stopLogging()
        scope.cancel()
        super.onDestroy()
    }

    private fun startLogging() {
        logJob?.cancel()
        try {
            openNewSegment()
        } catch (e: Exception) {
            Log.e(TAG, "openNewSegment failed: ${e.message} -- logging disabled for this session")
            updateNotificationText("Log error: ${e.message?.take(40)}")
            return
        }
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CanLoggingService::logging")
        wakeLock?.acquire()
        logJob = scope.launch {
            pipeline?.frames?.collect { frame ->
                val writer = currentWriter ?: return@collect

                writer.writeFrame(frame)

                val elapsed = System.currentTimeMillis() - segmentStartMs
                if (writer.bytesWritten >= MAX_SEGMENT_BYTES ||
                    elapsed >= MAX_SEGMENT_MS ||
                    segmentPolicy.shouldRoll(frame)) {
                    rollSegment()
                }

                if (writer.frameCount % 500L == 0L) {
                    updateNotification(writer)
                }
            }
        }
    }

    private fun stopLogging() {
        logJob?.cancel()
        logJob = null
        currentWriter?.close()
        currentWriter = null
        currentSegmentName = null
        wakeLock?.release()
        wakeLock = null
        val idleMsg = if (triggerMode == TRIGGER_POWER) "Waiting for power..." else "Waiting for screen on..."
        updateNotificationText(idleMsg)
    }

    private fun logDir(): File {
        val dir = if (logDirOverride != null) {
            // Caller-specified path (e.g. "/sdcard/VtruxLogs") — public SD card, accessible by
            // other apps without root. Requires MANAGE_EXTERNAL_STORAGE on API 30+.
            File(logDirOverride!!)
        } else {
            // Default: app-specific external storage, no special permission needed.
            // Subfolder name derived from vehicleName ("coda" -> "CodaLogs"), so that
            // each vehicle's logs land in a clearly-named subfolder.
            val folderName = vehicleName.replaceFirstChar { it.uppercase() } + "Logs"
            File(getExternalFilesDir(null), folderName)
        }
        dir.mkdirs()
        Log.i(TAG, "logDir: ${dir.absolutePath}")
        return dir
    }

    private fun openNewSegment() {
        currentWriter?.close()
        val logDir = logDir()
        val filename = "${vehicleName}_${sessionTag}_T${segmentIndex}.log"
        val file = File(logDir, filename)
        segmentStartMs = System.currentTimeMillis()
        val writer = BusmasterWriter(
            file = file,
            numBuses = maxOf(pipeline?.activeBusCount() ?: 1, 1),
            bitrateKbps = bitrateKbps,
            sessionStartMs = segmentStartMs
        )
        writer.open()
        currentWriter = writer
        currentSegmentName = filename
        Log.i(TAG, "Logging to ${file.absolutePath}")
        updateNotificationText("Logging  |  ${sessionTimeDisplay()}  |  seg T$segmentIndex")
    }

    private fun rollSegment() {
        segmentIndex++
        openNewSegment()
        pruneOldLogs()
    }

    private fun pruneOldLogs() {
        val logDir = logDir()
        val logs = logDir.listFiles { f -> f.name.endsWith(".log") }
            ?.sortedBy { it.lastModified() }
            ?: return
        var totalBytes = logs.sumOf { it.length() }
        for (log in logs) {
            if (totalBytes <= MAX_TOTAL_BYTES) break
            totalBytes -= log.length()
            log.delete()
            Log.i(TAG, "Pruned old log: ${log.name}")
        }
    }

    // Returns "HH:mm" from sessionTag "yyyyMMdd_HHmmss", e.g. "20260322_153045" -> "15:30"
    private fun sessionTimeDisplay(): String {
        return if (sessionTag.length >= 15)
            "${sessionTag.substring(9, 11)}:${sessionTag.substring(11, 13)}"
        else sessionTag
    }

    // --- Notification ---

    private fun startForegroundCompat(notification: android.app.Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "CAN Logging", NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Background CAN bus logging"
                lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
            }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun appIconRes(): Int {
        // Prefer ic_notification (white silhouette, proper for status bar) if the vehicle
        // module provides one; fall back to ic_launcher (app icon).
        val notifId = resources.getIdentifier("ic_notification", "drawable", packageName)
        if (notifId != 0) return notifId
        val id = resources.getIdentifier("ic_launcher", "mipmap", packageName)
        return if (id != 0) id else android.R.drawable.ic_menu_save
    }

    private fun buildNotification(text: String): android.app.Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
            ?.apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP }
        val pendingIntent = launchIntent?.let {
            PendingIntent.getActivity(
                this, 0, it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("CAN Logger")
            .setContentText(text)
            .setSmallIcon(appIconRes())
            .setOngoing(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .apply { if (pendingIntent != null) setContentIntent(pendingIntent) }
            .build()
    }

    private fun updateNotification(writer: BusmasterWriter) {
        val now = System.currentTimeMillis()
        if (now - lastNotifUpdateMs < 2_000L) return
        lastNotifUpdateMs = now
        val mb = writer.bytesWritten / (1024.0 * 1024.0)
        val buses = pipeline?.activeDeviceCount() ?: 0
        val text = "$buses bus(es)  |  ${sessionTimeDisplay()}  |  seg T$segmentIndex  |  %.1f MB".format(mb)
        updateNotificationText(text)
    }

    private fun updateNotificationText(text: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIF_ID, buildNotification(text))
    }
}
