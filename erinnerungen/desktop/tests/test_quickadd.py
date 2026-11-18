from datetime import date, time

from erinnerungen import quickadd

TODAY = date(2024, 5, 6)  # Montag


def test_plain_title():
    r = quickadd.parse("Milch kaufen", today=TODAY)
    assert r.title == "Milch kaufen"
    assert r.day is None and r.clock is None and r.list_name is None


def test_tomorrow_with_time_and_list():
    r = quickadd.parse("Milch kaufen morgen 18 Uhr !Einkaufen", list_names=["Einkaufen"], today=TODAY)
    assert r.title == "Milch kaufen"
    assert r.day == date(2024, 5, 7)
    assert r.clock == time(18, 0)
    assert r.list_name == "Einkaufen"


def test_uebermorgen_clock_colon():
    r = quickadd.parse("Zahnarzt übermorgen 9:30", today=TODAY)
    assert r.title == "Zahnarzt"
    assert r.day == date(2024, 5, 8)
    assert r.clock == time(9, 30)


def test_in_days():
    r = quickadd.parse("Bericht in 3 Tagen", today=TODAY)
    assert r.day == date(2024, 5, 9)
    assert r.title == "Bericht"


def test_in_weeks():
    r = quickadd.parse("Team-Meeting in 2 Wochen", today=TODAY)
    assert r.day == date(2024, 5, 20)


def test_weekday_next():
    r = quickadd.parse("Kino freitag", today=TODAY)  # heute ist Montag
    assert r.day == date(2024, 5, 10)
    r2 = quickadd.parse("Kino montag", today=TODAY)  # today is Monday → next Monday
    assert r2.day == date(2024, 5, 13)


def test_numeric_date():
    r = quickadd.parse("Miete am 01.06.", today=TODAY)
    assert r.day == date(2024, 6, 1)
    assert r.title == "Miete"


def test_list_via_in():
    r = quickadd.parse("Steuererklärung in Arbeit", list_names=["Arbeit", "Privat"], today=TODAY)
    assert r.list_name == "Arbeit"
    assert r.title == "Steuererklärung"


def test_list_sigil_hash():
    r = quickadd.parse("Zähne putzen #Haushalt morgen", list_names=["Haushalt"], today=TODAY)
    assert r.list_name == "Haushalt"
    assert r.day == date(2024, 5, 7)
    assert r.title == "Zähne putzen"


def test_heute():
    r = quickadd.parse("Müll raus heute", today=TODAY)
    assert r.day == TODAY
    assert r.title == "Müll raus"


def test_to_due_string():
    assert quickadd.to_due_string(date(2024, 5, 7), time(18, 0)) == "2024-05-07 18:00"
    assert quickadd.to_due_string(date(2024, 5, 7), None) == "2024-05-07"
    assert quickadd.to_due_string(None, None) is None
