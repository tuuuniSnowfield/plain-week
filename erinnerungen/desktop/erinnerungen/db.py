"""Offline-first SQLite store – the local database is the source of truth.

Sync (CalDAV/.ics folder) only writes back. All queries are parameterized,
foreign keys are on, WAL mode. Schema version lives in PRAGMA user_version.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from . import recurrence

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
  uid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#3584e4',
  icon TEXT NOT NULL DEFAULT '●',
  sort INTEGER NOT NULL DEFAULT 0,
  remote_path TEXT,
  etag TEXT,
  created TEXT NOT NULL,
  modified TEXT NOT NULL,
  dirty INTEGER NOT NULL DEFAULT 1,
  deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
  uid TEXT PRIMARY KEY,
  list_uid TEXT NOT NULL REFERENCES lists(uid) ON DELETE CASCADE,
  title TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  due TEXT,
  rrule TEXT,
  status TEXT NOT NULL DEFAULT 'NEEDS-ACTION',
  percent INTEGER NOT NULL DEFAULT 0,
  parent_uid TEXT REFERENCES tasks(uid) ON DELETE CASCADE,
  sort INTEGER NOT NULL DEFAULT 0,
  etag TEXT,
  created TEXT NOT NULL,
  modified TEXT NOT NULL,
  sequence INTEGER NOT NULL DEFAULT 0,
  dirty INTEGER NOT NULL DEFAULT 1,
  deleted INTEGER NOT NULL DEFAULT 0,
  notified TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_list ON tasks(list_uid);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_uid);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due);
"""


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_uid() -> str:
    return f"{uuid.uuid4().hex}@erinnerungen"


def format_due(d: date | None, t: time | None) -> str | None:
    if d is None:
        return None
    return d.isoformat() if t is None else f"{d.isoformat()} {t.strftime('%H:%M')}"


def parse_due(value: str | None) -> tuple[date | None, time | None]:
    if not value:
        return None, None
    parts = value.split(" ")
    d = date.fromisoformat(parts[0])
    t = time.fromisoformat(parts[1]) if len(parts) > 1 else None
    return d, t


@dataclass
class List:
    uid: str
    name: str
    color: str
    icon: str
    sort: int
    remote_path: str | None
    etag: str | None
    created: str
    modified: str
    dirty: int
    deleted: int


@dataclass
class Task:
    uid: str
    list_uid: str
    title: str
    notes: str
    due: str | None
    rrule: str | None
    status: str
    percent: int
    parent_uid: str | None
    sort: int
    etag: str | None
    created: str
    modified: str
    sequence: int
    dirty: int
    deleted: int
    notified: str | None

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"

    def due_parts(self) -> tuple[date | None, time | None]:
        return parse_due(self.due)


