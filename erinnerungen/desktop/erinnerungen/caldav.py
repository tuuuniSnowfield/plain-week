"""Minimal CalDAV client (RFC 4791 / RFC 5545) – Python stdlib only.

Security:
- HTTPS is mandatory. http:// is only accepted for localhost/127.0.0.1 and only
  when allow_http=True is set explicitly.
- Certificate verification against the system CA is always on (check_hostname + CERT_REQUIRED).
- Optional pin for self-signed home servers:
    "sha256/<base64>"  → SHA-256 des SubjectPublicKeyInfo (DER), HPKP-Stil
                         (openssl x509 -in cert.pem -pubkey -noout | openssl pkey -pubin
                          -outform DER | openssl dgst -sha256 -binary | base64)
    oder 64 Hex-Zeichen → SHA-256 des gesamten DER-Zertifikats
  The pin is checked after the TLS handshake and combined with standard TLS
  verification (never replaces it). On mismatch the connection is dropped.
- Optional custom CA bundle (ca_file) for internal CAs.
- Credentials: HTTP Basic over TLS only; the password lives in the Secret
  Service (see secrets.py) and is never persisted in plaintext.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import re
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"


class CalDAVError(Exception):
    pass


class TLSMismatch(CalDAVError):
    pass


class HTTPError(CalDAVError):
    def __init__(self, status: int, reason: str, path: str):
        super().__init__(f"HTTP {status} {reason} for {path}")
        self.status = status
        self.reason = reason
        self.path = path


# --- minimal ASN.1 reader for SPKI pins --------------------------------------


def _read_tlv(data: bytes, off: int) -> tuple[int, bytes, int]:
    if off >= len(data):
        raise CalDAVError("Truncated DER")
    tag = data[off]
    off += 1
    length = data[off]
    off += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[off : off + n], "big")
        off += n
    return tag, data[off : off + length], off + length


def _encode_tlv(tag: int, value: bytes) -> bytes:
    length = len(value)
    if length < 0x80:
        len_bytes = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
        len_bytes = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + len_bytes + value


def spki_sha256_b64(der_cert: bytes) -> str:
    """Base64(SHA-256(DER-SubjectPublicKeyInfo)) des Zertifikats."""
    _, cert, _ = _read_tlv(der_cert, 0)
    _, tbs, _ = _read_tlv(cert, 0)
    children: list[tuple[int, bytes]] = []
    off = 0
    while off < len(tbs):
        tag, value, off = _read_tlv(tbs, off)
        children.append((tag, value))
    idx = 6 if children and children[0][0] == 0xA0 else 5
    if len(children) <= idx:
        raise CalDAVError("SPKI not found in certificate")
    tag, value = children[idx]
    return base64.b64encode(hashlib.sha256(_encode_tlv(tag, value)).digest()).decode("ascii")


def check_pin(pin: str, der_cert: bytes) -> None:
    pin = pin.strip()
    if pin.startswith("sha256/"):
        expect = pin.split("/", 1)[1].strip()
        actual = spki_sha256_b64(der_cert)
        if not _const_eq(actual, expect):
            raise TLSMismatch("SPKI pin mismatch – certificate rejected")
    else:
        hex_pin = re.sub(r"[^0-9a-fA-F]", "", pin).lower()
        actual = hashlib.sha256(der_cert).hexdigest()
        if len(hex_pin) != 64 or not _const_eq(actual, hex_pin):
            raise TLSMismatch("Certificate pin (SHA-256) mismatch – rejected")


def _const_eq(a: str, b: str) -> bool:
    return hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()


# --- Client ---------------------------------------------------------------


@dataclass
class RemoteItem:
    href: str
    etag: str | None
    data: str | None


@dataclass
class RemoteCollection:
    path: str
    displayname: str


class CalDAVClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        ca_file: str | None = None,
        pin: str | None = None,
        allow_http: bool = False,
        timeout: float = 15.0,
    ):
        u = urlsplit(base_url if "://" in base_url else "https://" + base_url)
        if u.scheme == "https":
            if not u.hostname:
                raise CalDAVError("Invalid server URL")
        elif u.scheme == "http":
            if not allow_http or u.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise CalDAVError(
                    "HTTPS only. http:// is allowed for localhost only with an explicit option."
                )
        else:
            raise CalDAVError(f"Unknown URL scheme: {u.scheme!r}")
        self.scheme = u.scheme
        self.host = u.hostname or ""
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base_path = u.path.rstrip("/")
        self.timeout = timeout
        self.ca_file = ca_file or None
        self.pin = pin.strip() if pin else None
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._auth = "Basic " + token

    # --- Transport --------------------------------------------------------

    def _connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            ctx = ssl.create_default_context(cafile=self.ca_file)
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
            conn.connect()
            der = conn.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
            if self.pin and der:
                check_pin(self.pin, der)
            elif self.pin and not der:
                conn.close()
                raise TLSMismatch("No peer certificate received – pin check failed")
            return conn
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        conn.connect()
        return conn

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        full_path = self.base_path + path if not path.startswith("http") else path
        headers = {
            "Authorization": self._auth,
            "User-Agent": "erinnerungen/0.1 (CalDAV; offline-first)",
            "Host": self.host if self.port in (80, 443) else f"{self.host}:{self.port}",
        }
        if body is not None:
            if isinstance(body, str):
                body = body.encode("utf-8")
            headers["Content-Length"] = str(len(body))
        if extra_headers:
            headers.update(extra_headers)
        conn = self._connect()
        try:
            conn.request(method, full_path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def _expect(self, method: str, path: str, ok: tuple[int, ...], **kw) -> tuple[dict[str, str], bytes]:
        status, headers, data = self.request(method, path, **kw)
        if status not in ok:
            raise HTTPError(status, data[:200].decode("utf-8", "replace"), path)
        return headers, data

    # --- Discovery --------------------------------------------------------

    def _href_of(self, elem: ET.Element, tag: str) -> str | None:
        for child in elem.iter():
            if child.tag == f"{{{DAV}}}{tag}" or child.tag == f"{{{CAL}}}{tag}":
                for h in child.iter(f"{{{DAV}}}href"):
                    return (h.text or "").strip()
        return None

    def discover_home(self) -> str:
        """current-user-principal → calendar-home-set."""
        _, data = self._expect(
            "PROPFIND", "/", (207,),
            body=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<propfind xmlns="DAV:"><prop><current-user-principal/></prop></propfind>'
            ),
            extra_headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
        )
        root = ET.fromstring(data)
        principal = None
        for resp in root.iter(f"{{{DAV}}}response"):
            principal = self._href_of(resp, "current-user-principal")
        if not principal:
            raise CalDAVError("No current-user-principal found (not a CalDAV server?)")
        _, data = self._expect(
            "PROPFIND", principal, (207,),
            body=(
                '<?xml version="1.0" encoding="utf-8"?>'
                f'<propfind xmlns="DAV:" xmlns:C="{CAL}">'
                "<prop><C:calendar-home-set/></prop></propfind>"
            ),
            extra_headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
        )
        root = ET.fromstring(data)
        home = None
        for resp in root.iter(f"{{{DAV}}}response"):
            home = self._href_of(resp, "calendar-home-set")
        if not home:
            raise CalDAVError("No calendar-home-set found")
        return home

    def list_calendars(self, home: str) -> list[RemoteCollection]:
        _, data = self._expect(
            "PROPFIND", home, (207,),
            body=(
                '<?xml version="1.0" encoding="utf-8"?>'
                f'<propfind xmlns="DAV:" xmlns:C="{CAL}">'
                "<prop><displayname/><resourcetype/></prop></propfind>"
            ),
            extra_headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        )
        root = ET.fromstring(data)
        out = []
        for resp in root.iter(f"{{{DAV}}}response"):
            href_el = next(resp.iter(f"{{{DAV}}}href"), None)
            if href_el is None or not (href_el.text or "").strip():
                continue
            href = href_el.text.strip()
            is_cal = any(el.tag == f"{{{CAL}}}calendar" for el in resp.iter())
            if not is_cal:
                continue
            name = ""
            for el in resp.iter(f"{{{DAV}}}displayname"):
                name = el.text or ""
                break
            out.append(RemoteCollection(path=href, displayname=name or href.rstrip("/").rsplit("/", 1)[-1]))
        return out

    def mkcalendar(self, path: str, displayname: str) -> None:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<mkcalendar xmlns="DAV:" xmlns:C="{CAL}">'
            f"<set><prop><displayname>{escape(displayname)}</displayname>"
            "<C:calendar-color></C:calendar-color>"
            "<resourcetype><collection/><C:calendar/></resourcetype></prop></set>"
            "</mkcalendar>"
        )
        self._expect(
            "MKCALENDAR", path, (201, 200, 204),
            body=body,
            extra_headers={"Content-Type": "application/xml; charset=utf-8"},
        )

    # --- VTODO CRUD -------------------------------------------------------

    def query_todos(self, calendar_path: str) -> list[RemoteItem]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<C:calendar-query xmlns:D="DAV:" xmlns:C="{CAL}">'
            "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
            '<C:filter><C:comp-filter name="VCALENDAR">'
            '<C:comp-filter name="VTODO"/></C:comp-filter></C:filter>'
            "</C:calendar-query>"
        )
        _, data = self._expect(
            "REPORT", calendar_path, (207,),
            body=body,
            extra_headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        )
        root = ET.fromstring(data)
        items = []
        for resp in root.iter(f"{{{DAV}}}response"):
            href_el = next(resp.iter(f"{{{DAV}}}href"), None)
            if href_el is None:
                continue
            href = (href_el.text or "").strip()
            etag = None
            cal_data = None
            for prop in resp.iter(f"{{{DAV}}}prop"):
                for el in prop:
                    if el.tag == f"{{{DAV}}}getetag":
                        etag = (el.text or "").strip().strip('"')
                    elif el.tag == f"{{{CAL}}}calendar-data":
                        # itertext() returns the raw (unescaped) iCalendar payload,
                        # which is what real servers send inside calendar-data
                        cal_data = "".join(el.itertext())
            items.append(RemoteItem(href=href, etag=etag, data=cal_data))
        return items

    def put_todo(self, calendar_path: str, href: str, ics: str, etag: str | None) -> str:
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = f'"{etag}"'
        else:
            headers["If-None-Match"] = "*"
        hdrs, _ = self._expect(
            "PUT", calendar_path.rstrip("/") + "/" + quote(href), (201, 204, 200, 412, 428),
            body=ics, extra_headers=headers,
        )
        if "etag" in hdrs:
            return hdrs["etag"].strip('"')
        _, body = self._expect(
            "PROPFIND", calendar_path.rstrip("/") + "/" + quote(href), (207,),
            body='<?xml version="1.0"?><propfind xmlns="DAV:"><prop><getetag/></prop></propfind>',
            extra_headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        root = ET.fromstring(body)
        for el in root.iter(f"{{{DAV}}}getetag"):
            return (el.text or "").strip('"')
        return ""

    def delete_todo(self, calendar_path: str, href: str, etag: str | None) -> None:
        headers = {"If-Match": f'"{etag}"'} if etag else {}
        self._expect(
            "DELETE", calendar_path.rstrip("/") + "/" + quote(href), (204, 200, 404),
            extra_headers=headers,
        )


class CalDAVBackend:
    """Adapter mapping CalDAVClient onto the sync interface (see folder.py)."""

    def __init__(self, client: CalDAVClient):
        self.client = client
        self._home: str | None = None

    def _home_path(self) -> str:
        if self._home is None:
            self._home = self.client.discover_home()
        return self._home

    @staticmethod
    def _slug(name: str) -> str:
        import re as _re

        slug = _re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-") or "liste"
        return slug + "/"

    def discover_lists(self) -> list[tuple[str, str]]:
        return [(c.path, c.displayname) for c in self.client.list_calendars(self._home_path())]

    def ensure_list(self, path: str | None, name: str, color: str | None = None, icon: str | None = None) -> str:
        if path:
            return path
        home = self._home_path()
        new_path = home.rstrip("/") + "/" + self._slug(name)
        try:
            self.client.mkcalendar(new_path, name)
        except HTTPError as exc:
            if exc.status not in (405, 301):  # already exists
                raise
        return new_path

    def fetch_tasks(self, calendar_path: str) -> list[RemoteItem]:
        return self.client.query_todos(calendar_path)

    def upload(self, calendar_path: str, uid: str, vtodo_block: str, etag: str | None) -> str:
        cal = ics_serialize_calendar(vtodo_block)
        return self.client.put_todo(calendar_path, uid + ".ics", cal, etag)

    def remove(self, calendar_path: str, uid: str, etag: str | None) -> None:
        self.client.delete_todo(calendar_path, uid + ".ics", etag)


def ics_serialize_calendar(vtodo_block: str) -> str:
    from . import ics as _ics

    return _ics._assemble_calendar(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:" + _ics.PRODID + "\r\nEND:VCALENDAR\r\n",
        [vtodo_block],
    )
