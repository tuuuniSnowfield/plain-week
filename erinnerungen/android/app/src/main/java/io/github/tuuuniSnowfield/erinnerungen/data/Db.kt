package io.github.tuuuniSnowfield.erinnerungen.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Update
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

fun utcNow(): String =
    SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
        timeZone = java.util.TimeZone.getTimeZone("UTC")
    }.format(Date())

fun newUid(): String = "${UUID.randomUUID().hex}@erinnerungen"

// Column names match spec/DATA-MODEL.md exactly (shared schema with the desktop app).
@Entity(tableName = "lists", indices = [Index("name")])
data class ListEntity(
    @PrimaryKey val uid: String = newUid(),
    val name: String,
    val color: String = "#3584e4",
    val icon: String = "●",
    val sort: Int = 0,
    @ColumnInfo(name = "remote_path") val remotePath: String? = null,
    val etag: String? = null,
    val created: String = utcNow(),
    val modified: String = utcNow(),
    val dirty: Int = 1,
    val deleted: Int = 0,
)

@Entity(
    tableName = "tasks",
    foreignKeys = [
        ForeignKey(ListEntity::class, ["uid"], ["list_uid"], ForeignKey.CASCADE),
        ForeignKey(TaskEntity::class, ["uid"], ["parent_uid"], ForeignKey.CASCADE),
    ],
    indices = [Index("list_uid"), Index("parent_uid"), Index("due")],
)
data class TaskEntity(
    @PrimaryKey val uid: String = newUid(),
    @ColumnInfo(name = "list_uid") val listUid: String,
    val title: String,
    val notes: String = "",
    val due: String? = null, // "YYYY-MM-DD" or "YYYY-MM-DD HH:MM" (floating local)
    val rrule: String? = null,
    val status: String = "NEEDS-ACTION",
    val percent: Int = 0,
    @ColumnInfo(name = "parent_uid") val parentUid: String? = null,
    val sort: Int = 0,
    val etag: String? = null,
    val created: String = utcNow(),
    val modified: String = utcNow(),
    val sequence: Int = 0,
    val dirty: Int = 1,
    val deleted: Int = 0,
    val notified: String? = null,
) {
    val completed: Boolean get() = status == "COMPLETED"
}

@Dao
interface ListDao {
    @Query("SELECT * FROM lists WHERE deleted=0 ORDER BY sort, name")
    suspend fun all(): List<ListEntity>

    @Query("SELECT * FROM lists WHERE uid=:uid")
    suspend fun byUid(uid: String): ListEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(l: ListEntity)

    @Query("UPDATE lists SET name=:name, color=:color, icon=:icon, modified=:modified, dirty=1 WHERE uid=:uid")
    suspend fun restyle(uid: String, name: String, color: String, icon: String, modified: String)

    @Query("UPDATE lists SET deleted=1, dirty=1, modified=:modified WHERE uid=:uid")
    suspend fun tombstone(uid: String, modified: String)

    @Query("UPDATE lists SET remote_path=:path, dirty=0 WHERE uid=:uid")
    suspend fun markSynced(uid: String, path: String)
}

@Dao
interface TaskDao {
    @Query("SELECT * FROM tasks WHERE list_uid=:listUid AND deleted=0 ORDER BY (status='COMPLETED'), due IS NULL, due, sort")
    suspend fun inList(listUid: String): List<TaskEntity>

    @Query("SELECT * FROM tasks WHERE parent_uid=:parentUid AND deleted=0 ORDER BY sort")
    suspend fun children(parentUid: String): List<TaskEntity>

    @Query("SELECT * FROM tasks WHERE uid=:uid")
    suspend fun byUid(uid: String): TaskEntity?

    // Smart list "Heute": due <= end of today, not completed
    @Query("SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL AND due <= :endOfDay ORDER BY due, sort")
    suspend fun dueToday(endOfDay: String): List<TaskEntity>

    // Smart list "Geplant": due after today, not completed
    @Query("SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL AND due > :endOfDay ORDER BY due, sort")
    suspend fun scheduled(endOfDay: String): List<TaskEntity>

    @Query("SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' ORDER BY due IS NULL, due, sort")
    suspend fun allOpen(): List<TaskEntity>

    // due reminders: due <= now and not yet notified for this due value
    @Query("SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL AND due <= :now AND (notified IS NULL OR notified != due) ORDER BY due")
    suspend fun dueReminders(now: String): List<TaskEntity>

    @Query("SELECT * FROM tasks WHERE dirty=1 ORDER BY modified")
    suspend fun dirty(): List<TaskEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(t: TaskEntity)

    @Query("UPDATE tasks SET title=:title, notes=:notes, due=:due, rrule=:rrule, status=:status, percent=:percent, parent_uid=:parentUid, modified=:modified, sequence=sequence+1, dirty=1, notified=CASE WHEN due != :due THEN NULL ELSE notified END WHERE uid=:uid")
    suspend fun update(
        uid: String, title: String, notes: String, due: String?, rrule: String?,
        status: String, percent: Int, parentUid: String?, modified: String,
    )

    @Query("UPDATE tasks SET status=:status, percent=:percent, modified=:modified, sequence=sequence+1, dirty=1 WHERE uid=:uid")
    suspend fun setStatus(uid: String, status: String, percent: Int, modified: String)

    @Query("UPDATE tasks SET due=:due, modified=:modified, dirty=1, notified=NULL WHERE uid=:uid")
    suspend fun setDue(uid: String, due: String?, modified: String)

    @Query("UPDATE tasks SET deleted=1, dirty=1, modified=:modified WHERE uid=:uid")
    suspend fun tombstone(uid: String, modified: String)

    @Query("UPDATE tasks SET dirty=0, etag=:etag WHERE uid=:uid")
    suspend fun markSynced(uid: String, etag: String?)

    @Query("UPDATE tasks SET notified=:due WHERE uid=:uid")
    suspend fun markNotified(uid: String, due: String?)

    @Query("DELETE FROM tasks WHERE deleted=1 AND dirty=0")
    suspend fun purgeDeleted()

    @Query("UPDATE tasks SET deleted=1, dirty=0, modified=:modified WHERE uid=:uid AND deleted=0")
    suspend fun markDeletedLocal(uid: String, modified: String)
}

@Database(entities = [ListEntity::class, TaskEntity::class], version = 1)
abstract class AppDatabase : RoomDatabase() {
    abstract fun listDao(): ListDao
    abstract fun taskDao(): TaskDao
}
