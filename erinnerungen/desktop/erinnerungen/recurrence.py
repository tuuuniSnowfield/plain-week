"""Recurrence rules (RRULE subset of RFC 5545).

Deliberately small (1:1 Apple Reminders): DAILY, WEEKLY, MONTHLY, YEARLY with
INTERVAL, BYDAY, BYMONTHDAY (incl. -1 = last day of month), UNTIL, COUNT.
To extend, just widen ALLOWED_KEYS/ALLOWED_FREQ – the Android/Windows ports
implement the same subset (see spec/DATA-MODEL.md).
"""
from __future__ import annotations

from datetime import datetime

from dateutil.rrule import rrulestr

ALLOWED_KEYS = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "UNTIL", "COUNT"}
ALLOWED_FREQ = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}

PRESETS = ("none", "daily", "weekly", "monthly", "last_day_of_month", "yearly")

WEEKDAY_NAMES_DE = {
    "MO": "Mo",
    "TU": "Di",
    "WE": "Mi",
    "TH": "Do",
    "FR": "Fr",
    "SA": "Sa",
    "SU": "So",
}


class RuleError(ValueError):
    pass


def parse_rrule(value: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in value.strip().split(";"):
        if not chunk:
            continue
        key, sep, val = chunk.partition("=")
        key = key.strip().upper()
        if not sep or key not in ALLOWED_KEYS:
            raise RuleError(f"Unsupported RRULE field: {chunk!r}")
        parts[key] = val.strip().upper()
    freq = parts.get("FREQ")
    if freq not in ALLOWED_FREQ:
        raise RuleError(f"FREQ missing or not allowed: {freq!r}")
    if "INTERVAL" in parts and (not parts["INTERVAL"].isdigit() or int(parts["INTERVAL"]) < 1):
        raise RuleError("INTERVAL must be a positive integer")
    if "COUNT" in parts and (not parts["COUNT"].isdigit() or int(parts["COUNT"]) < 1):
        raise RuleError("COUNT must be a positive integer")
    if "BYDAY" in parts:
        days = parts["BYDAY"].split(",")
        if any(d not in WEEKDAYS for d in days):
            raise RuleError(f"BYDAY has invalid values: {parts['BYDAY']!r}")
    if "BYMONTHDAY" in parts:
        vals = parts["BYMONTHDAY"].split(",")
        if not all(v.lstrip("-").isdigit() and v != "0" for v in vals):
            raise RuleError(f"BYMONTHDAY has invalid values: {parts['BYMONTHDAY']!r}")
    if "UNTIL" in parts:
        u = parts["UNTIL"].rstrip("Z")
        if not (u.isdigit() and len(u) in (8, 15)):
            raise RuleError(f"UNTIL has an invalid format: {parts['UNTIL']!r}")
    return parts


def build_rrule(
    freq: str,
    interval: int = 1,
    byday: list[str] | None = None,
    bymonthday: list[int] | None = None,
    until: str | None = None,
    count: int | None = None,
) -> str:
    freq = freq.upper()
    if freq not in ALLOWED_FREQ:
        raise RuleError(f"FREQ not allowed: {freq!r}")
    if interval < 1:
        raise RuleError("INTERVAL must be >= 1")
    parts = [f"FREQ={freq}"]
    if interval > 1:
        parts.append(f"INTERVAL={interval}")
    if byday:
        for d in byday:
            if d.upper() not in WEEKDAYS:
                raise RuleError(f"BYDAY invalid: {d!r}")
        parts.append("BYDAY=" + ",".join(d.upper() for d in byday))
    if bymonthday:
        parts.append("BYMONTHDAY=" + ",".join(str(v) for v in bymonthday))
    if until:
        parts.append(f"UNTIL={until}")
    if count:
        parts.append(f"COUNT={count}")
    return ";".join(parts)


def preset(preset_key: str, anchor: datetime) -> str | None:
    """Apple presets. anchor = due date/time of the task."""
    if preset_key == "none":
        return None
    if preset_key == "daily":
        return build_rrule("DAILY")
    if preset_key == "weekly":
        weekday = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[anchor.weekday()]
        return build_rrule("WEEKLY", byday=[weekday])
    if preset_key == "monthly":
        return build_rrule("MONTHLY")
    if preset_key == "last_day_of_month":
        return build_rrule("MONTHLY", bymonthday=[-1])
    if preset_key == "yearly":
        return build_rrule("YEARLY")
    raise RuleError(f"Unknown preset: {preset_key!r}")


def next_after(rrule_value: str, dtstart: datetime, after: datetime) -> datetime | None:
    """Next occurrence after `after` (exclusive). None when COUNT/UNTIL is reached."""
    parts = parse_rrule(rrule_value)
    until = parts.get("UNTIL", "")
    if until and len(until.rstrip("Z")) == 8:
        # RFC 5545: UNTIL muss zum Wertetyp passen; bei Datum+Uhrzeit auf Tagesende setzen
        parts["UNTIL"] = until.rstrip("Z") + "T235959" + ("Z" if until.endswith("Z") else "")
    normalized = ";".join(f"{k}={v}" for k, v in parts.items())
    text = f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{normalized}"
    rule = rrulestr(text)
    if after < dtstart:
        after = dtstart
    return rule.after(after, inc=False)


def describe(rrule_value: str) -> str:
    parts = parse_rrule(rrule_value)
    freq = parts["FREQ"]
    interval = int(parts.get("INTERVAL", "1"))
    if freq == "DAILY":
        return "Täglich" if interval == 1 else f"Alle {interval} Tage"
    if freq == "WEEKLY":
        days = parts.get("BYDAY", "")
        names = ", ".join(WEEKDAY_NAMES_DE[d] for d in days.split(",") if d in WEEKDAY_NAMES_DE)
        if interval == 1:
            return f"Wöchentlich ({names})" if names else "Wöchentlich"
        return f"Alle {interval} Wochen ({names})" if names else f"Alle {interval} Wochen"
    if freq == "MONTHLY":
        if parts.get("BYMONTHDAY") == "-1":
            return "Monatlich – letzter Tag im Monat"
        return "Monatlich" if interval == 1 else f"Alle {interval} Monate"
    if freq == "YEARLY":
        return "Jährlich" if interval == 1 else f"Alle {interval} Jahre"
    return rrule_value
