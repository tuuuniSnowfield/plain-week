import os

from erinnerungen import ics
from erinnerungen.db import Database
from erinnerungen.folder import FolderBackend
from erinnerungen.sync import SyncEngine


def make_pair(tmp_path):
    db = Database(os.path.join(tmp_path, "t.db"))
    backend = FolderBackend(os.path.join(tmp_path, "ordner"))
    return db, SyncEngine(db, backend)


def test_folder_sync_push_and_pull(tmp_path):
    db, engine = make_pair(tmp_path)
    lst = db.add_list("Einkaufen", color="#ff0000", icon="🛒")
    db.add_task(lst.uid, "Milch", due="2024-05-10 18:00")
    db.add_task(lst.uid, "Brot")
    report = engine.sync()
    assert report.pushed == 2 and not report.errors

    # file exists and contains both VTODOs
    files = os.listdir(engine.backend.root)
    assert files == ["einkaufen.ics"]
    with open(os.path.join(engine.backend.root, files[0]), encoding="utf-8") as f:
        text = f.read()
    assert {t.summary for t in ics.parse_calendar(text)} == {"Milch", "Brot"}
    props = ics.parse_calendar_props(text)
    assert props[ics.LIST_NAME_PROP] == "Einkaufen"

    # zweite "Instanz" (neue DB, gleiche Datei) pullt alles
    db2 = Database(os.path.join(tmp_path, "t2.db"))
    engine2 = SyncEngine(db2, FolderBackend(os.path.join(tmp_path, "ordner")))
    lst2 = db2.add_list("Einkaufen")
    rep2 = engine2.sync()
    assert rep2.pulled == 2
    titles = {t.title for t in db2.tasks_in_list(lst2.uid)}
    assert titles == {"Milch", "Brot"}
    assert db2.get_task([t for t in db2.tasks_in_list(lst2.uid) if t.title == "Milch"][0].uid).due == "2024-05-10 18:00"


def test_folder_sync_delete_and_lww(tmp_path):
    db, engine = make_pair(tmp_path)
    lst = db.add_list("L")
    t = db.add_task(lst.uid, "alt", due="2024-05-01")
    engine.sync()
    # delete locally → deleted remotely
    db.delete_task(t.uid)
    rep = engine.sync()
    assert rep.pushed == 1
    with open(os.path.join(backend_path(engine), "l.ics"), encoding="utf-8") as f:
        assert ics.parse_calendar(f.read()) == []

    # remote change (directly in file) wins over non-dirty local
    engine.backend.upload("l.ics", t.uid, ics.serialize_vtodo(ics.VTodo(uid=t.uid, summary="remote-geändert")), None)
    # use a fresh DB for a clean case:
    db2 = Database(os.path.join(tmp_path, "t3.db"))
    engine2 = SyncEngine(db2, FolderBackend(os.path.join(tmp_path, "ordner")))
    lst2 = db2.add_list("L")
    engine2.sync()
    t2 = [x for x in db2.tasks_in_list(lst2.uid) if x.uid == t.uid][0]
    assert t2.title == "remote-geändert"
    assert t2.dirty == 0


def backend_path(engine) -> str:
    return engine.backend.root


def test_conflict_remote_newer_wins_over_dirty(tmp_path):
    db, engine = make_pair(tmp_path)
    lst = db.add_list("L")
    t = db.add_task(lst.uid, "lokal")
    engine.sync()
    # remote changes – simulate a newer remote state
    import datetime
    v = ics.VTodo(uid=t.uid, summary="remote-neuer", modified=datetime.datetime(2030, 1, 1))
    engine.backend.upload("l.ics", t.uid, ics.serialize_vtodo(v), None)
    # local dirty but older → remote wins
    db.update_task(t.uid, title="lokal-alt")
    # set local modified artificially old
    db._exec("UPDATE tasks SET modified='2020-01-01T00:00:00Z' WHERE uid=?", (t.uid,))
    rep = engine.sync()
    assert rep.conflicts_lww_remote_wins == 1
    assert db.get_task(t.uid).title == "remote-neuer"
    assert db.get_task(t.uid).dirty == 0


def test_subtask_relation_survives_sync(tmp_path):
    db, engine = make_pair(tmp_path)
    lst = db.add_list("Projekt")
    parent = db.add_task(lst.uid, "Umzug")
    engine.sync()
    db.add_task(lst.uid, "Kartons", parent_uid=parent.uid)
    engine.sync()
    db2 = Database(os.path.join(tmp_path, "t2.db"))
    engine2 = SyncEngine(db2, FolderBackend(os.path.join(tmp_path, "ordner")))
    lst2 = db2.add_list("Projekt")
    engine2.sync()
    child2 = [x for x in db2.tasks_in_list(lst2.uid) if x.title == "Kartons"][0]
    parent2 = [x for x in db2.tasks_in_list(lst2.uid) if x.title == "Umzug"][0]
    assert child2.parent_uid == parent2.uid
