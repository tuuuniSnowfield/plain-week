package io.github.tuuuniSnowfield.erinnerungen.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import io.github.tuuuniSnowfield.erinnerungen.ReminderApp
import io.github.tuuuniSnowfield.erinnerungen.data.SettingsRepo
import io.github.tuuuniSnowfield.erinnerungen.sync.CalDavBackend
import io.github.tuuuniSnowfield.erinnerungen.sync.CalDavClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Setup in under 60 seconds: URL, user, password — done.
 * No account, no cloud sign-up, no telemetry. Password goes to
 * EncryptedSharedPreferences only.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(app: ReminderApp, nav: NavController) {
    val scope = rememberCoroutineScope()
    var mode by remember { mutableStateOf("local") }
    var url by remember { mutableStateOf("") }
    var user by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var pin by remember { mutableStateOf("") }
    var ca by remember { mutableStateOf("") }
    var folder by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(false) }
    val modes = listOf("local" to "Nur lokal (kein Sync)", "caldav" to "CalDAV-Server (empfohlen)", "folder" to "Lokaler Ordner (.ics)")

    LaunchedEffect(Unit) {
        mode = app.settings.syncMode.first()
        url = app.settings.serverUrl.first()
        user = app.settings.username.first()
        pin = app.settings.certPin.first()
        ca = app.settings.caFile.first()
        folder = app.settings.folderPath.first()
        password = if (user.isNotBlank()) app.settings.loadPassword(user) ?: "" else ""
    }

    fun save() {
        scope.launch(Dispatchers.IO) {
            app.settings.set(SettingsRepo.SYNC_MODE, mode)
            app.settings.set(SettingsRepo.SERVER_URL, url.trim())
            app.settings.set(SettingsRepo.USERNAME, user.trim())
            app.settings.set(SettingsRepo.CERT_PIN, pin.trim())
            app.settings.set(SettingsRepo.CA_FILE, ca.trim())
            app.settings.set(SettingsRepo.FOLDER_PATH, folder.trim())
            if (user.isNotBlank()) {
                if (password.isNotBlank()) app.settings.savePassword(user.trim(), password)
                else app.settings.deletePassword(user.trim())
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Einstellungen") },
                navigationIcon = { IconButton(onClick = { nav.popBackStack() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Zurück") } },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).padding(16.dp).verticalScroll(rememberScrollState())) {
            ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
                OutlinedTextField(
                    modes.first { it.first == mode }.second, {}, label = { Text("Modus") },
                    readOnly = true, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
                    modifier = Modifier.menuAnchor().fillMaxWidth(),
                )
                ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    modes.forEach { (k, label) ->
                        DropdownMenuItem(text = { Text(label) }, onClick = { mode = k; expanded = false; save() })
                    }
                }
            }
            if (mode == "caldav") {
                OutlinedTextField(url, { url = it; save() }, label = { Text("Server-URL (https://…)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(user, { user = it; save() }, label = { Text("Benutzername") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(password, { password = it; save() }, label = { Text("Passwort (verschlüsselt gespeichert)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(pin, { pin = it; save() }, label = { Text("Zertifikats-Pin (sha256/<base64> oder 64 Hex)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(ca, { ca = it; save() }, label = { Text("Eigenes CA-Bundle (PEM-Pfad, optional)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Button(onClick = {
                    scope.launch {
                        status = withContext(Dispatchers.IO) {
                            try {
                                val pw = app.settings.loadPassword(user.trim())
                                if (url.isBlank() || user.isBlank() || pw.isNullOrBlank()) return@withContext "URL, Benutzername und Passwort eintragen."
                                val client = CalDavClient(url.trim(), user.trim(), pw, ca.trim().ifBlank { null }, pin.trim().ifBlank { null })
                                CalDavBackend(client).discoverLists()
                                "Verbindung OK ✔"
                            } catch (e: Exception) {
                                "Verbindung fehlgeschlagen: ${e.message}"
                            }
                        }
                    }
                }, modifier = Modifier.padding(top = 12.dp)) { Text("Verbindung testen") }
            }
            if (mode == "folder") {
                OutlinedTextField(folder, { folder = it; save() }, label = { Text("Ordner mit .ics-Dateien") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Text("leer = App-Ordner (getExternalFilesDir/ics)", style = androidx.compose.material3.MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
            }
            if (status.isNotBlank()) Text(status, modifier = Modifier.padding(top = 12.dp))
            Text(
                "Kein Account, keine Cloud, keine Telemetrie. Daten liegen lokal (SQLite) " +
                    "und optional auf deinem eigenen CalDAV-Server. GPLv3.",
                style = androidx.compose.material3.MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 16.dp),
            )
        }
    }
}
