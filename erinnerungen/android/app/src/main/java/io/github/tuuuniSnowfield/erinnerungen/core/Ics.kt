package io.github.tuuuniSnowfield.erinnerungen.core

import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * Minimal ICS (RFC 5545) parser/serializer for VCALENDAR/VTODO — port of
 * desktop/erinnerungen/ics.py. Mapping per spec/DATA-MODEL.md.
 * Times are floating local; UTC (…Z) is converted to local on read.
 */
object Ics {

    const val PRODID = "-//erinnerungen//Erinnerungen//DE"
    const val LIST_NAME_PROP = "X-WR-CALNAME"
    const val LIST_COLOR_PROP = "X-ERINNERUNGEN-COLOR"
    const val LIST_ICON_PROP = "X-ERINNERUNGEN-ICON"

    data class VTodo(
        val uid: String,
        var summary: String = "",
        var description: String = "",
        var dueDate: LocalDate? = null,
        var dueTime: LocalTime? = null,
        var rrule: String? = null,
        var status: String = "NEEDS-ACTION",
        var percent: Int = 0,
        var relatedParents: MutableList<String> = mutableListOf(),
        var sequence: Int = 0,
        var created: LocalDateTime? = null,
        var modified: LocalDateTime? = null,
    ) {
        val due: String?
            get() = dueDate?.let { d -> if (dueTime != null) "$d ${dueTime.toString().take(5)}" else d.toString() }
    }

    fun unfold(text: String): List<String> {
        val out = mutableListOf<String>()
        for (raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")) {
            if (raw.startsWith(" ") || raw.startsWith("\t")) {
                if (out.isNotEmpty()) out[out.size - 1] += raw.substring(1)
                else out.add(raw)
            } else out.add(raw)
        }
        return out.filter { it.isNotEmpty() }
    }

    fun escapeText(v: String): String =
        v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    fun unescapeText(v: String): String {
        val out = StringBuilder()
        var i = 0
        while (i < v.length) {
            if (v[i] == '\\' && i + 1 < v.length) {
                out.append(if (v[i + 1] == 'n' || v[i + 1] == 'N') '\n' else v[i + 1])
                i += 2
            } else {
                out.append(v[i]); i++
            }
        }
        return out.toString()
    }

    data class Prop(val name: String, val params: Map<String, String>, val value: String)

    fun splitProp(line: String): Prop {
        var inQuotes = false
        var sep = -1
        for (i in line.indices) {
            when (line[i]) {
                '"' -> inQuotes = !inQuotes
                ':' -> if (!inQuotes) { sep = i; break }
            }
        }
        if (sep < 0) return Prop(line.trim().uppercase(), emptyMap(), "")
        val head = line.substring(0, sep)
        val value = line.substring(sep + 1)
        val pieces = mutableListOf<String>()
        val buf = StringBuilder()
        inQuotes = false
        for (c in head) {
            if (c == '"') { inQuotes = !inQuotes; buf.append(c) }
            else if (c == ';' && !inQuotes) { pieces.add(buf.toString()); buf.setLength(0) }
            else buf.append(c)
        }
        pieces.add(buf.toString())
        val name = pieces[0].trim().uppercase()
        val params = pieces.drop(1).associate {
            val (k, v) = it.split("=", limit = 2)
            k.trim().uppercase() to v.trim().trim('"')
        }
        return Prop(name, params, value)
    }

    private val BASIC = DateTimeFormatter.BASIC_ISO_DATE
    private val BASIC_DT = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss")

    fun parseIcsDt(value: String): Pair<LocalDate, LocalTime?> {
        var v = value.trim()
        val utc = v.endsWith("Z")
        v = v.removeSuffix("Z")
        return if ("T" in v) {
            var dt = LocalDateTime.parse(v, BASIC_DT)
            if (utc) dt = dt.atOffset(ZoneOffset.UTC).atZoneSameInstant(java.time.ZoneId.systemDefault()).toLocalDateTime()
            dt.toLocalDate() to dt.toLocalTime().withSecond(0).withNano(0)
        } else {
            LocalDate.parse(v, BASIC) to null
        }
    }

    fun formatDate(d: LocalDate): String = d.format(BASIC)
    fun formatDtLocal(d: LocalDate, t: LocalTime): String = d.format(BASIC) + "T" + t.format(DateTimeFormatter.ofPattern("HHmmss"))

    private fun blocks(lines: List<String>, name: String): List<List<String>> {
        val out = mutableListOf<List<String>>()
        var cur: MutableList<String>? = null
        for (line in lines) {
            val u = line.uppercase()
            if (u == "BEGIN:$name") cur = mutableListOf(line)
            else if (u == "END:$name" && cur != null) { cur.add(line); out.add(cur); cur = null }
            else cur?.add(line)
        }
        return out
    }

