# DATA-MODEL – shared specification for all platforms

Android (Kotlin/Room) and Windows port against this spec. The Linux app (Python)
is the reference implementation; all core modules are pytest-covered.

## 1. SQLite schema (user_version = 1)

```sql
lists(uid TEXT PK, name TEXT, color TEXT DEFAULT '#3584e4', icon TEXT DEFAULT '●',
      sort INT, remote_path TEXT NULL, etag TEXT NULL,
      created TEXT, modified TEXT, dirty INT DEFAULT 1, deleted INT DEFAULT 0)

tasks(uid TEXT PK, list_uid TEXT NOT NULL REFERENCES lists(uid) ON DELETE CASCADE,
      title TEXT, notes TEXT DEFAULT '', due TEXT NULL, rrule TEXT NULL,
      status TEXT DEFAULT 'NEEDS-ACTION',            -- NEEDS-ACTION | COMPLETED | IN-PROCESS
      percent INT DEFAULT 0, parent_uid TEXT NULL REFERENCES tasks(uid) ON DELETE CASCADE,
      sort INT, etag TEXT NULL, created TEXT, modified TEXT, sequence INT DEFAULT 0,
      dirty INT DEFAULT 1, deleted INT DEFAULT 0, notified TEXT NULL)
```

- `created`/`modified`: UTC ISO-8601 with `Z` (`YYYY-MM-DDTHH:MM:SSZ`).
- `due`: local floating, `YYYY-MM-DD` (date only) or `YYYY-MM-DD HH:MM`.
  Lexicographic order equals chronological order.
- `notified`: holds the `due` value last notified for (prevents duplicate
  notifications; reset when the due date changes).
- `dirty=1` → local state still needs syncing; `deleted=1` → tombstone.

## 2. ICS mapping (RFC 5545; one list = one VCALENDAR, one task = one VTODO)

| lokal            | VTODO                                            |
|------------------|--------------------------------------------------|
| `uid`            | `UID`                                            |
| `title`          | `SUMMARY` (escaped: `\ , ; \n`)                  |
| `notes`          | `DESCRIPTION`                                    |
| `due` Datum only | `DUE;VALUE=DATE:YYYYMMDD`                        |
| `due` mit Zeit   | `DUE:YYYYMMDDTHHMMSS` (floating local)           |
| `rrule`          | `RRULE:…`                                        |
| `status`         | `STATUS`                                         |
| `percent`        | `PERCENT-COMPLETE`                               |
| `parent_uid`     | `RELATED-TO;RELTYPE=PARENT:<uid>`                |
| `sequence`       | `SEQUENCE`                                       |
| `created/modified` | `CREATED` / `LAST-MODIFIED` (UTC, `…Z`)        |
| Liste: name      | VCALENDAR `X-WR-CALNAME`                         |
| Liste: color     | VCALENDAR `X-ERINNERUNGEN-COLOR`                 |
| Liste: icon      | VCALENDAR `X-ERINNERUNGEN-ICON`                  |

Times with `Z` (UTC) are converted to local time when read. Unknown properties
from other clients are preserved in folder mode via raw-block replacement.

## 3. Recurrence (RRULE subset)

Allowed: `FREQ` in {DAILY, WEEKLY, MONTHLY, YEARLY}, `INTERVAL`, `BYDAY`
(MO..SU), `BYMONTHDAY` (incl. `-1` = last day of month), `UNTIL`, `COUNT`.
Preset mapping (Apple 1:1): daily → `FREQ=DAILY`; weekly →
`FREQ=WEEKLY;BYDAY=<weekday of the task>`; monthly → `FREQ=MONTHLY`;
last day of month → `FREQ=MONTHLY;BYMONTHDAY=-1`.

**Behavior when ticking off**: a recurring task stays open and advances to the
next occurrence after the previous `due` (`next_after(rrule, due, due)`, exclusive);
with no further occurrence (COUNT/UNTIL) → `COMPLETED`, `PERCENT-COMPLETE=100`.

## 4. CalDAV endpoints (client behavior)

1. `PROPFIND /` Depth 0 → `current-user-principal`
2. `PROPFIND <principal>` Depth 0 → `calendar-home-set`
3. `PROPFIND <home>` Depth 1 → Calendars (`resourcetype` enthält `caldav:calendar`)
4. Neue Liste: `MKCALENDAR <home>/<slug>/` mit `displayname`
5. Pull: `REPORT <cal>` `calendar-query` (VTODO-Filter), `getetag` + `calendar-data`
6. Push: `PUT <cal>/<uid>.ics` (`If-Match: "<etag>"` bzw. `If-None-Match: *` beim Anlegen)
7. Löschen: `DELETE <cal>/<uid>.ics` (`If-Match`)

Auth: HTTP Basic, over HTTPS only (http only for localhost with opt-in). TLS:
system CA + optional pin (`sha256/<base64>` SPKI or 64-hex SHA-256 of the DER
cert), checked after the handshake; mismatch → abort.

## 5. Sync rules (offline-first)

- Local DB is authoritative; changes are local immediately, `dirty=1`.
- Pull: remote newer (`LAST-MODIFIED` > local) and local not dirty → apply.
- Push: upload/delete all `dirty=1` (incl. tombstones), then `dirty=0`, store `etag`.
- Conflict: last-write-wins by `modified`; on ties the dirty side wins (local), else remote.
- Tasks deleted on the remote (no longer in the REPORT, local not dirty) → local tombstone.

## 6. Quick entry (German grammar)

`[Titel …] [Datum] [Uhrzeit] [!Liste | #Liste | »in <Listenname>«]`
Date: `heute`, `morgen`, `übermorgen`, weekday (next, incl. prefix
`nächsten/kommenden/am`), `in N Tagen/Wochen/Monaten`, `DD.MM.[YYYY]`.
Time: `HH:MM`, `HH.MM`, `HH Uhr`. List: sigil `!`/`#` or `in <name>`.
Reference: `desktop/erinnerungen/quickadd.py` + `desktop/tests/test_quickadd.py`.

## 7. Notifications

On due (`due <= now`, `status=NEEDS-ACTION`, `notified != due`) a local notification
with title + (recurrence, date/time); then `notified=due`. Interval: every 30 s
while the app runs + catch-up at start. Android: WorkManager + exact alarms;
Windows: toast notifications.

## 8. Smart lists

- **Today**: `due <= today 23:59`, not completed (incl. overdue)
- **Scheduled**: `due > today 23:59`, not completed
- **All**: all incomplete tasks across all lists
