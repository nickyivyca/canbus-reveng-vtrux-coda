package com.reverseit.companion

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.util.Log
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

private const val TAG = "SyncEngine"
private const val INDEX_FILE_NAME = ".codacompanion-synced.json"

/**
 * Headless sync runner. One call to [runSync] performs a single end-to-end pass:
 *   1. Verify the phone is on the configured SSID and has a usable WiFi gateway.
 *   2. Probe `/health` to confirm the head unit is reachable and authed.
 *   3. List `/files` and pull every `complete=true` file not already in the target folder.
 *      Streams to a private cache file, verifies byte count, copies into the SAF tree URI,
 *      then DELETEs server-side. SeaDrive never sees a partial file because the cache copy
 *      is internal-only.
 *   4. Returns a [SyncResult] with per-file outcomes for the UI to render.
 *
 * Synchronous from the caller's POV (suspend on Dispatchers.IO). For Phase 2 manual sync this
 * is enough; Phase 3 will wrap this in WorkManager + foreground service.
 */
class SyncEngine(private val context: Context) {

    suspend fun runSync(
        settings: CompanionSettings,
        onProgress: (String) -> Unit = {}
    ): SyncResult = withContext(Dispatchers.IO) {
        val events = mutableListOf<String>()
        fun log(msg: String) { Log.i(TAG, msg); events += msg; onProgress(msg) }

        val currentSsid = WifiInfo.currentSsid(context)
        if (currentSsid == null) {
            return@withContext SyncResult(false, "No WiFi connection (or location permission missing)", events, emptyList(), emptyList())
        }
        if (currentSsid != settings.ssid) {
            return@withContext SyncResult(false, "Connected to '$currentSsid', expected '${settings.ssid}'", events, emptyList(), emptyList())
        }
        log("On WiFi '$currentSsid'")

        val gateway = WifiInfo.gatewayIp(context)
        if (gateway == null || gateway == "0.0.0.0") {
            return@withContext SyncResult(false, "No WiFi gateway found", events, emptyList(), emptyList())
        }
        log("Gateway $gateway")

        // Force HTTP via the WiFi network, not the cellular interface. Without this, when
        // mobile data is on, Android may route the request through cellular (CGNAT 100.x.x.x)
        // which can't reach the head unit's local-only subnet. Network.openConnection() pins
        // each connection to a specific transport.
        val wifiNet = WifiInfo.findWifiNetwork(context)
        if (wifiNet == null) {
            return@withContext SyncResult(false, "No active non-VPN WiFi network found", events, emptyList(), emptyList())
        }
        log("WiFi network handle acquired")

        val targetUri = settings.targetFolderUri
            ?: return@withContext SyncResult(false, "No target folder configured", events, emptyList(), emptyList())
        val targetTree = DocumentFile.fromTreeUri(context, android.net.Uri.parse(targetUri))
        if (targetTree == null || !targetTree.canWrite()) {
            return@withContext SyncResult(false, "Target folder not writable (was it deleted or revoked?)", events, emptyList(), emptyList())
        }

        val base = "http://$gateway:${settings.port}"
        val auth = "Bearer ${settings.token}"
        log("Base $base, token first8=${settings.token.take(8)}, len=${settings.token.length}")

        val healthRes = httpGet(URL("$base/health"), auth, wifiNet)
        if (healthRes.body == null) {
            val why = if (healthRes.error != null) "exception: ${healthRes.error}"
                      else "HTTP ${healthRes.status}"
            return@withContext SyncResult(false, "Health probe failed ($why)", events, emptyList(), emptyList())
        }
        log("Health: ${healthRes.body}")

        val listRes = httpGet(URL("$base/files"), auth, wifiNet)
        if (listRes.body == null) {
            val why = if (listRes.error != null) "exception: ${listRes.error}"
                      else "HTTP ${listRes.status}"
            return@withContext SyncResult(false, "Listing failed ($why)", events, emptyList(), emptyList())
        }
        val arr = JSONArray(listRes.body)
        log("Listed ${arr.length()} file(s)")

        val pulled = mutableListOf<PulledFile>()
        val skipped = mutableListOf<SkippedFile>()

        // Persistent "already pulled" index. Lives inside the SAF target folder so it survives
        // companion-app reinstall (user re-picks the same folder) AND "Delete local copies"
        // (which only deletes .log files). Prevents re-pulling a file that was already pushed
        // to SeaDrive but locally deleted to free phone storage.
        val syncedIndex = readSyncedIndex(targetTree)
        if (syncedIndex.isNotEmpty()) log("Index: ${syncedIndex.size} previously-synced name(s)")

        // Pre-filter so progress counts reflect actual work, not server-side total.
        val candidates = (0 until arr.length()).map { arr.getJSONObject(it) }
            .filter { it.getBoolean("complete") }
        val toFetch = candidates.filter { obj ->
            val name = obj.getString("name")
            name !in syncedIndex && targetTree.findFile(name) == null
        }
        val alreadyHave = candidates.size - toFetch.size
        if (alreadyHave > 0) log("Already have $alreadyHave file(s) locally or indexed; skipping")
        log("To fetch: ${toFetch.size} file(s)")

        // Categorize skips: active vs in-folder vs in-index.
        for (i in 0 until arr.length()) {
            val obj = arr.getJSONObject(i)
            val name = obj.getString("name")
            if (!obj.getBoolean("complete")) {
                skipped += SkippedFile(name, "active segment")
            } else if (targetTree.findFile(name) != null) {
                skipped += SkippedFile(name, "already in target folder")
            } else if (name in syncedIndex) {
                skipped += SkippedFile(name, "in synced index (locally deleted)")
            }
        }

        toFetch.forEachIndexed { idx, obj ->
            val name = obj.getString("name")
            val size = obj.getLong("size")
            log("[${idx + 1}/${toFetch.size}] Pulling $name (%.1f MB)".format(size / 1_048_576.0))

            try {
                val started = System.currentTimeMillis()
                val cache = File(context.cacheDir, "syncing_$name")
                val bytes = httpDownload(URL("$base/files/$name"), auth, cache, wifiNet)
                if (bytes != size) {
                    cache.delete()
                    skipped += SkippedFile(name, "size mismatch (expected $size, got $bytes)")
                    return@forEachIndexed
                }
                val newDoc = targetTree.createFile("application/octet-stream", name)
                if (newDoc == null) {
                    cache.delete()
                    skipped += SkippedFile(name, "createFile returned null in target folder")
                    return@forEachIndexed
                }
                val copied = context.contentResolver.openOutputStream(newDoc.uri)?.use { out ->
                    cache.inputStream().use { it.copyTo(out) }
                    true
                } ?: false
                if (!copied) {
                    cache.delete()
                    newDoc.delete()
                    skipped += SkippedFile(name, "could not open target output stream")
                    return@forEachIndexed
                }
                cache.delete()

                val deleted = httpDelete(URL("$base/files/$name"), auth, wifiNet)
                if (!deleted) {
                    skipped += SkippedFile(name, "downloaded ok but server DELETE failed; will retry next sync")
                    return@forEachIndexed
                }
                val durationMs = System.currentTimeMillis() - started
                pulled += PulledFile(name, bytes, durationMs)
                syncedIndex += name
                log("Pulled $name (%.1f MB) in %d ms".format(bytes / 1_048_576.0, durationMs))
            } catch (e: Exception) {
                Log.e(TAG, "Sync failed for $name: ${e.message}", e)
                skipped += SkippedFile(name, "error: ${e.message}")
            }
        }

        // Persist the index once at the end. Crash mid-sync is OK: server-side files for
        // anything we DID pull are already deleted (httpDelete returns 200 before we update
        // the index), so they wouldn't reappear on a retry. The cost of skipping the index
        // write is at most that we lose dedup info for one session — trivial.
        if (pulled.isNotEmpty()) {
            writeSyncedIndex(targetTree, syncedIndex)
            log("Index updated (${syncedIndex.size} entries)")
        }

        SyncResult(true, null, events, pulled, skipped)
    }

