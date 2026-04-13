package com.reverseit.vtrux

import android.app.PendingIntent
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity

/**
 * Invisible activity that handles ACTION_USB_DEVICE_ATTACHED.
 *
 * Android requires an Activity to receive USB_DEVICE_ATTACHED via manifest intent-filter.
 * This activity does the minimum needed (request permission or hand off to Application),
 * then immediately finishes so the user never sees it. The logging service starts in the
 * background via VtruxApplication.onDeviceReady().
 */
class UsbLaunchActivity : ComponentActivity() {

    companion object {
        private const val TAG = "VtruxUsb"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val device = intent.usbDevice()
        if (device != null && isInnomaker(device)) {
            DebugLog.log(TAG, "USB attached: ${device.productName}")
            checkAndRequestPermission(device)
        }

        finish()
    }

    private fun isInnomaker(device: UsbDevice) =
        device.vendorId == com.reverseit.cancore.GsUsbDevice.VENDOR_ID &&
        device.productId == com.reverseit.cancore.GsUsbDevice.PRODUCT_ID

    private fun checkAndRequestPermission(device: UsbDevice) {
        val usbManager = getSystemService(USB_SERVICE) as UsbManager
        if (usbManager.hasPermission(device)) {
            (application as VtruxApplication).onDeviceReady(device)
        } else {
            val pi = PendingIntent.getBroadcast(
                applicationContext, device.deviceId,
                Intent(VtruxApplication.ACTION_USB_PERMISSION).setPackage(packageName),
                PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            usbManager.requestPermission(device, pi)
            // Result arrives at VtruxApplication.usbReceiver — this activity is already gone.
        }
    }

    @Suppress("DEPRECATION")
    private fun Intent.usbDevice(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        else
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
}
