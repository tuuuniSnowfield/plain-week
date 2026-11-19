"""Reusable widgets: sidebar rows, task rows, quick-add bar."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango  # noqa: E402

from . import recurrence  # noqa: E402


def _due_human(due):
    from .window import format_due_human as f  # local import: window imports widgets

    return f(due)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, key, name: str, icon: str, color: str, uid: str | None = None):
        super().__init__()
        self.key = key
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_start=6, margin_end=6,
                        margin_top=4, margin_bottom=4)
        if icon and not icon.endswith("-symbolic") and len(icon) <= 4:
            icon_label = Gtk.Label(label=icon)
        else:
            icon_label = Gtk.Image(icon_name=icon if icon.endswith("-symbolic") else "list-symbolic")
        dot = Gtk.Label()
        dot.set_markup(f'<span foreground="{color}" size="large">●</span>')
        name_label = Gtk.Label(label=name, halign=Gtk.Align.START, hexpand=True,
                               ellipsize=Pango.EllipsizeMode.END)
        box.append(dot)
        box.append(icon_label)
        box.append(name_label)
        self.set_child(box)


class TaskRow(Gtk.ListBoxRow):
    def __init__(self, task, db, open_detail):
        super().__init__()
        self.task = task
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                        margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.set_active(task.completed)
        check.connect("toggled", self._on_toggle, db, open_detail)
        box.append(check)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=task.title, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
        if task.completed:
            title.add_css_class("dim-label")
            title.set_attributes(_strike())
        vbox.append(title)
        sub = self._subtitle(task, db)
        if sub:
            sub_label = Gtk.Label(label=sub, halign=Gtk.Align.START, css_classes=["caption", "dim-label"])
            vbox.append(sub_label)
        box.append(vbox)
        arrow = Gtk.Image(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER, css_classes=["dim-label"])
        box.append(arrow)
        self.set_child(box)
        self.connect("activate", lambda *_: open_detail(self.task))

    def _subtitle(self, task, db) -> str:
        parts = []
        due = _due_human(task.due)
        if due:
            parts.append(due)
        if task.rrule:
            parts.append("🔁 " + recurrence.describe(task.rrule))
        kids = db.children(task.uid)
        if kids:
            done = sum(1 for k in kids if k.completed)
            parts.append(f"{done}/{len(kids)} Teilaufgaben")
        if task.notes:
            parts.append("📝")
        return "  ·  ".join(parts)

    def _on_toggle(self, check, db, open_detail):
        db.toggle_task(self.task.uid)
        self.task = db.get_task(self.task.uid)
        if self.task and self.task.completed:
            pass  # list is reloaded below
        parent = self.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ListBox):
            parent = parent.get_parent()
        if parent is not None:
            # Fenster neu laden
            win = self.get_root()
            if hasattr(win, "reload"):
                win.reload()


def _strike():
    attr = Pango.AttrList()
    attr.insert(Pango.AttrStrikethrough(True, 0, -1))
    return attr


class QuickAddBar(Gtk.Box):
    def __init__(self, on_submit):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                         margin_start=12, margin_end=12, margin_top=12)
        self.entry = Gtk.Entry(
            placeholder_text="Neue Erinnerung …  z. B. »Milch kaufen morgen 18 Uhr !Einkaufen«",
            hexpand=True,
        )
        self.entry.connect("activate", self._on_activate, on_submit)
        icon = Gtk.Image(icon_name="list-add-symbolic", css_classes=["dim-label"])
        self.append(icon)
        self.append(self.entry)

    def _on_activate(self, entry, on_submit):
        text = entry.get_text().strip()
        if text:
            on_submit(text)
        entry.set_text("")
