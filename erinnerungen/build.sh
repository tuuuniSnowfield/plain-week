#!/usr/bin/env bash
# Erinnerungen — build script (Linux/macOS shell)
# Usage: ./build.sh [all|linux|android|check]     (default: all)
#   check   -> run unit tests + lint, report missing build prerequisites
#   linux   -> build the Linux executable (PyInstaller onedir) into dist/linux/
#   android -> build the APK into dist/android/
#   all     -> check + linux + android
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
DIST="$ROOT/dist"
MODE="${1:-all}"

log()  { printf '[build] %s\n' "$*"; }
warn() { printf '[warn]  %s\n' "$*" >&2; }
die()  { printf '[error] %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing tool: $1 — $2"; }

run_checks() {
  log "check: python3 + pip"
  need python3 "install Python 3.11+"
  python3 --version
  need pip3 "install pip"
  log "check: unit tests + lint (desktop core)"
  (cd desktop && python3 -m pip install -q pytest ruff python-dateutil \
    && python3 -m pytest tests/ -q && ruff check .)
  log "prerequisites for the full build:"
  if python3 -c "import gi" 2>/dev/null; then
    log "  python3-gi: OK"
  else
    warn "  python3-gi missing — Linux GUI build needs system packages:"
    warn "    Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libglib2.0-bin"
    warn "    Fedora:        sudo dnf install python3-gobject gtk4 libadwaita glib2-devel"
  fi
  if command -v java >/dev/null 2>&1; then
    java -version 2>&1 | head -1 | sed 's/^/  java: /'
  else
    warn "  java missing — Android build needs JDK 17"
  fi
  if [ -n "${ANDROID_HOME:-}" ]; then
    log "  ANDROID_HOME=$ANDROID_HOME"
  else
    warn "  ANDROID_HOME not set — Android build needs the Android SDK (compileSdk 35)"
  fi
}

build_linux() {
  need python3 "install Python 3.11+"
  need pip3 "install pip"
  python3 -c "import gi" 2>/dev/null || die "python3-gi + GTK4/libadwaita required (see ./build.sh check)"
  need glib-compile-schemas "install libglib2.0-bin (Debian/Ubuntu) or glib2-devel (Fedora)"
  log "linux: build venv + deps"
  python3 -m venv "$ROOT/.venv-build"
  "$ROOT/.venv-build/bin/pip" install -q python-dateutil pyinstaller
  log "linux: compile GSettings schema into the bundle"
  mkdir -p desktop/build/schemas
  cp desktop/data/*.gschema.xml desktop/build/schemas/
  glib-compile-schemas desktop/build/schemas
  cat > desktop/build/launcher.py <<'PY'
from erinnerungen.app import main

raise SystemExit(main())
PY
  log "linux: PyInstaller (onedir)"
  (cd desktop && "$ROOT/.venv-build/bin/pyinstaller" --noconfirm --clean --onedir \
      --name erinnerungen --paths . \
      --hidden-import gi --collect-submodules gi \
      --add-data "build/schemas:schemas" \
      build/launcher.py)
  mkdir -p "$DIST/linux"
  rm -rf "$DIST/linux/erinnerungen"
  cp -r desktop/dist/erinnerungen "$DIST/linux/erinnerungen"
  cat > "$DIST/linux/erinnerungen.sh" <<'SH'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export GSETTINGS_SCHEMA_DIR="$DIR/erinnerungen/schemas"
exec "$DIR/erinnerungen/erinnerungen" "$@"
SH
  chmod +x "$DIST/linux/erinnerungen.sh"
  rm -rf "$ROOT/.venv-build" desktop/build
  log "linux build OK -> $DIST/linux/  (start with: $DIST/linux/erinnerungen.sh)"
}

build_android() {
  need java "install JDK 17"
  [ -n "${ANDROID_HOME:-}" ] || die "ANDROID_HOME not set — point it to your Android SDK (compileSdk 35)"
  cd android
  if [ -x ./gradlew ]; then
    GRADLE=./gradlew
  elif command -v gradle >/dev/null 2>&1; then
    GRADLE=gradle
  else
    die "neither ./gradlew nor gradle found — run 'gradle wrapper' once on a machine with Gradle to generate the wrapper"
  fi
  log "android: $GRADLE :app:assembleRelease"
  "$GRADLE" :app:assembleRelease
  cd "$ROOT"
  mkdir -p "$DIST/android"
  cp android/app/build/outputs/apk/release/app-release.apk "$DIST/android/erinnerungen-1.0.0.apk"
  log "android build OK -> $DIST/android/erinnerungen-1.0.0.apk"
}

case "$MODE" in
  check)   run_checks ;;
  linux)   build_linux ;;
  android) build_android ;;
  all)     run_checks; build_linux; build_android ;;
  *)       die "usage: $0 [all|linux|android|check]" ;;
esac
