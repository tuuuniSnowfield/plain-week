"""Minimal ICS parser/serializer (RFC 5545) for VCALENDAR/VTODO – stdlib only.

Mapping see spec/DATA-MODEL.md. Times are stored as floating local (no timezone);
UTC times (…Z) are converted to local time when read.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

PRODID = "-//erinnerungen//Erinnerungen//DE"
LIST_NAME_PROP = "X-WR-CALNAME"
LIST_COLOR_PROP = "X-ERINNERUNGEN-COLOR"
LIST_ICON_PROP = "X-ERINNERUNGEN-ICON"


@dataclass
class VTodo:
    uid: str
    summary: str = ""
    description: str = ""
    due_date: date | None = None
    due_time: time | None = None
    dtstart: datetime | None = None
    rrule: str | None = None
    status: str = "NEEDS-ACTION"
    percent: int = 0
    related_parents: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    sequence: int = 0
    created: datetime | None = None
    modified: datetime | None = None
    completed: datetime | None = None

    @property
    def due(self) -> str | None:
        if self.due_date is None:
            return None
        if self.due_time is None:
            return self.due_date.isoformat()
        return f"{self.due_date.isoformat()} {self.due_time.strftime('%H:%M')}"


# --- Zeilen/Escape --------------------------------------------------------


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [line for line in lines if line]


def fold(line: str) -> list[str]:
    out = []
    while len(line.encode("utf-8")) > 75:
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return out


def escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def unescape_text(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            out.append({"n": "\n", "N": "\n"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_prop(line: str) -> tuple[str, dict[str, str], str]:
    """NAME;PARAM=VAL;PARAM2="q":value → (NAME, {PARAM: VAL}, value)."""
    in_quotes = False
    sep = -1
    for i, c in enumerate(line):
        if c == '"':
            in_quotes = not in_quotes
        elif c == ":" and not in_quotes:
            sep = i
            break
    if sep < 0:
        return line.strip().upper(), {}, ""
    head, value = line[:sep], line[sep + 1 :]
    pieces = []
    buf = ""
    in_quotes = False
    for c in head:
        if c == '"':
            in_quotes = not in_quotes
            buf += c
        elif c == ";" and not in_quotes:
            pieces.append(buf)
            buf = ""
        else:
            buf += c
    pieces.append(buf)
    name = pieces[0].strip().upper()
    params: dict[str, str] = {}
    for p in pieces[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


# --- Datum/Zeit -----------------------------------------------------------


def format_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def format_datetime_local(d: date, t: time) -> str:
    return f"{d.strftime('%Y%m%d')}T{t.strftime('%H%M%S')}"


def parse_ics_dt(value: str) -> tuple[date, time | None]:
    v = value.strip()
    is_utc = v.endswith("Z")
    v = v.rstrip("Z")
    if "T" in v:
        dt = datetime.strptime(v, "%Y%m%dT%H%M%S")
        if is_utc:
            dt = dt.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
        return dt.date(), dt.time().replace(second=0, microsecond=0)
    d = datetime.strptime(v, "%Y%m%d").date()
    return d, None


# --- Komponenten ----------------------------------------------------------


def _blocks(lines: list[str], name: str) -> list[list[str]]:
    out = []
    cur = None
    for line in lines:
        u = line.upper()
        if u == f"BEGIN:{name}":
            cur = [line]
        elif u == f"END:{name}" and cur is not None:
            cur.append(line)
            out.append(cur)
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


def vtodo_blocks(text: str) -> list[tuple[str, str]]:
    """All VTODO raw blocks as (UID, raw text)."""
    out = []
    for block in _blocks(unfold(text), "VTODO"):
        uid = ""
        for line in block:
            name, _, value = split_prop(line)
            if name == "UID":
                uid = value.strip()
                break
        out.append((uid, "\r\n".join(block) + "\r\n"))
    return out


def replace_vtodo_block(text: str, uid: str, new_block: str) -> str:
    blocks = vtodo_blocks(text)
    replaced = False
    body = []
    for buid, btext in blocks:
        if buid == uid:
            body.append(new_block.rstrip("\r\n"))
            replaced = True
        else:
            body.append(btext.rstrip("\r\n"))
    if not replaced:
        body.append(new_block.rstrip("\r\n"))
    head = text
    for _, btext in blocks:
        head = head.replace(btext, "", 1)
    return _assemble_calendar(head, body)


def remove_vtodo_block(text: str, uid: str) -> str:
    blocks = vtodo_blocks(text)
    body = [b.rstrip("\r\n") for buid, b in blocks if buid != uid]
    head = text
    for _, btext in blocks:
        head = head.replace(btext, "", 1)
    return _assemble_calendar(head, body)


def _assemble_calendar(head: str, bodies: list[str]) -> str:
    lines = unfold(head)
    out = [line for line in lines if line]
    insert_at = next((i for i, x in enumerate(out) if x.upper() == "END:VCALENDAR"), len(out))
    for b in bodies:
        out[insert_at:insert_at] = unfold(b)
        insert_at += len(unfold(b))
    return "\r\n".join(out) + "\r\n"


def parse_vtodo(block_lines: list[str]) -> VTodo:
    v = VTodo(uid="")
    for line in block_lines:
        name, params, value = split_prop(line)
        if name == "UID":
            v.uid = value.strip()
        elif name == "SUMMARY":
            v.summary = unescape_text(value)
        elif name == "DESCRIPTION":
            v.description = unescape_text(value)
        elif name == "DUE":
            v.due_date, v.due_time = parse_ics_dt(value)
        elif name == "DTSTART":
            d, t = parse_ics_dt(value)
            v.dtstart = datetime.combine(d, t or time.min)
        elif name == "RRULE":
            v.rrule = value.strip().upper()
        elif name == "STATUS":
            v.status = value.strip().upper()
        elif name == "PERCENT-COMPLETE":
            with contextlib.suppress(ValueError):
                v.percent = max(0, min(100, int(value)))
        elif name == "RELATED-TO" and params.get("RELTYPE", "PARENT").upper() == "PARENT":
            v.related_parents.append(value.strip())
        elif name == "CATEGORIES":
            v.categories = [unescape_text(c) for c in value.split(",")]
        elif name == "SEQUENCE":
            with contextlib.suppress(ValueError):
                v.sequence = int(value)
        elif name == "CREATED":
            d, t = parse_ics_dt(value)
            v.created = datetime.combine(d, t or time.min)
        elif name == "LAST-MODIFIED":
            d, t = parse_ics_dt(value)
            v.modified = datetime.combine(d, t or time.min)
        elif name == "COMPLETED":
            d, t = parse_ics_dt(value)
            v.completed = datetime.combine(d, t or time.min)
    return v


def parse_calendar(text: str) -> list[VTodo]:
    return [parse_vtodo(b) for b in _blocks(unfold(text), "VTODO")]


def parse_calendar_props(text: str) -> dict[str, str]:
    """VCALENDAR-level properties (list name/color/icon)."""
    props = {}
    inside = False
    for line in unfold(text):
        u = line.upper()
        if u == "BEGIN:VCALENDAR":
            inside = True
            continue
        if u == "END:VCALENDAR":
            break
        if inside:
            name, _, value = split_prop(line)
            if name in (LIST_NAME_PROP, LIST_COLOR_PROP, LIST_ICON_PROP, "VERSION", "PRODID"):
                props[name] = value
    return props


# --- Serialisieren --------------------------------------------------------


def serialize_vtodo(v: VTodo) -> str:
    lines = ["BEGIN:VTODO", f"UID:{v.uid}"]
    if v.created:
        lines.append(f"CREATED:{v.created.strftime('%Y%m%dT%H%M%SZ')}")
    if v.modified:
        lines.append(f"LAST-MODIFIED:{v.modified.strftime('%Y%m%dT%H%M%SZ')}")
    lines.append(f"SEQUENCE:{v.sequence}")
    lines.append(f"SUMMARY:{escape_text(v.summary)}")
    if v.description:
        lines.append(f"DESCRIPTION:{escape_text(v.description)}")
    if v.due_date:
        if v.due_time:
            lines.append(f"DUE:{format_datetime_local(v.due_date, v.due_time)}")
        else:
            lines.append(f"DUE;VALUE=DATE:{format_date(v.due_date)}")
    if v.dtstart:
        lines.append(f"DTSTART:{v.dtstart.strftime('%Y%m%dT%H%M%S')}")
    if v.rrule:
        lines.append(f"RRULE:{v.rrule}")
    lines.append(f"STATUS:{v.status}")
    lines.append(f"PERCENT-COMPLETE:{v.percent}")
    for parent in v.related_parents:
        lines.append(f"RELATED-TO;RELTYPE=PARENT:{parent}")
    if v.categories:
        lines.append("CATEGORIES:" + ",".join(escape_text(c) for c in v.categories))
    if v.completed:
        lines.append(f"COMPLETED:{v.completed.strftime('%Y%m%dT%H%M%SZ')}")
    lines.append("END:VTODO")
    out = []
    for line in lines:
        out.extend(fold(line))
    return "\r\n".join(out) + "\r\n"


def serialize_calendar(
    vtodos: list[VTodo],
    name: str | None = None,
    color: str | None = None,
    icon: str | None = None,
) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
    ]
    if name:
        lines.append(f"{LIST_NAME_PROP}:{escape_text(name)}")
    if color:
        lines.append(f"{LIST_COLOR_PROP}:{color}")
    if icon:
        lines.append(f"{LIST_ICON_PROP}:{escape_text(icon)}")
    out = list(lines)
    for v in vtodos:
        out.extend(unfold(serialize_vtodo(v)))
    out.append("END:VCALENDAR")
    folded = []
    for line in out:
        folded.extend(fold(line))
    return "\r\n".join(folded) + "\r\n"


UID_IN_HREF = re.compile(r"([^/]+)\.ics$", re.IGNORECASE)


def href_uid(href: str) -> str | None:
    m = UID_IN_HREF.search(href.rstrip("/"))
    return m.group(1) if m else None
