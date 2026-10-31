package com.reverseit.p914

import android.Manifest
import android.app.Application
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.util.Log
import androidx.core.content.ContextCompat
import com.reverseit.cancore.CanLoggingService
import com.reverseit.cancore.SlcanFrameSource
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.concurrent.thread

/**
 * Owns the SLCAN source and the logging service binding.
 *
 * Two transports, deliberately behind the same code path: TCP to the replay bridge (A4b) and USB
 * CDC to the VCU (A6). Both end as an [InputStream] handed to `SlcanFrameSource.pump()`, so the
 * decode and logging path proven over TCP is bit-for-bit the one used on the car.
 *
 * The 914 has no gs_usb dongle, so there is no `CanPipelineManager` here. `SlcanFrameSource`
 * implements the `CanFrameSource` seam the logging service consumes.
 *
 * Trigger: "log while the source is attached", mapped onto the service's `TRIGGER_POWER` mode,
 * where the service is passive and acts only on `notifyPowerState()`. Nothing reads the charger.
 */
class P914Application : Application() {

    companion object {
        private const val TAG = "P914"
        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val ACTION_USB_PERMISSION = "com.reverseit.p914.USB_PERMISSION"

        /**
         * Pause between the image landing on the volume and the reset.
         *
         * Not tuned -- there is no signal to tune against, since the interface MCU reports neither
         * start nor finish of programming. Chosen to be comfortably longer than a ~340 KB image
         * takes, on the reasoning that waiting too long costs seconds and waiting too little costs
         * a target that looks bricked.
         */
        private const val FLASH_SETTLE_MS = 8_000L
    }

    enum class Transport { TCP, USB }

    val source = SlcanFrameSource()

    @Volatile var status: String = "idle"; private set
    @Volatile var bytesRead: Long = 0L; private set

    private var service: CanLoggingService? = null
    private var pumpThread: Thread? = null
    private var statsThread: Thread? = null
    private var socket: Socket? = null
    private var usb: UsbCdcSerial? = null

    @Volatile private var wantConnected = false
    @Volatile private var transport = Transport.TCP

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
    /** Main-thread only. Guards against sending trigger-inactive without a prior active. */
    private var signalledActive = false

