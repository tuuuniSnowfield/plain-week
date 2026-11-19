from datetime import date, time

from erinnerungen import ics


def test_roundtrip_vtodo():
    v = ics.VTodo(
        uid="abc@erinnerungen",
        summary="Milch, Butter; Kuchen",
        description="Zeile 1\nZeile 2",
        due_date=date(2024, 2, 29),
        due_time=time(18, 30),
        rrule="FREQ=WEEKLY;BYDAY=TH",
        status="NEEDS-ACTION",
        percent=0,
        related_parents=["parent-1"],
        sequence=2,
    )
    text = ics.serialize_vtodo(v)
    back = ics.parse_calendar(text)[0]
    assert back.uid == v.uid
    assert back.summary == "Milch, Butter; Kuchen"
    assert back.description == "Zeile 1\nZeile 2"
    assert back.due_date == date(2024, 2, 29)
    assert back.due_time == time(18, 30)
    assert back.rrule == "FREQ=WEEKLY;BYDAY=TH"
    assert back.related_parents == ["parent-1"]
    assert back.sequence == 2


def test_date_only_due():
    v = ics.VTodo(uid="u1", summary="x", due_date=date(2024, 3, 1))
    text = ics.serialize_vtodo(v)
    assert "DUE;VALUE=DATE:20240301" in text
    back = ics.parse_calendar(text)[0]
    assert back.due_date == date(2024, 3, 1)
    assert back.due_time is None
    assert back.due == "2024-03-01"


def test_unfold_and_fold():
    long_line = "SUMMARY:" + "x" * 200
    folded = ics.fold(long_line)
    assert all(len(x.encode()) <= 75 for x in folded)
    assert ics.unfold("\r\n".join(folded)) == [long_line]


def test_utc_z_converted_to_local():
    d, t = ics.parse_ics_dt("20240601T120000Z")
    assert d == date(2024, 6, 1)
    assert t is not None


def test_replace_and_remove_vtodo_block_preserves_rest():
    cal = ics.serialize_calendar(
        [ics.VTodo(uid="u1", summary="alt"), ics.VTodo(uid="u2", summary="bleibt")],
        name="Liste", color="#ff0000",
    )
    new_block = ics.serialize_vtodo(ics.VTodo(uid="u1", summary="neu"))
    out = ics.replace_vtodo_block(cal, "u1", new_block)
    todos = ics.parse_calendar(out)
    assert {t.uid: t.summary for t in todos} == {"u1": "neu", "u2": "bleibt"}
    props = ics.parse_calendar_props(out)
    assert props[ics.LIST_NAME_PROP] == "Liste"
    out2 = ics.remove_vtodo_block(out, "u2")
    assert [t.uid for t in ics.parse_calendar(out2)] == ["u1"]


def test_href_uid():
    assert ics.href_uid("/remote.php/dav/calendars/u/liste/abc.ics") == "abc"
    assert ics.href_uid("abc.ics") == "abc"
