"""CalDAV client against a loopback stub server – incl. TLS pinning tests with a
self-signed certificate (openssl). Everything local, no external network."""
import base64
import hashlib
import http.server
import ssl
import subprocess
import threading

import pytest

from erinnerungen import caldav, ics

USER = "testuser"
PASSWORD = "geheim123"


class StubState:
    def __init__(self):
        self.calendars: dict[str, dict[str, str]] = {}  # path → {href: ics}
        self.etags: dict[str, str] = {}
        self.home = "/dav/calendars/testuser/"

    def etag_for(self, href: str) -> str:
        n = self.etags.get(href, 0) + 1
        self.etags[href] = n
        return f'"{n}"'


STATE = StubState()


def auth_ok(handler) -> bool:
    header = handler.headers.get("Authorization", "")
    want = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    return header == want


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", ctype="application/xml; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_PROPFIND(self):
        if not auth_ok(self):
            return self._send(401, "auth required", "text/plain")
        depth = self.headers.get("Depth", "0")
        path = self.path
        if path == "/" or path == "/dav":
            body = (
                '<?xml version="1.0"?><multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<response><href>/dav/principals/testuser/</href><propstat><prop>"
                '<current-user-principal><href>/dav/principals/testuser/</href></current-user-principal>'
                "</prop></propstat></response></multistatus>"
            )
            return self._send(207, body)
        if path.startswith("/dav/principals/"):
            body = (
                '<?xml version="1.0"?><multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<response><href>/dav/principals/testuser/</href><propstat><prop>"
                f'<C:calendar-home-set><href>{STATE.home}</href></C:calendar-home-set>'
                "</prop></propstat></response></multistatus>"
            )
            return self._send(207, body)
        if path.rstrip("/") == STATE.home.rstrip("/"):
            responses = ""
            for cal_path in STATE.calendars:
                name = cal_path.rstrip("/").rsplit("/", 1)[-1]
                responses += (
                    f"<response><href>{cal_path}</href><propstat><prop>"
                    f"<displayname>{name}</displayname>"
                    '<resourcetype><collection/><C:calendar xmlns:C="urn:ietf:params:xml:ns:caldav"/></resourcetype>'
                    "</prop></propstat></response>"
                )
            body = (
                '<?xml version="1.0"?><multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                + responses + "</multistatus>"
            )
            return self._send(207, body)
        # getetag for a resource
        if depth == "0" and path.endswith(".ics"):
            cal = path.rsplit("/", 2)[0] + "/"
            href = path.rsplit("/", 1)[-1]
            etag = STATE.calendars.get(cal, {}).get(href)
            if etag is None:
                return self._send(404, "nf", "text/plain")
            body = (
                '<?xml version="1.0"?><multistatus xmlns="DAV:">'
                f"<response><href>{path}</href><propstat><prop><getetag>{etag}</getetag></prop></propstat></response>"
                "</multistatus>"
            )
            return self._send(207, body)
        self._send(404, "nf", "text/plain")

    def do_MKCALENDAR(self):
        if not auth_ok(self):
            return self._send(401, "auth required", "text/plain")
        STATE.calendars.setdefault(self.path, {})
        self._send(201, "")

    def do_REPORT(self):
        if not auth_ok(self):
            return self._send(401, "auth required", "text/plain")
        cal = self.path
        responses = ""
        for href, text in STATE.calendars.get(cal, {}).items():
            etag = None
            # etag aus STATE.etags invertieren
            for k, v in STATE.etags.items():
                if k.endswith(href):
                    etag = v
            responses += (
                f"<response><href>{cal.rstrip('/')}/{href}</href><propstat><prop>"
                f"<getetag>{etag or ''}</getetag>"
                '<C:calendar-data xmlns:C="urn:ietf:params:xml:ns:caldav">'
                + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</C:calendar-data>"
                "</prop></propstat></response>"
            )
        body = (
            '<?xml version="1.0"?><multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            + responses + "</multistatus>"
        )
        self._send(207, body)

    def do_PUT(self):
        if not auth_ok(self):
            return self._send(401, "auth required", "text/plain")
        body = self._body().decode()
        cal = self.path.rsplit("/", 1)[0] + "/"
        href = self.path.rsplit("/", 1)[-1]
        STATE.calendars.setdefault(cal, {})[href] = body
        etag = STATE.etag_for(self.path)
        self._send(201, "", extra={"ETag": etag})

    def do_DELETE(self):
        if not auth_ok(self):
            return self._send(401, "auth required", "text/plain")
        cal = self.path.rsplit("/", 1)[0] + "/"
        href = self.path.rsplit("/", 1)[-1]
        STATE.calendars.get(cal, {}).pop(href, None)
        self._send(204, "")