    private val usbManager by lazy { getSystemService(Context.USB_SERVICE) as UsbManager }

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            // A detach must actively tear the connection down. bulkTransfer cannot tell a
            // detached device from an idle one -- both just return -1 -- so without this the
            // reader spins forever and a replug is never noticed.
            if (intent?.action == UsbManager.ACTION_USB_DEVICE_DETACHED) {
                val dev: UsbDevice? = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
                if (dev == null || (dev.vendorId == UsbCdcSerial.VID_MBED &&
                        dev.productId == UsbCdcSerial.PID_MBED)) {
                    Log.i(TAG, "VCU detached -- closing stream so the pump can retry")
                    status = "VCU detached"
                    runCatching { usb?.close() }
                }
                return
            }
            if (intent?.action != ACTION_USB_PERMISSION) return
            val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
            Log.i(TAG, "USB permission result: granted=$granted")
            if (granted) {
                status = "usb permission granted"
                startPump()
            } else {
                status = "usb permission DENIED"
                wantConnected = false
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        val filter = IntentFilter(ACTION_USB_PERMISSION).apply {
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        ContextCompat.registerReceiver(this, usbReceiver, filter,
            ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val svc = (binder as CanLoggingService.LocalBinder).getService()
            service = svc
            svc.pipeline = source
            Log.i(TAG, "service bound, source attached")
            if (wantConnected) startPump()
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            service = null
        }
    }

    /**
     * Whether [P914Constants.PUBLIC_LOG_DIR] is writable. API 30+ needs "All files access"; below
     * that the legacy WRITE_EXTERNAL_STORAGE grant is what counts. `isExternalStorageManager()`
     * can throw on a device misreporting its API level (seen by `:coda`), and a throw here must
     * not stop logging, so it reads as "no access".
     */
    private fun hasAllFilesAccess(): Boolean = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
                PackageManager.PERMISSION_GRANTED
        }
    } catch (e: Throwable) {
        Log.w(TAG, "all-files access check threw ${e.javaClass.simpleName}: ${e.message}")
        false
    }

    fun connect(which: Transport) {
        if (wantConnected) return
        transport = which
        wantConnected = true
        status = "starting service"

        val intent = Intent(this, CanLoggingService::class.java).apply {
            putExtra(CanLoggingService.EXTRA_VEHICLE_NAME, P914Constants.VEHICLE_NAME)
            putExtra(CanLoggingService.EXTRA_BITRATE_KBPS, P914Constants.BITRATE_KBPS)
            putExtra(CanLoggingService.EXTRA_TRIGGER_MODE, CanLoggingService.TRIGGER_POWER)
            if (hasAllFilesAccess()) {
                putExtra(CanLoggingService.EXTRA_LOG_DIR, P914Constants.PUBLIC_LOG_DIR)
            } else {
                Log.w(TAG, "no all-files access: logging to the app-private directory, " +
                    "which a sync app cannot see")
            }
        }
        startForegroundService(intent)
        bindService(intent, connection, Context.BIND_AUTO_CREATE)

        if (service != null) startPump()
    }

    /** True if permission is already held; otherwise requests it and returns false. */
    private fun ensureUsbPermission(): Boolean {
        val device = UsbCdcSerial.find(usbManager)
        if (device == null) {
            // Absent is TRANSIENT, not terminal. Clearing wantConnected here was a real bug:
            // on a detach the device is of course gone, so the first retry killed the pump loop
            // outright, status went to "idle", and a later replug had nothing left running to
            // notice it. Keep waiting instead.
            status = "waiting for VCU (0d28:0204) -- host mode? cable?"
            return false
        }
        if (usbManager.hasPermission(device)) return true

        status = "requesting usb permission"
        // Android 14 rejects FLAG_MUTABLE with an implicit Intent, so the intent must name its
        // own package while staying mutable for UsbManager to write EXTRA_DEVICE into it.
        val pi = PendingIntent.getBroadcast(
            this, 0,
            Intent(ACTION_USB_PERMISSION).setPackage(packageName),
            PendingIntent.FLAG_MUTABLE,
        )
        usbManager.requestPermission(device, pi)
        return false
    }

    fun disconnect() {
        wantConnected = false
        status = "disconnecting"
        // Closing the stream is what unblocks a pump sitting in read(); SlcanSource treats the
        // resulting IOException as end-of-stream, because a stream going away is ordinary.
        runCatching { socket?.close() }
        runCatching { usb?.close() }
        setTriggerActive(false)
    }

    private fun openStream(): InputStream {
        return if (transport == Transport.USB) {
            val device = UsbCdcSerial.find(usbManager)
                ?: throw java.io.IOException("VCU not present on the USB bus")
            val cdc = UsbCdcSerial.open(usbManager, device)
                ?: throw java.io.IOException("failed to open CDC interfaces")
            usb = cdc
            cdc.inputStream()
        } else {
            val s = Socket()
            s.connect(
                InetSocketAddress(P914Constants.BRIDGE_HOST, P914Constants.BRIDGE_PORT),
                CONNECT_TIMEOUT_MS,
            )
            socket = s
            s.getInputStream()
        }
    }

    /**
     * `CanLoggingService`'s trigger methods are **not thread-safe** -- `stopLogging()` closes the
     * writer without synchronisation, so two concurrent calls both see a non-null writer and the
     * second crashes in `writeFooter()` with "Stream closed". `:vtrux` only ever calls them from
     * the main thread (service connection callback, broadcast receiver), which hides this.
     *
     * The pump runs on its own thread, so every trigger notification is marshalled to the main
     * thread. `signalledActive` additionally ensures inactive is only ever sent after active,
     * so a failed connection attempt cannot stop a session it never started.
     */
    private fun setTriggerActive(active: Boolean) {
        mainHandler.post {
            if (active == signalledActive) return@post
            signalledActive = active
            service?.notifyPowerState(active)
            service?.notifyBusChange()
        }
    }

    /**
     * Emit link health to logcat every 10 s while streaming.
     *
     * The on-screen readout is not enough on its own: it cannot be captured from a running
     * session (the 500 ms UI tick means `uiautomator dump` never finds an idle window), and it is
     * gone the moment the activity is backgrounded. Integrity-block results are the only evidence
     * that a log is trustworthy, so they belong somewhere durable rather than only on a screen
     * nobody is looking at.
     */
    private fun startStatsLogger() {
        if (statsThread?.isAlive == true) return
        statsThread = thread(start = true, isDaemon = true, name = "slcan-stats") {
            while (wantConnected) {
                val s = source.stats
                Log.i(
                    TAG,
                    "link: frames=${s.frames} integrity=${s.integrity} csv=${s.csv} " +
                        "malformed=${s.malformed} blocks=${s.blocksChecked} " +
                        "crcBad=${s.blocksCrcBad} cntBad=${s.blocksCountBad} " +
                        "digest=%016x".format(source.digest),
                )
                Thread.sleep(10_000)
            }
        }
    }

    private fun startPump() {
        if (pumpThread?.isAlive == true) return
        pumpThread = thread(start = true, name = "slcan-pump") {
            while (wantConnected) {
                try {
                    // Re-checked every attempt, not once: Android revokes USB permission on
                    // detach, so a replug needs a fresh grant before the device can be opened.
                    if (transport == Transport.USB && !ensureUsbPermission()) {
                        Thread.sleep(2_000)
                        continue
                    }
                    status = if (transport == Transport.USB) "opening USB CDC"
                    else "connecting to ${P914Constants.BRIDGE_HOST}:${P914Constants.BRIDGE_PORT}"
                    val stream = openStream()
                    status = "streaming (${transport.name})"
                    setTriggerActive(true)
                    startStatsLogger()
                    bytesRead = source.pump(stream)
                } catch (e: Exception) {
                    Log.w(TAG, "stream ended: ${e.message}")
                    status = "disconnected: ${e.message}"
                } finally {
                    runCatching { socket?.close() }
                    runCatching { usb?.close() }
                    usb = null
                }
                setTriggerActive(false)
                if (!wantConnected) break
                status = "retrying in 2s"
                Thread.sleep(2_000)
            }
            status = "idle"
        }
    }

    /** True while the pump is meant to be running -- used to restore state after a flash. */
    val streaming: Boolean get() = wantConnected

    /**
     * Flash a firmware image to the VCU and reset it.
     *
     * Owns the whole documented sequence, because its three parts live in three places: stopping
     * the SLCAN pump (here), writing the image ([MbedFlasher]), and the reset ([UsbCdcSerial]).
     * Getting the order wrong is the failure this is built to prevent -- see the ordering note in
     * `MbedFlasher`.
     *
     * The pump is stopped first for two reasons. The reset ends the stream anyway, so there is
     * nothing to preserve; and the break needs the CDC control interface, which a running session
     * holds claimed.
     *
     * Blocking -- call from a background thread. [log] is called from that thread.
     */
    fun flashAndReset(
        treeUri: android.net.Uri,
        openSource: () -> InputStream,
        name: String,
        sizeBytes: Long,
        log: (String) -> Unit,
    ): Boolean {
        val resumeAfter = wantConnected
        if (resumeAfter) {
            log("stopping the logger...")
            disconnect()
            pumpThread?.join(5_000)
        }

        val result = try {
            openSource().use { MbedFlasher.flash(this, treeUri, it, name, sizeBytes, log) }
        } catch (e: Exception) {
            MbedFlasher.Result(false, "could not read the image: ${e.message}")
        }

        if (!result.ok) {
            log("FAILED: ${result.message}")
            if (resumeAfter) { log("restarting the logger"); connect(Transport.USB) }
            return false
        }
        log(result.message)

        // The readback above proves the FAT write landed, not that the target was programmed.
        // Resetting before programming finishes leaves the target halted with no serial output --
        // the failure that looked like a bricked board on 2026-08-13. So: wait.
        log("waiting ${FLASH_SETTLE_MS / 1000}s for programming to finish...")
        Thread.sleep(FLASH_SETTLE_MS)

        MbedFlasher.readFailure(this, treeUri)?.let {
            log("interface MCU rejected the image -- FAIL.TXT says: $it")
            if (resumeAfter) { log("restarting the logger"); connect(Transport.USB) }
            return false
        }

        val device = UsbCdcSerial.find(usbManager)
        if (device == null) {
            log("VCU is not on the bus -- cannot send the reset. Reset it by hand.")
            return false
        }
        log("sending serial BREAK to reset the target...")
        val err = UsbCdcSerial.sendBreak(usbManager, device)
        if (err != null) {
            log("reset FAILED: $err")
            log("The image is on the volume; the target just was not restarted.")
            return false
        }
        log("target reset")

        if (resumeAfter) {
            log("restarting the logger -- frames resuming is the real proof it booted")
            connect(Transport.USB)
        } else {
            log("done. Start the logger to confirm the target came back.")
        }
        return true
    }

    fun statusLine(): String {
        val st = source.stats
        return buildString {
            appendLine("status:     $status")
            appendLine("bytes:      $bytesRead")
            appendLine("frames:     ${st.frames}")
            appendLine("integrity:  ${st.integrity}")
            appendLine("csv:        ${st.csv}")
            appendLine("malformed:  ${st.malformed}")
            appendLine("blocks:     ${st.blocksChecked} checked")
            appendLine("  crc bad:  ${st.blocksCrcBad}")
            appendLine("  cnt bad:  ${st.blocksCountBad}")
            appendLine("digest:     %016x".format(source.digest))
        }
    }
}
