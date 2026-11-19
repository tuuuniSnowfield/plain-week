#!/usr/bin/env bash
# Erinnerungen — build script (Linux/macOS shell)
# Usage: ./build.sh [all|linux|android|portable|check]   (default: all)
#   check    -> unit tests + lint + prerequisite report
#   portable -> dist/linux/erinnerungen-1.0.0.pyz (zipapp; runs on any Linux with python3-gi/GTK4)
#   linux    -> dist/linux/ PyInstaller onedir bundle + launcher (needs python3-gi/GTK4/libadwaita)
#   android  -> dist/android/erinnerungen-1.0.0.apk (needs JDK 17 + ANDROID_HOME)
#   all      -> check + portable + linux + android (skips what lacks prerequisites, with warnings)
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

build_portable() {
  need python3 "install Python 3.11+"
  need pip3 "install pip"
  log "portable: vendor deps + zipapp"
  rm -rf desktop/build
  mkdir -p desktop/build/portable desktop/build/schemas
  cp -r desktop/erinnerungen desktop/build/portable/
  python3 -m pip install -q --target desktop/build/portable python-dateutil
  cp desktop/data/*.gschema.xml desktop/build/schemas/
  glib-compile-schemas desktop/build/schemas 2>/dev/null \
    || warn "glib-compile-schemas not found — schemas are bundled as XML and compiled at first start"
  cp desktop/build/schemas/* desktop/build/portable/ 2>/dev/null || true
  cat > desktop/build/portable/__main__.py <<'PY'
import os
import subprocess
import sys
import tempfile
import zipfile


def _ensure_schema_dir():
    if os.environ.get("GSETTINGS_SCHEMA_DIR"):
        return
    arc = os.path.abspath(__file__)
    while not arc.endswith(".pyz"):
        arc = os.path.dirname(arc)
    target = tempfile.mkdtemp(prefix="erinnerungen-schemas-")
    try:
        with zipfile.ZipFile(arc) as z:
            for name in z.namelist():
                if name.endswith(".gschema.xml") or name.endswith(".gschema.valid"):
                    z.extract(name, target)
        if not any(n.endswith(".gschema.valid") for n in os.listdir(target)):
            subprocess.run(["glib-compile-schemas", target], check=False)
        os.environ["GSETTINGS_SCHEMA_DIR"] = target
    except Exception:
        pass


try:
    import gi  # noqa: F401
except ImportError:
    sys.stderr.write(
        "erinnerungen needs the GNOME stack at runtime.\n"
        "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libglib2.0-bin\n"
        "  Fedora:        sudo dnf install python3-gobject gtk4 libadwaita glib2\n"
    )
    raise SystemExit(2)

_ensure_schema_dir()
from erinnerungen.app import main

raise SystemExit(main())
PY
  mkdir -p "$DIST/linux"
  python3 -m zipapp desktop/build/portable \
    -o "$DIST/linux/erinnerungen-1.0.0.pyz" -p "/usr/bin/env python3"
  rm -rf desktop/build
  log "portable build OK -> $DIST/linux/erinnerungen-1.0.0.pyz  (run: python3 erinnerungen-1.0.0.pyz)"
}

build_linux() {
  need python3 "install Python 3.11+"
  need pip3 "install pip"
  python3 -c "import gi" 2>/dev/null || { warn "python3-gi/GTK4/libadwaita missing — skipping linux bundle (use ./build.sh portable instead)"; return 1; }
  command -v glib-compile-schemas >/dev/null 2>&1 || { warn "glib-compile-schemas missing — skipping linux bundle"; return 1; }
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
  command -v java >/dev/null 2>&1 || { warn "java (JDK 17) missing — skipping android build"; return 1; }
  [ -n "${ANDROID_HOME:-}" ] || { warn "ANDROID_HOME not set — skipping android build"; return 1; }
  cd android
  if [ -x ./gradlew ]; then
    GRADLE=./gradlew
  elif command -v gradle >/dev/null 2>&1; then
    GRADLE=gradle
  else
    warn "neither ./gradlew nor gradle found — skipping android build (run 'gradle wrapper' once to generate the wrapper)"
    cd "$ROOT"
    return 1
  fi
  log "android: $GRADLE :app:assembleRelease"
  "$GRADLE" :app:assembleRelease
  cd "$ROOT"
  mkdir -p "$DIST/android"
  cp android/app/build/outputs/apk/release/app-release.apk "$DIST/android/erinnerungen-1.0.0.apk"
  log "android build OK -> $DIST/android/erinnerungen-1.0.0.apk"
}

case "$MODE" in
  check)    run_checks ;;
  portable) build_portable ;;
  linux)    build_linux ;;
  android)  build_android ;;
  all)
    run_checks
    build_portable
    build_linux || true
    build_android || true
    log "done -> artifacts in $DIST/"
    ;;
  *)        die "usage: $0 [all|linux|android|portable|check]" ;;
esac
