package io.github.tuuuniSnowfield.erinnerungen.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import io.github.tuuuniSnowfield.erinnerungen.core.Recurrence
import io.github.tuuuniSnowfield.erinnerungen.data.TaskEntity
import io.github.tuuuniSnowfield.erinnerungen.data.utcNow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val RECURRENCE_CHOICES = listOf(
    "none" to "Keine", "daily" to "Täglich", "weekly" to "Wöchentlich",
    "monthly" to "Monatlich", "last_day_of_month" to "Letzter Tag im Monat", "yearly" to "Jährlich",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(app: ReminderApp, nav: NavController, uid: String) {
    var task by remember { mutableStateOf<TaskEntity?>(null) }
    var title by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    var dueEnabled by remember { mutableStateOf(false) }
    var dueDate by remember { mutableStateOf("") }
    var dueTime by remember { mutableStateOf("") }
    var recIndex by remember { mutableStateOf(0) }
    var subs by remember { mutableStateOf<List<TaskEntity>>(emptyList()) }
    var showDelete by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    suspend fun reload() = withContext(Dispatchers.IO) {
        task = app.db.taskDao().byUid(uid)
        task?.let {
            title = it.title
            notes = it.notes
            dueEnabled = it.due != null
            val p = it.due?.split(" ")
            dueDate = p?.get(0) ?: ""
            dueTime = p?.getOrNull(1) ?: ""
            recIndex = when {
                it.rrule.isNullOrBlank() -> 0
                else -> {
                    val r = runCatching { Recurrence.parse(it.rrule) }.getOrNull()
                    when {
                        r == null -> 0
                        r.freq == "DAILY" -> 1
                        r.freq == "WEEKLY" -> 2
                        r.freq == "MONTHLY" && r.bymonthday == setOf(-1) -> 4
                        r.freq == "MONTHLY" -> 3
                        else -> 5
                    }
                }
            }
            subs = app.db.taskDao().children(uid)
        }
    }

    LaunchedEffect(uid) { reload() }

    fun save() {
        scope.launch(Dispatchers.IO) {
            val now = utcNow()
            val due = if (dueEnabled) {
                if (dueTime.isNotBlank()) "$dueDate $dueTime" else dueDate.ifBlank { null }
            } else null
            val anchor = runCatching { LocalDateTime.of(LocalDate.parse(dueDate.ifBlank { LocalDate.now().toString() }), LocalTime.MIDNIGHT) }.getOrNull() ?: LocalDateTime.now()
            val rrule = Recurrence.preset(RECURRENCE_CHOICES[recIndex].first, anchor)
            app.db.taskDao().update(uid, title.ifBlank { "Ohne Titel" }, notes, due, rrule,
                task?.status ?: "NEEDS-ACTION", task?.percent ?: 0, task?.parentUid, now)
            reload()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Erinnerung") },
                navigationIcon = { IconButton(onClick = { nav.popBackStack() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Zurück") } },
                actions = { IconButton(onClick = { showDelete = true }) { Icon(Icons.Default.Delete, "Löschen") } },
            )
        },
    ) { padding ->
        LazyColumn(modifier = Modifier.padding(padding).padding(16.dp)) {
            item {
                OutlinedTextField(title, { title = it; save() }, label = { Text("Titel") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(notes, { notes = it; save() }, label = { Text("Notizen") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Row(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
                    Text("Fälligkeit", modifier = Modifier.weight(1f))
                    Switch(dueEnabled, { dueEnabled = it; save() })
                }
                if (dueEnabled) {
                    OutlinedTextField(dueDate, { dueDate = it; save() }, label = { Text("Datum (YYYY-MM-DD)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                    OutlinedTextField(dueTime, { dueTime = it; save() }, label = { Text("Uhrzeit (HH:MM, optional)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                }
                var expanded by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }, modifier = Modifier.padding(top = 12.dp)) {
                    OutlinedTextField(
                        RECURRENCE_CHOICES[recIndex].second, {}, label = { Text("Wiederholen") },
                        readOnly = true, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
                        modifier = Modifier.menuAnchor().fillMaxWidth(),
                    )
                    ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                        RECURRENCE_CHOICES.forEachIndexed { i, (_, label) ->
                            DropdownMenuItem(text = { Text(label) }, onClick = { recIndex = i; expanded = false; save() })
                        }
                    }
                }
            }
            item { Text("Teilaufgaben", modifier = Modifier.padding(top = 16.dp)) }
            items(subs, key = { it.uid }) { s ->
                Row(modifier = Modifier.fillMaxWidth()) {
                    Checkbox(s.completed, {
                        scope.launch(Dispatchers.IO) {
                            val now = utcNow()
                            app.db.taskDao().setStatus(s.uid, if (s.completed) "NEEDS-ACTION" else "COMPLETED", if (s.completed) 0 else 100, now)
                            reload()
                        }
                    })
                    Text(s.title, modifier = Modifier.weight(1f))
                }
            }
            item {
                TextButton(onClick = {
                    scope.launch(Dispatchers.IO) {
                        app.db.taskDao().upsert(
                            TaskEntity(listUid = task?.listUid ?: "", title = "Neue Teilaufgabe", parentUid = uid, created = utcNow(), modified = utcNow())
                        )
                        reload()
                    }
                }) { Icon(Icons.Default.Add, null); Text("Teilaufgabe hinzufügen") }
            }
        }
    }

    if (showDelete) {
        AlertDialog(
            onDismissRequest = { showDelete = false },
            title = { Text("Erinnerung löschen?") },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch(Dispatchers.IO) {
                        app.db.taskDao().tombstone(uid, utcNow())
                        app.db.taskDao().purgeDeleted()
                    }
                    nav.popBackStack()
                }) { Text("Löschen") }
            },
            dismissButton = { TextButton(onClick = { showDelete = false }) { Text("Abbrechen") } },
        )
    }
}
