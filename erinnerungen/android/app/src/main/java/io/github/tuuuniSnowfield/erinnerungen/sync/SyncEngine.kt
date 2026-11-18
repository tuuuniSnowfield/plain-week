package io.github.tuuuniSnowfield.erinnerungen.sync

import io.github.tuuuniSnowfield.erinnerungen.core.Ics
import io.github.tuuuniSnowfield.erinnerungen.data.AppDatabase
import io.github.tuuuniSnowfield.erinnerungen.data.ListEntity
import io.github.tuuuniSnowfield.erinnerungen.data.TaskEntity
import io.github.tuuuniSnowfield.erinnerungen.data.utcNow
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * Offline-first sync engine — port of desktop/erinnerungen/sync.py.
 * Local DB is authoritative; last-write-wins by LAST-MODIFIED (modified).
 * Backends: CalDAV (one calendar per list) or a local folder of .ics files.
 */
interface Backend {
    suspend fun discoverLists(): List<Pair<String, String>> // (path, name)
    suspend fun ensureList(path: String?, name: String, color: String?, icon: String?): String
    suspend fun fetchTasks(path: String): List<Triple<String, String?, String>> // (uid, etag, vtodo block)
    suspend fun upload(path: String, uid: String, vtodoBlock: String, etag: String?): String
    suspend fun remove(path: String, uid: String, etag: String?)
}

class CalDavBackend(private val client: CalDavClient) : Backend {
    private var home: String? = null
    private fun home(): String = home ?: client.discoverHome().also { home = it }

    override suspend fun discoverLists() = client.listCalendars(home()).map { it.path to it.displayName }

    override suspend fun ensureList(path: String?, name: String, color: String?, icon: String?): String {
        if (path != null) return path
        val slug = name.lowercase().replace(Regex("[^\\w\\-]+"), "-").trim('-').ifBlank { "liste" } + "/"
        val newPath = home().trimEnd('/') + "/" + slug
        try { client.mkcalendar(newPath, name) } catch (e: CalDavClient.HttpError) { if (e.status !in setOf(405, 301)) throw e }
        return newPath
    }

    override suspend fun fetchTasks(path: String) =
        client.queryTodos(path).flatMap { item ->
            Ics.parseCalendar(item.data ?: "").map { it.uid to Triple(it.uid, item.etag, Ics.serializeVtodo(it)) }
        }

    override suspend fun upload(path: String, uid: String, vtodoBlock: String, etag: String?) =
        client.putTodo(path, "$uid.ics", CalDavClient.wrapCalendar(vtodoBlock), etag)

    override suspend fun remove(path: String, uid: String, etag: String?) =
        client.deleteTodo(path, "$uid.ics", etag)
}

class FolderBackend(private val root: File) : Backend {
    init { root.mkdirs() }

    private fun slug(name: String) =
        name.lowercase().replace(Regex("[^\\w\\-]+"), "-").trim('-').ifBlank { "liste" } + ".ics"

    private fun etagOf(f: File) = "${f.lastModified()}:${f.length()}"

    override suspend fun discoverLists(): List<Pair<String, String>> =
        root.listFiles { f -> f.extension.equals("ics", ignoreCase = true) }?.sortedBy { it.name }?.map { f ->
            f.name to (Ics.parseCalendarProps(f.readText()).let { it[Ics.LIST_NAME_PROP] ?: f.nameWithoutExtension })
        } ?: emptyList()

    override suspend fun ensureList(path: String?, name: String, color: String?, icon: String?): String {
        val fname = path ?: slug(name)
        val f = File(root, fname)
        if (!f.exists()) f.writeText(Ics.serializeCalendar(emptyList(), name, color, icon))
        return fname
    }

    override suspend fun fetchTasks(path: String): List<Triple<String, String?, String>> {
        val f = File(root, path)
        if (!f.exists()) return emptyList()
        val text = f.readText()
        val etag = etagOf(f)
        return Ics.vtodoBlocks(text).map { (uid, block) -> Triple(uid, etag, block) }
    }

    override suspend fun upload(path: String, uid: String, vtodoBlock: String, etag: String?): String {
        val f = File(root, path)
        require(f.exists()) { "missing $path" }
        if (etag != null && etag != etagOf(f)) throw SyncConflict("File was changed in the meantime")
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.writeText(Ics.replaceVtodoBlock(f.readText(), uid, vtodoBlock))
        tmp.renameTo(f)
        return etagOf(f)
    }

    override suspend fun remove(path: String, uid: String, etag: String?) {
        val f = File(root, path)
        if (!f.exists()) return
        if (etag != null && etag != etagOf(f)) throw SyncConflict("File was changed in the meantime")
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.writeText(Ics.removeVtodoBlock(f.readText(), uid))
        tmp.renameTo(f)
    }
}

class SyncConflict(msg: String) : Exception(msg)

