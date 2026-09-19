package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import java.time.Clock
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
    val instant = clock.instant()
    val rule = if (this != null && binding != null && currentBinding() == binding) {
        cached(binding) ?: refresh(binding).getOrNull()
    } else null
    val zone = rule?.takeIf { it.ledgerId == binding?.ledgerId && this?.currentBinding() == binding }
        ?.let { ZoneId.of(it.timezoneName) } ?: clock.zone
    // No known rule (old server or offline cold start) preserves the previous usable default.
    return YearMonth.from(instant.atZone(zone)).toString()
}
