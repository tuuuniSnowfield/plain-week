import os
from datetime import datetime

from erinnerungen import notify
from erinnerungen.db import Database


def test_fire_due_once(tmp_path):
    db = Database(os.path.join(tmp_path, "t.db"))
    lst = db.add_list("L")
    db.add_task(lst.uid, "Wichtig", due="2024-05-10 09:00", rrule="FREQ=DAILY")
    now = datetime(2024, 5, 10, 9, 5)
    fired = notify.fire_due(db, now)
    assert [t.title for t in fired] == ["Wichtig"]
    assert notify.notification_body(fired[0]) == "Täglich – 10.05.2024 09:00 Uhr"
    assert notify.fire_due(db, now) == []  # kein Duplikat
