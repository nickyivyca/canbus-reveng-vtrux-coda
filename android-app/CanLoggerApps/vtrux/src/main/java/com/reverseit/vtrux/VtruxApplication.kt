package com.reverseit.vtrux

import android.app.Application
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.ServiceConnection
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.core.content.ContextCompat
import com.reverseit.cancore.BuildConfig
import com.reverseit.cancore.CanLoggingService
import com.reverseit.cancore.CanPipelineManager
import com.reverseit.cancore.DisplayServer
import com.reverseit.cancore.GsUsbDevice
import java.io.File
import java.io.IOException

/**
 * Application-level singleton for the Vtrux background logger.
 *
 * Power state determines whether to log:
 *   POWERED   -- charger connected (truck on), logging active
 *   UNPOWERED -- no charger (truck off), logging stopped
 *
 * OTG bus power management (cutting 5V VBUS to the hub when unpowered) was
 * attempted via sysfs ufp/dfp role switching but abandoned -- see
 * canlogger-build-notes.md "OTG Bus Power -- Abandoned" for details.
 * A hardware relay on the hub's upstream USB cable is the intended solution.
 */
class VtruxApplication : Application() {

    val pipeline = CanPipelineManager()
    private var displayServer: DisplayServer? = null

    companion object {
        const val ACTION_USB_PERMISSION = "com.reverseit.vtrux.USB_PERMISSION"
        private const val USB_RESCAN_INTERVAL_MS = 2_000L
        private const val USB_RESCAN_MAX_ATTEMPTS = 45

        // After POWER_DISCONNECTED, wait this long before confirming the power loss.
        // 5 minutes: the GM interior 12V may cycle on/off while the driver is getting in
        // or starting the truck. We want to log continuously during that window and only
        // stop once the truck is clearly off. Also covers PD renegotiation transients.
        private const val POWER_SETTLE_MS = 300_000L
    }

    private val handler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // true = charger connected (truck on), false = no charger (truck off)
    @Volatile private var powered = false

    // Runs after POWER_SETTLE_MS to confirm a power disconnect was real
    private val evaluatePowerRunnable = Runnable { evaluatePowerState() }

    // --- USB rescan ---
    private var rescanAttempts = 0
    private var rescanActive = false
    private val rescanRunnable = Runnable { doRescan() }

    // Set to true by stopRescan() to abort any in-flight attemptRootOtgRecovery() thread.
    // Prevents the recovery's post-toggle doRescan() from firing (and the ufp step from
    // detaching a device that naturally re-enumerated after the recovery thread started).
    @Volatile private var recoveryAborted = false

    override fun onCreate() {
        super.onCreate()
        DebugLog.start()

        val crashFile = File(cacheDir, "last_crash.txt")
        if (crashFile.exists()) {
            DebugLog.log("CRASH", "--- crash from previous run ---")
            crashFile.forEachLine { DebugLog.log("CRASH", it) }
            DebugLog.log("CRASH", "--- end of previous crash ---")
            crashFile.delete()
        }

        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
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

        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
            addAction(Intent.ACTION_POWER_CONNECTED)
            addAction(Intent.ACTION_POWER_DISCONNECTED)
        }
        ContextCompat.registerReceiver(this, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)

        powered = readPluggedState()
        DebugLog.log("App", "Startup: powered=$powered")

        // Cancel any stale FGS notification from a previous process instance. Android keeps
        // FGS notifications alive after the process dies, so without this the old
        // "Logging | ..." notification lingers indefinitely after a process kill.
        getSystemService(NotificationManager::class.java)
            .cancel(com.reverseit.cancore.CanLoggingService.NOTIF_ID)

        // Fallback poll: ACTION_POWER_DISCONNECTED can be missed when the process is in a
        // restricted state. Every 30s we re-read the battery state and kick the timer if
        // power is gone but the broadcast was never received.
        scope.launch {
            while (true) {
                delay(30_000L)
                val plugged = readPluggedState()
                if (!plugged && powered && !handler.hasCallbacks(evaluatePowerRunnable)) {
                    DebugLog.w("App", "Power poll: unplugged detected -- starting settle timer")
                    handler.post { onPowerEvent(Intent.ACTION_POWER_DISCONNECTED) }
                }
            }
        }

        // Pick up any already-connected Innomaker dongles. LiveDisplayActivity
        // is the launcher and doesn't itself scan USB, so when the process
        // (re)starts with dongles already attached we'd otherwise wait for an
        // ATTACHED broadcast that never fires.
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        usbManager.deviceList.values
            .filter { it.vendorId == GsUsbDevice.VENDOR_ID &&
                      it.productId == GsUsbDevice.PRODUCT_ID }
            .forEach { handleAttachedDevice(it) }

