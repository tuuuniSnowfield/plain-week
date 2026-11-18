"""Sync engine: offline-first. The local DB is authoritative; sync only runs
when a backend is configured and pushes local changes to CalDAV/.ics or pulls
remote changes.

Conflict rule: last-write-wins by LAST-MODIFIED (modified). Local changes
(dirty=1) win unless they are older than the remote state.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import ics
from .db import Database, Task


@dataclass
class RemoteTask:
    uid: str
    etag: str | None
    vtodo: ics.VTodo


@dataclass
class SyncReport:
    pushed: int = 0
    pulled: int = 0
    deleted_remote: int = 0
    conflicts_lww_remote_wins: int = 0
    errors: list[str] = field(default_factory=list)


class SyncEngine:
    def __init__(self, db: Database, backend):
        self.db = db
        self.backend = backend

    # --- mapping local → remote VTodo ---------------------------------------

    def _task_to_vtodo(self, t: Task) -> ics.VTodo:
        d, tm = t.due_parts()
        modified = None
        with contextlib.suppress(ValueError):
            modified = datetime.fromisoformat(t.modified.replace("Z", "+00:00")).replace(tzinfo=None)
        created = None
        with contextlib.suppress(ValueError):
            created = datetime.fromisoformat(t.created.replace("Z", "+00:00")).replace(tzinfo=None)
        return ics.VTodo(
            uid=t.uid,
            summary=t.title,
            description=t.notes,
            due_date=d,
            due_time=tm,
            rrule=t.rrule,
            status=t.status,
            percent=t.percent,
            related_parents=[t.parent_uid] if t.parent_uid else [],
            sequence=t.sequence,
            created=created,
            modified=modified or datetime.utcnow(),
        )

    def _vtodo_to_task(self, v: ics.VTodo, list_uid: str) -> Task:
        modified = v.modified or _utcnow_naive()
        created = v.created or modified
        return Task(
            uid=v.uid,
            list_uid=list_uid,
            title=v.summary,
            notes=v.description,
            due=v.due,
            rrule=v.rrule,
            status=v.status if v.status in ("NEEDS-ACTION", "COMPLETED", "IN-PROCESS") else "NEEDS-ACTION",
            percent=v.percent,
            parent_uid=v.related_parents[0] if v.related_parents else None,
            sort=0,
            etag=None,
            created=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            modified=modified.strftime("%Y-%m-%dT%H:%M:%SZ"),
            sequence=v.sequence,
            dirty=0,
            deleted=0,
            notified=None,
        )

    # --- Sync --------------------------------------------------------------

    def sync(self) -> SyncReport:
        report = SyncReport()
        remote_lists = self.backend.discover_lists()
        by_name = {name: path for path, name in remote_lists}
        for lst in self.db.lists():
            if lst.deleted:
                continue
            try:
                self._sync_list(lst, by_name, report)
            except Exception as exc:  # noqa: BLE001 – sync must never break the UI
                report.errors.append(f"{lst.name}: {exc}")
        return report

    def _sync_list(self, lst, by_name: dict[str, str], report: SyncReport) -> None:
        path = lst.remote_path or by_name.get(lst.name)
        if path is None:
            path = self.backend.ensure_list(None, lst.name, lst.color, lst.icon)
        self.db.update_list(lst.uid, remote_path=path)
        self.db.mark_list_synced(lst.uid)

        remote_items = self.backend.fetch_tasks(path)
        remote_by_uid: dict[str, RemoteTask] = {}
        for item in remote_items:
            for v in ics.parse_calendar(item.data):
                remote_by_uid[v.uid] = RemoteTask(uid=v.uid, etag=item.etag, vtodo=v)

        local_tasks = self.db.tasks_in_list(lst.uid, include_completed=True, include_deleted=True)
        local_by_uid = {t.uid: t for t in local_tasks}

        # Pull: remote → lokal
        for uid, rt in remote_by_uid.items():
            local = local_by_uid.get(uid)
            remote_modified = rt.vtodo.modified or _utcnow_naive()
            if local is None:
                task = self._vtodo_to_task(rt.vtodo, lst.uid)
                self.db.upsert_from_remote(task, rt.etag)
                report.pulled += 1
            elif local.deleted and not local.dirty:
                self.db.upsert_from_remote(self._vtodo_to_task(rt.vtodo, lst.uid), rt.etag)
                report.pulled += 1
            elif not local.dirty:
                local_modified = _parse_utc(local.modified)
                if remote_modified > local_modified:
                    self.db.upsert_from_remote(self._vtodo_to_task(rt.vtodo, lst.uid), rt.etag)
                    report.pulled += 1
            else:
                local_modified = _parse_utc(local.modified)
                if remote_modified > local_modified:
                    self.db.upsert_from_remote(self._vtodo_to_task(rt.vtodo, lst.uid), rt.etag)
                    report.conflicts_lww_remote_wins += 1

        # Local, but no longer present remotely and not dirty → deleted remotely
        for t in local_tasks:
            if t.uid not in remote_by_uid and not t.dirty and not t.deleted:
                self.db.mark_deleted_local(t.uid)
                report.deleted_remote += 1

        # Push: dirty → remote (including deleted tombstones)
        for t in self.db.tasks_in_list(lst.uid, include_completed=True, include_deleted=True):
            if not t.dirty:
                continue
            if t.deleted:
                if t.etag:
                    try:
                        self.backend.remove(path, t.uid, t.etag)
                        self.db.purge_deleted()
                        report.pushed += 1
                    except Exception as exc:  # noqa: BLE001
                        report.errors.append(f"delete {t.uid}: {exc}")
                else:
                    self.db.purge_deleted()
                continue
            vtodo = self._task_to_vtodo(t)
            block = ics.serialize_vtodo(vtodo)
            try:
                etag = self.backend.upload(path, t.uid, block, t.etag)
                self.db.mark_task_synced(t.uid, etag)
                report.pushed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"upload {t.uid}: {exc}")


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_utc(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return _utcnow_naive()

