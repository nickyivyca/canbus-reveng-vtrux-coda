package com.reverseit.companion

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.reverseit.cancore.BuildConfig as CanCoreBuildConfig
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "companion_settings")

data class CompanionSettings(
    val ssid: String,
    val token: String,
    val port: Int,
    val targetFolderUri: String?,
    val displayHost: String,
    val displayPort: Int,
)

class SettingsRepo(private val context: Context) {

    companion object {
        private val KEY_SSID         = stringPreferencesKey("ssid")
        private val KEY_TOKEN        = stringPreferencesKey("token")
        private val KEY_PORT         = intPreferencesKey("port")
        private val KEY_FOLDER       = stringPreferencesKey("folder_uri")
        private val KEY_DISPLAY_HOST = stringPreferencesKey("display_host")
        private val KEY_DISPLAY_PORT = intPreferencesKey("display_port")

        const val DEFAULT_PORT = 9877
        const val DEFAULT_DISPLAY_PORT = 9878
    }

    val flow: Flow<CompanionSettings> = context.dataStore.data.map { prefs ->
        CompanionSettings(
            ssid            = prefs[KEY_SSID]   ?: BuildConfig.DEFAULT_SSID,
            token           = prefs[KEY_TOKEN]  ?: CanCoreBuildConfig.SYNC_TOKEN,
            port            = prefs[KEY_PORT]   ?: DEFAULT_PORT,
            targetFolderUri = prefs[KEY_FOLDER],
            displayHost     = prefs[KEY_DISPLAY_HOST] ?: "",
            displayPort     = prefs[KEY_DISPLAY_PORT] ?: DEFAULT_DISPLAY_PORT,
        )
    }

    suspend fun setSsid(v: String)        = context.dataStore.edit { it[KEY_SSID]         = v }
    suspend fun setToken(v: String)       = context.dataStore.edit { it[KEY_TOKEN]        = v }
    suspend fun setPort(v: Int)           = context.dataStore.edit { it[KEY_PORT]         = v }
    suspend fun setFolder(v: String)      = context.dataStore.edit { it[KEY_FOLDER]       = v }
    suspend fun setDisplayHost(v: String) = context.dataStore.edit { it[KEY_DISPLAY_HOST] = v }
    suspend fun setDisplayPort(v: Int)    = context.dataStore.edit { it[KEY_DISPLAY_PORT] = v }
}
