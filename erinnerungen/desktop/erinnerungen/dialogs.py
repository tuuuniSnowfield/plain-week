"""Dialogs: settings (server/folder/TLS), new list, password prompt.
Setup goal: URL + user + password in under 60 seconds."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from . import constants, secrets  # noqa: E402

LIST_COLORS = ["#3584e4", "#33d17a", "#f6d32d", "#ff7800",
               "#e01b24", "#9141ac", "#00c8d7", "#cdab8f"]
LIST_ICONS = ["●", "🛒", "🏠", "💼", "❤️", "🎓", "✈️", "🎯", "📌", "⭐"]


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, app, parent_window):
        super().__init__()
        self.app = app
        s = app.settings
        page = Adw.PreferencesPage(title="Sync & Datenschutz")

        group = Adw.PreferencesGroup(title="Quelle", description="Wohin werden deine Aufgaben synchronisiert?")
        self.mode_row = Adw.ComboRow(title="Modus")
        self.mode_row.set_model(Gtk.StringList.new(
            ["CalDAV-Server (empfohlen)", "Lokaler Ordner (.ics)", "Nur lokal (kein Sync)"]))
        mode = s.get_string("sync-mode")
        self.mode_row.set_selected({"caldav": 0, "folder": 1, "local": 2}.get(mode, 2))
        self.mode_row.connect("notify::selected", self._save_mode)
        group.add(self.mode_row)

        self.url_row = Adw.EntryRow(title="Server-URL (https://…)")
        self.url_row.set_text(s.get_string("server-url"))
        self.url_row.connect("changed", lambda r: s.set_string("server-url", r.get_text().strip()))
        group.add(self.url_row)

        self.user_row = Adw.EntryRow(title="Benutzername")
        self.user_row.set_text(s.get_string("username"))
        self.user_row.connect("changed", lambda r: s.set_string("username", r.get_text().strip()))
        group.add(self.user_row)

        self.pass_row = Adw.PasswordEntryRow(title="Passwort (wird im GNOME-Schlüsselbund gespeichert)")
        self.pass_row.connect("changed", self._save_password)
        group.add(self.pass_row)

        test_row = Adw.ActionRow(title="Verbindung testen", activatable=True)
        test_row.add_suffix(Gtk.Image(icon_name="network-wireless-symbolic"))
        test_row.connect("activated", self._test_connection)
        group.add(test_row)
        page.add(group)

        tls = Adw.PreferencesGroup(title="TLS-Sicherheit (Heimserver mit Self-Signed)",
                                   description="Zertifikat wird gegen System-CA geprüft. Optional zusätzlich pinnen.")
        self.pin_row = Adw.EntryRow(title="Zertifikats-Pin (sha256/<base64> oder 64 Hex)")
        self.pin_row.set_text(s.get_string("cert-pin"))
        self.pin_row.connect("changed", lambda r: s.set_string("cert-pin", r.get_text().strip()))
        tls.add(self.pin_row)

        self.ca_row = Adw.EntryRow(title="Eigenes CA-Bundle (Dateipfad, optional)")
        self.ca_row.set_text(s.get_string("ca-file"))
        self.ca_row.connect("changed", lambda r: s.set_string("ca-file", r.get_text().strip()))
        tls.add(self.ca_row)
        page.add(tls)

        folder_group = Adw.PreferencesGroup(title="Lokaler Ordner (.ics-Dateien als Fallback)")
        self.folder_row = Adw.ActionRow(title=s.get_string("folder-path") or "Ordner wählen …", activatable=True)
        self.folder_row.connect("activated", self._pick_folder)
        folder_group.add(self.folder_row)
        page.add(folder_group)

        self.add(page)
        self._parent = parent_window

    def _save_mode(self, row, _):
        keys = ["caldav", "folder", "local"]
        self.app.settings.set_string("sync-mode", keys[row.get_selected()])

    def _save_password(self, row):
        user = self.app.settings.get_string("username")
        if not user:
            return
        pw = row.get_text()
        try:
            if pw:
                secrets.store_password(constants.APP_ID, user, pw)
            else:
                secrets.delete_password(constants.APP_ID, user)
        except secrets.SecretsUnavailable:
            pass  # headless: Passwort wird nicht gespeichert, bei Start erneut abgefragt

    def _pick_folder(self, *_):
        dlg = Gtk.FileDialog(title="Ordner mit .ics-Dateien wählen")
        dlg.select_folder(self._parent, None, self._on_folder, None)

    def _on_folder(self, dlg, result, _):
        try:
            f = dlg.select_folder_finish(result)
            if f:
                path = f.get_path()
                self.app.settings.set_string("folder-path", path)
                self.folder_row.set_subtitle(path)
        except Exception:
            pass

    def _test_connection(self, *_):
        try:
            backend = self.app.make_backend()
        except Exception as exc:
            self._toast(f"Fehler: {exc}")
            return
        if backend is None:
            self._toast("Bitte URL und Benutzername eintragen (Passwort ggf. zuerst speichern)")
            return
        try:
            backend.discover_lists()
            self._toast("Verbindung OK ✔")
        except Exception as exc:
            self._toast(f"Verbindung fehlgeschlagen: {exc}")

    def _toast(self, text):
        win = self._parent
        if hasattr(win, "show_toast"):
            win.show_toast(text)


class NewListDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title="Neue Liste")
        self.window = window
        self.db = window.db
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16,
                        margin_top=16, margin_bottom=16)
        self.name_row = Adw.EntryRow(title="Name")
        box.append(self.name_row)
        box.append(Gtk.Label(label="Farbe", halign=Gtk.Align.START, css_classes=["heading"]))
        self.color_row = Gtk.Box(spacing=6)
        self._color = LIST_COLORS[0]
        for c in LIST_COLORS:
            b = Gtk.ToggleButton()
            b.add_css_class("flat")
            b.set_child(Gtk.Label(label="●"))
            b.get_child().set_markup(f'<span foreground="{c}">●</span>')
            b.connect("toggled", lambda btn, col=c: self._set_color(col) if btn.get_active() else None)
            if c == self._color:
                b.set_active(True)
            self.color_row.append(b)
        box.append(self.color_row)
        box.append(Gtk.Label(label="Icon", halign=Gtk.Align.START, css_classes=["heading"]))
        self.icon_row = Gtk.Box(spacing=6)
        self._icon = LIST_ICONS[0]
        for ic in LIST_ICONS:
            b = Gtk.ToggleButton(label=ic)
            b.connect("toggled", lambda btn, i=ic: setattr(self, "_icon", i) if btn.get_active() else None)
            if ic == self._icon:
                b.set_active(True)
            self.icon_row.append(b)
        box.append(self.icon_row)
        btn = Gtk.Button(label="Anlegen", css_classes=["suggested-action"], halign=Gtk.Align.END)
        btn.connect("clicked", self._create)
        box.append(btn)
        self.set_child(box)
        self.set_content_width(380)

    def _set_color(self, c):
        self._color = c

    def _create(self, *_):
        name = self.name_row.get_text().strip()
        if not name:
            return
        self.db.add_list(name, color=self._color, icon=self._icon)
        self.close()
        self.window.reload()


def prompt_password(parent, username: str) -> str | None:
    """Ask for the password (fallback when no Secret Service is running)."""
    result: dict[str, str | None] = {"pw": None}
    dlg = Adw.Dialog(title=f"Passwort für {username}")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16,
                    margin_top=16, margin_bottom=16)
    row = Adw.PasswordEntryRow(title="Passwort (nur lokal, im Schlüsselbund gespeichert)")
    box.append(row)
    btn = Gtk.Button(label="OK", css_classes=["suggested-action"], halign=Gtk.Align.END)

    def ok(*_):
        result["pw"] = row.get_text()
        dlg.close()

    btn.connect("clicked", ok)
    row.connect("activate", ok)
    box.append(btn)
    dlg.set_child(box)
    dlg.present(parent)
    # simple modal wait loop
    import time

    while result["pw"] is None and dlg.get_visible():
        time.sleep(0.05)
        while Gtk.events_pending():
            Gtk.main_iteration()
    return result["pw"]
