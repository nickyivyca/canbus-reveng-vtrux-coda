package com.reverseit.companion

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.reverseit.cancore.DataSourceStatus
import com.reverseit.cancore.RemoteCanDataSource
import com.reverseit.cancore.SubscriptionManifest
import com.reverseit.display.LiveDisplayScreen
import com.reverseit.display.LiveDisplayViewModel
import com.reverseit.display.StatusBanner
import org.json.JSONObject

/**
 * Vtrux companion launcher screen. Live display fills the screen; a small
 * "settings" button overlays a corner and launches [MainActivity] for the
 * file-sync UI and the live-display server-host editor.
 *
 * Server host/port come from persisted DataStore settings (see
 * [SettingsRepo]). Token reuses the project-wide `BuildConfig.SYNC_TOKEN`.
 * On launch / resume, if a host is configured the activity auto-connects;
 * otherwise the screen shows a "tap settings" prompt.
 */
class LiveDisplayActivity : ComponentActivity() {

    private val vm: CompanionViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Keep the screen awake while Live Display is the foreground activity.
        // Cleared automatically when the window is destroyed; the flag is
        // window-scoped, not app-scoped.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.systemBars),
                    color = androidx.compose.ui.graphics.Color.Black,
                ) {
                    LiveDisplayRoute(vm = vm, onOpenSettings = ::openSettings)
                }
            }
        }
    }

    private fun openSettings() {
        startActivity(Intent(this, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN_SETTINGS, true))
    }
}

