package io.github.tuuuniSnowfield.erinnerungen.core

import java.time.LocalDate
import java.time.LocalTime
import java.time.YearMonth
import java.util.regex.Pattern

/**
 * German natural-language quick entry — port of desktop/erinnerungen/quickadd.py.
 * Examples: "Milch kaufen morgen 18 Uhr !Einkaufen", "Zahnarzt übermorgen 9:30",
 * "Bericht in 3 Tagen #Arbeit", "Miete am 01.06. in Haushalt".
 */
object QuickAdd {

    data class Parsed(
        val title: String,
        val day: LocalDate? = null,
        val clock: LocalTime? = null,
        val listName: String? = null,
    )

    private val WEEKDAYS = mapOf(
        "montag" to 0, "dienstag" to 1, "mittwoch" to 2, "donnerstag" to 3,
        "freitag" to 4, "samstag" to 5, "sonntag" to 6,
    )
    private val TIME_CLOCK = Pattern.compile("\\b([01]?\\d|2[0-3])[:.]([0-5]\\d)\\b")
    private val TIME_UHR = Pattern.compile("\\b([01]?\\d|2[0-3])\\s*uhr\\b", Pattern.CASE_INSENSITIVE)
    private val IN_DAYS = Pattern.compile("\\bin\\s+(\\d+)\\s+(tag|tage|tagen)\\b", Pattern.CASE_INSENSITIVE)
    private val IN_WEEKS = Pattern.compile("\\bin\\s+(\\d+)\\s+(woche|wochen)\\b", Pattern.CASE_INSENSITIVE)
    private val IN_MONTHS = Pattern.compile("\\bin\\s+(\\d+)\\s+(monat|monate|monaten)\\b", Pattern.CASE_INSENSITIVE)
    private val DATE_DE = Pattern.compile("\\b(\\d{1,2})\\.(\\d{1,2})\\.(?:(\\d{4}))?(?=$|\\b|\\s)")
    private val LIST_SIGIL = Pattern.compile("[!#](\\S+)")
    private val LIST_IN = Pattern.compile(
        "\\bin\\s+([^\\d!?\\s][^!#]*?)(?=\\s*$|\\s+(?:heute|morgen|übermorgen|uebermorgen|in\\s|\\d{1,2}[:.]\\d{2}|\\d{1,2}\\s*uhr)\\b)",
        Pattern.CASE_INSENSITIVE,
    )
    private val WEEKDAY = Pattern.compile(
        "\\b(nächsten|naechsten|kommenden|am\\s+)?(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\\b",
        Pattern.CASE_INSENSITIVE,
    )

    private fun addMonths(d: LocalDate, months: Int): LocalDate {
        val ym = YearMonth.from(d).plusMonths(months.toLong())
        return ym.atDay(d.dayOfMonth.coerceAtMost(ym.lengthOfMonth()))
    }

    fun parse(text: String, listNames: List<String> = emptyList(), today: LocalDate = LocalDate.now()): Parsed {
        var rest = text.trim()
        var listName: String? = null

        LIST_SIGIL.matcher(rest).let { m ->
            if (m.find()) {
                listName = resolve(m.group(1), listNames) ?: m.group(1)
                rest = (rest.substring(0, m.start()) + rest.substring(m.end())).trim()
            }
        }

        // date first so "01.06." is not misread as time "01.06"
        var day: LocalDate? = null
        val low = rest.lowercase()
        when {
            "heute" in low -> { day = today; rest = rest.replace(Regex("\\bheute\\b", RegexOption.IGNORE_CASE), "").trim() }
            Regex("\\b(übermorgen|uebermorgen)\\b").containsMatchIn(low) -> {
                day = today.plusDays(2)
                rest = rest.replace(Regex("\\b(übermorgen|uebermorgen)\\b", RegexOption.IGNORE_CASE), "").trim()
            }
            "morgen" in low -> { day = today.plusDays(1); rest = rest.replace(Regex("\\bmorgen\\b", RegexOption.IGNORE_CASE), "").trim() }
            else -> {
                var m = IN_DAYS.matcher(rest)
                if (m.find()) { day = today.plusDays(m.group(1).toLong()); rest = rest.removeRange(m.start(), m.end()) }
                else {
                    m = IN_WEEKS.matcher(rest)
                    if (m.find()) { day = today.plusWeeks(m.group(1).toLong()); rest = rest.removeRange(m.start(), m.end()) }
                    else {
                        m = IN_MONTHS.matcher(rest)
                        if (m.find()) { day = addMonths(today, m.group(1).toInt()); rest = rest.removeRange(m.start(), m.end()) }
                        else {
                            m = DATE_DE.matcher(rest)
                            if (m.find()) {
                                val d = m.group(1).toInt(); val mo = m.group(2).toInt()
                                val y = m.group(3)?.toInt() ?: if (mo to d >= today.monthValue to today.dayOfMonth) today.year else today.year + 1
                                try {
                                    day = LocalDate.of(y, mo, d)
                                    rest = rest.removeRange(m.start(), m.end())
                                    rest = rest.replace(Regex("\\bam\\s*$", RegexOption.IGNORE_CASE), "").trim()
                                } catch (_: Exception) { }
                            } else {
                                m = WEEKDAY.matcher(rest)
                                if (m.find()) {
                                    val target = WEEKDAYS[m.group(2).lowercase()]!!
                                    val ahead = (target - today.dayOfWeek.value + 7) % 7
                                    day = today.plusDays(if (ahead == 0) 7L else ahead.toLong())
                                    rest = rest.removeRange(m.start(), m.end())
                                }
                            }
                        }
                    }
                }
            }
        }

        var clock: LocalTime? = null
        TIME_CLOCK.matcher(rest).let { m ->
            if (m.find()) {
                clock = LocalTime.of(m.group(1).toInt() % 24, m.group(2).toInt())
                rest = (rest.substring(0, m.start()) + rest.substring(m.end())).trim()
            } else {
                TIME_UHR.matcher(rest).let { u ->
                    if (u.find()) {
                        clock = LocalTime.of(u.group(1).toInt() % 24, 0)
                        rest = (rest.substring(0, u.start()) + rest.substring(u.end())).trim()
                    }
                }
            }
        }

        if (listName == null && listNames.isNotEmpty()) {
            val m = LIST_IN.matcher(rest)
            if (m.find()) {
                val match = resolve(m.group(1).trim(), listNames)
                if (match != null) {
                    listName = match
                    rest = (rest.substring(0, m.start()) + rest.substring(m.end())).trim()
                }
            }
        }

        val title = rest.replace(Regex("\\s{2,}"), " ").trim().trim(',')
        return Parsed(title, day, clock, listName)
    }

    private fun resolve(ref: String, listNames: List<String>): String? {
        val r = ref.lowercase()
        return listNames.sortedByDescending { it.length }.firstOrNull {
            it.lowercase() == r || it.lowercase().startsWith(r)
        }
    }

    fun toDueString(day: LocalDate?, clock: LocalTime?): String? = when {
        day == null -> null
        clock != null -> "${day} ${clock.toString().take(5)}"
        else -> day.toString()
    }
}
