package com.reverseit.tpms

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.PermissionInfo
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.telephony.TelephonyManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.sqrt

/**
 * A one-off inventory of what the head unit's hardware offers, written as a file that reaches
 * Seafile -- there is no ADB to the car, so a file is the only way to read it.
 *
 * Owner, 2026-09-26: "using the headunit's Gyro/accel if it has one, let's add a diagnostic feature
 * to the app that prints out what hardware features it sees, into the seafile directory as a
 * separate file." The question behind it: whether the head unit has a gyro or accelerometer that
 * could help separate curves, camber and load from pressure. A listed sensor is not a working one
 * -- head units often declare sensors that are absent or dead -- so every continuous sensor is also
 * sampled for a few seconds and its event rate, per-axis mean and sd, and timestamp spacing are
 * recorded (continuous and on-change sensors; an on-change one reporting nothing may simply not
 * have changed).
 *
 * Written to `CodaLogs/diag/hardware_<apk update time>.json`, once per installed APK. Being in a
 * subfolder of `CodaLogs/`, its arrival on the server is also the first evidence that SeaDrive
 * syncs subfolders -- which `CodaLogs/tpms/` depends on.
 *
 * **No position.** GNSS is described by its hardware and capabilities only; no location is read.
 */
class HardwareReport(private val context: Context, private val dir: File) {

    /** Write the report on a background thread unless this APK already has one. */
    fun writeIfMissing(sampleMs: Long = SAMPLE_MS) {
        val stamp = apkStamp()
        val out = File(dir, "hardware_$stamp.json")
        if (out.exists()) return
        Thread({
            try {
                val json = build(sampleMs)
                dir.mkdirs()
                val tmp = File(dir, out.name + ".tmp")
                tmp.writeText(json.toString(1), Charsets.UTF_8)
                if (!tmp.renameTo(out)) error("rename to ${out.name} failed")
                TpmsLog.d(TAG, "wrote ${out.absolutePath}")
            } catch (e: Throwable) {
                TpmsLog.e(TAG, "hardware report failed", e)
            }
        }, "hw-report").apply { isDaemon = true }.start()
    }

    /**
     * Schema 2 (build 28): `sensor_system`, `platform`, `cameras` and `telephony` added, and
     * `permissions` per requested permission with whether the platform defines it. Build 23 and 27's
     * reports listed no sensors although the declared features include an accelerometer and gyro;
     * these sections tell "no such hardware" from "hardware without a working driver", and say why
     * `HIGH_SAMPLING_RATE_SENSORS` read not granted.
     */
    fun build(sampleMs: Long): JSONObject {
        val sensorSystem = JSONObject()
        return JSONObject()
            .put("schema", 2)
            .put("written", fmt(System.currentTimeMillis()))
            .put("apk_updated", apkStamp())
            .put("device", device())
            .put("platform", platform())
            .put("display", display())
            .put("permissions", permissions())
            .put("features", features())
            .put("gnss", gnss())
            .put("cameras", cameras())
            .put("telephony", telephony())
            .put("sensors", sensors(sampleMs, sensorSystem))
            .put("sensor_system", sensorSystem)
    }

    private fun device() = JSONObject()
        .put("manufacturer", Build.MANUFACTURER).put("brand", Build.BRAND)
        .put("model", Build.MODEL).put("device", Build.DEVICE).put("product", Build.PRODUCT)
        .put("board", Build.BOARD).put("hardware", Build.HARDWARE)
        .put("release", Build.VERSION.RELEASE).put("sdk_int", Build.VERSION.SDK_INT)
        .put("fingerprint", Build.FINGERPRINT)
        .put("supported_abis", JSONArray(Build.SUPPORTED_ABIS.toList()))
        .apply {
            if (Build.VERSION.SDK_INT >= 31) {
                put("soc_manufacturer", Build.SOC_MANUFACTURER).put("soc_model", Build.SOC_MODEL)
            }
        }

