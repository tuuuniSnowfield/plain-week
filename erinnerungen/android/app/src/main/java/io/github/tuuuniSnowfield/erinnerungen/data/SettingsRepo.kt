package io.github.tuuuniSnowfield.erinnerungen.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "settings")

/** Non-secret settings in DataStore; the password only in EncryptedSharedPreferences. */
class SettingsRepo(private val context: Context) {
    companion object {
        val SYNC_MODE = stringPreferencesKey("sync_mode") // caldav | folder | local
        val SERVER_URL = stringPreferencesKey("server_url")
        val USERNAME = stringPreferencesKey("username")
        val FOLDER_PATH = stringPreferencesKey("folder_path")
        val CERT_PIN = stringPreferencesKey("cert_pin")
        val CA_FILE = stringPreferencesKey("ca_file")
    }

    val syncMode: Flow<String> = context.dataStore.data.map { it[SYNC_MODE] ?: "local" }
    val serverUrl: Flow<String> = context.dataStore.data.map { it[SERVER_URL] ?: "" }
    val username: Flow<String> = context.dataStore.data.map { it[USERNAME] ?: "" }
    val folderPath: Flow<String> = context.dataStore.data.map { it[FOLDER_PATH] ?: "" }
    val certPin: Flow<String> = context.dataStore.data.map { it[CERT_PIN] ?: "" }
    val caFile: Flow<String> = context.dataStore.data.map { it[CA_FILE] ?: "" }

    suspend fun set(key: androidx.datastore.preferences.core.Preferences.Key<String>, value: String) {
        context.dataStore.edit { it[key] = value }
    }

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "secrets",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun savePassword(username: String, password: String) {
        prefs.edit().putString("password:$username", password).apply()
    }

    fun loadPassword(username: String): String? = prefs.getString("password:$username", null)

    fun deletePassword(username: String) {
        prefs.edit().remove("password:$username").apply()
    }
}
