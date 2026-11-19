package io.github.tuuuniSnowfield.erinnerungen.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.tuuuniSnowfield.erinnerungen.R
import io.github.tuuuniSnowfield.erinnerungen.ReminderApp
import io.github.tuuuniSnowfield.erinnerungen.core.Recurrence
import io.github.tuuuniSnowfield.erinnerungen.data.utcNow
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/**
 * Local due-date notifications + periodic sync trigger.
 * Rule (spec/DATA-MODEL.md §7): notify when due <= now, status=NEEDS-ACTION,
 * notified != due; then set notified=due (once per due value).
 */
object Notify {
    const val CHANNEL_ID = "reminders"

    fun ensureChannel(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Erinnerungen", NotificationManager.IMPORTANCE_HIGH)
            )
        }
    }

    fun schedulePeriodic(context: Context) {
        val req = PeriodicWorkRequestBuilder<ReminderWorker>(15, TimeUnit.MINUTES).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "reminders", ExistingPeriodicWorkPolicy.KEEP, req
        )
    }

    suspend fun fireDue(app: ReminderApp, context: Context) {
        val now = LocalDateTime.now()
        val nowStr = now.toLocalDate().toString() + " " + now.toLocalTime().format(DateTimeFormatter.ofPattern("HH:mm"))
        val due = app.db.taskDao().dueReminders(nowStr)
        val nm = NotificationManagerCompat.from(context)
        val allowed = Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        for (t in due) {
            if (allowed) {
                val body = buildString {
                    t.rrule?.let { append(Recurrence.describe(it)) }
                    t.due?.let {
                        if (isNotEmpty()) append(" – ")
                        append(it.replace("T", " ").replace("-", ".").let { s ->
                            // "2024-05-10 09:00" → "10.05.2024 09:00 Uhr"
                            val p = s.split(" ")
                            val d = p[0].split("-")
                            if (p.size == 2) "${d[2]}.${d[1]}.${d[0]} ${p[1]} Uhr" else "${d[2]}.${d[1]}.${d[0]}"
                        })
                    }
                }
                nm.notify(t.uid.hashCode(), NotificationCompat.Builder(context, CHANNEL_ID)
                    .setSmallIcon(R.drawable.ic_launcher)
                    .setContentTitle(t.title)
                    .setContentText(body)
                    .setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setAutoCancel(true)
                    .build())
            }
            app.db.taskDao().markNotified(t.uid, t.due)
        }
    }
}

class ReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as ReminderApp
        Notify.ensureChannel(applicationContext)
        Notify.fireDue(app, applicationContext)
        return Result.success()
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Notify.schedulePeriodic(context)
        }
    }
}