@Composable
private fun LiveDisplayRoute(vm: CompanionViewModel, onOpenSettings: () -> Unit) {
    val context = LocalContext.current
    val settings by vm.settings.collectAsState()
    val lifecycleOwner = LocalLifecycleOwner.current

    val displayVm = remember { mutableStateOf<LiveDisplayViewModel?>(null) }
    var lastError by remember { mutableStateOf<String?>(null) }
    var isResumed by remember { mutableStateOf(false) }

    // Track lifecycle as a plain Boolean. Re-launching the connect block from
    // a LaunchedEffect lets it respond to (isResumed, settings) independently
    // -- on first launch the activity is resumed before DataStore has emitted
    // settings, so we need both edges to be observed.
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> isResumed = true
                Lifecycle.Event.ON_PAUSE -> isResumed = false
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LaunchedEffect(
        isResumed,
        settings?.displayHost,
        settings?.displayPort,
        settings?.token,
    ) {
        if (!isResumed) {
            displayVm.value?.stop()
            displayVm.value = null
            return@LaunchedEffect
        }
        val s = settings ?: return@LaunchedEffect
        // On the Vtrux hotspot the logger phone IS the gateway, so re-read
        // the current gateway IP every connection attempt. Off-network we
        // fall back to whatever was last saved in settings (testing config).
        val host = resolveDisplayHost(context, s) ?: run {
            lastError = null
            return@LaunchedEffect
        }
        val token = s.token.takeIf { it.isNotBlank() } ?: run {
            lastError = "no auth token configured"
            return@LaunchedEffect
        }
        try {
            val manifestJson = readAsset(context, "live-display/manifest.json")
            val manifest = parseManifest(manifestJson)
            val busesUsed = manifest.subscriptions.map { it.bus }.toSet()
            val dbcs = busesUsed.associateWith {
                readAsset(context, "live-display/dbcs/$it.dbc")
            }
            val unitsCombined = HashMap<String, String>()
            for (text in dbcs.values) unitsCombined.putAll(extractUnits(text))
            // Pin the WebSocket to the active WiFi Network so Android doesn't
            // route the truck-hotspot subnet via cellular (CGNAT) when mobile
            // data is on. Same trick `SyncEngine` uses for the file-sync HTTP
            // calls. Null if no WiFi is up; OkHttp falls back to default
            // routing and surfaces a meaningful error in the banner.
            val wifiSocketFactory = WifiInfo.findWifiNetwork(context)?.socketFactory
            val ds = RemoteCanDataSource(
                url = "ws://$host:${s.displayPort}/stream",
                token = token,
                socketFactory = wifiSocketFactory,
            )
            val newVm = LiveDisplayViewModel(ds)
            newVm.setUnits(unitsCombined)
            displayVm.value?.stop()
            displayVm.value = newVm
            newVm.start(dbcs, manifest)
            lastError = null
        } catch (e: Exception) {
            lastError = "${e.javaClass.simpleName}: ${e.message}"
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        // Main content fills the screen; LiveDisplayScreen reserves its own
        // bottom-margin spacer so signal cards don't slide under the banner.
        Box(modifier = Modifier.fillMaxSize()) {
            when {
                settings == null -> Centered("Loading…")
                resolveDisplayHost(context, settings!!) == null -> Centered(
                    "Connect to the '${BuildConfig.DEFAULT_SSID}' WiFi, " +
                        "or tap the cog to set a server host."
                )
                lastError != null -> Centered("Error: $lastError")
                displayVm.value == null -> Centered("Connecting…")
                else -> LiveDisplayScreen(
                    viewModel = displayVm.value!!,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }

        // Bottom stack: settings cog above the status banner. The cog rides
        // on top of the banner so it stays visible when the banner wraps
        // (e.g. "Failed: <long reason>").
        val ds = displayVm.value
        val statusForBanner: DataSourceStatus = ds?.status?.collectAsState()?.value
            ?: DataSourceStatus.Idle
        Column(
            modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth(),
        ) {
            Box(
                modifier = Modifier
                    .align(Alignment.End)
                    .padding(end = 16.dp, bottom = 8.dp),
            ) {
                TextButton(
                    onClick = onOpenSettings,
                    modifier = Modifier
                        .size(56.dp)
                        .background(Color(0xCC424242), shape = CircleShape),
                ) {
                    Text(text = "⚙", color = Color.White)
                }
            }
            StatusBanner(
                status = statusForBanner,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun Centered(text: String) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(text, style = MaterialTheme.typography.titleMedium)
    }
}

private fun readAsset(context: android.content.Context, path: String): String =
    context.assets.open(path).bufferedReader(Charsets.UTF_8).use { it.readText() }

private fun parseManifest(json: String): SubscriptionManifest {
    val obj = JSONObject(json)
    val arr = obj.optJSONArray("subscriptions")
        ?: throw IllegalArgumentException("manifest missing 'subscriptions' array")
    val subs = ArrayList<SubscriptionManifest.Subscription>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.getJSONObject(i)
        val signalsRaw = item.opt("signals")
        val signals: List<String>? = when (signalsRaw) {
            is String -> if (signalsRaw == "*") null else listOf(signalsRaw)
            null -> null
            else -> {
                val sa = item.getJSONArray("signals")
                List(sa.length()) { sa.getString(it) }
            }
        }
        subs += SubscriptionManifest.Subscription(
            bus = item.getString("bus"),
            messageId = item.getInt("message_id"),
            signals = signals,
            rateHz = item.getDouble("rate_hz"),
            aggregation = SubscriptionManifest.Aggregation.values()
                .firstOrNull { it.wire == item.getString("aggregation") }
                ?: throw IllegalArgumentException("unknown aggregation ${item.getString("aggregation")}"),
        )
    }
    return SubscriptionManifest(subs)
}

/**
 * Decide which host the live display should connect to.
 *
 * On the Vtrux hotspot the logger phone IS the WiFi gateway, so we re-read
 * `WifiInfo.gatewayIp` every connection attempt — no manual configuration
 * and no risk of a stale IP after the logger reboots. Off the Vtrux SSID
 * (typical test setup where the logger and companion sit on the same
 * office WiFi) we fall back to the manually-saved `displayHost` so the
 * tester can point at any server.
 *
 * Returns null when neither path applies (off-Vtrux with a blank saved
 * host, or on-Vtrux before DHCP completes). The caller surfaces a
 * "tap the cog" / "connect to Vtrux WiFi" message.
 */
private fun resolveDisplayHost(context: android.content.Context, s: CompanionSettings): String? {
    val ssid = WifiInfo.currentSsid(context)
    if (ssid == BuildConfig.DEFAULT_SSID) {
        WifiInfo.gatewayIp(context)?.takeIf { it != "0.0.0.0" }?.let { return it }
    }
    return s.displayHost.takeIf { it.isNotBlank() }
}

private fun extractUnits(dbc: String): Map<String, String> {
    val regex = Regex("""\s*SG_\s+(\S+)[^"]*"([^"]*)"""")
    val out = HashMap<String, String>()
    for (line in dbc.lineSequence()) {
        val m = regex.find(line) ?: continue
        out[m.groupValues[1]] = m.groupValues[2]
    }
    return out
}