def make_server(use_tls=False, certfile=None, keyfile=None):
    STATE.calendars.clear()
    STATE.etags.clear()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if use_tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


@pytest.fixture
def server():
    httpd = make_server()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def tls_server(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "2",
         "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    httpd = make_server(use_tls=True, certfile=str(cert), keyfile=str(key))
    yield f"https://127.0.0.1:{httpd.server_address[1]}", str(cert), str(key)
    httpd.shutdown()


def client_for(url, **kw):
    return caldav.CalDAVClient(url, USER, PASSWORD, allow_http=True, **kw)


def test_http_rejected_unless_localhost_allowed():
    with pytest.raises(caldav.CalDAVError):
        caldav.CalDAVClient("http://example.com/dav", USER, PASSWORD)
    # localhost ohne allow_http auch nicht:
    with pytest.raises(caldav.CalDAVError):
        caldav.CalDAVClient("http://127.0.0.1:9999", USER, PASSWORD)


def test_discover_and_crud_over_http(server):
    c = client_for(server)
    home = c.discover_home()
    assert home == STATE.home
    c.mkcalendar(home + "liste/", "Liste")
    cals = c.list_calendars(home)
    assert any(c.path.endswith("liste/") for c in cals)

    v = ics.VTodo(uid="u1@x", summary="Test", due_date=__import__("datetime").date(2024, 5, 1))
    cal_text = caldav.ics_serialize_calendar(ics.serialize_vtodo(v))
    etag = c.put_todo(home + "liste/", "u1@x.ics", cal_text, None)
    assert etag
    items = c.query_todos(home + "liste/")
    assert len(items) == 1
    parsed = ics.parse_calendar(items[0].data or "")
    assert parsed and parsed[0].summary == "Test"
    c.delete_todo(home + "liste/", "u1@x.ics", etag)
    assert c.query_todos(home + "liste/") == []


def test_bad_auth_rejected(server):
    c = caldav.CalDAVClient(server, USER, "falsch", allow_http=True)
    with pytest.raises(caldav.HTTPError) as ei:
        c.discover_home()
    assert ei.value.status == 401


def test_tls_pin_spki_accepted(tls_server):
    url, cert, _ = tls_server
    spki_b64 = subprocess.run(
        f"openssl x509 -in {cert} -pubkey -noout | openssl pkey -pubin -outform DER"
        " | openssl dgst -sha256 -binary | base64",
        shell=True, capture_output=True, check=True,
    ).stdout.decode().strip()
    c = caldav.CalDAVClient(url, USER, PASSWORD, ca_file=cert, pin=f"sha256/{spki_b64}")
    assert c.discover_home() == STATE.home  # Pin OK + CA OK


def test_tls_pin_wrong_rejected(tls_server):
    url, cert, _ = tls_server
    wrong = base64.b64encode(hashlib.sha256(b"falsch").digest()).decode()
    c = caldav.CalDAVClient(url, USER, PASSWORD, ca_file=cert, pin=f"sha256/{wrong}")
    with pytest.raises(caldav.TLSMismatch):
        c.discover_home()


def test_tls_pin_cert_hex(tls_server):
    url, cert, _ = tls_server
    der = subprocess.run(
        f"openssl x509 -in {cert} -outform DER | openssl dgst -sha256",
        shell=True, capture_output=True, check=True,
    ).stdout.decode().split()[-1]
    c = caldav.CalDAVClient(url, USER, PASSWORD, ca_file=cert, pin=der)
    assert c.discover_home() == STATE.home


def test_tls_selfsigned_without_ca_rejected(tls_server):
    url, _, _ = tls_server
    c = caldav.CalDAVClient(url, USER, PASSWORD)
    with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
        c.discover_home()


def test_spki_extraction_matches_openssl(tmp_path):
    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    der = subprocess.run(
        f"openssl x509 -in {cert} -outform DER", shell=True, capture_output=True, check=True
    ).stdout
    expected = subprocess.run(
        f"openssl x509 -in {cert} -pubkey -noout | openssl pkey -pubin -outform DER"
        " | openssl dgst -sha256 -binary | base64",
        shell=True, capture_output=True, check=True,
    ).stdout.decode().strip()
    assert caldav.spki_sha256_b64(der) == expected