class Database:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        with self._lock:
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version < SCHEMA_VERSION:
                self._conn.executescript(SCHEMA)
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                self._conn.commit()

    # --- interne Helfer -------------------------------------------------

    @staticmethod
    def _to_list(row: sqlite3.Row) -> List:
        return List(**dict(row))

    @staticmethod
    def _to_task(row: sqlite3.Row) -> Task:
        return Task(**dict(row))

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    # --- Listen ----------------------------------------------------------

    def add_list(self, name: str, color: str = "#3584e4", icon: str = "●") -> List:
        now = utcnow()
        uid = new_uid()
        with self._lock:
            sort = (self._one("SELECT COALESCE(MAX(sort)+1, 0) AS s FROM lists") or {"s": 0})["s"]
            self._conn.execute(
                "INSERT INTO lists (uid,name,color,icon,sort,created,modified,dirty)"
                " VALUES (?,?,?,?,?,?,?,1)",
                (uid, name, color, icon, sort, now, now),
            )
            self._conn.commit()
        return self.get_list(uid)  # type: ignore[return-value]

    def get_list(self, uid: str) -> List | None:
        row = self._one("SELECT * FROM lists WHERE uid=?", (uid,))
        return self._to_list(row) if row else None

    def lists(self, include_deleted: bool = False) -> list[List]:
        sql = "SELECT * FROM lists"
        if not include_deleted:
            sql += " WHERE deleted=0"
        sql += " ORDER BY sort, name"
        return [self._to_list(r) for r in self._query(sql)]

    def update_list(self, uid: str, **fields) -> None:
        allowed = {"name", "color", "icon", "sort", "remote_path", "etag"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        self._exec(
            f"UPDATE lists SET {sets}, modified=?, dirty=CASE WHEN dirty=0 THEN 1 ELSE dirty END"
            " WHERE uid=?",
            (*vals, utcnow(), uid),
        )

    def delete_list(self, uid: str) -> None:
        self._exec("UPDATE lists SET deleted=1, dirty=1, modified=? WHERE uid=?", (utcnow(), uid))

    def lists_dirty(self) -> list[List]:
        return [self._to_list(r) for r in self._query("SELECT * FROM lists WHERE dirty=1")]

    # --- Aufgaben --------------------------------------------------------

    def add_task(
        self,
        list_uid: str,
        title: str,
        notes: str = "",
        due: str | None = None,
        rrule: str | None = None,
        parent_uid: str | None = None,
    ) -> Task:
        now = utcnow()
        uid = new_uid()
        with self._lock:
            sort = (
                self._one(
                    "SELECT COALESCE(MAX(sort)+1, 0) AS s FROM tasks WHERE list_uid=? AND parent_uid IS ?",
                    (list_uid, parent_uid),
                )
                or {"s": 0}
            )["s"]
            self._conn.execute(
                "INSERT INTO tasks (uid,list_uid,title,notes,due,rrule,parent_uid,sort,created,"
                "modified,dirty) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                (uid, list_uid, title, notes, due, rrule, parent_uid, sort, now, now),
            )
            self._conn.commit()
        return self.get_task(uid)  # type: ignore[return-value]

    def get_task(self, uid: str) -> Task | None:
        row = self._one("SELECT * FROM tasks WHERE uid=?", (uid,))
        return self._to_task(row) if row else None

    def update_task(self, uid: str, **fields) -> None:
        allowed = {
            "list_uid", "title", "notes", "due", "rrule", "status",
            "percent", "parent_uid", "sort", "notified",
        }
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        self._exec(
            f"UPDATE tasks SET {sets}, modified=?, sequence=sequence+1, dirty=1 WHERE uid=?",
            (*vals, utcnow(), uid),
        )

    def toggle_task(self, uid: str) -> Task | None:
        """Toggle the checkbox. Recurring tasks advance to the next occurrence."""
        task = self.get_task(uid)
        if task is None or task.deleted:
            return None
        if task.completed:
            self.update_task(uid, status="NEEDS-ACTION", percent=0)
        elif task.rrule:
            due_d, due_t = task.due_parts()
            base = datetime.combine(due_d or date.today(), due_t or time.min)
            nxt = recurrence.next_after(task.rrule, base, base)
            if nxt is None:
                self.update_task(uid, status="COMPLETED", percent=100)
            else:
                nxt_time = time(nxt.hour, nxt.minute) if due_t else None
                self.update_task(uid, due=format_due(nxt.date(), nxt_time), percent=0, notified=None)
        else:
            self.update_task(uid, status="COMPLETED", percent=100)
        return self.get_task(uid)

    def delete_task(self, uid: str) -> None:
        self._exec("UPDATE tasks SET deleted=1, dirty=1, modified=? WHERE uid=?", (utcnow(), uid))

    def tasks_in_list(
        self, list_uid: str, include_completed: bool = True, include_deleted: bool = False
    ) -> list[Task]:
        sql = "SELECT * FROM tasks WHERE list_uid=?"
        if not include_deleted:
            sql += " AND deleted=0"
        if not include_completed:
            sql += " AND status='NEEDS-ACTION'"
        sql += " ORDER BY (status='COMPLETED'), due IS NULL, due, sort"
        return [self._to_task(r) for r in self._query(sql, (list_uid,))]

    def children(self, parent_uid: str) -> list[Task]:
        return [
            self._to_task(r)
            for r in self._query(
                "SELECT * FROM tasks WHERE parent_uid=? AND deleted=0 ORDER BY sort", (parent_uid,)
            )
        ]

    def all_tasks(self, include_completed: bool = True) -> list[Task]:
        sql = "SELECT * FROM tasks WHERE deleted=0"
        if not include_completed:
            sql += " AND status='NEEDS-ACTION'"
        sql += " ORDER BY (status='COMPLETED'), due IS NULL, due, sort"
        return [self._to_task(r) for r in self._query(sql)]

    def due_today(self, now: datetime | None = None) -> list[Task]:
        """Smart list \"Today\": overdue or due today, not completed."""
        now = now or datetime.now()
        end_of_day = f"{now.date().isoformat()} 23:59"
        return [
            self._to_task(r)
            for r in self._query(
                "SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL"
                " AND due <= ? ORDER BY due, sort",
                (end_of_day,),
            )
        ]

    def scheduled(self, now: datetime | None = None) -> list[Task]:
        """Smart list \"Scheduled\": due in the future, not completed."""
        now = now or datetime.now()
        end_of_day = f"{now.date().isoformat()} 23:59"
        return [
            self._to_task(r)
            for r in self._query(
                "SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL"
                " AND due > ? ORDER BY due, sort",
                (end_of_day,),
            )
        ]

    def due_reminders(self, now: datetime | None = None) -> list[Task]:
        """Due, not yet notified reminders (for local notifications)."""
        now = now or datetime.now()
        now_str = f"{now.date().isoformat()} {now.strftime('%H:%M')}"
        return [
            self._to_task(r)
            for r in self._query(
                "SELECT * FROM tasks WHERE deleted=0 AND status='NEEDS-ACTION' AND due IS NOT NULL"
                " AND due <= ? AND (notified IS NULL OR notified != due) ORDER BY due",
                (now_str,),
            )
        ]

    def mark_notified(self, uid: str) -> None:
        task = self.get_task(uid)
        if task and task.due:
            self._exec("UPDATE tasks SET notified=? WHERE uid=?", (task.due, uid))

    # --- Sync-Hooks ------------------------------------------------------

    def dirty_tasks(self) -> list[Task]:
        return [
            self._to_task(r)
            for r in self._query("SELECT * FROM tasks WHERE dirty=1 ORDER BY modified")
        ]

    def mark_task_synced(self, uid: str, etag: str | None) -> None:
        self._exec(
            "UPDATE tasks SET dirty=0, etag=? WHERE uid=?", (etag, uid)
        )

    def mark_list_synced(self, uid: str) -> None:
        self._exec("UPDATE lists SET dirty=0 WHERE uid=?", (uid,))

    def upsert_from_remote(self, task: Task, etag: str | None) -> None:
        """Apply a remote state (already decoded to Task) locally, dirty=0."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (uid,list_uid,title,notes,due,rrule,status,percent,parent_uid,"
                "sort,etag,created,modified,sequence,dirty,deleted,notified)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)"
                " ON CONFLICT(uid) DO UPDATE SET list_uid=excluded.list_uid, title=excluded.title,"
                " notes=excluded.notes, due=excluded.due, rrule=excluded.rrule, status=excluded.status,"
                " percent=excluded.percent, parent_uid=excluded.parent_uid, sort=excluded.sort,"
                " etag=excluded.etag, modified=excluded.modified, sequence=excluded.sequence,"
                " dirty=0, deleted=0, notified=excluded.notified",
                (
                    task.uid, task.list_uid, task.title, task.notes, task.due, task.rrule,
                    task.status, task.percent, task.parent_uid, task.sort, etag,
                    task.created, task.modified, task.sequence, task.notified,
                ),
            )
            self._conn.commit()

    def mark_deleted_local(self, uid: str) -> None:
        self._exec("UPDATE tasks SET deleted=1, dirty=0, modified=? WHERE uid=?", (utcnow(), uid))

    def purge_deleted(self) -> None:
        self._exec("DELETE FROM tasks WHERE deleted=1 AND dirty=0")
