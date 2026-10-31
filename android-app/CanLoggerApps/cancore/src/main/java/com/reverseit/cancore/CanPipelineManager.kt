package com.reverseit.cancore

import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
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
 *
 * Also the app's [CanTransmitter] over the same dongles. Callers should not reach this interface
 * directly for periodic output -- go through [PeriodicTransmitter], which holds the interlocks.
 */
class CanPipelineManager : CanFrameSource, CanTransmitter {

    companion object {
        private const val TAG = "CanCore"
        private const val OPEN_DEBOUNCE_MS = 4_000L
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val _frames = MutableSharedFlow<CanFrame>(extraBufferCapacity = 1024)
    override val frames: SharedFlow<CanFrame> = _frames.asSharedFlow()

    /**
     * Data and error frames, for the log writer; see [CanFrameSource.logFrames]. Buffered for a
     * writer stall: [CanFrameSource.LOG_BUFFER_FRAMES].
     */
    private val _logFrames = MutableSharedFlow<CanFrame>(extraBufferCapacity = CanFrameSource.LOG_BUFFER_FRAMES)
    override val logFrames: SharedFlow<CanFrame> = _logFrames.asSharedFlow()

    /** `tryEmit` results per flow, always counted (Bug 4); see [FlowHealth]. */
    private val framesHealth = FlowHealth.register(frames, "pipe.frames")
    private val logFramesHealth = FlowHealth.register(logFrames, "pipe.log")

    /**
     * Held while a frame is stamped **and** emitted, so the order frames leave [frames] and
     * [logFrames] is the order of their timestamps. Each dongle has its own reader thread; without this, bus 1 could stamp
     * a frame, lose the CPU to bus 0 stamping and emitting a later one, and emit second. The log
     * writer relies on this ordering: its time origin is the first frame it writes, and no later
     * frame may be earlier than that. `tryEmit` never suspends, so holding a monitor is fine.
     */
    private val stampLock = Any()

    /**
     * Route one stamped frame: [logFrames] gets every frame, [frames] only data frames. Called
     * under [stampLock]; `internal` so the split can be tested without a USB device.
     */
    internal fun emit(frame: CanFrame) {
        logFramesHealth.record(_logFrames.tryEmit(frame))
        if (!frame.isError) framesHealth.record(_frames.tryEmit(frame))
    }

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
            delay(OPEN_DEBOUNCE_MS)
            try {
                gsDevice.open()
                Log.i(TAG, "Bus $busIndex: device ${usbDevice.deviceId} (${usbDevice.productName}) open")
                gsDevice.readFrames { gsFrame ->
                    // GS_CAN_FLAG_OVERFLOW: the adapter dropped frames before this one (Bug 12).
                    if (gsFrame.flags and 0x01 != 0) FlowHealth.count("gs_usb.overflowFlag")
                    synchronized(stampLock) {
                        emit(gsFrame.toCanFrame(busIndex, System.currentTimeMillis(), System.nanoTime()))
                    }
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

    /**
     * Device owning [busIndex], or null. Bus indices are retired rather than re-used, so a stale
     * index resolves to nothing rather than to whichever dongle happens to be in that slot now.
     */
    private fun deviceForBus(busIndex: Int): GsUsbDevice? =
        activeDevices.values.firstOrNull { it.first == busIndex }?.second

    override fun canTransmit(busIndex: Int): Boolean =
        deviceForBus(busIndex)?.canTransmit == true

    override fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean): Boolean {
        val device = deviceForBus(busIndex) ?: return false
        return device.send(id, data, isExtended)
    }

    override fun activeDeviceCount(): Int = activeDevices.size

    override fun activeBusCount(): Int = nextBusIndex  // total ever assigned (for log header)

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