    fun parseVtodo(block: List<String>): VTodo {
        val v = VTodo(uid = "")
        for (line in block) {
            val (name, params, value) = splitProp(line)
            when (name) {
                "UID" -> v.uid = value.trim()
                "SUMMARY" -> v.summary = unescapeText(value)
                "DESCRIPTION" -> v.description = unescapeText(value)
                "DUE" -> { val (d, t) = parseIcsDt(value); v.dueDate = d; v.dueTime = t }
                "RRULE" -> v.rrule = value.trim().uppercase()
                "STATUS" -> v.status = value.trim().uppercase()
                "PERCENT-COMPLETE" -> v.percent = value.toIntOrNull()?.coerceIn(0, 100) ?: 0
                "RELATED-TO" -> if ((params["RELTYPE"] ?: "PARENT").uppercase() == "PARENT") v.relatedParents.add(value.trim())
                "SEQUENCE" -> v.sequence = value.toIntOrNull() ?: 0
                "CREATED" -> { val (d, t) = parseIcsDt(value); v.created = LocalDateTime.of(d, t ?: LocalTime.MIN) }
                "LAST-MODIFIED" -> { val (d, t) = parseIcsDt(value); v.modified = LocalDateTime.of(d, t ?: LocalTime.MIN) }
            }
        }
        return v
    }

    fun parseCalendar(text: String): List<VTodo> = blocks(unfold(text), "VTODO").map { parseVtodo(it) }

    fun parseCalendarProps(text: String): Map<String, String> {
        val props = mutableMapOf<String, String>()
        var inside = false
        for (line in unfold(text)) {
            val u = line.uppercase()
            if (u == "BEGIN:VCALENDAR") { inside = true; continue }
            if (u == "END:VCALENDAR") break
            if (inside) {
                val (name, _, value) = splitProp(line)
                if (name in setOf(LIST_NAME_PROP, LIST_COLOR_PROP, LIST_ICON_PROP, "VERSION", "PRODID")) props[name] = value
            }
        }
        return props
    }

    fun serializeVtodo(v: VTodo): String {
        val lines = mutableListOf("BEGIN:VTODO", "UID:${v.uid}")
        v.created?.let { lines.add("CREATED:" + it.format(BASIC_DT) + "Z") }
        v.modified?.let { lines.add("LAST-MODIFIED:" + it.format(BASIC_DT) + "Z") }
        lines.add("SEQUENCE:${v.sequence}")
        lines.add("SUMMARY:${escapeText(v.summary)}")
        if (v.description.isNotEmpty()) lines.add("DESCRIPTION:${escapeText(v.description)}")
        v.dueDate?.let { d ->
            if (v.dueTime != null) lines.add("DUE:${formatDtLocal(d, v.dueTime!!)}")
            else lines.add("DUE;VALUE=DATE:${formatDate(d)}")
        }
        v.rrule?.let { lines.add("RRULE:$it") }
        lines.add("STATUS:${v.status}")
        lines.add("PERCENT-COMPLETE:${v.percent}")
        v.relatedParents.forEach { lines.add("RELATED-TO;RELTYPE=PARENT:$it") }
        lines.add("END:VTODO")
        return lines.joinToString("\r\n") + "\r\n"
    }

    fun serializeCalendar(vtodos: List<VTodo>, name: String? = null, color: String? = null, icon: String? = null): String {
        val lines = mutableListOf("BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:$PRODID")
        name?.let { lines.add("$LIST_NAME_PROP:${escapeText(it)}") }
        color?.let { lines.add("$LIST_COLOR_PROP:$it") }
        icon?.let { lines.add("$LIST_ICON_PROP:${escapeText(it)}") }
        val out = lines + vtodos.flatMap { unfold(serializeVtodo(it)) } + "END:VCALENDAR"
        return out.joinToString("\r\n") + "\r\n"
    }

    /** All VTODO raw blocks as (uid, raw block text). */
    fun vtodoBlocks(text: String): List<Pair<String, String>> =
        blocks(unfold(text), "VTODO").map { b ->
            val uid = b.firstOrNull { splitProp(it).name == "UID" }?.let { splitProp(it).value.trim() } ?: ""
            uid to b.joinToString("\r\n") + "\r\n"
        }

    fun replaceVtodoBlock(text: String, uid: String, newBlock: String): String {
        val blocks = vtodoBlocks(text)
        val bodies = blocks.map { (buid, b) -> if (buid == uid) newBlock.trimEnd('\r', '\n') else b.trimEnd('\r', '\n') }
            .toMutableList()
        if (blocks.none { it.first == uid }) bodies.add(newBlock.trimEnd('\r', '\n'))
        return assembleCalendar(stripBlocks(text, blocks), bodies)
    }

    fun removeVtodoBlock(text: String, uid: String): String {
        val blocks = vtodoBlocks(text)
        val bodies = blocks.filter { it.first != uid }.map { it.second.trimEnd('\r', '\n') }
        return assembleCalendar(stripBlocks(text, blocks), bodies)
    }

    private fun stripBlocks(text: String, blocks: List<Pair<String, String>>): String {
        var head = text
        for ((_, b) in blocks) head = head.replace(b, "", ignoreCase = false)
        return head
    }

    private fun assembleCalendar(head: String, bodies: List<String>): String {
        val out = unfold(head)
        val insertAt = out.indexOfFirst { it.uppercase() == "END:VCALENDAR" }.let { if (it < 0) out.size else it }
        val result = out.toMutableList()
        for (b in bodies) {
            val lines = unfold(b)
            result.addAll(insertAt, lines)
        }
        return result.joinToString("\r\n") + "\r\n"
    }
}
