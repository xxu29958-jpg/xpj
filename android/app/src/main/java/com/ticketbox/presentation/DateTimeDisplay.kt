package com.ticketbox.presentation

import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.UiText
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

// One spelling for a date, and for a date with a clock time, wherever the app shows one.
private const val DATE_PATTERN = "yyyy年M月d日"
private const val DATE_TIME_PATTERN = "$DATE_PATTERN HH:mm"

fun displayTime(value: String?): String {
    if (value.isNullOrBlank()) return "未填写时间"
    val localZone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter.ofPattern(DATE_TIME_PATTERN).withZone(localZone)
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrElse { value.replace("T", " ").removeSuffix("Z") }
}

fun displayDate(value: String?): String {
    if (value.isNullOrBlank()) return "未设置"
    val localZone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter.ofPattern(DATE_PATTERN).withZone(localZone)
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrElse { value.take(10) }
}

/** A frozen calendar day, spelled like other dates and never moved by the device zone. */
fun displayCalendarDay(day: String): String =
    runCatching { LocalDate.parse(day).format(DateTimeFormatter.ofPattern(DATE_PATTERN)) }.getOrDefault(day)

/** Frozen input/ledger days stay independent of the current device time zone and read like other dates. */
fun accountingTimeDateText(evidence: ExpenseAccountingTime?, legacyInstant: String?): UiText {
    if (evidence == null) return UiText.raw(displayDate(legacyInstant))
    val day = evidence.userLocalDate ?: evidence.accountingDate
        ?: return UiText.res(R.string.accounting_time_date_unknown)
    val label = displayCalendarDay(day)
    val accountingDay = evidence.accountingDate
    return if (accountingDay != null && accountingDay != day) {
        UiText.res(R.string.accounting_time_date_with_ledger_day, label, displayCalendarDay(accountingDay))
    } else UiText.raw(label)
}

fun displayDateTime(value: String?): String {
    if (value.isNullOrBlank()) return "未设置"
    val formatter = DateTimeFormatter.ofPattern(DATE_TIME_PATTERN)
    return parseLocalDateTime(value)
        ?.format(formatter)
        ?: value.replace("T", " ").removeSuffix("Z")
}

fun selectedDateMillisFromIso(value: String?, zoneId: ZoneId = ZoneId.systemDefault()): Long? {
    if (value.isNullOrBlank()) return null
    val localDate = parseLocalDateTime(value, zoneId)
        ?.toLocalDate()
        ?: return null
    return localDate.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
}

fun nowUtcIso(): String = Instant.now().truncatedTo(ChronoUnit.MINUTES).toString()

private fun parseLocalDateTime(
    value: String?,
    zoneId: ZoneId = ZoneId.systemDefault(),
): LocalDateTime? {
    if (value.isNullOrBlank()) return null
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDateTime() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDateTime() }
        .recoverCatching { LocalDateTime.parse(value) }
        .recoverCatching { LocalDate.parse(value.take(10)).atStartOfDay() }
        .getOrNull()
}
