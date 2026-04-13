package com.reverseit.vtrux

import android.Manifest
import android.content.pm.PackageManager
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.content.Intent
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts

class MainActivity : ComponentActivity() {

    companion object {
        private const val TAG = "VtruxApp"
    }

    private val notificationPermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            Log.i(TAG, "POST_NOTIFICATIONS granted: $granted")
        }

    private val writeStoragePermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            DebugLog.log(TAG, "WRITE_EXTERNAL_STORAGE granted: $granted")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        DebugLog.log(TAG, "onCreate")

        // Request notification permission (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermissionRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        // Request storage access for the public SD card log directory.
        val needsStorageManager = try {
            val isManager = Environment.isExternalStorageManager()
            DebugLog.log(TAG, "isExternalStorageManager() = $isManager")
            !isManager
        } catch (e: Throwable) {
            DebugLog.log(TAG, "isExternalStorageManager() threw ${e.javaClass.simpleName}: ${e.message}")
            if (checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
                writeStoragePermissionRequest.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            }
            true
        }
        if (needsStorageManager) {
            try {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                        data = Uri.parse("package:$packageName")
                    }
                )
            } catch (e: Exception) {
                DebugLog.w(TAG, "storage settings intent failed: ${e.message}")
            }
        }

        // Check any already-connected Innomaker devices and hand them to the Application.
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        usbManager.deviceList.values
            .filter { it.vendorId == com.reverseit.cancore.GsUsbDevice.VENDOR_ID &&
                      it.productId == com.reverseit.cancore.GsUsbDevice.PRODUCT_ID }
            .forEach { (application as VtruxApplication).onDeviceReady(it) }

        // This activity has no UI — it exists only for first-run permission requests and
        // initial USB device scan. Finish immediately so it never appears as a blank screen.
        finish()
    }
}
