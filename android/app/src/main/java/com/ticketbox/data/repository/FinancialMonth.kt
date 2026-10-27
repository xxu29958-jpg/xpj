package com.ticketbox.data.repository

import com.ticketbox.domain.model.LedgerCalendar
import java.time.Clock
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

interface LedgerCalendarReader {
    fun currentBinding(): LogicalSessionBinding?
    fun cached(binding: LogicalSessionBinding, revision: Long? = null): LedgerCalendar?
    suspend fun refresh(binding: LogicalSessionBinding, revision: Long? = null): Result<LedgerCalendar?>
}

/** Capture once for a new task. Selected months and durable command bodies never call this. */
suspend fun LedgerCalendarReader?.newTaskMonth(
    binding: LogicalSessionBinding? = this?.currentBinding(),
    clock: Clock = Clock.systemDefaultZone(),
): Result<String?> {
    val instant = clock.instant()
    if (this == null || binding == null || currentBinding() != binding) return Result.success(null)
    val rule = cached(binding)?.let { Result.success(it) } ?: refresh(binding)
    return rule.mapCatching { calendar ->
        check(currentBinding() == binding) { "Ledger binding changed while reading its calendar" }
        calendar?.let {
            check(it.ledgerId == binding.ledgerId) { "Calendar belongs to another ledger" }
            YearMonth.from(instant.atZone(ZoneId.of(it.timezoneName))).toString()
        }
    }
}

/** A new date-only financial form uses a known ledger day; unknown rules need an explicit date. */
suspend fun LedgerCalendarReader?.newTaskDate(
    binding: LogicalSessionBinding? = this?.currentBinding(),
    clock: Clock = Clock.systemDefaultZone(),
): LocalDate? {
    val instant = clock.instant()
    val rule = if (this != null && binding != null && currentBinding() == binding) {
        cached(binding) ?: refresh(binding).getOrNull()
    } else null
    val zone = rule?.takeIf { it.ledgerId == binding?.ledgerId && this?.currentBinding() == binding }
        ?.let { ZoneId.of(it.timezoneName) }
    return zone?.let { instant.atZone(it).toLocalDate() }
}

/** Live presentation reads distinguish an unsupported calendar from a retryable read failure. */
suspend fun LedgerCalendarReader?.refreshedLedgerDate(
    binding: LogicalSessionBinding? = this?.currentBinding(),
    clock: Clock = Clock.systemUTC(),
): Result<LocalDate?> = refreshedLedgerCalendar(binding).mapCatching { rule ->
    rule?.let { clock.instant().atZone(ZoneId.of(it.timezoneName)).toLocalDate() }
}

/** Return the same verified rule for both the displayed day and its next midnight. */
suspend fun LedgerCalendarReader?.refreshedLedgerCalendar(
    binding: LogicalSessionBinding? = this?.currentBinding(),
): Result<LedgerCalendar?> {
    if (this == null || binding == null || currentBinding() != binding) return Result.success(null)
    return refresh(binding).recoverCatching { error -> cached(binding) ?: throw error }.mapCatching { rule ->
        rule?.takeIf { it.ledgerId == binding.ledgerId && currentBinding() == binding }
            ?.also { ZoneId.of(it.timezoneName) }
    }
}
