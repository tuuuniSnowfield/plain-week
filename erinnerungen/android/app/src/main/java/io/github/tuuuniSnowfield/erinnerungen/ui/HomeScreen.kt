package io.github.tuuuniSnowfield.erinnerungen.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import io.github.tuuuniSnowfield.erinnerungen.ReminderApp
import io.github.tuuuniSnowfield.erinnerungen.core.QuickAdd
import io.github.tuuuniSnowfield.erinnerungen.core.Recurrence
import io.github.tuuuniSnowfield.erinnerungen.data.ListEntity
import io.github.tuuuniSnowfield.erinnerungen.data.TaskEntity
import io.github.tuuuniSnowfield.erinnerungen.data.utcNow
import io.github.tuuuniSnowfield.erinnerungen.notify.Notify
import io.github.tuuuniSnowfield.erinnerungen.sync.Backend
import io.github.tuuuniSnowfield.erinnerungen.sync.CalDavBackend
import io.github.tuuuniSnowfield.erinnerungen.sync.FolderBackend
import io.github.tuuuniSnowfield.erinnerungen.sync.SyncEngine
import io.github.tuuuniSnowfield.erinnerungen.sync.CalDavClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val SMART = listOf("today" to "Heute", "scheduled" to "Geplant", "all" to "Alle")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(app: ReminderApp, nav: NavController) {
    var lists by remember { mutableStateOf<List<ListEntity>>(emptyList()) }
    var tasks by remember { mutableStateOf<List<TaskEntity>>(emptyList()) }
    var current by remember { mutableStateOf<Pair<String, String?>>("today" to null) } // kind to listUid
    var title by remember { mutableStateOf("Heute") }
    var quickText by remember { mutableStateOf("") }
    var showNewList by remember { mutableStateOf(false) }
    var menuOpen by remember { mutableStateOf(false) }
    val drawerState = rememberDrawerState(initialValue = androidx.compose.material3.DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    suspend fun reload() {
        withContext(Dispatchers.IO) {
            lists = app.db.listDao().all()
            val today = LocalDate.now()
            val endOfDay = "$today 23:59"
            val now = LocalDateTime.now()
            val nowStr = "$today " + now.toLocalTime().format(DateTimeFormatter.ofPattern("HH:mm"))
            tasks = when (current.first) {
                "today" -> app.db.taskDao().dueToday(endOfDay)
                "scheduled" -> app.db.taskDao().scheduled(endOfDay)
                "all" -> app.db.taskDao().allOpen()
                else -> current.second?.let { app.db.taskDao().inList(it) } ?: emptyList()
            }
            title = if (current.first == "list") lists.firstOrNull { it.uid == current.second }?.name ?: ""
            else SMART.first { it.first == current.first }.second
        }
    }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            if (app.db.listDao().all().isEmpty()) {
                app.db.listDao().upsert(
                    ListEntity(name = "Erinnerungen", created = utcNow(), modified = utcNow())
                )
            }
        }
        Notify.fireDue(app, app)
        reload()
    }

    fun backend(): Backend? = kotlinx.coroutines.runBlocking {
        val mode = app.settings.syncMode.first()
        when (mode) {
            "folder" -> {
                val p = app.settings.folderPath.first()
                val dir = if (p.isNotBlank()) File(p) else File(app.getExternalFilesDir(null), "ics")
                FolderBackend(dir)
            }
            "caldav" -> {
                val url = app.settings.serverUrl.first()
                val user = app.settings.username.first()
                if (url.isBlank() || user.isBlank()) return@runBlocking null
                val pw = app.settings.loadPassword(user) ?: return@runBlocking null
                CalDavBackend(
                    CalDavClient(
                        url, user, pw,
                        caFile = app.settings.caFile.first().ifBlank { null },
                        pin = app.settings.certPin.first().ifBlank { null },
                    )
                )
            }
            else -> null
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("Bibliothek", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
                SMART.forEach { (key, name) ->
                    Text(name, modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            current = key to null
                            scope.launch { reload(); drawerState.close() }
                        }
                        .padding(vertical = 10.dp))
                }
                Text("Listen", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 12.dp))
                lists.forEach { l ->
                    Row(modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            current = "list" to l.uid
                            scope.launch { reload(); drawerState.close() }
                        }
                        .padding(vertical = 10.dp)) {
                        Text(l.icon.ifBlank { "●" }, color = Color(android.graphics.Color.parseColor(l.color)))
                        Text(l.name, modifier = Modifier.padding(start = 8.dp))
                    }
                }
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text(title) },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) { Icon(Icons.Default.Menu, "Menü") }
                    },
                    actions = {
                        IconButton(onClick = {
                            scope.launch(Dispatchers.IO) {
                                backend()?.let { SyncEngine(app.db, it).sync() }
                                reload()
                            }
                        }) { Icon(Icons.Default.Refresh, "Synchronisieren") }
                        IconButton(onClick = { menuOpen = true }) { Icon(Icons.Default.MoreVert, "Mehr") }
                        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                            DropdownMenuItem(text = { Text("Neue Liste …") }, onClick = { menuOpen = false; showNewList = true })
                            DropdownMenuItem(text = { Text("Einstellungen") }, onClick = { menuOpen = false; nav.navigate("settings") })
                        }
                    },
                )
            },
        ) { padding ->
            Column(modifier = Modifier.padding(padding)) {
                OutlinedTextField(
                    value = quickText,
                    onValueChange = { quickText = it },
                    placeholder = { Text("Neue Erinnerung … z. B. »Milch morgen 18 Uhr !Einkaufen«") },
                    leadingIcon = { Icon(Icons.Default.Add, null) },
                    singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Done),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(onDone = {
                        val text = quickText.trim()
                        if (text.isNotEmpty()) {
                            scope.launch(Dispatchers.IO) {
                                val parsed = QuickAdd.parse(text, lists.map { it.name })
                                if (parsed.title.isNotBlank()) {
                                    var listUid = if (current.first == "list") current.second else null
                                    if (parsed.listName != null) {
                                        listUid = lists.firstOrNull { it.name == parsed.listName }?.uid
                                    }
                                    if (listUid == null) {
                                        listUid = (app.db.listDao().all().firstOrNull()?.uid
                                            ?: app.db.listDao().let {
                                                val l = ListEntity(name = "Erinnerungen", created = utcNow(), modified = utcNow())
                                                it.upsert(l); l.uid
                                            })
                                    }
                                    app.db.taskDao().upsert(
                                        TaskEntity(
                                            listUid = listUid, title = parsed.title,
                                            due = QuickAdd.toDueString(parsed.day, parsed.clock),
                                            created = utcNow(), modified = utcNow(),
                                        )
                                    )
                                    reload()
                                }
                            }
                            quickText = ""
                        }
                    }),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                )
                LazyColumn(modifier = Modifier.weight(1f)) {
                    items(tasks, key = { it.uid }) { t ->
                        TaskRow(t, onToggle = {
                            scope.launch(Dispatchers.IO) {
                                toggle(app, t.uid)
                                reload()
                            }
                        }, onOpen = { nav.navigate("task/${t.uid}") })
                    }
                }
            }
        }
    }

    if (showNewList) {
        NewListDialog(app) { showNewList = false; scope.launch { reload() } }
    }
}