        // Display Protocol WebSocket server -- companion connects to this.
        // Started early (always-on) so a client can connect even before the
        // truck powers on; the server emits status messages only until buses
        // are identified and subscriptions match live traffic.
        try {
            val srv = DisplayServer(
                port = DisplayServer.DEFAULT_PORT,
                token = BuildConfig.SYNC_TOKEN,
                rawFrames = pipeline.frames,
                identities = VtruxConstants.BUS_IDENTITIES,
            )
            srv.start()
            displayServer = srv
            DebugLog.log("App", "DisplayServer started on port ${DisplayServer.DEFAULT_PORT}")
        } catch (e: Exception) {
            DebugLog.e("App", "DisplayServer failed to start: ${e.message}", e)
        }

        DebugLog.log("App", "VtruxApplication.onCreate complete")
    }

    override fun onTerminate() {
        try { displayServer?.stop(1_000) } catch (_: Exception) {}
        displayServer = null
        pipeline.shutdown()
        super.onTerminate()
    }

    // =====================================================================
    // Power state
    // =====================================================================

    private fun readPluggedState(): Boolean {
        val sticky = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val plugged = sticky?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        return plugged != 0
    }

    /**
     * POWER_CONNECTED while unpowered: transition immediately.
     * POWER_DISCONNECTED while powered: wait [POWER_SETTLE_MS] to filter PD transients.
     */
    private fun onPowerEvent(action: String) {
        DebugLog.log("App", "Power event: $action")
        handler.removeCallbacks(evaluatePowerRunnable)

        if (action == Intent.ACTION_POWER_CONNECTED && !powered) {
            powered = true
            DebugLog.log("App", "-> POWERED")
            loggingService?.notifyPowerState(true)
        } else if (action == Intent.ACTION_POWER_DISCONNECTED && powered) {
            handler.postDelayed(evaluatePowerRunnable, POWER_SETTLE_MS)
        }
    }

    private fun evaluatePowerState() {
        val plugged = readPluggedState()
        DebugLog.log("App", "Power settled: plugged=$plugged, was powered=$powered, svc=${loggingService != null}")

        if (!plugged && powered) {
            powered = false
            val svc = loggingService
            if (svc != null) {
                DebugLog.log("App", "-> UNPOWERED via service")
                svc.notifyPowerState(false)
            } else {
                DebugLog.w("App", "-> UNPOWERED but loggingService null -- cancelling notification directly")
                getSystemService(NotificationManager::class.java)
                    .cancel(CanLoggingService.NOTIF_ID)
            }
        }
    }

    // =====================================================================
    // USB device handling
    // =====================================================================

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val device = intent.usbDevice()
                    if (granted && device != null) {
                        DebugLog.log("App", "USB permission granted: ${device.productName}")
                        onDeviceReady(device)
                    } else {
                        DebugLog.w("App", "USB permission denied")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device = intent.usbDevice()
                    if (device != null) {
                        val wasActive = pipeline.removeDevice(device)
                        if (wasActive) {
                            DebugLog.log("App", "Innomaker detached: ${device.deviceId}")
                            loggingService?.notifyBusChange()
                            startRescan()
                        } else if (!rescanActive) {
                            startRescan()
                        }
                    }
                }
                Intent.ACTION_POWER_CONNECTED,
                Intent.ACTION_POWER_DISCONNECTED -> {
                    onPowerEvent(intent.action!!)
                }
            }
        }
    }

    fun onDeviceReady(device: UsbDevice) {
        stopRescan()
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        pipeline.addDevice(usbManager, device, VtruxConstants.BITRATE_KBPS)
        startLoggingService()
    }

    /**
     * Hand an already-attached Innomaker to the pipeline, first requesting USB
     * permission if we don't hold it. Used by the onCreate scan and MainActivity,
     * both of which run when dongles are plugged in before the app process starts:
     * in that case no ATTACHED broadcast fires and permission has usually not been
     * granted yet, so calling onDeviceReady directly would fail to open the device
     * (pipeline.open() needs USB permission) and logging would never start.
     */
    fun handleAttachedDevice(device: UsbDevice) {
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        if (usbManager.hasPermission(device)) {
            onDeviceReady(device)
        } else {
            val pi = PendingIntent.getBroadcast(
                applicationContext, device.deviceId,
                Intent(ACTION_USB_PERMISSION).setPackage(packageName),
                PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            usbManager.requestPermission(device, pi)
            // Result arrives at receiver -> onDeviceReady once granted.
        }
    }

    // =====================================================================
    // USB rescan
    // =====================================================================

    private fun startRescan() {
        handler.removeCallbacks(rescanRunnable)
        rescanAttempts = 0
        rescanActive = true
        recoveryAborted = false
        handler.postDelayed(rescanRunnable, USB_RESCAN_INTERVAL_MS)
    }

    private fun stopRescan() {
        handler.removeCallbacks(rescanRunnable)
        rescanAttempts = 0
        rescanActive = false
        recoveryAborted = true  // abort any in-flight recovery thread
    }

    private fun doRescan() {
        rescanAttempts++
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        val innomakers = usbManager.deviceList.values.filter {
            it.vendorId == GsUsbDevice.VENDOR_ID && it.productId == GsUsbDevice.PRODUCT_ID
        }
        if (innomakers.isNotEmpty()) {
            DebugLog.log("App", "USB rescan attempt $rescanAttempts: found ${innomakers.size} device(s)")
            for (device in innomakers) {
                handleAttachedDevice(device)
            }
        } else if (rescanAttempts < USB_RESCAN_MAX_ATTEMPTS) {
            DebugLog.log("App", "USB rescan attempt $rescanAttempts: no devices yet")
            if (rescanAttempts == 2 || rescanAttempts == 6) {
                attemptRootOtgRecovery()
            }
            handler.postDelayed(rescanRunnable, USB_RESCAN_INTERVAL_MS)
        } else {
            DebugLog.w("App", "USB rescan gave up after $rescanAttempts attempts")
            rescanActive = false
        }
    }

    // =====================================================================
    // Hub recovery -- forces re-enumeration via root OTG role toggle
    // =====================================================================

    /**
     * Toggles the phone's USB role ufp -> (wait for hub devices to disappear) -> dfp
     * via Magisk root. This power-cycles the hub from the phone's side, forcing all
     * ports to re-enumerate. Used to recover from stuck hub states where the dongle
     * detaches and doesn't come back on its own.
     *
     * Fails gracefully on unrooted phones -- the rescan loop continues as fallback.
     */
    private fun attemptRootOtgRecovery() {
        Thread {
            try {
                val cmd =
                    "for f in /sys/class/dual_role_usb/*/mode; do [ -w \"\$f\" ] && echo ufp > \"\$f\"; done; " +
                    "for f in /sys/class/typec/*/data_role; do [ -w \"\$f\" ] && echo device > \"\$f\"; done; " +
                    "i=0; while [ \$i -lt 7 ]; do " +
                    "ls /sys/bus/usb/devices/ 2>/dev/null | grep -qE '^[0-9]+-[0-9]' || break; " +
                    "sleep 0.3; i=\$((\$i+1)); done; " +
                    "for f in /sys/class/dual_role_usb/*/mode; do [ -w \"\$f\" ] && echo dfp > \"\$f\"; done; " +
                    "for f in /sys/class/typec/*/data_role; do [ -w \"\$f\" ] && echo host > \"\$f\"; done"
                val proc = Runtime.getRuntime().exec(arrayOf("su", "-c", cmd))
                val exit = proc.waitFor()
                if (exit == 0) {
                    if (recoveryAborted) {
                        // Device was found naturally while recovery was running -- the ufp step
                        // may have disrupted the newly attached device. Start a fresh rescan to
                        // pick it back up, but don't reset rescanAttempts (stopRescan already did).
                        DebugLog.log("App", "Root OTG recovery: aborted (device found naturally), triggering rescan")
                        handler.post { startRescan() }
                    } else {
                        DebugLog.log("App", "Root OTG recovery: role toggle sent (attempt $rescanAttempts)")
                        handler.post { doRescan() }
                    }
                } else {
                    DebugLog.w("App", "Root OTG recovery: su exited $exit (attempt $rescanAttempts)")
                }
            } catch (e: IOException) {
                DebugLog.w("App", "Root OTG recovery: su not available -- ${e.message}")
            } catch (e: Exception) {
                DebugLog.w("App", "Root OTG recovery: unexpected error -- ${e.message}")
            }
        }.apply { isDaemon = true; start() }
    }

    // =====================================================================
    // Logging service
    // =====================================================================

    private fun startLoggingService() {
        val intent = Intent(this, CanLoggingService::class.java).apply {
            putExtra(CanLoggingService.EXTRA_VEHICLE_NAME, VtruxConstants.VEHICLE_NAME)
            putExtra(CanLoggingService.EXTRA_BITRATE_KBPS, VtruxConstants.BITRATE_KBPS)
            putExtra(CanLoggingService.EXTRA_LOG_DIR, VtruxConstants.LOG_DIR)
            putExtra(CanLoggingService.EXTRA_TRIGGER_MODE, CanLoggingService.TRIGGER_POWER)
        }
        startForegroundService(intent)
        bindService(intent, serviceConnection, BIND_AUTO_CREATE)
    }

    private var loggingService: CanLoggingService? = null

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            val service = (binder as CanLoggingService.LocalBinder).getService()
            service.pipeline = pipeline
            service.notifyPowerState(powered)
            loggingService = service
        }
        override fun onServiceDisconnected(name: ComponentName) {
            DebugLog.w("App", "onServiceDisconnected -- binder lost")
            loggingService = null
        }
    }

    @Suppress("DEPRECATION")
    private fun Intent.usbDevice(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        else
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
}
