package com.reverseit.vtrux

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.reverseit.cancore.DataSourceStatus
import com.reverseit.cancore.LocalCanDataSource
import com.reverseit.cancore.SubscriptionManifest
import com.reverseit.display.LiveDisplayScreen
import com.reverseit.display.LiveDisplayViewModel
import com.reverseit.display.StatusBanner
import org.json.JSONObject

/**
 * Vtrux logger phone's embedded live display.
 *
 * Mirrors the `:companion` vtrux flavor's UX: live display is the launcher
 * screen, settings cog overlays the bottom-right corner, status banner at
 * the bottom of the screen. The data source is a [LocalCanDataSource]
 * tapping the in-process [VtruxApplication.pipeline] -- no network round-trip.
 *
 * Settings (legacy permissions / log directory / etc) live in
 * [MainActivity]; the cog forwards there.
 */
class LiveDisplayActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.systemBars),
                    color = Color.Black,
                ) {
                    LiveDisplayRoute(
                        onOpenSettings = {
                            startActivity(Intent(this, MainActivity::class.java))
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun LiveDisplayRoute(onOpenSettings: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as VtruxApplication

    val displayVm = remember { mutableStateOf<LiveDisplayViewModel?>(null) }
    var lastError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            val manifestJson = readAsset(context, "live-display/manifest.json")
            val manifest = parseManifest(manifestJson)
            val busesUsed = manifest.subscriptions.map { it.bus }.toSet()
            val dbcs = busesUsed.associateWith {
                readAsset(context, "live-display/dbcs/$it.dbc")
            }
            val unitsCombined = HashMap<String, String>()
            for (text in dbcs.values) unitsCombined.putAll(extractUnits(text))
            val ds = LocalCanDataSource(
                rawFrames = app.pipeline.frames,
                identities = VtruxConstants.BUS_IDENTITIES,
            )
            val newVm = LiveDisplayViewModel(ds)
            newVm.setUnits(unitsCombined)
            displayVm.value = newVm
            newVm.start(dbcs, manifest)
            lastError = null
        } catch (e: Exception) {
            lastError = "${e.javaClass.simpleName}: ${e.message}"
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Box(modifier = Modifier.fillMaxSize()) {
            when {
                lastError != null -> Centered("Error: $lastError")
                displayVm.value == null -> Centered("Connecting…")
                else -> LiveDisplayScreen(
                    viewModel = displayVm.value!!,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }

        // Bottom stack: settings cog above the status banner. The cog rides
        // on the top of the banner so it stays visible even when the banner
        // wraps to multiple lines (e.g. "Failed: ..." with a long reason).
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
                    Text("⚙", color = Color.White)
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
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(text, color = Color.White)
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
                ?: throw IllegalArgumentException(
                    "unknown aggregation ${item.getString("aggregation")}"
                ),
        )
    }
    return SubscriptionManifest(subs)
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
