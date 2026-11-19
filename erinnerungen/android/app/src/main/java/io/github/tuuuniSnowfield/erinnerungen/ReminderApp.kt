package io.github.tuuuniSnowfield.erinnerungen

import android.app.Application
import androidx.room.Room
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import io.github.tuuuniSnowfield.erinnerungen.data.AppDatabase
import io.github.tuuuniSnowfield.erinnerungen.data.SettingsRepo
import io.github.tuuuniSnowfield.erinnerungen.notify.ReminderWorker
import java.util.concurrent.TimeUnit

class ReminderApp : Application() {
    val db: AppDatabase by lazy {
        Room.databaseBuilder(this, AppDatabase::class.java, "erinnerungen.db")
            .fallbackToDestructiveMigration() // schema v1; migrations go here when bumping
            .build()
    }
    val settings: SettingsRepo by lazy { SettingsRepo(this) }

    override fun onCreate() {
        super.onCreate()
        // periodic due-check (offline-first local notifications + sync trigger)
        val req = PeriodicWorkRequestBuilder<ReminderWorker>(15, TimeUnit.MINUTES).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "reminders", ExistingPeriodicWorkPolicy.KEEP, req
        )
    }
}
