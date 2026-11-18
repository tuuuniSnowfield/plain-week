"""Main window: sidebar (smart lists + own lists), quick-add on top, task list.
Details are a NavigationPage (see detail.py)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import constants, quickadd  # noqa: E402
from .db import parse_due  # noqa: E402
from .widgets import QuickAddBar, SidebarRow, TaskRow  # noqa: E402

SMART = [("today", "Heute", "alarm-symbolic"), ("scheduled", "Geplant", "x-office-calendar-symbolic"),
         ("all", "Alle", "view-list-symbolic")]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application_id=constants.APP_ID)
        self.app = app
        self.db = app.db
        self.current_kind = "today"
        self.current_uid: str | None = None
        self.set_title(constants.APP_NAME)
        self.set_default_size(
            self.app.settings.get_int("window-width") or 900,
            self.app.settings.get_int("window-height") or 600,
        )

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.set_content(self.toast_overlay)
        self.toast_overlay.set_child(toolbar)

        # content is a NavigationView so task details can be pushed as pages
        self._nav = Adw.NavigationView()
        self._split = Adw.OverlaySplitView(collapsed=True)
        self._split.set_sidebar(self._build_sidebar())
        self._split.set_content(self._nav)
        self._nav.add(Adw.NavigationPage(child=self._build_content(), title=constants.APP_NAME))
        toolbar.set_content(self._split)

        self.header = Adw.HeaderBar()
        self.sidebar_toggle = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self.sidebar_toggle.bind_property("active", self._split, "show-sidebar", Gio.BindingFlags.BIDIRECTIONAL)
        self.header.pack_start(self.sidebar_toggle)
        self.title_label = Gtk.Label(label="Heute", css_classes=["title-2"], hexpand=True, halign=Gtk.Align.CENTER)
        self.header.set_title_widget(self.title_label)
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Neue Erinnerung")
        new_btn.connect("clicked", self.on_new_task)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Neu synchronisieren", "app.sync")
        menu.append("Neue Liste …", "win.new-list")
        menu.append("Einstellungen …", "app.preferences")
        menu.append("Über", "app.about")
        menu_btn.set_menu_model(menu)
        self.header.pack_end(new_btn)
        self.header.pack_end(menu_btn)
        toolbar.add_top_bar(self.header)

        self._install_actions()
        self.connect("close-request", self._on_close)
        self.reload()

    # --- Aufbau ------------------------------------------------------------

    def _install_actions(self):
        a = Gio.SimpleAction.new("new-list", None)
        a.connect("activate", lambda *_: self.on_new_list())
        self.add_action(a)

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(Gtk.Label(label="Bibliothek", css_classes=["heading", "dim-label"],
                             margin_top=12, margin_start=12, halign=Gtk.Align.START))
        self.smart_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.smart_box.connect("row-activated", self._on_sidebar_activated)
        for key, name, icon in SMART:
            row = SidebarRow(key, name, icon, "#3584e4")
            self.smart_box.append(row)
        box.append(self.smart_box)
        box.append(Gtk.Label(label="Listen", css_classes=["heading", "dim-label"],
                             margin_top=12, margin_start=12, halign=Gtk.Align.START))
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.list_box.connect("row-activated", self._on_sidebar_activated)
        box.append(self.list_box)
        scrolled = Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       min_content_width=220, propagate_natural_width=True)
        return scrolled

    def _build_content(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.quick_add = QuickAddBar(self._on_quick_add)
        outer.append(self.quick_add)
        self.count_label = Gtk.Label(halign=Gtk.Align.START, margin_start=12, margin_top=6,
                                     css_classes=["dim-label", "caption"])
        outer.append(self.count_label)
        self.task_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.task_box.set_margin_start(12)
        self.task_box.set_margin_end(12)
        self.task_box.set_margin_top(6)
        self.task_box.set_margin_bottom(12)
        scrolled = Gtk.ScrolledWindow(child=self.task_box, vexpand=True,
                                       hscrollbar_policy=Gtk.PolicyType.NEVER)
        outer.append(scrolled)
        return outer

    # --- Daten → UI ----------------------------------------------------------

    @staticmethod
    def _clear_listbox(box: Gtk.ListBox):
        while (row := box.get_row_at_index(0)) is not None:
            box.remove(row)

    def reload(self):
        self._clear_listbox(self.list_box)
        for lst in self.db.lists():
            self.list_box.append(SidebarRow(("list", lst.uid), lst.name, lst.icon, lst.color, lst.uid))
        tasks = self._current_tasks()
        self._clear_listbox(self.task_box)
        for t in tasks:
            self.task_box.append(TaskRow(t, self.db, self._open_detail))
        n = len(tasks)
        self.count_label.set_label(f"{n} offen" if n != 1 else "1 offen")
        name = dict((k, n) for k, n, _ in SMART).get(self.current_kind)
        if name:
            self.title_label.set_label(name)
        else:
            lst = self.db.get_list(self.current_uid or "")
            self.title_label.set_label(lst.name if lst else "")
        self._select_sidebar_row()

    def _current_tasks(self):
        if self.current_kind == "today":
            return self.db.due_today()
        if self.current_kind == "scheduled":
            return self.db.scheduled()
        if self.current_kind == "all":
            return self.db.all_tasks(include_completed=False)
        if self.current_kind == "list" and self.current_uid:
            return self.db.tasks_in_list(self.current_uid, include_completed=False)
        return []

    def _select_sidebar_row(self):
        for box in (self.smart_box, self.list_box):
            i = 0
            while (row := box.get_row_at_index(i)) is not None:
                key = row.key
                active = (key == self.current_kind) or (
                    isinstance(key, tuple) and key == ("list", self.current_uid)
                )
                if active:
                    box.select_row(row)
                    return
                i += 1
            box.select_row(None)

    # --- Events ----------------------------------------------------------------

    def _on_sidebar_activated(self, box, row):
        key = row.key
        if isinstance(key, tuple):
            self.current_kind, self.current_uid = key
        else:
            self.current_kind, self.current_uid = key, None
        self.reload()

    def on_new_task(self, *_):
        self.quick_add.entry.grab_focus()

    def _on_quick_add(self, text: str):
        parsed = quickadd.parse(text, [x.name for x in self.db.lists()])
        if not parsed.title:
            self.show_toast("Titel fehlt")
            return
        list_uid = self.current_uid if self.current_kind == "list" else None
        if parsed.list_name:
            for lst in self.db.lists():
                if lst.name == parsed.list_name:
                    list_uid = lst.uid
                    break
        if list_uid is None:
            lists = self.db.lists()
            list_uid = lists[0].uid if lists else self.db.add_list("Erinnerungen").uid
        due = quickadd.to_due_string(parsed.day, parsed.clock)
        self.db.add_task(list_uid, parsed.title, due=due)
        self.show_toast(f"»{parsed.title}« hinzugefügt")
        self.reload()

    def _open_detail(self, task):
        from .detail import TaskDetailPage

        self._nav.push(TaskDetailPage(self, task))

    def on_new_list(self):
        from .dialogs import NewListDialog

        NewListDialog(self).present()

    def show_toast(self, text: str):
        self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _on_close(self, *_):
        self.app.settings.set_int("window-width", self.get_width())
        self.app.settings.set_int("window-height", self.get_height())
        return False


def format_due_human(due: str | None) -> str:
    if not due:
        return ""
    from datetime import datetime

    d, t = parse_due(due)
    now = datetime.now()
    if d == now.date():
        label = "Heute"
    elif d.toordinal() == now.date().toordinal() + 1:
        label = "Morgen"
    else:
        label = d.strftime("%a, %d.%m.")
    if t:
        label += f" {t.strftime('%H:%M')}"
    return label