    private fun readSyncedIndex(targetTree: DocumentFile): MutableSet<String> {
        val file = targetTree.findFile(INDEX_FILE_NAME) ?: return mutableSetOf()
        return try {
            context.contentResolver.openInputStream(file.uri)?.use { input ->
                val text = input.bufferedReader().readText()
                val arr = JSONArray(text)
                (0 until arr.length()).mapTo(mutableSetOf()) { arr.getString(it) }
            } ?: mutableSetOf()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to read synced index: ${e.message}")
            mutableSetOf()
        }
    }

    private fun writeSyncedIndex(targetTree: DocumentFile, names: Set<String>) {
        val arr = JSONArray()
        names.sorted().forEach { arr.put(it) }
        val text = arr.toString()
        val existing = targetTree.findFile(INDEX_FILE_NAME)
        // Truncate existing by deleting + recreating; SAF doesn't reliably support open(uri, "w")
        // for replacing existing content on every provider.
        existing?.delete()
        val file = targetTree.createFile("application/json", INDEX_FILE_NAME) ?: run {
            Log.w(TAG, "Failed to create synced index file")
            return
        }
        try {
            context.contentResolver.openOutputStream(file.uri)?.use { it.write(text.toByteArray()) }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to write synced index: ${e.message}")
        }
    }

