package com.reverseit.cancore

import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

/**
 * Manages N Innomaker USB-CAN dongles and merges their frames into a single SharedFlow.
 *
 * Bus indices are assigned in insertion order (first device added = bus 0).
 * Indices are stable: removing a device does not re-number remaining devices.
 * This matches the Python can_logger.py convention.
 */
class CanPipelineManager {

    companion object {
        private const val TAG = "CanCore"
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val _frames = MutableSharedFlow<CanFrame>(extraBufferCapacity = 1024)
    val frames: SharedFlow<CanFrame> = _frames.asSharedFlow()

    // Maps UsbDevice.deviceId -> (busIndex, GsUsbDevice, read job)
    private val activeDevices = mutableMapOf<Int, Triple<Int, GsUsbDevice, Job>>()
    private var nextBusIndex = 0

    /**
     * Open [usbDevice] and start emitting its frames into [frames] with [bitrateKbps].
     * Safe to call from main thread -- USB open runs on IO dispatcher.
     * No-op if the device is already open.
     */
    fun addDevice(usbManager: UsbManager, usbDevice: UsbDevice, bitrateKbps: Int = 500) {
        if (activeDevices.containsKey(usbDevice.deviceId)) {
            Log.w(TAG, "Device ${usbDevice.deviceId} already open, ignoring addDevice")
            return
        }
        val busIndex = nextBusIndex++
        val gsDevice = GsUsbDevice(usbManager, usbDevice, bitrateKbps)

        val job = scope.launch {
            try {
                gsDevice.open()
                Log.i(TAG, "Bus $busIndex: device ${usbDevice.deviceId} (${usbDevice.productName}) open")
                gsDevice.readFrames { gsFrame ->
                    val frame = gsFrame.toCanFrame(busIndex, System.currentTimeMillis())
                    _frames.tryEmit(frame)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Bus $busIndex: device error: ${e.message}", e)
            } finally {
                gsDevice.close()
                activeDevices.remove(usbDevice.deviceId)
                Log.i(TAG, "Bus $busIndex: device ${usbDevice.deviceId} removed from active set")
            }
        }

        activeDevices[usbDevice.deviceId] = Triple(busIndex, gsDevice, job)
    }

    /**
     * Close [usbDevice] and remove it from the active set.
     * Returns true if the device was active and was removed; false if it was unknown
     * (e.g. a device that failed to open, or a phantom detach event from the hub).
     * Its busIndex slot is retired (not re-used for the session).
     */
    fun removeDevice(usbDevice: UsbDevice): Boolean {
        val (busIndex, gsDevice, job) = activeDevices[usbDevice.deviceId] ?: return false
        Log.i(TAG, "Bus $busIndex: closing device ${usbDevice.deviceId}")
        gsDevice.close()
        job.cancel()
        activeDevices.remove(usbDevice.deviceId)
        return true
    }

    fun activeDeviceCount(): Int = activeDevices.size

    fun activeBusCount(): Int = nextBusIndex  // total ever assigned (for log header)

    /** Close all devices and cancel the coroutine scope. Call when the app is shutting down. */
    fun shutdown() {
        activeDevices.values.forEach { (_, gsDevice, job) ->
            gsDevice.close()
            job.cancel()
        }
        activeDevices.clear()
        scope.cancel()
    }
}
