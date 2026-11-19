"""Local notifications – core logic without GUI (testable); GLib scheduling lives in app.py."""
from __future__ import annotations

from datetime import datetime

from . import db as dbmod
from . import recurrence
from .db import Task


def due_reminders(database: dbmod.Database, now: datetime | None = None) -> list[Task]:
    return database.due_reminders(now)


def notification_title(task: Task) -> str:
    return task.title


def notification_body(task: Task) -> str:
    parts = []
    if task.rrule:
        parts.append(recurrence.describe(task.rrule))
    d, t = task.due_parts()
    if d:
        when = d.strftime("%d.%m.%Y")
        if t:
            when += f" {t.strftime('%H:%M')} Uhr"
        parts.append(when)
    return " – ".join(parts)


def fire_due(database: dbmod.Database, now: datetime | None = None) -> list[Task]:
    """Return due tasks and mark them notified (once per due value)."""
    due = due_reminders(database, now)
    for t in due:
        database.mark_notified(t.uid)
    return due