data class SyncReport(var pushed: Int = 0, var pulled: Int = 0, var remoteDeleted: Int = 0, var lwwRemoteWins: Int = 0, val errors: MutableList<String> = mutableListOf())

class SyncEngine(private val db: AppDatabase, private val backend: Backend) {

    private val iso = DateTimeFormatter.ISO_LOCAL_DATE_TIME

    private fun parseUtc(s: String): LocalDateTime =
        LocalDateTime.parse(s.removeSuffix("Z"), iso)

    private fun taskToVtodo(t: TaskEntity): Ics.VTodo {
        val dueParts = t.due?.split(" ")
        val d = dueParts?.get(0)?.let { LocalDate.parse(it) }
        val tm = dueParts?.getOrNull(1)?.let { LocalTime.parse(it) }
        return Ics.VTodo(
            uid = t.uid, summary = t.title, description = t.notes,
            dueDate = d, dueTime = tm, rrule = t.rrule, status = t.status, percent = t.percent,
            relatedParents = t.parentUid?.let { mutableListOf(it) } ?: mutableListOf(),
            sequence = t.sequence,
            created = runCatching { parseUtc(t.created) }.getOrNull(),
            modified = runCatching { parseUtc(t.modified) }.getOrNull() ?: LocalDateTime.now(),
        )
    }

    private fun vtodoToTask(v: Ics.VTodo, listUid: String): TaskEntity {
        val modified = v.modified ?: LocalDateTime.now()
        return TaskEntity(
            uid = v.uid, listUid = listUid, title = v.summary, notes = v.description,
            due = v.due, rrule = v.rrule,
            status = v.status.ifBlank { "NEEDS-ACTION" }, percent = v.percent,
            parentUid = v.relatedParents.firstOrNull(), etag = null,
            created = (v.created ?: modified).format(iso) + "Z",
            modified = modified.format(iso) + "Z",
            sequence = v.sequence, dirty = 0, deleted = 0, notified = null,
        )
    }

    suspend fun sync(): SyncReport {
        val report = SyncReport()
        val byName = backend.discoverLists().toMap()
        for (lst in db.listDao().all()) {
            if (lst.deleted == 1) continue
            try {
                syncList(lst, byName, report)
            } catch (e: Exception) {
                report.errors.add("${lst.name}: ${e.message}")
            }
        }
        return report
    }

    private suspend fun syncList(lst: ListEntity, byName: Map<String, String>, report: SyncReport) {
        val path = lst.remotePath ?: byName[lst.name] ?: backend.ensureList(null, lst.name, lst.color, lst.icon)
        db.listDao().markSynced(lst.uid, path)

        val remote = backend.fetchTasks(path).associateBy { it.first }
        val localAll = db.taskDao().inList(lst.uid)

        // pull
        for ((uid, item) in remote) {
            val (_, etag, block) = item
            val v = Ics.parseCalendar(block).firstOrNull() ?: continue
            val localTask = db.taskDao().byUid(uid)
            val remoteModified = v.modified ?: LocalDateTime.now()
            when {
                localTask == null -> {
                    db.taskDao().upsert(vtodoToTask(v, lst.uid).copy(etag = etag)); report.pulled++
                }
                localTask.deleted == 1 && localTask.dirty == 0 -> {
                    db.taskDao().upsert(vtodoToTask(v, lst.uid).copy(etag = etag)); report.pulled++
                }
                localTask.dirty == 0 && remoteModified > parseUtc(localTask.modified) -> {
                    db.taskDao().upsert(vtodoToTask(v, lst.uid).copy(etag = etag)); report.pulled++
                }
                localTask.dirty == 1 && remoteModified > parseUtc(localTask.modified) -> {
                    db.taskDao().upsert(vtodoToTask(v, lst.uid).copy(etag = etag)); report.lwwRemoteWins++
                }
            }
        }

        // deleted remotely?
        for (t in localAll) {
            if (t.uid !in remote && t.dirty == 0 && t.deleted == 0) {
                db.taskDao().markDeletedLocal(t.uid, utcNow()); report.remoteDeleted++
            }
        }

        // push dirty (incl. tombstones)
        val dirty = db.taskDao().dirty().filter { it.listUid == lst.uid }
        for (t in dirty) {
            if (t.deleted == 1) {
                if (t.etag != null) {
                    try {
                        backend.remove(path, t.uid, t.etag); db.taskDao().purgeDeleted(); report.pushed++
                    } catch (e: Exception) { report.errors.add("delete ${t.uid}: ${e.message}") }
                } else db.taskDao().purgeDeleted()
                continue
            }
            try {
                val etag = backend.upload(path, t.uid, Ics.serializeVtodo(taskToVtodo(t)), t.etag)
                db.taskDao().markSynced(t.uid, etag); report.pushed++
            } catch (e: Exception) {
                report.errors.add("upload ${t.uid}: ${e.message}")
            }
        }
    }
}
