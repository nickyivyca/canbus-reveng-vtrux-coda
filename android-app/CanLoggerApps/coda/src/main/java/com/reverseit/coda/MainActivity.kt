package com.reverseit.coda

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import com.reverseit.cancore.CanLoggingService
import com.reverseit.cancore.watched
import com.reverseit.tpms.GpsRateAccumulator
import com.reverseit.tpms.GpsSpeedService

class MainActivity : ComponentActivity() {

    companion object {
        private const val TAG = "CodaApp"
        private const val ACTION_USB_PERMISSION = "com.reverseit.coda.USB_PERMISSION"
    }

    private lateinit var usbManager: UsbManager
    private val viewModel: CodaViewModel by viewModels()

    private val notificationPermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            Log.i(TAG, "POST_NOTIFICATIONS granted: $granted")
        }

    /**
     * GPS speed for the TPMS common-mode channel. Optional: denied or unavailable, the app loses
     * only that channel. Asked once at start and again from page 3's GPS line.
     */
    private val locationPermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            DebugLog.log(TAG, "location permission result: $result")
            startGpsIfPermitted()
        }

    private val writeStoragePermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            DebugLog.log(TAG, "WRITE_EXTERNAL_STORAGE granted: $granted")
        }

    private val pipeline get() = (application as CodaApplication).pipeline

    /** Frames for the display and the logger: the dongles, or the SLCAN harness in an AVD. */
    private val frameSource get() = (application as CodaApplication).frameSource

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val device  = intent.usbDevice()
                    if (granted && device != null) {
                        Log.i(TAG, "USB permission granted: ${device.productName}")
                        onDeviceReady(device)
                    } else {
                        Log.w(TAG, "USB permission denied")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    val device = intent.usbDevice()
                    if (device != null && isInnomaker(device)) {
                        Log.i(TAG, "Innomaker attached: ${device.deviceId}")
                        checkAndRequestPermission(device)
                    }
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device = intent.usbDevice()
                    if (device != null && isInnomaker(device)) {
                        Log.i(TAG, "Innomaker detached: ${device.deviceId}")
                        pipeline.removeDevice(device)
                    }
                }
            }
        }
    }

    // HorizontalPager is still experimental in the foundation version pinned by
    // Compose BOM 2024.04.01; it stabilises in foundation 1.7.
    @OptIn(ExperimentalFoundationApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        DebugLog.log(TAG, "onCreate start")

        usbManager = getSystemService(USB_SERVICE) as UsbManager
        DebugLog.log(TAG, "usbManager ok")

        // Request notification permission (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermissionRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        DebugLog.log(TAG, "notifications done")

        // Request all-files access so logs land in /sdcard/CodaLogs/.
        // NOTE: do NOT gate this on Build.VERSION.SDK_INT — the Coda head unit reports a
        // spoofed SDK_INT of 29 (Android 9) while actually running Android 12. The API level
        // check would silently skip the permission request, causing mkdirs() to fail at runtime.
        // Instead, call isExternalStorageManager() directly in a try/catch: it throws on genuine
        // pre-API-30 devices (where no permission is needed anyway), so the catch is the right
        // behaviour for those.
        val needsStorageManager = try {
            val isManager = Environment.isExternalStorageManager()
            DebugLog.log(TAG, "isExternalStorageManager() = $isManager")
            !isManager
        } catch (e: Throwable) {
            // isExternalStorageManager() doesn't exist OR device is spoofing API level
            // (e.g. A007 head unit reports SDK 29 while running Android 12).
            DebugLog.log(TAG, "isExternalStorageManager() threw ${e.javaClass.simpleName}: ${e.message}")
            // Request WRITE_EXTERNAL_STORAGE for genuine pre-API-30 devices, AND also
            // open the MANAGE_EXTERNAL_STORAGE settings page for spoofed Android 12 devices
            // where WRITE_EXTERNAL_STORAGE alone is not enough.
            if (checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
                DebugLog.log(TAG, "requesting WRITE_EXTERNAL_STORAGE (pre-API-30 or spoofed device)")
                writeStoragePermissionRequest.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            } else {
                DebugLog.log(TAG, "WRITE_EXTERNAL_STORAGE already granted")
            }
            true  // also try MANAGE_EXTERNAL_STORAGE settings — needed on spoofed Android 12
        }
        if (needsStorageManager) {
            DebugLog.log(TAG, "requesting MANAGE_EXTERNAL_STORAGE")
            try {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                        data = Uri.parse("package:$packageName")
                    }
                )
                DebugLog.log(TAG, "storage settings intent ok")
            } catch (e: Exception) {
                DebugLog.w(TAG, "storage settings intent failed: ${e.message}")
            }
        } else {
            DebugLog.log(TAG, "storage manager not needed")
        }

        // Attach a frame source to the ViewModel. Live USB frames normally, or a
        // replayed log when no dongle is present -- the emulator has no USB host
        // passthrough, so replay is the only way to exercise the display there.
        val replay = findReplayLog()
        if ((application as CodaApplication).harness != null) {
            // The harness feeds the real frame path, so the logger runs too -- start it now rather
            // than on a dongle attaching, which in an AVD never happens.
            DebugLog.log(TAG, "attaching SLCAN harness")
            viewModel.attach(frameSource.frames.watched("viewmodel"))
            startLoggingService()
        } else if (replay != null && usbManager.deviceList.values.none { isInnomaker(it) }) {
            DebugLog.log(TAG, "no dongle present; replaying ${replay.name}")
            val source = com.reverseit.cancore.ReplayCanSource(
                file = replay,
                loop = true,
                anchorIds = CodaConstants.B_CAN_ANCHOR_IDS,
            )
            viewModel.attach(source.frames())
        } else {
            DebugLog.log(TAG, "attaching live pipeline")
            viewModel.attach(frameSource.frames.watched("viewmodel"))
        }
        DebugLog.log(TAG, "frame source attached")

        // Register USB receiver
        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        ContextCompat.registerReceiver(this, usbReceiver, filter, ContextCompat.RECEIVER_EXPORTED)
        DebugLog.log(TAG, "USB receiver registered")

        // Check already-connected Innomaker devices
        usbManager.deviceList.values
            .filter { isInnomaker(it) }
            .forEach { checkAndRequestPermission(it) }
        DebugLog.log(TAG, "USB device scan done")

        if (!hasLocationPermission()) requestLocation() else startGpsIfPermitted()

        // Compose UI
        viewModel.useTpmsStore((application as CodaApplication).tpmsStore)
        DebugLog.log(TAG, "setContent start")
        setContent {
            val state by viewModel.displayState.collectAsState()
            val specs by viewModel.specsState.collectAsState()
            val lastTpmsCal by viewModel.tpmsStore.lastEntry.collectAsState()
            val tpmsEstimate by viewModel.tpmsStore.estimate.collectAsState()
            val tpmsUndoTarget by viewModel.tpmsStore.undoTarget.collectAsState()
            val tpmsStorageError by viewModel.tpmsStore.storageError.collectAsState()
            val gpsStatus by (application as CodaApplication).gps.status.collectAsState()
            // Three discrete pages. HorizontalPager snaps to a whole page by
            // default, so there is no partial-scroll resting position.
            // GreenScreenView is a bare Canvas with no gesture handling, so it
            // does not compete with the pager for the swipe.
            //
            // Page 2's buttons consume taps rather than drags, so they do not
            // fight the pager either; its one text field only takes the
            // horizontal drag while it is focused, which is also when the user
            // wants the caret rather than a page change.
            val pagerState = rememberPagerState(pageCount = { 3 })
            HorizontalPager(
                state = pagerState,
                modifier = Modifier.fillMaxSize(),
            ) { page ->
                when (page) {
                    0 -> GreenScreenView(state = state)
                    1 -> SpecsScreen(state = specs)
                    else -> SettingsScreen(
                        lastEntry = lastTpmsCal,
                        undoTarget = tpmsUndoTarget,
                        estimate = tpmsEstimate,
                        onSet = { viewModel.tpmsStore.set(it) },
                        onUndo = { viewModel.tpmsStore.undoLast() },
                        storageError = tpmsStorageError,
                        gpsStatus = gpsStatus,
                        onRequestGps = { requestLocation() },
                    )
                }
            }
        }
        DebugLog.log(TAG, "onCreate complete")
    }

    override fun onStart() {
        super.onStart()
        viewModel.setForeground(true)
        // Location may have been granted in system settings (see requestLocation) while away.
        if (hasLocationPermission()) startGpsIfPermitted()
    }

    override fun onStop() {
        super.onStop()
        viewModel.setForeground(false)
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(usbReceiver)
    }

    /**
     * First `.log` in `<externalFilesDir>/replay/`, or null.
     *
     * Push one with:
     *   adb push <log> /sdcard/Android/data/com.reverseit.coda/files/replay/
     */
    private fun findReplayLog(): java.io.File? {
        val dir = java.io.File(getExternalFilesDir(null), CodaConstants.REPLAY_DIR)
        if (!dir.isDirectory) return null
        return dir.listFiles { f -> f.isFile && f.name.endsWith(".log", ignoreCase = true) }
            ?.sortedBy { it.name }
            ?.firstOrNull()
    }

    private fun isInnomaker(device: UsbDevice) =
        device.vendorId == com.reverseit.cancore.GsUsbDevice.VENDOR_ID &&
        device.productId == com.reverseit.cancore.GsUsbDevice.PRODUCT_ID

    private fun checkAndRequestPermission(device: UsbDevice) {
        if (usbManager.hasPermission(device)) {
            onDeviceReady(device)
        } else {
            val pi = PendingIntent.getBroadcast(
                this, device.deviceId,
                Intent(ACTION_USB_PERMISSION), PendingIntent.FLAG_IMMUTABLE
            )
            usbManager.requestPermission(device, pi)
        }
    }

    private fun onDeviceReady(device: UsbDevice) {
        pipeline.addDevice(usbManager, device, CodaConstants.BITRATE_KBPS)
        startLoggingService()
    }

    private fun startLoggingService() {
        val intent = Intent(this, CanLoggingService::class.java).apply {
            putExtra(CanLoggingService.EXTRA_VEHICLE_NAME, CodaConstants.VEHICLE_NAME)
            putExtra(CanLoggingService.EXTRA_BITRATE_KBPS, CodaConstants.BITRATE_KBPS)
        }
        startForegroundService(intent).also {
            // Give the service our pipeline reference via the binder
            bindService(intent, serviceConnection, BIND_AUTO_CREATE)
        }
    }

    private fun hasLocationPermission() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private var askedLocation = false

    /**
     * Ask for location, or -- once Android has stopped showing the prompt (denied twice, or "don't
     * ask again") -- open this app's system settings page, so page 3's ALLOW never silently does
     * nothing. The owner must choose **Precise**: approximate location gives no GPS speed.
     */
    private fun requestLocation() {
        if (askedLocation && !shouldShowRequestPermissionRationale(Manifest.permission.ACCESS_FINE_LOCATION)) {
            try {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:$packageName")))
            } catch (e: Exception) {
                DebugLog.w(TAG, "app settings intent failed: ${e.message}")
            }
            return
        }
        askedLocation = true
        locationPermissionRequest.launch(
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    /** Start the GPS service while this activity is in front (Android 12 forbids it from background). */
    private fun startGpsIfPermitted() {
        val gps = (application as CodaApplication).gps
        if (!hasLocationPermission()) {
            gps.setState(GpsRateAccumulator.State.NO_PERMISSION)
            return
        }
        try {
            startForegroundService(Intent(this, GpsSpeedService::class.java))
        } catch (e: Exception) {
            DebugLog.e(TAG, "GPS service start failed", e)
        }
    }

    @Suppress("DEPRECATION")
    private fun Intent.usbDevice(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        else
            getParcelableExtra(UsbManager.EXTRA_DEVICE)

    private val serviceConnection = object : android.content.ServiceConnection {
        override fun onServiceConnected(name: android.content.ComponentName, binder: android.os.IBinder) {
            val service = (binder as CanLoggingService.LocalBinder).getService()
            service.pipeline = frameSource
        }
        override fun onServiceDisconnected(name: android.content.ComponentName) {}
    }
}