    /**
     * The screen as the app's layouts see it. Compose lays out in dp, and the head unit's density
     * was unknown until build 23's page 3 overflowed on it (the AVD is 1024 x 600 mdpi).
     */
    private fun display(): JSONObject {
        val m = context.resources.displayMetrics
        val c = context.resources.configuration
        return JSONObject()
            .put("width_px", m.widthPixels).put("height_px", m.heightPixels)
            .put("density", m.density.toDouble()).put("density_dpi", m.densityDpi)
            .put("xdpi", m.xdpi.toDouble()).put("ydpi", m.ydpi.toDouble())
            .put("font_scale", c.fontScale.toDouble())
            .put("screen_width_dp", c.screenWidthDp).put("screen_height_dp", c.screenHeightDp)
            .put("smallest_width_dp", c.smallestScreenWidthDp)
    }

    /**
     * Every permission this APK requests: granted or not, and whether the platform defines it at
     * all, with its protection level. A permission the framework does not define can never be
     * granted -- which a "not granted" alone cannot tell from a denial. Normal permissions are granted
     * at install without a prompt; only dangerous ones prompt.
     */
    private fun permissions() = JSONObject().apply {
        val pm = context.packageManager
        val requested = runCatching {
            pm.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS).requestedPermissions
        }.getOrNull() ?: arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        for (p in requested.sorted()) {
            val info = runCatching { pm.getPermissionInfo(p, 0) }.getOrNull()
            put(p, JSONObject()
                .put("granted", context.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED)
                .put("defined", info != null)
                .put("protection", info?.let { protectionName(it) } ?: JSONObject.NULL))
        }
    }

    private fun protectionName(i: PermissionInfo): String {
        val base = if (Build.VERSION.SDK_INT >= 28) i.protection
            else @Suppress("DEPRECATION") (i.protectionLevel and PermissionInfo.PROTECTION_MASK_BASE)
        return when (base) {
            PermissionInfo.PROTECTION_NORMAL -> "normal"
            PermissionInfo.PROTECTION_DANGEROUS -> "dangerous"
            PermissionInfo.PROTECTION_SIGNATURE -> "signature"
            else -> base.toString()
        }
    }

    /**
     * What the platform says about itself. The A007 reports `SDK_INT` 29 while running Android 12
     * (a known ROM quirk), so the build properties are read directly too, along with any property
     * that mentions sensors (a sensor HAL is usually named by one).
     */
    private fun platform(): JSONObject {
        val props = getprop()
        val keep = props.filterKeys { k ->
            k.startsWith("ro.build.version.") || k.startsWith("ro.vendor.build.version.") ||
                k == "ro.product.first_api_level" || k == "ro.board.platform" ||
                k.startsWith("ro.hardware") || k.contains("sensor", ignoreCase = true)
        }
        return JSONObject()
            .put("sdk_int", Build.VERSION.SDK_INT)
            .put("release", Build.VERSION.RELEASE)
            .put("app_target_sdk", context.applicationInfo.targetSdkVersion)
            .put("props", JSONObject(keep.toSortedMap() as Map<*, *>))
            .put("props_read", props.size)
    }

    /** `getprop` output as a map; empty if the command is unavailable. */
    private fun getprop(): Map<String, String> = runCatching {
        val p = ProcessBuilder("getprop").redirectErrorStream(true).start()
        val re = Regex("^\\[(.+?)\\]: \\[(.*)\\]$")
        val out = p.inputStream.bufferedReader().readLines()
        p.waitFor()
        out.mapNotNull { re.find(it)?.let { m -> m.groupValues[1] to m.groupValues[2] } }.toMap()
    }.getOrDefault(emptyMap())

    /** Camera ids and which way each faces. No permission needed; nothing is opened. */
    private fun cameras(): JSONArray = JSONArray().apply {
        runCatching {
            val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            for (id in cm.cameraIdList) {
                val c = cm.getCameraCharacteristics(id)
                put(JSONObject().put("id", id).put("facing", when (c.get(CameraCharacteristics.LENS_FACING)) {
                    CameraCharacteristics.LENS_FACING_FRONT -> "front"
                    CameraCharacteristics.LENS_FACING_BACK -> "back"
                    CameraCharacteristics.LENS_FACING_EXTERNAL -> "external"
                    else -> "unknown"
                }))
            }
        }.onFailure { put(JSONObject().put("error", it.javaClass.simpleName + ": " + it.message)) }
    }

    /** Modem and SIM slot state only -- no identifiers (those need a permission the app does not hold). */
    private fun telephony(): JSONObject = runCatching {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
        @Suppress("DEPRECATION") val slots = tm.phoneCount
        JSONObject()
            .put("phone_type", when (tm.phoneType) {
                TelephonyManager.PHONE_TYPE_NONE -> "none"
                TelephonyManager.PHONE_TYPE_GSM -> "gsm"
                TelephonyManager.PHONE_TYPE_CDMA -> "cdma"
                TelephonyManager.PHONE_TYPE_SIP -> "sip"
                else -> tm.phoneType.toString()
            })
            .put("slots", slots)
            .put("sim_state", JSONArray((0 until slots).map { simStateName(tm.getSimState(it)) }))
    }.getOrElse { JSONObject().put("error", it.javaClass.simpleName + ": " + it.message) }

    private fun simStateName(s: Int) = when (s) {
        TelephonyManager.SIM_STATE_ABSENT -> "absent"
        TelephonyManager.SIM_STATE_READY -> "ready"
        TelephonyManager.SIM_STATE_NOT_READY -> "not_ready"
        TelephonyManager.SIM_STATE_PIN_REQUIRED -> "pin_required"
        TelephonyManager.SIM_STATE_UNKNOWN -> "unknown"
        else -> s.toString()
    }

    /** Every system feature the package manager reports, e.g. `android.hardware.sensor.gyroscope`. */
    private fun features() = JSONArray().apply {
        context.packageManager.systemAvailableFeatures
            .mapNotNull { f -> f.name?.let { it to f.version } }
            .sortedBy { it.first }
            .forEach { (name, v) -> put(if (v != 0) "$name=$v" else name) }
    }

    private fun gnss(): JSONObject {
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        return JSONObject().apply {
            put("providers", JSONArray(lm.allProviders))
            put("gps_provider_enabled", runCatching { lm.isProviderEnabled(LocationManager.GPS_PROVIDER) }.getOrNull())
            put("location_enabled", if (Build.VERSION.SDK_INT >= 28) lm.isLocationEnabled else JSONObject.NULL)
            if (Build.VERSION.SDK_INT >= 28) {
                put("hardware_model", lm.gnssHardwareModelName ?: JSONObject.NULL)
                put("hardware_year", lm.gnssYearOfHardware)
            }
            if (Build.VERSION.SDK_INT >= 30) {
                val c = lm.gnssCapabilities
                put("capabilities", c.toString())
            }
        }
    }

    // ----------------------------------------------------------------------- sensors ----

    private class Stats(val dims: Int) {
        var n = 0L
        var firstNs = 0L
        var lastNs = 0L
        var maxGapNs = 0L
        val sum = DoubleArray(dims)
        val sq = DoubleArray(dims)
        val min = DoubleArray(dims) { Double.POSITIVE_INFINITY }
        val max = DoubleArray(dims) { Double.NEGATIVE_INFINITY }
        var accuracy = -1
        var seenDims = 0

        fun add(e: SensorEvent) {
            if (n == 0L) firstNs = e.timestamp else maxGapNs = maxOf(maxGapNs, e.timestamp - lastNs)
            lastNs = e.timestamp
            n++
            seenDims = maxOf(seenDims, minOf(dims, e.values.size))
            for (i in 0 until minOf(dims, e.values.size)) {
                val v = e.values[i].toDouble()
                sum[i] += v; sq[i] += v * v
                if (v < min[i]) min[i] = v
                if (v > max[i]) max[i] = v
            }
            accuracy = e.accuracy
        }

        fun toJson(windowMs: Long): JSONObject {
            val o = JSONObject().put("events", n)
                .put("rate_hz", round(n * 1000.0 / windowMs))
                .put("accuracy", accuracy)
            if (n == 0L) return o
            if (n > 1) {
                o.put("rate_hz_by_timestamps", round((n - 1) * 1e9 / (lastNs - firstNs).coerceAtLeast(1)))
                o.put("max_gap_ms", round(maxGapNs / 1e6))
            }
            // Event timestamps should be elapsedRealtimeNanos; a large offset means another clock.
            o.put("timestamp_offset_ms", round((SystemClock.elapsedRealtimeNanos() - lastNs) / 1e6))
            val axes = JSONArray()
            for (i in 0 until seenDims) {
                val mean = sum[i] / n
                val sd = sqrt(maxOf(0.0, sq[i] / n - mean * mean))
                axes.put(JSONObject().put("mean", round(mean)).put("sd", round(sd))
                    .put("min", round(min[i])).put("max", round(max[i])))
            }
            return o.put("axes", axes)
        }
    }

    /**
     * Every sensor with its declared properties; each continuous or on-change one also sampled for [windowMs]
     * at the fastest rate, all at once on one background thread.
     */
    private fun sensors(windowMs: Long, system: JSONObject): JSONArray {
        val sm = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val list = sm.getSensorList(Sensor.TYPE_ALL)
        val stats = HashMap<Sensor, Stats>()
        val thread = HandlerThread("hw-report-sensors").apply { start() }

        // Sensors can also be registered at runtime ("dynamic"); built-in ones almost never are, but
        // this rules it out: the current dynamic list, and any that connect during the window.
        system.put("sensor_list_count", list.size)
        system.put("dynamic_discovery_supported", sm.isDynamicSensorDiscoverySupported)
        system.put("dynamic_sensors", JSONArray(sm.getDynamicSensorList(Sensor.TYPE_ALL).map { "${it.name} (${it.stringType})" }))
        val connected = java.util.Collections.synchronizedList(ArrayList<String>())
        val dynamicCb = object : SensorManager.DynamicSensorCallback() {
            override fun onDynamicSensorConnected(s: Sensor) { connected.add("${s.name} (${s.stringType})") }
        }
        sm.registerDynamicSensorCallback(dynamicCb, Handler(thread.looper))
        // Below the framework: a sensor HAL library, kernel IIO devices, input devices. Each is
        // recorded as found, empty, or not readable (SELinux), since an unreadable path proves nothing.
        system.put("hal_libraries", listDirs(listOf("/vendor/lib64/hw", "/vendor/lib/hw", "/odm/lib64/hw",
            "/system/lib64/hw", "/system/lib/hw")) { it.contains("sensor", ignoreCase = true) })
        system.put("iio_devices", readNames("/sys/bus/iio/devices") { d -> File(d, "name").readText().trim() })
        system.put("input_devices", runCatching {
            JSONArray(File("/proc/bus/input/devices").readLines()
                .filter { it.startsWith("N: Name=") }.map { it.removePrefix("N: Name=").trim('"') })
        }.getOrElse { "not readable: ${it.javaClass.simpleName}" })
        val listener = object : SensorEventListener {
            override fun onSensorChanged(e: SensorEvent) {
                synchronized(stats) { stats[e.sensor]?.add(e) }
            }
            override fun onAccuracyChanged(s: Sensor, accuracy: Int) {}
        }
        // On-change sensors (ambient temperature, light) are sampled too: most report their current
        // value on registration, which shows whether they are live. One-shot and special are not.
        val sampled = list.filter {
            it.reportingMode == Sensor.REPORTING_MODE_CONTINUOUS || it.reportingMode == Sensor.REPORTING_MODE_ON_CHANGE
        }
        try {
            synchronized(stats) { sampled.forEach { stats[it] = Stats(dimsOf(it)) } }
            sampled.forEach { sm.registerListener(listener, it, SensorManager.SENSOR_DELAY_FASTEST, Handler(thread.looper)) }
            Thread.sleep(windowMs)
        } finally {
            sm.unregisterListener(listener)
            sm.unregisterDynamicSensorCallback(dynamicCb)
            thread.quitSafely()
        }
        system.put("dynamic_connected_during_window", JSONArray(connected.toList()))
        return JSONArray().apply {
            list.forEach { s ->
                val o = JSONObject()
                    .put("name", s.name).put("vendor", s.vendor).put("version", s.version)
                    .put("type", s.type).put("string_type", s.stringType)
                    .put("reporting_mode", modeName(s.reportingMode))
                    .put("wake_up", s.isWakeUpSensor)
                    .put("resolution", s.resolution.toDouble()).put("max_range", s.maximumRange.toDouble())
                    .put("power_ma", s.power.toDouble())
                    .put("min_delay_us", s.minDelay).put("max_delay_us", s.maxDelay)
                    .put("fifo_max", s.fifoMaxEventCount)
                    .put("dynamic", s.isDynamicSensor)
                synchronized(stats) { stats[s] }?.let { o.put("sample", it.toJson(windowMs)) }
                put(o)
            }
        }
    }

    /** File names matching [keep] in each directory, or why it could not be listed. */
    private fun listDirs(dirs: List<String>, keep: (String) -> Boolean) = JSONObject().apply {
        for (d in dirs) {
            val names = runCatching { File(d).list() }.getOrNull()
            put(d, when {
                !File(d).exists() -> "missing"
                names == null -> "not readable"
                else -> JSONArray(names.filter(keep).sorted())
            })
        }
    }

    /** One value per entry of [dir] via [read], or why it could not be read. */
    private fun readNames(dir: String, read: (File) -> String): Any {
        val entries = runCatching { File(dir).listFiles() }.getOrNull()
        return when {
            !File(dir).exists() -> "missing"
            entries == null -> "not readable"
            else -> JSONArray(entries.sortedBy { it.name }.map { e ->
                "${e.name}: " + runCatching { read(e) }.getOrElse { "not readable" }
            })
        }
    }

    private fun dimsOf(s: Sensor): Int = when (s.type) {
        Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE, Sensor.TYPE_MAGNETIC_FIELD,
        Sensor.TYPE_GRAVITY, Sensor.TYPE_LINEAR_ACCELERATION -> 3
        Sensor.TYPE_ACCELEROMETER_UNCALIBRATED, Sensor.TYPE_GYROSCOPE_UNCALIBRATED,
        Sensor.TYPE_MAGNETIC_FIELD_UNCALIBRATED -> 6
        Sensor.TYPE_ROTATION_VECTOR, Sensor.TYPE_GAME_ROTATION_VECTOR,
        Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR -> 4
        else -> 3
    }

    private fun modeName(m: Int) = when (m) {
        Sensor.REPORTING_MODE_CONTINUOUS -> "continuous"
        Sensor.REPORTING_MODE_ON_CHANGE -> "on_change"
        Sensor.REPORTING_MODE_ONE_SHOT -> "one_shot"
        Sensor.REPORTING_MODE_SPECIAL_TRIGGER -> "special"
        else -> m.toString()
    }

    /** The APK's install/update time, so each new build writes one report and restarts do not. */
    private fun apkStamp(): String {
        val t = runCatching { context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime }
            .getOrDefault(0L)
        return fmt(t)
    }

    private fun fmt(ms: Long) = SimpleDateFormat(TpmsEpochStore.TS_PATTERN, Locale.US).format(Date(ms))

    private companion object {
        const val TAG = "HwReport"
        const val SAMPLE_MS = 5_000L
        fun round(x: Double) = Math.round(x * 1e4) / 1e4
    }
}
