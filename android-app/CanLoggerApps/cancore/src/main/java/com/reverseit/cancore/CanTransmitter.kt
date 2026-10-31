package com.reverseit.cancore

/**
 * Anything that can put a frame on a CAN bus.
 *
 * The mirror of [CanFrameSource], and deliberately the same shape of seam: the narrowest interface
 * that lets a feature transmit without knowing whether the transport underneath is gs_usb, SLCAN,
 * or a recording stub in a test. `CanPipelineManager` implements it over the bulk OUT endpoint of
 * whichever dongle owns the requested bus; `SlcanFrameSource` could later implement it over the
 * `t`/`T` commands without either being changed here.
 *
 * Nothing in this interface decides *whether* a transmission is allowed. Gating, allowlisting and
 * contention avoidance live in [PeriodicTransmitter], which is where they can be unit-tested --
 * this layer is the raw capability.
 */
interface CanTransmitter {

    /** True if [busIndex] currently has an open device with a usable transmit path. */
    fun canTransmit(busIndex: Int): Boolean

    /**
     * Put one frame on [busIndex]. Returns true if the transport accepted it.
     *
     * A true return means the frame was handed to the hardware, not that it was acknowledged on the
     * bus. Confirmation comes from the echo arriving back through [CanFrameSource.frames] with
     * `isTx = true`.
     *
     * Blocking; call from an IO context.
     */
    fun transmit(busIndex: Int, id: Int, data: ByteArray, isExtended: Boolean = false): Boolean
}
