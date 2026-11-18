# Security Policy

## Supported versions

Only the latest release series receives security fixes.

## Threat model

- **Network attacker**: Sync runs exclusively over HTTPS with certificate
  verification against the system CA (hostname + CERT_REQUIRED). `http://` is
  rejected except explicitly for `localhost`. Optionally a certificate pin can
  be set (SPKI SHA-256 in HPKP format `sha256/<base64>`, or SHA-256 of the DER
  certificate as 64 hex chars); the pin is checked after the TLS handshake and
  complements CA verification (never replaces it). Mismatch → connection dropped
  (`TLSMismatch`).
- **Malicious server**: Basic auth only over TLS. The server only ever sees VTODO
  data (title, notes, dates) — that is the price of sync; anyone who wants less
  uses the local folder mode or "local only".
- **Local attacker**: The password lives in the OS keyring (libsecret /
  EncryptedSharedPreferences), never in settings, DB, or plaintext files.
  Without a keyring: no storage, prompt at every start. The SQLite file lives in
  the user's private directory with default permissions.
- **Tampered sync data**: The ICS/RRULE parsers accept only a whitelisted RRULE
  subset; all DB queries are parameterized; ICS parsing is stdlib-only and tested
  against parser pitfalls (line folding, escaping).

## What we deliberately do NOT do

No telemetry, no crash reports with content, no cloud credentials, no third-party
auto-updates, no network access except the configured CalDAV server / local folder.

## Reporting

Please do **not** open a public issue with exploit details. Email the maintainer
(see GitHub profile) with affected version, reproduction and possible impact.
We acknowledge within 72 hours.
