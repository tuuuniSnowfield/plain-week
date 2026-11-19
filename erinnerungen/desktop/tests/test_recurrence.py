from datetime import datetime

import pytest

from erinnerungen import recurrence as rec


def test_parse_rejects_unknown_keys():
    with pytest.raises(rec.RuleError):
        rec.parse_rrule("FREQ=DAILY;EVIL=1")
    with pytest.raises(rec.RuleError):
        rec.parse_rrule("RRULE:X")
    with pytest.raises(rec.RuleError):
        rec.parse_rrule("INTERVAL=2")  # FREQ fehlt


def test_daily():
    r = rec.build_rrule("DAILY")
    assert rec.next_after(r, datetime(2024, 1, 31, 18, 0), datetime(2024, 1, 31, 18, 0)) == datetime(2024, 2, 1, 18, 0)


def test_weekly_keeps_weekday():
    anchor = datetime(2024, 1, 31, 9, 0)  # Mittwoch
    r = rec.preset("weekly", anchor)
    assert r == "FREQ=WEEKLY;BYDAY=WE"
    nxt = rec.next_after(r, anchor, anchor)
    assert nxt == datetime(2024, 2, 7, 9, 0)
    assert nxt.weekday() == 2


def test_monthly():
    anchor = datetime(2024, 1, 15, 12, 0)
    r = rec.preset("monthly", anchor)
    assert rec.next_after(r, anchor, anchor) == datetime(2024, 2, 15, 12, 0)


def test_last_day_of_month():
    anchor = datetime(2024, 1, 31, 10, 0)
    r = rec.preset("last_day_of_month", anchor)
    assert r == "FREQ=MONTHLY;BYMONTHDAY=-1"
    assert rec.next_after(r, anchor, anchor) == datetime(2024, 2, 29, 10, 0)  # 2024 ist Schaltjahr
    assert rec.next_after(r, datetime(2024, 2, 29, 10, 0), datetime(2024, 2, 29, 10, 0)) == datetime(2024, 3, 31, 10, 0)
    assert rec.next_after(r, datetime(2023, 2, 28, 10, 0), datetime(2023, 2, 28, 10, 0)) == datetime(2023, 3, 31, 10, 0)


def test_interval_and_count():
    r = rec.build_rrule("DAILY", interval=2, count=3)
    start = datetime(2024, 3, 1, 8, 0)
    assert rec.next_after(r, start, start) == datetime(2024, 3, 3, 8, 0)
    assert rec.next_after(r, start, datetime(2024, 3, 3, 8, 0)) == datetime(2024, 3, 5, 8, 0)
    assert rec.next_after(r, start, datetime(2024, 3, 5, 8, 0)) is None  # COUNT=3 erreicht


def test_until():
    r = rec.build_rrule("DAILY", until="20240305")
    start = datetime(2024, 3, 1, 8, 0)
    assert rec.next_after(r, start, datetime(2024, 3, 4, 8, 0)) == datetime(2024, 3, 5, 8, 0)
    assert rec.next_after(r, start, datetime(2024, 3, 5, 8, 0)) is None


def test_describe_de():
    assert rec.describe("FREQ=DAILY") == "Täglich"
    assert rec.describe("FREQ=WEEKLY;BYDAY=MO") == "Wöchentlich (Mo)"
    assert rec.describe("FREQ=MONTHLY;BYMONTHDAY=-1") == "Monatlich – letzter Tag im Monat"
    assert rec.describe("FREQ=MONTHLY") == "Monatlich"
    assert rec.describe("FREQ=DAILY;INTERVAL=3") == "Alle 3 Tage"