    private data class HttpResult(val body: String?, val status: Int, val error: String?)

    private fun httpGet(url: URL, auth: String, network: Network): HttpResult {
        val conn = network.openConnection(url) as HttpURLConnection
        conn.connectTimeout = 5_000
        conn.readTimeout = 10_000
        conn.setRequestProperty("Authorization", auth)
        return try {
            val code = conn.responseCode
            if (code == 200) {
                HttpResult(conn.inputStream.bufferedReader().use { it.readText() }, code, null)
            } else {
                Log.w(TAG, "GET $url -> $code")
                HttpResult(null, code, null)
            }
        } catch (e: Exception) {
            Log.w(TAG, "GET $url failed: ${e.javaClass.simpleName}: ${e.message}")
            HttpResult(null, 0, "${e.javaClass.simpleName}: ${e.message}")
        } finally {
            conn.disconnect()
        }
    }

    /** Streams body to [outFile] and returns bytes read. Returns -1 on error. */
    private fun httpDownload(url: URL, auth: String, outFile: File, network: Network): Long {
        val conn = network.openConnection(url) as HttpURLConnection
        conn.connectTimeout = 5_000
        conn.readTimeout = 60_000
        conn.setRequestProperty("Authorization", auth)
        return try {
            if (conn.responseCode != 200) {
                Log.w(TAG, "GET $url -> ${conn.responseCode}")
                -1L
            } else {
                conn.inputStream.use { input ->
                    outFile.outputStream().use { out -> input.copyTo(out) }
                }
                outFile.length()
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun httpDelete(url: URL, auth: String, network: Network): Boolean {
        val conn = network.openConnection(url) as HttpURLConnection
        conn.requestMethod = "DELETE"
        conn.connectTimeout = 5_000
        conn.readTimeout = 10_000
        conn.setRequestProperty("Authorization", auth)
        return try {
            val code = conn.responseCode
            code in 200..299
        } catch (e: IOException) {
            Log.w(TAG, "DELETE $url failed: ${e.message}")
            false
        } finally {
            conn.disconnect()
        }
    }
}

data class SyncResult(
    val ok: Boolean,
    val reason: String?,
    val log: List<String>,
    val pulled: List<PulledFile>,
    val skipped: List<SkippedFile>
)

data class PulledFile(val name: String, val bytes: Long, val durationMs: Long)
data class SkippedFile(val name: String, val reason: String)

/**
 * Wi-Fi inspection helpers — SSID and default gateway.
 *
 * On Android 12+ the modern path is via ConnectivityManager.NetworkCapabilities + TransportInfo,
 * but the legacy WifiManager APIs still work on min SDK 26 and are simpler. SSID requires
 * ACCESS_FINE_LOCATION at runtime on 8.1+.
 */
object WifiInfo {
    fun currentSsid(context: Context): String? {
        val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return null
        @Suppress("DEPRECATION")
        val info = wm.connectionInfo ?: return null
        if (info.networkId == -1) return null
        // SSID comes wrapped in quotes when valid; <unknown ssid> when permission missing.
        val raw = info.ssid ?: return null
        return raw.trim('"').takeIf { it.isNotBlank() && it != "<unknown ssid>" }
    }

    fun gatewayIp(context: Context): String? {
        val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return null
        @Suppress("DEPRECATION")
        val dhcp = wm.dhcpInfo ?: return null
        val gw = dhcp.gateway
        if (gw == 0) return null
        // dhcpInfo stores IPs as little-endian ints.
        return "${gw and 0xff}.${(gw shr 8) and 0xff}.${(gw shr 16) and 0xff}.${(gw shr 24) and 0xff}"
    }

    /** True if any network is currently up. Useful for failing fast before HTTP calls. */
    @Suppress("unused")
    fun isOnline(context: Context): Boolean {
        val cm = context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return false
        val net = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(net) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ||
               caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    /**
     * Returns the active WiFi network handle, suitable for [Network.openConnection]. Excludes
     * VPN-flagged networks. Returns null if WiFi isn't connected.
     *
     * Without binding HTTP connections to this network, Android may route requests for the
     * head unit's local subnet through the cellular interface (which can't reach it), producing
     * mysterious connect timeouts when mobile data is on.
     */
    fun findWifiNetwork(context: Context): Network? {
        val cm = context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return null
        return cm.allNetworks.firstOrNull { net ->
            val caps = cm.getNetworkCapabilities(net) ?: return@firstOrNull false
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                !caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
        }
    }
}
