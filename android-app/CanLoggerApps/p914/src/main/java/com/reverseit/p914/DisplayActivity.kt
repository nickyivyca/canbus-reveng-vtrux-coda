package com.reverseit.p914

import android.content.Intent
import android.hardware.usb.UsbManager
import android.os.Bundle
import android.util.Log
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
import com.reverseit.cancore.DbcParser
import com.reverseit.cancore.LocalCanDataSource
import com.reverseit.cancore.SubscriptionManifest
import com.reverseit.display.LiveDisplayViewModel
import com.reverseit.display.StatusBanner
import kotlinx.coroutines.delay
import org.json.JSONObject

private const val TAG = "P914Display"

/**
 * The in-car display, and the app's launcher.
 *
 * Mirrors `:vtrux`'s `LiveDisplayActivity`: display fills the screen, settings cog overlays the
 * bottom-right, status banner along the bottom. [MainActivity] is the settings screen behind the
 * cog.
 *
 * The USB attach filter lives on THIS activity, not on [MainActivity]. Two things depend on that
 * and only one of them is obvious. Plugging the VCU in should of course bring up the display
 * rather than the settings screen -- but the manifest `<usb-device>` filter is also what makes
 * Android offer "use by default for this USB device" on the permission dialog at all. Without a
 * matching filter on the launched activity, `requestPermission()` can only ever produce a
 * one-shot grant, and every replug stops to wait for a dialog nobody is there to tap. That was
 * diagnosed once already (A6) and it does not announce itself as a bug -- it reads as Android
 * being annoying.
 */
class DisplayActivity : ComponentActivity() {

    private val app get() = application as P914Application

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // This is a dash display. It must never sleep.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.systemBars),
                    color = Color.Black,
                ) {
                    P914Route(
                        onOpenSettings = {
                            startActivity(Intent(this, MainActivity::class.java))
                        },
                    )
                }
            }
        }
        handleLaunchIntent(intent)
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        setIntent(newIntent)
        handleLaunchIntent(newIntent)
    }

    /**
     * Connect if the launch asked for it. Moved here from [MainActivity] along with the intent
     * filter -- the filter without the handler would auto-launch the display and then sit idle.
     *
     * `USB_DEVICE_ATTACHED` carries no extras of ours, so it has to be recognised by action.
     */
    private fun handleLaunchIntent(i: Intent?) {
        val byExtra = i?.getBooleanExtra("autoconnect", false) == true
        val byUsb = i?.action == UsbManager.ACTION_USB_DEVICE_ATTACHED
        if (byExtra || byUsb) {
            Log.i(TAG, "connecting (usb=$byUsb extra=$byExtra)")
            app.connect(P914Application.Transport.USB)
        }
    }
}

@Composable
private fun P914Route(onOpenSettings: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as P914Application

    var vm by remember { mutableStateOf<LiveDisplayViewModel?>(null) }
    var stamp by remember { mutableStateOf<SchemaCheck.Stamp?>(null) }
    var opmodeNames by remember { mutableStateOf<Map<Int, String>>(emptyMap()) }
    var lastError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            val manifestJson = readAsset(context, "live-display/manifest.json")
            val manifest = parseManifest(manifestJson)
            val busesUsed = manifest.subscriptions.map { it.bus }.toSet()
            val dbcs = busesUsed.associateWith {
                readAsset(context, "live-display/dbcs/$it.dbc")
            }

            // Parse once here for the two things the data source does not expose: the schema
            // stamp in the CM_ file comment, and per-signal units. Using DbcParser rather than a
            // second set of regexes means this agrees with the decoder by construction.
            val vcuText = dbcs.getValue("vcu")
            val vcuDbc = DbcParser.parse(vcuText)
            stamp = SchemaCheck.parseStamp(vcuDbc.fileComment)
            if (stamp == null) {
                Log.w(TAG, "vcu.dbc carries no SCHEMA_HASH= stamp -- broadcast cannot be checked")
            }
            opmodeNames = extractValueTable(vcuText, OPMODE_MSG_ID, "InvOpmode")

            val units = HashMap<String, String>()
            for (msg in vcuDbc.messages.values) {
                for (sig in msg.signals) if (sig.unit.isNotBlank()) units[sig.name] = sig.unit
            }

            val ds = LocalCanDataSource(
                rawFrames = app.source.frames,
                identities = P914Constants.BUS_IDENTITIES,
            )
            val newVm = LiveDisplayViewModel(ds)
            newVm.setUnits(units)
            vm = newVm
            newVm.start(dbcs, manifest)
            lastError = null
        } catch (e: Exception) {
            Log.w(TAG, "display start failed", e)
            lastError = "${e.javaClass.simpleName}: ${e.message}"
        }
    }

    // Age of this screen, ticked once a second only until the beacon grace period has elapsed.
    //
    // A clock is genuinely needed here: with no stream at all nothing else recomposes, so
    // "no SchemaId for 10 s" would never be reached and the band would sit on "SCHEMA ?"
    // forever -- the one degraded state that looks most like everything being fine.
    var elapsedMs by remember { mutableStateOf(0L) }
    LaunchedEffect(Unit) {
        while (elapsedMs < SchemaCheck.BEACON_GRACE_MS) {
            delay(1_000)
            elapsedMs += 1_000
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val currentVm = vm
        val signals = currentVm?.signalValues?.collectAsState()?.value ?: emptyMap()
        val status: DataSourceStatus =
            currentVm?.status?.collectAsState()?.value ?: DataSourceStatus.Idle

        Box(modifier = Modifier.fillMaxSize()) {
            when {
                lastError != null -> Centered("Error: $lastError")
                currentVm == null -> Centered("Starting...")
                else -> P914Screen(
                    signals = signals,
                    schema = SchemaCheck.evaluate(
                        stamp = stamp,
                        observed = SchemaCheck.readBroadcast(signals),
                        elapsedMs = elapsedMs,
                    ),
                    live = status is DataSourceStatus.Streaming,
                    opmodeNames = opmodeNames,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }

        // Cog above the banner, so it stays visible when the banner wraps to two lines.
        Column(modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
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
            StatusBanner(status = status, modifier = Modifier.fillMaxWidth())
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

// --- asset plumbing -------------------------------------------------------

/** `InverterState`, as it appears in the DBC's `VAL_` lines (raw BO_ number, 11-bit so unmarked). */
private const val OPMODE_MSG_ID = 2

private fun readAsset(context: android.content.Context, path: String): String =
    context.assets.open(path).bufferedReader(Charsets.UTF_8).use { it.readText() }

/**
 * Pull an enumeration out of a DBC `VAL_` line:
 *
 *     VAL_ 2 InvOpmode 0 "Off" 1 "Run" 2 "ManualRun" ... ;
 *
 * `DbcParser` deliberately skips `VAL_` -- it is a presentation concern the decoder has no use
 * for -- so this is read here instead, exactly as `:vtrux` reads units out of the DBC text rather
 * than extending the parser for them. Reading the firmware's own table is the point: the app
 * cannot invent an opmode name the VCU does not use.
 */
private fun extractValueTable(dbc: String, messageId: Int, signal: String): Map<Int, String> {
    val line = dbc.lineSequence().firstOrNull {
        it.startsWith("VAL_ $messageId $signal ")
    } ?: return emptyMap()
    val pairs = Regex("""(-?\d+)\s+"([^"]*)"""").findAll(line)
    return pairs.associate { it.groupValues[1].toInt() to it.groupValues[2] }
}

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
