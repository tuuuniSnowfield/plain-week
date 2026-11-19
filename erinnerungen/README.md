# Erinnerungen (native app)

A minimal, private to-do app — a clone of Apple's **Reminders** — for Linux
(GTK4/libadwaita, feels like a native GNOME app) and Android (Kotlin/Compose).
Deliberately 1:1 in features, nothing more.

**No account. No cloud. No telemetry. GPLv3. Privacy by design.**

Standalone open-source project, licensed under [GPLv3](LICENSE).

## Features

- **Lists** with color and icon
- **Quick entry**: type a title, optionally date/time/list — e.g.
  `Milch kaufen morgen 18 Uhr !Einkaufen`, `Zahnarzt übermorgen 9:30`,
  `Bericht in 3 Tagen #Arbeit`, `Miete am 01.06. in Haushalt`
  (German natural-language input, see `desktop/erinnerungen/quickadd.py`)
- **Local notifications** on due date + time
- **Recurring tasks**: daily, weekly, monthly, *last day of the month* (RRULE, RFC 5545)
- **Subtasks**, **notes** per task, **checkbox** to tick off
- **Smart lists**: Heute (Today), Geplant (Scheduled), Alle (All)
- Dark mode automatic (libadwaita / Material 3), compact typography

## Layout

- `desktop/` — Linux desktop app (Python 3, GTK4/libadwaita)
- `android/` — Android app (Kotlin, Jetpack Compose, Room, WorkManager) — F-Droid-compatible
- `spec/DATA-MODEL.md` — shared specification both platforms implement
  (same SQLite schema, same ICS mapping, same RRULE subset, same CalDAV endpoints)

## Data & sync

- **Offline-first**: local SQLite is the source of truth — the app works fully
  without network.
- **CalDAV (standard, RFC 4791/5545, VTODO)**: the server is configured by the user
  — Radicale, Nextcloud, Baïkal, any self-hosted server. One list = one calendar,
  one task = one VTODO.
- **Local folder mode (fallback)**: one `.ics` file per list in a chosen folder.
- **HTTPS certificate pinning** for home servers with self-signed certs
  (SPKI or certificate pin, *in addition to* normal CA verification — never instead).

### Setup in under 60 seconds

1. Start the app → **Settings** (☰)
2. Mode **CalDAV server**, enter URL, username, password
3. **Test connection** → done. The password is stored in the GNOME Keyring
   (Secret Service) on Linux / EncryptedSharedPreferences on Android — never plaintext.

### Certificate pin for self-signed home servers

```sh
openssl x509 -in cert.pem -pubkey -noout | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -binary | base64
# enter the result as "sha256/<base64>" in the app's TLS settings
```

Alternatively provide your own CA bundle (PEM). `http://` is refused
(except localhost with an explicit opt-in).

## Security & privacy

- Password only in the OS keyring (libsecret / EncryptedSharedPreferences);
  without a keyring it is asked for at every start, nothing is stored.
- TLS verification always on; optional additional pinning (see `SECURITY.md`).
- No trackers, no analytics, no network access except the configured CalDAV
  server or the local folder.
- SQLite: WAL, foreign keys, parameterized queries only.

## Build (automated)

```sh
./build.sh           # check + Linux executable + Android APK  -> dist/
./build.sh check     # only unit tests + lint + prerequisite report
./build.sh linux     # only dist/linux/  (PyInstaller onedir + launcher, needs python3-gi/GTK4/libadwaita)
./build.sh android   # only dist/android/erinnerungen-1.0.0.apk (needs JDK 17 + ANDROID_HOME)
```

On Windows use `build.bat` with the same modes — `linux` is delegated to WSL, `android` runs `gradlew :app:assembleRelease`.

## Development

```sh
cd desktop
pip install -e ".[test]"        # python-dateutil + pytest
python3 -m pytest tests/ -q      # core tests (run without GTK)
# GUI (needs system packages: python3-gi gir1.2-gtk-4.0 gir1.2-adw-1, libadwaita >= 1.5 / GNOME 45+):
glib-compile-schemas data/
python3 -m erinnerungen.app
```

All business logic (DB, ICS, RRULE, CalDAV, quick-add, notification logic) lives in
core modules **without** GTK imports and is covered by pytest — including the
CalDAV client against a loopback stub and TLS pinning tests with a self-signed
certificate. The GTK modules (`app.py`, `window.py`, `widgets.py`, `detail.py`,
`dialogs.py`) are thin and need a GNOME system to run.

Android: see [android/README.md](android/README.md).

## Platforms

1. **Linux desktop (GTK4/libadwaita)** — done, in `desktop/`
2. **Android (Kotlin)** — in `android/`, F-Droid build without proprietary deps
3. **Windows** — later (WinUI or platform-neutral via libical), against `spec/DATA-MODEL.md`

## License

[GPLv3](LICENSE) — see `SECURITY.md` for reporting vulnerabilities.
