package com.reverseit.companion

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.compose.runtime.collectAsState
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {

    private val vm: CompanionViewModel by viewModels()

    companion object {
        /** Intent extra: when true, MainActivity opens directly on the
         *  settings sub-screen instead of the file-sync main screen. Used
         *  by the vtrux flavor's Live Display cog. */
        const val EXTRA_OPEN_SETTINGS = "open_settings"
    }

    override fun onResume() {
        super.onResume()
        vm.refreshNetwork()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val openSettingsInitially = intent?.getBooleanExtra(EXTRA_OPEN_SETTINGS, false) ?: false
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var showSettings by rememberSaveable { mutableStateOf(openSettingsInitially) }
                    if (showSettings) {
                        // If we landed on settings directly (vtrux cog),
                        // Back from settings finishes back to Live Display.
                        // If we came from MainScreen (coda flow), Back returns
                        // to MainScreen.
                        SettingsScreen(vm = vm, onClose = {
                            if (openSettingsInitially) finish() else showSettings = false
                        })
                    } else {
                        MainScreen(vm = vm, onOpenSettings = { showSettings = true })
                    }
                }
            }
        }
    }
}

@Composable
fun MainScreen(vm: CompanionViewModel, onOpenSettings: () -> Unit) {
    val settings by vm.settings.collectAsState()
    val isSyncing by vm.isSyncing.collectAsState()
    val isDeleting by vm.isDeleting.collectAsState()
    val lastResult by vm.lastResult.collectAsState()
    val lastSyncMs by vm.lastSyncEpochMs.collectAsState()
    val liveSsid by vm.liveSsid.collectAsState()
    val liveGateway by vm.liveGateway.collectAsState()
    val progress by vm.progress.collectAsState()
    val localSummary by vm.localSummary.collectAsState()
    var showDeleteConfirm by rememberSaveable { mutableStateOf(false) }

    val ctx = vm.getApplication<android.app.Application>()
    val locationGranted = remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        locationGranted.value = granted
        if (granted) vm.refreshNetwork()
    }

    LaunchedEffect(Unit) {
        vm.refreshNetwork()
        vm.refreshLocalSummary()
    }
    LaunchedEffect(settings?.targetFolderUri) { vm.refreshLocalSummary() }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            stringResource(R.string.app_name),
            fontWeight = FontWeight.Bold,
            fontSize = 22.sp,
        )

        if (!locationGranted.value) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("Location permission needed to read SSID")
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = { permissionLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION) }) {
                        Text("Grant")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("WiFi", fontWeight = FontWeight.SemiBold)
                    TextButton(onClick = { vm.refreshNetwork() }) { Text("Refresh") }
                }
                StatusLine("SSID", liveSsid ?: "(unknown)")
                StatusLine("Gateway", liveGateway ?: "(none)")
                StatusLine("Expected SSID", settings?.ssid ?: "")
                val match = (liveSsid != null && liveSsid == settings?.ssid)
                StatusLine("Match", if (match) "yes" else "no")
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Target", fontWeight = FontWeight.SemiBold)
                val folder = settings?.targetFolderUri
                StatusLine("Folder", folder?.let { folderDisplayName(it) } ?: "(not set — open settings)")
                StatusLine("Last sync", lastSyncMs?.let { formatTime(it) } ?: "never")
                StatusLine(
                    "Local",
                    localSummary?.let { "${it.count} file(s), %.1f MB".format(it.totalBytes / 1_048_576.0) } ?: "—"
                )
            }
        }

        Button(
            onClick = { vm.syncNow() },
            modifier = Modifier.fillMaxWidth().height(56.dp),
            enabled = !isSyncing && !isDeleting && settings?.targetFolderUri != null
        ) {
            if (isSyncing) {
                CircularProgressIndicator(modifier = Modifier.width(20.dp).height(20.dp))
                Spacer(Modifier.width(12.dp))
                Text("Syncing...")
            } else {
                Text("Sync now")
            }
        }

        OutlinedButton(
            onClick = { showDeleteConfirm = true },
            modifier = Modifier.fillMaxWidth(),
            enabled = !isSyncing && !isDeleting && (localSummary?.count ?: 0) > 0
        ) {
            if (isDeleting) {
                CircularProgressIndicator(modifier = Modifier.width(20.dp).height(20.dp))
                Spacer(Modifier.width(12.dp))
                Text("Deleting...")
            } else {
                val n = localSummary?.count ?: 0
                val mb = (localSummary?.totalBytes ?: 0L) / 1_048_576.0
                Text(if (n == 0) "Delete local copies" else "Delete local copies ($n, %.1f MB)".format(mb))
            }
        }

        OutlinedButton(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth()) { Text("Settings") }

        // Live log during sync OR delete; result summary shown alongside the log after sync.
        if (progress.isNotEmpty() || lastResult != null) {
            ProgressCard(
                progressLines = progress,
                result = lastResult,
                isSyncing = isSyncing
            )
        }
    }

    if (showDeleteConfirm) {
        val n = localSummary?.count ?: 0
        val mb = (localSummary?.totalBytes ?: 0L) / 1_048_576.0
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showDeleteConfirm = false },
            title = { Text("Delete local copies?") },
            text = { Text("This will permanently delete $n .log file(s) (%.1f MB) from the target folder. Make sure SeaDrive has finished uploading them first.".format(mb)) },
            confirmButton = {
                androidx.compose.material3.TextButton(onClick = {
                    showDeleteConfirm = false
                    vm.deleteLocalCopies()
                }) { Text("Delete") }
            },
            dismissButton = {
                androidx.compose.material3.TextButton(onClick = { showDeleteConfirm = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
fun StatusLine(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, modifier = Modifier.width(120.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun ProgressCard(
    progressLines: List<String>,
    result: SyncResult?,
    isSyncing: Boolean
) {
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    LaunchedEffect(progressLines.size) {
        if (progressLines.isNotEmpty()) {
            listState.animateScrollToItem(progressLines.lastIndex)
        }
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            val title = when {
                isSyncing                 -> "Syncing..."
                result == null            -> "Working..."
                result.ok                 -> "Result"
                else                      -> "Failed: ${result.reason}"
            }
            Text(title, fontWeight = FontWeight.SemiBold)
            if (result != null) {
                Spacer(Modifier.height(4.dp))
                Text("Pulled: ${result.pulled.size}    Skipped: ${result.skipped.size}")
            }
            Divider(modifier = Modifier.padding(vertical = 8.dp))
            LazyColumn(state = listState, modifier = Modifier.fillMaxWidth().height(260.dp)) {
                items(progressLines) { line ->
                    Text(line, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
fun SettingsScreen(vm: CompanionViewModel, onClose: () -> Unit) {
    val settings by vm.settings.collectAsState()
    if (settings == null) return

    var ssid by rememberSaveable { mutableStateOf(settings!!.ssid) }
    var token by rememberSaveable { mutableStateOf(settings!!.token) }
    var portText by rememberSaveable { mutableStateOf(settings!!.port.toString()) }
    var displayHost by rememberSaveable { mutableStateOf(settings!!.displayHost) }
    var displayPortText by rememberSaveable { mutableStateOf(settings!!.displayPort.toString()) }

    val folderPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        vm.persistFolderPermission(result.data)
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("Settings", fontWeight = FontWeight.Bold, fontSize = 22.sp)

        OutlinedTextField(
            value = ssid,
            onValueChange = {
                ssid = it
                vm.setSsid(it)
            },
            label = { Text("Hotspot SSID") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )

        OutlinedTextField(
            value = token,
            onValueChange = {
                token = it
                vm.setToken(it)
            },
            label = { Text("Auth token") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )

        OutlinedTextField(
            value = portText,
            onValueChange = { txt ->
                portText = txt
                txt.toIntOrNull()?.let { vm.setPort(it) }
            },
            label = { Text("Server port") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )

        if (BuildConfig.VEHICLE == "vtrux") {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("Live Display server", fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = displayHost,
                        onValueChange = {
                            displayHost = it.trim()
                            vm.setDisplayHost(displayHost)
                        },
                        label = { Text("Host (laptop IP or logger phone)") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = displayPortText,
                        onValueChange = { txt ->
                            displayPortText = txt.filter { c -> c.isDigit() }
                            displayPortText.toIntOrNull()?.let { vm.setDisplayPort(it) }
                        },
                        label = { Text("Port") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Token reuses the file-sync token above.",
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Target folder", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                Text(settings!!.targetFolderUri?.let { folderDisplayName(it) } ?: "(not set)",
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(8.dp))
                Button(onClick = {
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                                 Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                                 Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
                    }
                    folderPicker.launch(intent)
                }) {
                    Text("Pick folder")
                }
            }
        }

        OutlinedButton(onClick = onClose, modifier = Modifier.fillMaxWidth()) { Text("Back") }
    }
}

private fun formatTime(ms: Long): String =
    SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date(ms))

private fun folderDisplayName(uri: String): String {
    return try {
        val decoded = android.net.Uri.decode(uri)
        // SAF tree URIs end with "...tree/<provider-encoded-path>". Strip down to the readable bit.
        val idx = decoded.lastIndexOf('/')
        if (idx >= 0) decoded.substring(idx + 1) else decoded
    } catch (_: Exception) { uri }
}
