# Contributing

Thanks! This project should stay small, secure and maintainable.

- **Language**: English for code, identifiers, comments, docs and commits.
  User-facing UI strings stay German (the app is a German-locale Reminders
  clone), including the quick-add parser keywords.
- **Core before GUI**: All logic belongs in a core module without GTK imports
  (`db.py`, `ics.py`, `recurrence.py`, `caldav.py`, `folder.py`, `sync.py`,
  `quickadd.py`, `notify.py`) and gets pytest tests in `tests/`. The Android port
  mirrors these in `android/app/src/main/java/.../core` + `sync`.
- **Security**: No new network access, no plaintext secrets, never disable TLS
  verification (pinning is additive only). See `SECURITY.md`.
- **Style**: `ruff check desktop` must be clean; small, descriptive commits.
- **Platform parity**: Data-model changes must be documented in
  `spec/DATA-MODEL.md` (both platforms implement it).
- **License**: GPLv3 — by contributing you agree to license your contribution under GPLv3.
