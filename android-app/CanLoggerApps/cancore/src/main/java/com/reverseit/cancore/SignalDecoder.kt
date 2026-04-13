package com.reverseit.cancore

/**
 * Vehicle-specific CAN signal decoder interface.
 *
 * Implementations receive every incoming frame and maintain internal state.
 * The CanViewModel calls [snapshot] at 10 Hz to get a stable Map for the UI.
 *
 * Named signal values are floats (raw decoded units -- scaling for display is up to the UI layer).
 */
interface SignalDecoder {
    /** Update internal state with the incoming frame. Called on IO thread for every frame. */
    fun update(frame: CanFrame)

    /**
     * Return a snapshot of all currently-decoded signal values.
     * Called on the main thread at the GUI update rate; must be thread-safe.
     * Values are in decoded physical units (Nm, kW, %, degC, etc.).
     */
    fun snapshot(): Map<String, Float>
}
