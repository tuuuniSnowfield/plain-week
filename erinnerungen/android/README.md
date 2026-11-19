# Erinnerungen — Android (Kotlin)

Android port of the native Reminders clone. Implements `../spec/DATA-MODEL.md`
(same SQLite schema, same ICS mapping, same RRULE subset, same CalDAV endpoints)
as the desktop reference in `../desktop/`.

- **UI**: Jetpack Compose + Material 3 (dark mode follows system), German UI strings
- **Storage**: Room (SQLite), offline-first — local DB is the source of truth
- **Sync**: CalDAV VTODO (RFC 4791/5545) with HTTPS + optional certificate pinning
  (`sha256/<base64>` SPKI or 64-hex cert SHA-256), or a local folder of `.ics` files
- **Secrets**: password only in EncryptedSharedPreferences (Android Keystore)
- **Notifications**: WorkManager periodic (15 min) + boot receiver; exact due handling
- **No proprietary dependencies** — F-Droid compatible (google()/mavenCentral() only)

## Build

```sh
cd android
./gradlew assembleRelease        # or: gradle wrapper, then assembleRelease
```

Requires JDK 17 and Android SDK (compileSdk 35, minSdk 26). Not compiled in CI yet
(no Android SDK on the runner) — desktop core tests run in
`.github/workflows/erinnerungen-tests.yml`.

## F-Droid

Standard Gradle project, no Google services, no Firebase, minify off, GPLv3
(see `../LICENSE`). Sign with F-Droid's standard key handling; no extra metadata
needed beyond the usual `fastlane/metadata/android/`.

## Structure

- `data/` — Room entities/DAOs (schema = spec), DataStore settings, encrypted secrets
- `core/` — Ics, Recurrence, QuickAdd (ports of the desktop Python modules, pytest-covered there)
- `sync/` — CalDav client (TLS+pinning), folder backend, SyncEngine (LWW)
- `notify/` — ReminderWorker, BootReceiver, notification helper
- `ui/` — Home (smart lists + lists + quick-add + tasks), Detail (title/notes/due/recurrence/subtasks), Settings
