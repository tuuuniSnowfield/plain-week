"""Application entry point (GTK4/libadwaita). All logic lives in the GI-free
core modules (db, sync, caldav, ...) – this layer is thin: UI + scheduling only."""
from __future__ import annotations

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import constants, notify, secrets  # noqa: E402
from .caldav import CalDAVBackend, CalDAVClient  # noqa: E402
from .db import Database  # noqa: E402
from .folder import FolderBackend  # noqa: E402
from .sync import SyncEngine  # noqa: E402
from .window import MainWindow  # noqa: E402


class ErinnerungenApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=constants.APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.db: Database | None = None
        self.settings: Gio.Settings | None = None
        self._sync_lock = threading.Lock()

    def do_startup(self):
        super().do_startup()
        self.settings = Gio.Settings.new(constants.APP_ID)
        data_dir = os.path.join(GLib.get_user_data_dir(), "erinnerungen")
        os.makedirs(data_dir, exist_ok=True)
        self.db = Database(os.path.join(data_dir, "erinnerungen.db"))
        if not self.db.lists():
            self.db.add_list("Erinnerungen")
        self._install_actions()
        GLib.timeout_add_seconds(30, self._notify_tick)
        GLib.timeout_add_seconds(3, self._initial_sync)

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            win = MainWindow(self)
        win.present()

    def _install_actions(self):
        for name, cb in (("sync", self.on_sync), ("preferences", self.on_preferences),
                         ("about", self.on_about), ("quit", lambda *_: self.quit())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

    # --- Benachrichtigungen ------------------------------------------------

    def _notify_tick(self):
        if self.db is None:
            return True
        for task in notify.fire_due(self.db):
            n = Gio.Notification.new(notify.notification_title(task))
            body = notify.notification_body(task)
            if body:
                n.set_body(body)
            n.set_priority(Gio.NotificationPriority.URGENT)
            self.send_notification(task.uid, n)
        return True

    def _initial_sync(self):
        self.sync_now(show_toast=False)
        return False

    # --- Sync ---------------------------------------------------------------

    def make_backend(self):
        """Backend aus den Einstellungen; None = rein lokal."""
        mode = self.settings.get_string("sync-mode")
        if mode == "folder":
            path = self.settings.get_string("folder-path")
            return FolderBackend(path) if path else None
        url = self.settings.get_string("server-url")
        user = self.settings.get_string("username")
        if not url or not user:
            return None
        password = None
        try:
            password = secrets.load_password(constants.APP_ID, user)
        except secrets.SecretsUnavailable:
            password = None
        if password is None:
            from .dialogs import prompt_password

            win = self.props.active_window
            password = prompt_password(win, user) if win else None
            if password is None:
                return None
            import contextlib

            with contextlib.suppress(secrets.SecretsUnavailable):
                secrets.store_password(constants.APP_ID, user, password)
        client = CalDAVClient(
            url,
            user,
            password,
            ca_file=self.settings.get_string("ca-file") or None,
            pin=self.settings.get_string("cert-pin") or None,
        )
        return CalDAVBackend(client)

    def sync_now(self, show_toast=True):
        if self.db is None or not self._sync_lock.acquire(blocking=False):
            return
        # make_backend() may show a password prompt → must run on the main thread
        try:
            backend = self.make_backend()
        except Exception:
            self._sync_lock.release()
            return
        if backend is None:
            self._sync_lock.release()
            return

        def work():
            try:
                report = SyncEngine(self.db, backend).sync()

                def done():
                    win = self.props.active_window
                    if win is not None:
                        win.reload()
                        if show_toast:
                            if report.errors:
                                win.show_toast(f"Sync: {len(report.errors)} Fehler")
                            else:
                                win.show_toast(
                                    f"Sync: {report.pushed} gesendet, {report.pulled} empfangen"
                                )
                    self._sync_lock.release()

                GLib.idle_add(done)
            except Exception:
                self._sync_lock.release()

        threading.Thread(target=work, daemon=True).start()

    def on_sync(self, *_):
        self.sync_now()

    # --- Dialoge -------------------------------------------------------------

    def on_preferences(self, *_):
        from .dialogs import SettingsDialog

        win = self.props.active_window
        if win:
            SettingsDialog(self, win).present()

    def on_about(self, *_):
        win = self.props.active_window
        if win:
            d = Adw.AboutDialog(
                application_name=constants.APP_NAME,
                application_icon=constants.APP_ID,
                developer_name="tuuuniSnowfield",
                version=constants.APP_VERSION,
                license_type=Gtk.License.GPL_3_0,
                website=constants.APP_WEBSITE,
            )
            d.set_comments(
                "Kein Account, keine Cloud, keine Telemetrie. Daten liegen lokal (SQLite) "
                "und optional auf deinem eigenen CalDAV-Server."
            )
            d.present(win)


def main():
    return ErinnerungenApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
