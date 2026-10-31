package com.reverseit.tpms

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import androidx.core.app.NotificationCompat

/**
 * Feeds GPS speed into [GpsRateAccumulator] for the TPMS common-mode channel.
 *
 * A foreground service of type `location`, separate from `CanLoggingService` (type
 * `connectedDevice`, shared with Vtrux), so that location updates continue while another app --
 * navigation, Zlink -- is in front, and so Vtrux's manifest and service are untouched.
 *
 * **Owner rule: no absolute position is ever stored.** [onLocationChanged] reads exactly five
 * values from the `Location` -- fix time, speed, speed accuracy, altitude, vertical accuracy --
 * into a [GpsRateAccumulator.Fix] and lets the `Location` go. Latitude and longitude are never
 * read, logged, or passed anywhere. Do not add a `Log` of the `Location` object: its `toString()`
 * contains the coordinates.
 *
 * Plain `LocationManager` GPS provider: the head unit is not assumed to have Play Services.
 * Whether the A007 has a GPS receiver at all is unknown until the car bringup; page 3 shows it.
 */
class GpsSpeedService : Service() {

    private val gps get() = (application as TpmsHost).gps
    private var thread: HandlerThread? = null
    private var lm: LocationManager? = null

    /** Fixes whose own time was implausible and replaced by the arrival time; logged once. */
    private var fixTimesReplaced = 0L

    private val listener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            // The fix time in the System.nanoTime() domain, which CAN frames are stamped in; see
            // GpsRateAccumulator.fixTimeNanos for the conversion and the skew guard.
            val (tNanos, replaced) = GpsRateAccumulator.fixTimeNanos(
                location.elapsedRealtimeNanos, SystemClock.elapsedRealtimeNanos(), System.nanoTime())
            if (replaced && fixTimesReplaced++ == 0L) {
                TpmsLog.d(TAG, "GPS fix time is ${(SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1_000_000} ms " +
                    "from its arrival; using arrival times (logged once)")
            }
            val o = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            gps.onFix(
                GpsRateAccumulator.Fix(
                    tNanos = tNanos,
                    speedMps = if (location.hasSpeed()) location.speed else null,
                    speedAccMps = if (o && location.hasSpeedAccuracy()) location.speedAccuracyMetersPerSecond else null,
                    altitudeM = if (location.hasAltitude()) location.altitude else null,
                    verticalAccM = if (o && location.hasVerticalAccuracy()) location.verticalAccuracyMeters else null,
                )
            )
        }

        // Implemented explicitly: they are abstract before API 30, and this head unit reports 29.
        override fun onProviderEnabled(provider: String) = gps.setState(GpsRateAccumulator.State.SEARCHING)
        override fun onProviderDisabled(provider: String) = gps.setState(GpsRateAccumulator.State.PROVIDER_OFF)
        @Deprecated("Deprecated in API 29")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    }

    private val gnss = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            var used = 0
            for (i in 0 until status.satelliteCount) if (status.usedInFix(i)) used++
            gps.setSatellites(used)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "GPS speed", NotificationManager.IMPORTANCE_LOW))
        }
        val n = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("TPMS GPS speed")
            .setContentText("Speed only - position is never recorded")
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    @SuppressLint("MissingPermission")    // checked by hasPermission() immediately above the use
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (thread != null) return START_STICKY
        if (!hasPermission()) {
            gps.setState(GpsRateAccumulator.State.NO_PERMISSION)
            stopSelf()
            return START_NOT_STICKY
        }
        val manager = getSystemService(LOCATION_SERVICE) as LocationManager
        if (LocationManager.GPS_PROVIDER !in manager.allProviders) {
            gps.setState(GpsRateAccumulator.State.NO_RECEIVER)
            TpmsLog.d(TAG, "no GPS provider on this device")
            stopSelf()
            return START_NOT_STICKY
        }
        val t = HandlerThread("tpms-gps").apply { start() }
        thread = t
        lm = manager
        manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 0L, 0f, listener, t.looper)
        manager.registerGnssStatusCallback(gnss, Handler(t.looper))
        gps.setActive(true)
        gps.setState(
            if (manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) GpsRateAccumulator.State.SEARCHING
            else GpsRateAccumulator.State.PROVIDER_OFF)
        TpmsLog.d(TAG, "GPS speed updates started")
        return START_STICKY
    }

    override fun onDestroy() {
        lm?.removeUpdates(listener)
        lm?.unregisterGnssStatusCallback(gnss)
        thread?.quitSafely()
        thread = null
        gps.setActive(false)
        super.onDestroy()
    }

    private fun hasPermission() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    companion object {
        private const val TAG = "TpmsGps"
        private const val CHANNEL_ID = "tpms_gps"
        private const val NOTIF_ID = 2      // CanLoggingService uses 1
    }
}
