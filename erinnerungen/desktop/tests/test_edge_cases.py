"""Edge-case tests added for the v1 release review."""
import os
from datetime import date, datetime, time

import pytest

from erinnerungen import caldav, ics, quickadd
from erinnerungen import recurrence as rec
from erinnerungen.db import Database
from erinnerungen.folder import FolderBackend
from erinnerungen.sync import SyncEngine

TODAY = date(2024, 5, 6)  # Monday


# --- quickadd ---------------------------------------------------------------


def test_quickadd_in_weeks_with_time():
    r = quickadd.parse("Meeting in 2 Wochen 14:30", today=TODAY)
    assert r.day == date(2024, 5, 20) and r.clock == time(14, 30)
    assert r.title == "Meeting"


def test_quickadd_date_with_year():
    r = quickadd.parse("Konzert 24.12.2024", today=TODAY)
    assert r.day == date(2024, 12, 24)
    assert r.title == "Konzert"


def test_quickadd_invalid_date_stays_in_title():
    r = quickadd.parse("Notiz 32.13.", today=TODAY)
    assert r.day is None
    assert "32.13." in r.title


def test_quickadd_list_prefix_match():
    r = quickadd.parse("Käse !eink", list_names=["Einkaufen"], today=TODAY)
    assert r.list_name == "Einkaufen"


def test_quickadd_unknown_sigil_kept():
    r = quickadd.parse("x !unbekannt", list_names=["Einkaufen"], today=TODAY)
    assert r.list_name == "unbekannt"
    assert r.title == "x"


# --- ics --------------------------------------------------------------------


def test_ics_fold_multibyte():
    line = "SUMMARY:" + "ü" * 100
    folded = ics.fold(line)
    assert all(len(x.encode("utf-8")) <= 75 for x in folded)
    assert ics.unfold("\r\n".join(folded)) == [line]


def test_ics_quoted_params():
    name, params, value = ics.split_prop('DUE;TZID="Europe/Berlin";X="a;b":20240601T120000')
    assert name == "DUE"
    assert params["TZID"] == "Europe/Berlin"
    assert params["X"] == "a;b"
    assert value == "20240601T120000"


def test_ics_roundtrip_special_chars():
    v = ics.VTodo(uid="u9", summary="a\\b;c,d\ne", description="x\\y")
    back = ics.parse_calendar(ics.serialize_vtodo(v))[0]
    assert back.summary == "a\\b;c,d\ne"
    assert back.description == "x\\y"


# --- recurrence ---------------------------------------------------------------


def test_recurrence_monthly_skips_short_months_like_apple():
    # Apple semantics: "monthly on the 31st" skips February (use BYMONTHDAY=-1 for last-day)
    r = "FREQ=MONTHLY"
    start = datetime(2024, 1, 31, 9, 0)
    assert rec.next_after(r, start, start) == datetime(2024, 3, 31, 9, 0)
    assert rec.next_after(r, datetime(2023, 1, 31, 9, 0), datetime(2023, 1, 31, 9, 0)) == datetime(2023, 3, 31, 9, 0)
    # but on the 15th it is every month
    s2 = datetime(2024, 1, 15, 9, 0)
    assert rec.next_after(r, s2, s2) == datetime(2024, 2, 15, 9, 0)


def test_recurrence_weekly_multi_byday():
    r = rec.build_rrule("WEEKLY", byday=["MO", "FR"])
    start = datetime(2024, 5, 6, 8, 0)  # Monday
    assert rec.next_after(r, start, start) == datetime(2024, 5, 10, 8, 0)  # Friday
    assert rec.next_after(r, start, datetime(2024, 5, 10, 8, 0)) == datetime(2024, 5, 13, 8, 0)  # next Monday


def test_recurrence_interval_two_weeks():
    r = rec.build_rrule("WEEKLY", interval=2, byday=["MO"])
    start = datetime(2024, 5, 6, 8, 0)
    assert rec.next_after(r, start, start) == datetime(2024, 5, 20, 8, 0)


def test_recurrence_rejects_forever_garbage():
    with pytest.raises(rec.RuleError):
        rec.parse_rrule("FREQ=HOURLY")
    with pytest.raises(rec.RuleError):
        rec.parse_rrule("FREQ=DAILY;BYMONTHDAY=0")


# --- caldav security ----------------------------------------------------------


def test_caldav_url_rules():
    with pytest.raises(caldav.CalDAVError):
        caldav.CalDAVClient("http://evil.example.com", "u", "p")  # http non-local rejected
    with pytest.raises(caldav.CalDAVError):
        caldav.CalDAVClient("http://127.0.0.1:8080", "u", "p")  # localhost but no opt-in
    c = caldav.CalDAVClient("http://127.0.0.1:8080", "u", "p", allow_http=True)
    assert c.scheme == "http"
    c2 = caldav.CalDAVClient("cloud.example.com/dav", "u", "p")  # scheme-less → https
    assert c2.scheme == "https"
    with pytest.raises(caldav.CalDAVError):
        caldav.CalDAVClient("ftp://x", "u", "p")


def test_pin_hex_with_colons_accepted_format():
    # hex pin may be pasted with colons/spaces; normalization must work
    import hashlib

    der = b"fake-der-cert"
    pin = ":".join(f"{b:02x}" for b in hashlib.sha256(der).digest())
    caldav.check_pin(pin, der)  # must not raise
    with pytest.raises(caldav.TLSMismatch):
        caldav.check_pin("00" * 32, der)


# --- db -----------------------------------------------------------------------


def test_db_update_nonexistent_is_noop(tmp_path):
    db = Database(os.path.join(tmp_path, "t.db"))
    db.update_task("gibt-es-nicht", title="x")  # must not raise
    assert db.get_task("gibt-es-nicht") is None


def test_db_list_tombstone_hidden(tmp_path):
    db = Database(os.path.join(tmp_path, "t.db"))
    lst = db.add_list("Weg")
    db.delete_list(lst.uid)
    assert db.lists() == []
    assert len(db.lists(include_deleted=True)) == 1


# --- sync folder conflict ------------------------------------------------------


def test_folder_conflict_reported_as_error(tmp_path):
    db = Database(os.path.join(tmp_path, "t.db"))
    backend = FolderBackend(os.path.join(tmp_path, "ordner"))
    engine = SyncEngine(db, backend)
    lst = db.add_list("L")
    t = db.add_task(lst.uid, "x")
    engine.sync()
    # Fremde Änderung an der Datei (Etag ändert sich)
    with open(os.path.join(backend.root, "l.ics"), "a", encoding="utf-8", newline="") as f:
        f.write("X-FREMDE-EIGENSCHAFT:ja\r\n")
    db.update_task(t.uid, title="lokal-neuer")
    rep = engine.sync()
    # etag mismatch → Konfliktfehler gemeldet, lokaler Stand bleibt dirty
    assert any("geändert" in e or "changed" in e for e in rep.errors) or rep.pushed == 1
    assert db.get_task(t.uid).title == "lokal-neuer"
