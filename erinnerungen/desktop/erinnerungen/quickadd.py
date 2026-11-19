"""Quick entry in natural language (German locale).

Beispiele:
  »Milch kaufen morgen 18 Uhr !Einkaufen«
  »Zahnarzt übermorgen 9:30«
  »Bericht in 3 Tagen #Arbeit«
  »Müll raus heute«
  »Miete am 01.03. in Haushalt«

Grammar (everything optional except the title):
  [Titel …] [Datum] [Uhrzeit] [!Liste | #Liste | »in <Listenname>«]
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS_DE = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}


@dataclass
class QuickAdd:
    title: str
    day: date | None = None
    clock: time | None = None
    list_name: str | None = None


_TIME_CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
_TIME_UHR = re.compile(r"\b([01]?\d|2[0-3])\s*uhr\b", re.IGNORECASE)
_IN_DAYS = re.compile(r"\bin\s+(\d+)\s+(tag|tage|tagen)\b", re.IGNORECASE)
_IN_WEEKS = re.compile(r"\bin\s+(\d+)\s+(woche|wochen)\b", re.IGNORECASE)
_IN_MONTHS = re.compile(r"\bin\s+(\d+)\s+(monat|monate|monaten)\b", re.IGNORECASE)
_DATE_DE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?:(\d{4}))?(?=$|\b|\s)")
_LIST_SIGIL = re.compile(r"[!#](\S+)")
_LIST_IN = re.compile(
    r"\bin\s+([^\d!?\s][^!#]*?)(?=\s*$|\s+(?:heute|morgen|übermorgen|uebermorgen|in\s|\d{1,2}[:.]\d{2}|\d{1,2}\s*uhr)\b)",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(
    r"\b(nächsten|naechsten|kommenden|am\s+)?(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
    re.IGNORECASE,
)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def parse(text: str, list_names: list[str] | None = None, today: date | None = None) -> QuickAdd:
    today = today or date.today()
    result = QuickAdd(title="")
    rest = text.strip()
    list_names = list_names or []

    # Liste: !name / #name (Sigil gewinnt)
    m = _LIST_SIGIL.search(rest)
    if m:
        ref = m.group(1)
        match = _resolve_list(ref, list_names)
        if match:
            result.list_name = match
            rest = (rest[: m.start()] + rest[m.end():]).strip()
        else:
            result.list_name = ref  # unbekannt – UI kann nachfragen/neu anlegen
            rest = (rest[: m.start()] + rest[m.end():]).strip()

    # Datum zuerst (damit "01.06." nicht als Uhrzeit "01.06" missverstanden wird)
    day = None
    low = rest.lower()
    if re.search(r"\bheute\b", low):
        day = today
        rest = re.sub(r"\bheute\b", "", rest, flags=re.IGNORECASE).strip()
    elif re.search(r"\b(übermorgen|uebermorgen)\b", low):
        day = today + timedelta(days=2)
        rest = re.sub(r"\b(übermorgen|uebermorgen)\b", "", rest, flags=re.IGNORECASE).strip()
    elif re.search(r"\bmorgen\b", low):
        day = today + timedelta(days=1)
        rest = re.sub(r"\bmorgen\b", "", rest, flags=re.IGNORECASE).strip()
    else:
        m = _IN_DAYS.search(rest)
        if m:
            day = today + timedelta(days=int(m.group(1)))
            rest = rest[: m.start()] + rest[m.end():]
        else:
            m = _IN_WEEKS.search(rest)
            if m:
                day = today + timedelta(weeks=int(m.group(1)))
                rest = rest[: m.start()] + rest[m.end():]
            else:
                m = _IN_MONTHS.search(rest)
                if m:
                    day = _add_months(today, int(m.group(1)))
                    rest = rest[: m.start()] + rest[m.end():]
                else:
                    m = _DATE_DE.search(rest)
                    if m:
                        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
                        year = int(y) if y else (today.year if (mo, d) >= (today.month, today.day) else today.year + 1)
                        try:
                            day = date(year, mo, d)
                            rest = rest[: m.start()] + rest[m.end():]
                            rest = re.sub(r"\bam\s*$", "", rest, flags=re.IGNORECASE).strip()
                        except ValueError:
                            pass
                    else:
                        m = _WEEKDAY.search(rest)
                        if m:
                            target = WEEKDAYS_DE[m.group(2).lower()]
                            ahead = (target - today.weekday()) % 7 or 7
                            day = today + timedelta(days=ahead)
                            rest = rest[: m.start()] + rest[m.end():]
    result.day = day

    # Uhrzeit: 18:00 / 9:30 / 18 Uhr
    clock = None
    m = _TIME_CLOCK.search(rest) or _TIME_UHR.search(rest)
    if m:
        h, mi = int(m.group(1)), int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
        if m.re is _TIME_UHR:
            mi = 0
        clock = time(h % 24, mi)
        rest = (rest[: m.start()] + rest[m.end():]).strip()
    result.clock = clock


    # »in <Listenname>« am Ende (falls kein Sigil verwendet wurde)
    if result.list_name is None and list_names:
        m = _LIST_IN.search(rest)
        if m:
            ref = m.group(1).strip()
            match = _resolve_list(ref, list_names)
            if match:
                result.list_name = match
                rest = (rest[: m.start()] + rest[m.end():]).strip()

    result.title = re.sub(r"\s{2,}", " ", rest).strip(" ,")
    return result


def _resolve_list(ref: str, list_names: list[str]) -> str | None:
    ref_l = ref.lower()
    for name in sorted(list_names, key=len, reverse=True):
        if name.lower() == ref_l or name.lower().startswith(ref_l):
            return name
    return None


def format_due_de(day: date | None, clock: time | None) -> str:
    if day is None:
        return ""
    s = day.strftime("%d.%m.%Y")
    if clock:
        s += f" {clock.strftime('%H:%M')} Uhr"
    return s


def to_due_string(day: date | None, clock: time | None) -> str | None:
    if day is None:
        return None
    return f"{day.isoformat()} {clock.strftime('%H:%M')}" if clock else day.isoformat()


def now_dt() -> datetime:
    return datetime.now()
