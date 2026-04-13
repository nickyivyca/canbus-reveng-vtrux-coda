package com.reverseit.canreader

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "CanReader"
        private const val ACTION_USB_PERMISSION = "com.reverseit.canreader.USB_PERMISSION"
    }

    private lateinit var usbManager: UsbManager
    private var gsUsbDevice: GsUsbDevice? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val device = intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)
                    if (granted && device != null) {
                        Log.i(TAG, "USB permission granted for ${device.productName}")
                        openCanDevice(device)
                    } else {
                        Log.w(TAG, "USB permission denied")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    val device = intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)
                    if (device != null && isInnomaker(device)) {
                        Log.i(TAG, "Innomaker attached")
                        checkAndRequestPermission(device)
                    }
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device = intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)
                    if (device != null && isInnomaker(device)) {
                        Log.i(TAG, "Innomaker detached")
                        gsUsbDevice?.close()
                        gsUsbDevice = null
                    }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "CAN Reader started")

        usbManager = getSystemService(USB_SERVICE) as UsbManager

        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        // RECEIVER_EXPORTED required on API 33+ when a custom (non-system) action is in the filter,
        // because the USB permission broadcast is sent from UsbManager (outside our process).
        ContextCompat.registerReceiver(this, usbReceiver, filter, ContextCompat.RECEIVER_EXPORTED)

        // Check if the Innomaker is already connected
        findInnomaker()?.let {
            Log.i(TAG, "Innomaker found on startup: ${it.productName}")
            checkAndRequestPermission(it)
        } ?: Log.i(TAG, "No Innomaker found on startup -- waiting for attach")
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(usbReceiver)
        gsUsbDevice?.close()
        scope.cancel()
    }

    private fun isInnomaker(device: UsbDevice) =
        device.vendorId == GsUsbDevice.VENDOR_ID && device.productId == GsUsbDevice.PRODUCT_ID

    private fun findInnomaker(): UsbDevice? =
        usbManager.deviceList.values.find { isInnomaker(it) }

    private fun checkAndRequestPermission(device: UsbDevice) {
        if (usbManager.hasPermission(device)) {
            openCanDevice(device)
        } else {
            val pi = PendingIntent.getBroadcast(
                this, 0, Intent(ACTION_USB_PERMISSION), PendingIntent.FLAG_IMMUTABLE
            )
            usbManager.requestPermission(device, pi)
        }
    }

    private fun openCanDevice(device: UsbDevice) {
        scope.launch {
            try {
                val gs = GsUsbDevice(usbManager, device)
                gs.open()
                gsUsbDevice = gs
                gs.readFrames { frame ->
                    Log.i(TAG, "CAN RX: id=0x%03X dlc=%d data=[%s]%s".format(
                        frame.arbitrationId,
                        frame.dlc,
                        frame.dataHex(),
                        if (frame.isExtended) " EXT" else ""
                    ))
                }
            } catch (e: Exception) {
                Log.e(TAG, "CAN device error: ${e.message}", e)
            }
        }
    }
}