private suspend fun toggle(app: ReminderApp, uid: String) {
    val t = app.db.taskDao().byUid(uid) ?: return
    val now = utcNow()
    if (t.completed) {
        app.db.taskDao().setStatus(uid, "NEEDS-ACTION", 0, now)
    } else if (!t.rrule.isNullOrBlank()) {
        val due = t.due
        val d = due?.split(" ")?.get(0)?.let { LocalDate.parse(it) } ?: LocalDate.now()
        val tm = due?.split(" ")?.getOrNull(1)?.let { LocalTime.parse(it) }
        val base = LocalDateTime.of(d, tm ?: LocalTime.MIN)
        val nxt = Recurrence.nextAfter(t.rrule, base, base)
        if (nxt == null) app.db.taskDao().setStatus(uid, "COMPLETED", 100, now)
        else {
            val dueStr = if (tm != null) {
                "${nxt.toLocalDate()} ${nxt.toLocalTime().format(DateTimeFormatter.ofPattern("HH:mm"))}"
            } else nxt.toLocalDate().toString()
            app.db.taskDao().setDue(uid, dueStr, now)
        }
    } else {
        app.db.taskDao().setStatus(uid, "COMPLETED", 100, now)
    }
}

@Composable
private fun TaskRow(t: TaskEntity, onToggle: () -> Unit, onOpen: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Checkbox(checked = t.completed, onCheckedChange = { onToggle() })
        Column {
            Text(
                t.title,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textDecoration = if (t.completed) TextDecoration.LineThrough else null,
                color = if (t.completed) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.onSurface,
            )
            val sub = buildString {
                t.due?.let { append(formatDueHuman(it)) }
                t.rrule?.let { if (isNotEmpty()) append("  ·  "); append("🔁 ${Recurrence.describe(it)}") }
            }
            if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
        }
    }
}

fun formatDueHuman(due: String): String {
    val now = LocalDate.now()
    val p = due.split(" ")
    val d = LocalDate.parse(p[0])
    val datePart = when (d) {
        now -> "Heute"
        now.plusDays(1) -> "Morgen"
        else -> d.format(DateTimeFormatter.ofPattern("EEE, dd.MM.", java.util.Locale.GERMAN))
    }
    return if (p.size == 2) "$datePart ${p[1]}" else datePart
}

@Composable
private fun NewListDialog(app: ReminderApp, onDone: () -> Unit) {
    var name by remember { mutableStateOf("") }
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDone,
        title = { Text("Neue Liste") },
        text = {
            OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Name") })
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = {
                if (name.isNotBlank()) {
                    kotlinx.coroutines.GlobalScope.launch(Dispatchers.IO) {
                        app.db.listDao().upsert(ListEntity(name = name.trim(), created = utcNow(), modified = utcNow()))
                    }
                }
                onDone()
            }) { Text("Anlegen") }
        },
        dismissButton = { androidx.compose.material3.TextButton(onClick = onDone) { Text("Abbrechen") } },
    )
}
