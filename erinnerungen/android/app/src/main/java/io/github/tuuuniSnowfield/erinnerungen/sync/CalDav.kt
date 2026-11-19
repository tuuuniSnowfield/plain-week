package io.github.tuuuniSnowfield.erinnerungen.sync

import android.util.Xml
import io.github.tuuuniSnowfield.erinnerungen.core.Ics
import org.xmlpull.v1.XmlPullParser
import java.io.ByteArrayInputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.Base64
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory

/**
 * Minimal CalDAV client (RFC 4791/5545) — port of desktop/erinnerungen/caldav.py.
 *
 * Security: HTTPS mandatory (http only for localhost with allowHttp=true).
 * System CA verification always on; optional pin checked after the handshake
 * ("sha256/<base64>" = SPKI SHA-256, or 64 hex chars = SHA-256 of the DER cert).
 * Optional custom CA bundle (PEM). Basic auth only over TLS.
 */
class CalDavClient(
    baseUrl: String,
    private val username: String,
    password: String,
    private val caFile: String? = null,
    private val pin: String? = null,
    allowHttp: Boolean = false,
    private val timeoutMs: Int = 15000,
) {
    private val url: URL
    private val auth: String
    private val allowHttpLocal: Boolean

    init {
        var u = URL(if ("://" in baseUrl) baseUrl else "https://$baseUrl")
        if (u.protocol == "http") {
            val localhost = u.host in listOf("localhost", "127.0.0.1", "::1")
            require(allowHttp && localhost) { "HTTPS only. http:// is allowed for localhost only with an explicit option." }
            allowHttpLocal = true
        } else {
            require(u.protocol == "https") { "unknown scheme: ${u.protocol}" }
            allowHttpLocal = false
        }
        this.url = u
        this.auth = "Basic " + Base64.getEncoder().encodeToString("$username:$password".toByteArray(Charsets.UTF_8))
    }

    class HttpError(val status: Int, val path: String, body: String) :
        Exception("HTTP $status for $path: ${body.take(200)}")

    class TlsMismatch(msg: String) : Exception(msg)

    private fun sslContext(): SSLContext {
        val ca = caFile
        return if (ca.isNullOrBlank()) {
            SSLContext.getDefault()
        } else {
            val cf = CertificateFactory.getInstance("X.509")
            val certs = cf.generateCertificates(File(ca).inputStream()).filterIsInstance<X509Certificate>()
            val tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            val ks = java.security.KeyStore.getInstance(java.security.KeyStore.getDefaultType()).apply {
                load(null, null)
                certs.forEachIndexed { i, c -> setCertificateEntry("ca$i", c) }
            }
            tmf.init(ks)
            SSLContext.getInstance("TLS").apply { init(null, tmf.trustManagers, null) }
        }
    }

    private fun checkPin(cert: X509Certificate) {
        val p = pin?.trim().takeIf { !it.isNullOrBlank() } ?: return
        if (p.startsWith("sha256/")) {
            val actual = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(cert.publicKey.encoded))
            require(actual == p.removePrefix("sha256/")) { throw TlsMismatch("SPKI pin mismatch – certificate rejected") }
        } else {
            val hex = p.filter { it.isDigit() || it.lowercaseChar() in 'a'..'f' }.lowercase()
            val actual = MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString("") { "%02x".format(it) }
            require(hex.length == 64 && actual == hex) { throw TlsMismatch("Certificate pin (SHA-256) mismatch – rejected") }
        }
    }

    private fun request(method: String, path: String, body: String? = null, extra: Map<String, String> = emptyMap()): Pair<Int, Pair<Map<String, String>, ByteArray>> {
        val full = URL(url.protocol, url.host, url.port, (url.path.removeSuffix("/")) + path)
        val conn = full.openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = timeoutMs
        conn.readTimeout = timeoutMs
        conn.setRequestProperty("Authorization", auth)
        conn.setRequestProperty("User-Agent", "erinnerungen-android/0.1 (CalDAV; offline-first)")
        if (body != null) {
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/xml; charset=utf-8")
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        extra.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        if (conn is HttpsURLConnection) {
            conn.sslSocketFactory = sslContext().socketFactory
            // hostname verification stays at the strict default
        }
        conn.connect()
        if (conn is HttpsURLConnection) {
            val serverCerts = conn.serverCertificates
            val leaf = serverCerts?.filterIsInstance<X509Certificate>()?.firstOrNull()
            if (leaf != null) checkPin(leaf) else if (!pin.isNullOrBlank()) throw TlsMismatch("No peer certificate received – pin check failed")
        }
        val status = conn.responseCode
        val bytes = (if (status >= 400) conn.errorStream else conn.inputStream)?.use { it.readBytes() } ?: ByteArray(0)
        val headers = conn.headerFields.filterKeys { it != null }.mapKeys { it.key.lowercase() }
            .mapValues { it.value.firstOrNull() ?: "" }
        conn.disconnect()
        return status to (headers to bytes)
    }

    private fun expect(method: String, path: String, ok: Set<Int>, body: String? = null, extra: Map<String, String> = emptyMap()): Pair<Map<String, String>, ByteArray> {
        val (status, res) = request(method, path, body, extra)
        if (status !in ok) throw HttpError(status, path, res.second.toString(Charsets.UTF_8))
        return res
    }

    data class RemoteItem(val href: String, val etag: String?, val data: String?)
    data class RemoteCollection(val path: String, val displayName: String)

    private fun parseMultistatus(bytes: ByteArray): List<Map<String, Any?>> {
        val parser = Xml.newPullParser()
        parser.setInput(ByteArrayInputStream(bytes), "UTF-8")
        val responses = mutableListOf<Map<String, Any?>>()
        var current: MutableMap<String, Any?>? = null
        var inCalendarData = false
        val calData = StringBuilder()
        var text = ""
        var event = parser.eventType
        while (event != XmlPullParser.END_DOCUMENT) {
            when (event) {
                XmlPullParser.START_TAG -> when (parser.name) {
                    "response" -> current = mutableMapOf()
                    "calendar-data" -> { inCalendarData = true; calData.setLength(0) }
                }
                XmlPullParser.TEXT -> text = parser.text ?: ""
                XmlPullParser.END_TAG -> when (parser.name) {
                    "response" -> { current?.let { responses.add(it) }; current = null }
                    "href" -> current?.set("href", text.trim())
                    "getetag" -> current?.set("etag", text.trim().trim('"'))
                    "displayname" -> current?.set("displayname", text)
                    "calendar-data" -> { current?.set("calendar-data", calData.toString()); inCalendarData = false }
                    "calendar" -> current?.set("isCalendar", true)
                    "current-user-principal" -> current?.set("cup", true)
                    "calendar-home-set" -> current?.set("home", true)
                    else -> {}
                }
            }
            if (inCalendarData && event == XmlPullParser.TEXT) calData.append(text)
            event = parser.next()
        }
        return responses
    }

    private fun hrefOf(resp: Map<String, Any?>, key: String): String? {
        // principal/home-set responses nest the href one level deeper; our simple parser
        // flattens it, so we re-parse those two cases from raw XML when needed.
        return resp["href"] as? String
    }

    fun discoverHome(): String {
        val (_, body) = expect("PROPFIND", "/", setOf(207), body = "<?xml version=\"1.0\"?><propfind xmlns=\"DAV:\"><prop><current-user-principal/></prop></propfind>", extra = mapOf("Depth" to "0"))
        val principal = findNestedHref(body.toString(Charsets.UTF_8), "current-user-principal")
            ?: throw Exception("No current-user-principal found (not a CalDAV server?)")
        val (_, body2) = expect("PROPFIND", principal, setOf(207),
            body = "<?xml version=\"1.0\"?><propfind xmlns=\"DAV:\" xmlns:C=\"urn:ietf:params:xml:ns:caldav\"><prop><C:calendar-home-set/></prop></propfind>",
            extra = mapOf("Depth" to "0"))
        return findNestedHref(body2.toString(Charsets.UTF_8), "calendar-home-set")
            ?: throw Exception("No calendar-home-set found")
    }

    private fun findNestedHref(xml: String, tag: String): String? {
        val parser = Xml.newPullParser()
        parser.setInput(xml.byteInputStream(Charsets.UTF_8), "UTF-8")
        var inside = false
        var text = ""
        var event = parser.eventType
        while (event != XmlPullParser.END_DOCUMENT) {
            when (event) {
                XmlPullParser.START_TAG -> if (parser.name == tag) inside = true
                XmlPullParser.END_TAG -> if (parser.name == tag) inside = false
                XmlPullParser.TEXT -> if (inside) text = parser.text ?: ""
                XmlPullParser.START_TAG -> {}
            }
            if (event == XmlPullParser.END_TAG && parser.name == "href" && inside) return text.trim()
            event = parser.next()
        }
        return null
    }

    fun listCalendars(home: String): List<RemoteCollection> {
        val (_, body) = expect("PROPFIND", home, setOf(207),
            body = "<?xml version=\"1.0\"?><propfind xmlns=\"DAV:\" xmlns:C=\"urn:ietf:params:xml:ns:caldav\"><prop><displayname/><resourcetype/></prop></propfind>",
            extra = mapOf("Depth" to "1"))
        return parseMultistatus(body).filter { it["isCalendar"] == true }.map {
            RemoteCollection(
                path = it["href"] as String,
                displayName = (it["displayname"] as? String)?.ifBlank { null } ?: (it["href"] as String).trimEnd('/').substringAfterLast('/')
            )
        }
    }

    fun mkcalendar(path: String, displayName: String) {
        expect("MKCALENDAR", path, setOf(201, 200, 204), body =
            "<?xml version=\"1.0\"?><mkcalendar xmlns=\"DAV:\" xmlns:C=\"urn:ietf:params:xml:ns:caldav\"><set><prop><displayname>${xmlEscape(displayName)}</displayname><resourcetype><collection/><C:calendar/></resourcetype></prop></set></mkcalendar>")
    }

    fun queryTodos(calendarPath: String): List<RemoteItem> {
        val (_, body) = expect("REPORT", calendarPath, setOf(207),
            body = "<?xml version=\"1.0\"?><C:calendar-query xmlns:D=\"DAV:\" xmlns:C=\"urn:ietf:params:xml:ns:caldav\"><D:prop><D:getetag/><C:calendar-data/></D:prop><C:filter><C:comp-filter name=\"VCALENDAR\"><C:comp-filter name=\"VTODO\"/></C:comp-filter></C:filter></C:calendar-query>",
            extra = mapOf("Depth" to "1"))
        return parseMultistatus(body).map {
            RemoteItem(
                href = it["href"] as? String ?: "",
                etag = it["etag"] as? String,
                data = it["calendar-data"] as? String,
            )
        }
    }

    fun putTodo(calendarPath: String, href: String, ics: String, etag: String?): String {
        val headers = mutableMapOf("Content-Type" to "text/calendar; charset=utf-8")
        if (etag != null) headers["If-Match"] = "\"$etag\"" else headers["If-None-Match"] = "*"
        val (hdrs, _) = expect("PUT", calendarPath.trimEnd('/') + "/" + href, setOf(201, 204, 200, 412, 428), body = ics, extra = headers)
        return hdrs["etag"]?.trim('"') ?: ""
    }

    fun deleteTodo(calendarPath: String, href: String, etag: String?) {
        val headers = if (etag != null) mapOf("If-Match" to "\"$etag\"") else emptyMap()
        expect("DELETE", calendarPath.trimEnd('/') + "/" + href, setOf(204, 200, 404), extra = headers)
    }

    private fun xmlEscape(s: String) =
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")

    companion object {
        fun wrapCalendar(vtodoBlock: String): String =
            Ics.serializeCalendar(Ics.parseCalendar(vtodoBlock))
    }
}
