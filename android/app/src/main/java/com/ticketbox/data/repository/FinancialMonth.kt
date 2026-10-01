package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import java.time.Clock
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

interface LedgerCalendarReader {
    fun currentBinding(): LogicalSessionBinding?
    fun cached(binding: LogicalSessionBinding, revision: Long? = null): LedgerCalendarDto?
    suspend fun refresh(binding: LogicalSessionBinding, revision: Long? = null): Result<LedgerCalendarDto?>
}

/** Capture once for a new task. Selected months and durable command bodies never call this. */
suspend fun LedgerCalendarReader?.newTaskMonth(
    binding: LogicalSessionBinding? = this?.currentBinding(),
    clock: Clock = Clock.systemDefaultZone(),
): String {
    val capturedClock = Clock.fixed(clock.instant(), clock.zone)
    // Keep the existing usable month default when no ledger rule has been read.
    return YearMonth.from(newTaskDate(binding, capturedClock) ?: LocalDate.now(capturedClock)).toString()
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
