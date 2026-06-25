package com.reverseit.companion

import android.app.Application
import android.content.Intent
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class LocalSummary(val count: Int, val totalBytes: Long)

class CompanionViewModel(app: Application) : AndroidViewModel(app) {

    private val settingsRepo = SettingsRepo(app)
    private val syncEngine = SyncEngine(app)

    val settings: StateFlow<CompanionSettings?> = settingsRepo.flow
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    private val _isSyncing = MutableStateFlow(false)
    val isSyncing: StateFlow<Boolean> = _isSyncing.asStateFlow()

    private val _isDeleting = MutableStateFlow(false)
    val isDeleting: StateFlow<Boolean> = _isDeleting.asStateFlow()

    private val _lastResult = MutableStateFlow<SyncResult?>(null)
    val lastResult: StateFlow<SyncResult?> = _lastResult.asStateFlow()

    private val _progress = MutableStateFlow<List<String>>(emptyList())
    val progress: StateFlow<List<String>> = _progress.asStateFlow()

    private val _lastSyncEpochMs = MutableStateFlow<Long?>(null)
    val lastSyncEpochMs: StateFlow<Long?> = _lastSyncEpochMs.asStateFlow()

    private val _liveSsid = MutableStateFlow<String?>(null)
    val liveSsid: StateFlow<String?> = _liveSsid.asStateFlow()

    private val _liveGateway = MutableStateFlow<String?>(null)
    val liveGateway: StateFlow<String?> = _liveGateway.asStateFlow()

    private val _localSummary = MutableStateFlow<LocalSummary?>(null)
    val localSummary: StateFlow<LocalSummary?> = _localSummary.asStateFlow()

    fun refreshNetwork() {
        _liveSsid.value = WifiInfo.currentSsid(getApplication())
        _liveGateway.value = WifiInfo.gatewayIp(getApplication())
    }

    fun refreshLocalSummary() {
        val uri = settings.value?.targetFolderUri ?: run { _localSummary.value = null; return }
        viewModelScope.launch(Dispatchers.IO) {
            _localSummary.value = computeLocalSummary(uri)
        }
    }

    private fun computeLocalSummary(uri: String): LocalSummary {
        val tree = DocumentFile.fromTreeUri(getApplication(), Uri.parse(uri)) ?: return LocalSummary(0, 0)
        val files = tree.listFiles().filter { it.isFile && it.name?.endsWith(".log") == true }
        return LocalSummary(files.size, files.sumOf { it.length() })
    }

    fun syncNow() {
        if (_isSyncing.value) return
        val s = settings.value ?: return
        viewModelScope.launch {
            _isSyncing.value = true
            _progress.value = emptyList()
            _lastResult.value = null
            try {
                val result = syncEngine.runSync(s) { line ->
                    _progress.value = _progress.value + line
                }
                _lastResult.value = result
                if (result.ok) _lastSyncEpochMs.value = System.currentTimeMillis()
            } finally {
                _isSyncing.value = false
                refreshNetwork()
                refreshLocalSummary()
            }
        }
    }

    /** Delete every .log file in the configured target folder. */
    fun deleteLocalCopies() {
        if (_isDeleting.value) return
        val uri = settings.value?.targetFolderUri ?: return
        viewModelScope.launch {
            _isDeleting.value = true
            _progress.value = listOf("Scanning local folder...")
            try {
                val (deleted, failed, freedBytes) = withContext(Dispatchers.IO) {
                    val tree = DocumentFile.fromTreeUri(getApplication(), Uri.parse(uri))
                        ?: return@withContext Triple(0, 0, 0L)
                    val files = tree.listFiles().filter { it.isFile && it.name?.endsWith(".log") == true }
                    var d = 0; var f = 0; var b = 0L
                    files.forEach { doc ->
                        val sz = doc.length()
                        if (doc.delete()) { d++; b += sz } else { f++ }
                    }
                    Triple(d, f, b)
                }
                _progress.value = listOf(
                    "Deleted $deleted file(s), freed %.1f MB".format(freedBytes / 1_048_576.0) +
                    if (failed > 0) "; $failed failed" else ""
                )
            } finally {
                _isDeleting.value = false
                refreshLocalSummary()
            }
        }
    }

    fun setSsid(v: String) = viewModelScope.launch { settingsRepo.setSsid(v) }
    fun setToken(v: String) = viewModelScope.launch { settingsRepo.setToken(v) }
    fun setPort(v: Int) = viewModelScope.launch { settingsRepo.setPort(v) }
    fun setDisplayHost(v: String) = viewModelScope.launch { settingsRepo.setDisplayHost(v) }
    fun setDisplayPort(v: Int) = viewModelScope.launch { settingsRepo.setDisplayPort(v) }
    fun setFolderUri(v: String) = viewModelScope.launch {
        settingsRepo.setFolder(v)
        refreshLocalSummary()
    }

    fun persistFolderPermission(intent: Intent?) {
        val uri = intent?.data ?: return
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        try {
            getApplication<Application>().contentResolver.takePersistableUriPermission(uri, flags)
        } catch (_: SecurityException) {
            // tree provider didn't grant persistable perms; user will need to re-pick each session
        }
        setFolderUri(uri.toString())
    }
}
