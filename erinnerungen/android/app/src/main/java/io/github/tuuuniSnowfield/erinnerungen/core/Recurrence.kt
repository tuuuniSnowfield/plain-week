package io.github.tuuuniSnowfield.erinnerungen.core

import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters

/**
 * RRULE subset per spec/DATA-MODEL.md (1:1 Apple Reminders):
 * FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, BYDAY, BYMONTHDAY (incl. -1), UNTIL, COUNT.
 * Reference implementation: desktop/erinnerungen/recurrence.py (pytest-covered).
 */
object Recurrence {

    private val ALLOWED = setOf("FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "UNTIL", "COUNT")
    private val DOW = mapOf(
        "MO" to DayOfWeek.MONDAY, "TU" to DayOfWeek.TUESDAY, "WE" to DayOfWeek.WEDNESDAY,
        "TH" to DayOfWeek.THURSDAY, "FR" to DayOfWeek.FRIDAY, "SA" to DayOfWeek.SATURDAY,
        "SU" to DayOfWeek.SUNDAY,
    )
    private val DOW_CODE = DOW.entries.associate { (k, v) -> v to k }
    private val DOW_NAME_DE = mapOf(
        DayOfWeek.MONDAY to "Mo", DayOfWeek.TUESDAY to "Di", DayOfWeek.WEDNESDAY to "Mi",
        DayOfWeek.THURSDAY to "Do", DayOfWeek.FRIDAY to "Fr", DayOfWeek.SATURDAY to "Sa",
        DayOfWeek.SUNDAY to "So",
    )

    data class Rule(
        val freq: String,
        val interval: Int = 1,
        val byday: Set<DayOfWeek> = emptySet(),
        val bymonthday: Set<Int> = emptySet(),
        val until: LocalDateTime? = null,
        val count: Int? = null,
    )

    fun parse(value: String): Rule {
        val parts = value.uppercase().split(";").filter { it.isNotBlank() }
            .associate { val (k, v) = it.split("=", limit = 2); k to v }
        require(parts.keys.all { it in ALLOWED }) { "unsupported RRULE field" }
        val freq = parts["FREQ"] ?: error("FREQ missing")
        require(freq in setOf("DAILY", "WEEKLY", "MONTHLY", "YEARLY")) { "FREQ not allowed" }
        return Rule(
            freq = freq,
            interval = parts["INTERVAL"]?.toIntOrNull() ?: 1,
            byday = parts["BYDAY"]?.split(",")?.mapNotNull { DOW[it] }?.toSet() ?: emptySet(),
            bymonthday = parts["BYMONTHDAY"]?.split(",")?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet(),
            until = parts["UNTIL"]?.let { parseUntil(it) },
            count = parts["COUNT"]?.toIntOrNull(),
        )
    }

    private val BASIC = DateTimeFormatter.BASIC_ISO_DATE
    private val BASIC_TIME = DateTimeFormatter.ofPattern("HHmmss")

    private fun parseUntil(u: String): LocalDateTime {
        val v = u.removeSuffix("Z")
        return if ("T" in v) {
            LocalDate.parse(v.take(8), BASIC).atTime(LocalTime.parse(v.drop(9), BASIC_TIME))
        } else {
            LocalDate.parse(v, BASIC).atTime(LocalTime.MAX) // date-only UNTIL = end of that day
        }
    }

    fun build(
        freq: String, interval: Int = 1, byday: Set<DayOfWeek> = emptySet(),
        bymonthday: Set<Int> = emptySet(), until: String? = null, count: Int? = null,
    ): String {
        val p = mutableListOf("FREQ=$freq")
        if (interval > 1) p += "INTERVAL=$interval"
        if (byday.isNotEmpty()) p += "BYDAY=" + byday.sorted().joinToString(",") { DOW_CODE[it]!! }
        if (bymonthday.isNotEmpty()) p += "BYMONTHDAY=" + bymonthday.sorted().joinToString(",")
        if (until != null) p += "UNTIL=$until"
        if (count != null) p += "COUNT=$count"
        return p.joinToString(";")
    }

    /** Apple presets; anchor = due date/time of the task. */
    fun preset(key: String, anchor: LocalDateTime): String? = when (key) {
        "none" -> null
        "daily" -> build("DAILY")
        "weekly" -> build("WEEKLY", byday = setOf(anchor.dayOfWeek))
        "monthly" -> build("MONTHLY")
        "last_day_of_month" -> build("MONTHLY", bymonthday = setOf(-1))
        "yearly" -> build("YEARLY")
        else -> error("unknown preset: $key")
    }

    /** All occurrences from dtstart, in order (lazy, capped). */
    private fun occurrences(rule: Rule, dtstart: LocalDateTime): Sequence<LocalDateTime> {
        val time = dtstart.toLocalTime()
        return when (rule.freq) {
            "DAILY" -> generateSequence(0L) { it + 1 }
                .map { dtstart.toLocalDate().plusDays(it * rule.interval).atTime(time) }
            "YEARLY" -> generateSequence(0L) { it + 1 }
                .map { i ->
                    val y = dtstart.year + (i * rule.interval).toInt()
                    val d = dtstart.dayOfMonth.coerceAtMost(YearMonth.of(y, dtstart.monthValue).lengthOfMonth())
                    LocalDate.of(y, dtstart.monthValue, d).atTime(time)
                }
            "WEEKLY" -> {
                val days = if (rule.byday.isNotEmpty()) rule.byday.sorted() else listOf(dtstart.dayOfWeek)
                val monday = dtstart.toLocalDate().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                generateSequence(0L) { it + 1 }.flatMap { w ->
                    days.map { d -> monday.plusWeeks(w * rule.interval).plusDays(d.value - 1L).atTime(time) }
                }
            }
            "MONTHLY" -> {
                val startYm = YearMonth.from(dtstart)
                generateSequence(0L) { it + 1 }.flatMap { m ->
                    val ym = startYm.plusMonths(m * rule.interval)
                    val days = if (rule.bymonthday.isNotEmpty()) {
                        rule.bymonthday.map { v -> if (v < 0) ym.lengthOfMonth() + 1 + v else v.coerceAtMost(ym.lengthOfMonth()) }
                            .sorted()
                    } else listOf(dtstart.dayOfMonth.coerceAtMost(ym.lengthOfMonth()))
                    days.map { ym.atDay(it).atTime(time) }
                }
            }
            else -> emptySequence()
        }.take(5000)
    }

    /** Next occurrence strictly after [after]; null when COUNT/UNTIL is exhausted. */
    fun nextAfter(rrule: String, dtstart: LocalDateTime, after: LocalDateTime): LocalDateTime? {
        val rule = parse(rrule)
        var seq = occurrences(rule, dtstart)
        if (rule.until != null) seq = seq.takeWhile { it <= rule.until }
        if (rule.count != null) seq = seq.take(rule.count)
        return seq.firstOrNull { it > after }
    }

    /** German UI label, e.g. "Täglich", "Wöchentlich (Mo)", "Monatlich – letzter Tag im Monat". */
    fun describe(rrule: String): String {
        val r = parse(rrule)
        return when (r.freq) {
            "DAILY" -> if (r.interval == 1) "Täglich" else "Alle ${r.interval} Tage"
            "WEEKLY" -> {
                val names = r.byday.sorted().joinToString(", ") { DOW_NAME_DE[it] ?: "" }
                if (r.interval == 1) "Wöchentlich ($names)" else "Alle ${r.interval} Wochen ($names)"
            }
            "MONTHLY" -> when {
                r.bymonthday == setOf(-1) -> "Monatlich – letzter Tag im Monat"
                r.interval == 1 -> "Monatlich"
                else -> "Alle ${r.interval} Monate"
            }
            "YEARLY" -> if (r.interval == 1) "Jährlich" else "Alle ${r.interval} Jahre"
            else -> rrule
        }
    }
}
