"""Task detail page: title, notes, due date, recurrence, subtasks, delete.
Changes are persisted locally immediately (offline-first)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from datetime import date, datetime, time  # noqa: E402

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import recurrence  # noqa: E402
from .db import format_due, parse_due  # noqa: E402

RECURRENCE_CHOICES = [
    ("none", "Keine"),
    ("daily", "Täglich"),
    ("weekly", "Wöchentlich"),
    ("monthly", "Monatlich"),
    ("last_day_of_month", "Letzter Tag im Monat"),
    ("yearly", "Jährlich"),
]


class TaskDetailPage(Adw.NavigationPage):
    def __init__(self, window, task):
        super().__init__(title=task.title)
        self.window = window
        self.db = window.db
        self.task = task
        self.set_child(self._build())

    def _build(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16,
                        margin_top=16, margin_bottom=24)

        group = Adw.PreferencesGroup()
        self.title_row = Adw.EntryRow(title="Titel")
        self.title_row.set_text(self.task.title)
        self.title_row.connect("changed", self._save_title)
        group.add(self.title_row)

        self.notes_row = Adw.EntryRow(title="Notizen")
        self.notes_row.set_text(self.task.notes)
        self.notes_row.connect("changed", self._save_notes)
        group.add(self.notes_row)

        self.due_switch = Adw.ActionRow(title="Fälligkeit", subtitle="Datum und optional Uhrzeit")
        sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        sw.set_active(self.task.due is not None)
        sw.connect("notify::active", self._on_due_switch)
        self.due_switch.add_suffix(sw)
        self.due_switch.set_activatable_widget(sw)
        group.add(self.due_switch)

        self.cal = Gtk.Calendar()
        self.cal.connect("day-selected", self._save_due)
        group.add(self.cal)
        d, t = parse_due(self.task.due)
        if d:
            self.cal.select_day(GLib.DateTime.new_local(d.year, d.month, d.day, 0, 0, 0))

        self.time_row = Adw.EntryRow(title="Uhrzeit (HH:MM, optional)")
        _, t = parse_due(self.task.due)
        self.time_row.set_text(t.strftime("%H:%M") if t else "")
        self.time_row.connect("changed", self._save_due)
        group.add(self.time_row)

        self.rec_row = Adw.ComboRow(title="Wiederholen")
        model = Gtk.StringList.new([label for _, label in RECURRENCE_CHOICES])
        self.rec_row.set_model(model)
        keys = [k for k, _ in RECURRENCE_CHOICES]
        current = "none"
        if self.task.rrule:
            try:
                r = recurrence.parse_rrule(self.task.rrule)
                if r.get("FREQ") == "DAILY":
                    current = "daily"
                elif r.get("FREQ") == "WEEKLY":
                    current = "weekly"
                elif r.get("FREQ") == "MONTHLY" and r.get("BYMONTHDAY") == "-1":
                    current = "last_day_of_month"
                elif r.get("FREQ") == "MONTHLY":
                    current = "monthly"
                elif r.get("FREQ") == "YEARLY":
                    current = "yearly"
            except recurrence.RuleError:
                current = "none"
        self.rec_row.set_selected(keys.index(current))
        self.rec_row.connect("notify::selected", self._save_recurrence)
        group.add(self.rec_row)
        box.append(group)

        # Subtasks
        sub_group = Adw.PreferencesGroup(title="Teilaufgaben")
        self.sub_box = Gtk.ListBox(css_classes=["boxed-list"])
        sub_group.add(self.sub_box)
        add_row = Adw.ActionRow(title="Teilaufgabe hinzufügen", activatable=True)
        add_row.connect("activated", self._add_subtask)
        add_row.add_suffix(Gtk.Image(icon_name="list-add-symbolic"))
        sub_group.add(add_row)
        box.append(sub_group)
        self._reload_subtasks()

        del_group = Adw.PreferencesGroup()
        del_row = Adw.ActionRow(title="Erinnerung löschen", css_classes=["destructive-action"])
        del_row.set_activatable(True)
        del_row.connect("activated", self._delete)
        del_group.add(del_row)
        box.append(del_group)

        scrolled.set_child(box)
        return scrolled

    # --- Speichern -----------------------------------------------------------

    def _refresh(self):
        self.task = self.db.get_task(self.task.uid)
        self.window.reload()

    def _save_title(self, row):
        self.db.update_task(self.task.uid, title=row.get_text() or "Ohne Titel")

    def _save_notes(self, row):
        self.db.update_task(self.task.uid, notes=row.get_text())

    def _on_due_switch(self, sw, _):
        if sw.get_active() and not self.task.due:
            self.db.update_task(self.task.uid, due=format_due(date.today(), None))
        elif not sw.get_active():
            self.db.update_task(self.task.uid, due=None, notified=None)
        self._refresh()

    def _save_due(self, *_):
        if not self.task.due:
            return
        d0, t0 = parse_due(self.task.due)
        cal_d = self.cal.get_date()
        d = date(cal_d.get_year(), cal_d.get_month(), cal_d.get_day_of_month())
        txt = self.time_row.get_text().strip()
        t = None
        if txt:
            try:
                hh, mm = txt.split(":")
                t = time(int(hh), int(mm))
            except ValueError:
                pass
        self.db.update_task(self.task.uid, due=format_due(d, t or t0), notified=None)

    def _save_recurrence(self, row, _):
        key = RECURRENCE_CHOICES[row.get_selected()][0]
        d, t = parse_due(self.task.due)
        anchor = datetime.combine(d or date.today(), t or time.min)
        self.db.update_task(self.task.uid, rrule=recurrence.preset(key, anchor))
        self._refresh()

    # --- Subtasks --------------------------------------------------------------

    def _reload_subtasks(self):
        while (row := self.sub_box.get_row_at_index(0)) is not None:
            self.sub_box.remove(row)
        for kid in self.db.children(self.task.uid):
            row = Adw.ActionRow(title=kid.title, subtitle="erledigt" if kid.completed else "")
            check = Gtk.CheckButton(active=kid.completed, valign=Gtk.Align.CENTER)
            check.connect("toggled", lambda c, k=kid.uid: (self.db.toggle_task(k), self._refresh()))
            row.add_prefix(check)
            del_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                  css_classes=["flat"])
            del_btn.connect("clicked", lambda *_a, k=kid.uid: (self.db.delete_task(k), self._refresh()))
            row.add_suffix(del_btn)
            self.sub_box.append(row)

    def _add_subtask(self, *_):
        self.db.add_task(self.task.list_uid, "Neue Teilaufgabe", parent_uid=self.task.uid)
        self._refresh()
        self._reload_subtasks()

    def _delete(self, *_):
        self.db.delete_task(self.task.uid)
        nav = self.get_parent()
        if isinstance(nav, Adw.NavigationView):
            nav.pop()
        self.window.reload()
