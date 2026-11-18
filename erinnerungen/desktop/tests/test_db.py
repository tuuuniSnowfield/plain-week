import os
from datetime import date, datetime, time

from erinnerungen.db import Database, format_due, parse_due


def make_db(tmp_path) -> Database:
    return Database(os.path.join(tmp_path, "test.db"))


def test_due_format_roundtrip():
    assert format_due(date(2024, 2, 29), time(18, 30)) == "2024-02-29 18:30"
    assert format_due(date(2024, 2, 29), None) == "2024-02-29"
    assert format_due(None, None) is None
    assert parse_due("2024-02-29 18:30") == (date(2024, 2, 29), time(18, 30))
    assert parse_due("2024-02-29") == (date(2024, 2, 29), None)
    assert parse_due(None) == (None, None)


def test_add_and_toggle_simple(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("Einkaufen")
    t = db.add_task(lst.uid, "Milch kaufen")
    assert not t.completed
    t2 = db.toggle_task(t.uid)
    assert t2.completed and t2.percent == 100
    t3 = db.toggle_task(t.uid)
    assert not t3.completed and t3.percent == 0


def test_toggle_recurring_advances_due(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("Haushalt")
    t = db.add_task(lst.uid, "Müll raus", due="2024-01-31 07:00", rrule="FREQ=DAILY")
    t2 = db.toggle_task(t.uid)
    assert not t2.completed  # stays open, advances
    assert t2.due == "2024-02-01 07:00"
    assert t2.notified is None


def test_toggle_last_day_of_month(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("Finanzen")
    t = db.add_task(lst.uid, "Miete", due="2024-01-31", rrule="FREQ=MONTHLY;BYMONTHDAY=-1")
    t2 = db.toggle_task(t.uid)
    assert t2.due == "2024-02-29"  # Schaltjahr


def test_smart_lists(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("Liste")
    db.add_task(lst.uid, "heute fällig", due="2024-05-10 09:00")
    db.add_task(lst.uid, "überfällig", due="2024-05-01")
    db.add_task(lst.uid, "zukunft", due="2024-05-20")
    db.add_task(lst.uid, "ohne datum")
    done = db.add_task(lst.uid, "erledigt", due="2024-05-10")
    db.toggle_task(done.uid)
    now = datetime(2024, 5, 10, 12, 0)
    titles_today = {t.title for t in db.due_today(now)}
    assert titles_today == {"heute fällig", "überfällig"}
    assert [t.title for t in db.scheduled(now)] == ["zukunft"]
    assert len(db.all_tasks(include_completed=False)) == 4
    assert len(db.all_tasks()) == 5


def test_due_reminders_and_mark_notified(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("L")
    db.add_task(lst.uid, "fällig", due="2024-05-10 09:00")
    db.add_task(lst.uid, "später", due="2024-05-11 09:00")
    now = datetime(2024, 5, 10, 10, 0)
    due = db.due_reminders(now)
    assert [t.title for t in due] == ["fällig"]
    db.mark_notified(due[0].uid)
    assert db.due_reminders(now) == []
    # notify again after a new due date (recurring)
    db.update_task(due[0].uid, due="2024-05-10 08:00")
    assert [t.title for t in db.due_reminders(now)] == ["fällig"]


def test_subtasks(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("Projekt")
    parent = db.add_task(lst.uid, "Umzug")
    db.add_task(lst.uid, "Kartons packen", parent_uid=parent.uid)
    db.add_task(lst.uid, "Spedition", parent_uid=parent.uid)
    kids = db.children(parent.uid)
    assert {k.title for k in kids} == {"Kartons packen", "Spedition"}


def test_dirty_flags_for_sync(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("L")
    t = db.add_task(lst.uid, "x")
    assert t.dirty == 1
    db.mark_task_synced(t.uid, '"abc"')
    assert db.get_task(t.uid).dirty == 0
    assert db.get_task(t.uid).etag == '"abc"'
    db.update_task(t.uid, title="y")
    assert db.get_task(t.uid).dirty == 1
    db.delete_task(t.uid)
    assert db.get_task(t.uid).deleted == 1
    db.mark_task_synced(t.uid, None)
    db.purge_deleted()
    assert db.get_task(t.uid) is None


def test_upsert_from_remote(tmp_path):
    db = make_db(tmp_path)
    lst = db.add_list("L")
    from erinnerungen.db import Task

    remote = Task(
        uid="remote-1", list_uid=lst.uid, title="Remote", notes="n", due="2024-06-01",
        rrule=None, status="NEEDS-ACTION", percent=0, parent_uid=None, sort=0,
        etag=None, created="2024-05-01T00:00:00Z", modified="2024-05-02T00:00:00Z",
        sequence=3, dirty=0, deleted=0, notified=None,
    )
    db.upsert_from_remote(remote, '"e1"')
    got = db.get_task("remote-1")
    assert got.title == "Remote" and got.dirty == 0 and got.etag == '"e1"'
