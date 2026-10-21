package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.data.repository.LedgerCalendarReader
import com.ticketbox.data.repository.LogicalSessionBinding
import java.time.Clock
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest

/** The recurring page's clock uses its verified rule; it never reloads facts or changes an intent. */
internal class RecurringLedgerDay(
    private val calendars: LedgerCalendarReader?,
    private val clock: Clock,
    private val onDay: (LocalDate) -> Unit,
) {
    private val calendar = MutableStateFlow<Pair<LogicalSessionBinding, LedgerCalendarDto>?>(null)

    fun clear() { calendar.value = null }

    fun update(binding: LogicalSessionBinding, rule: LedgerCalendarDto?): LocalDate? {
        calendar.value = rule?.let { binding to it }
        return rule?.let { clock.instant().atZone(ZoneId.of(it.timezoneName)).toLocalDate() }
    }

    /** Collected only while resumed. A changed rule cancels the old midnight deadline. */
    suspend fun observe() {
        calendar.collectLatest { snapshot ->
            val (binding, rule) = snapshot ?: return@collectLatest
            val zone = ZoneId.of(rule.timezoneName)
            while (calendars?.currentBinding() == binding && calendar.value == snapshot) {
                val now = clock.instant()
                val today = now.atZone(zone).toLocalDate()
                onDay(today)
                val midnight = today.plusDays(1).atStartOfDay(zone).toInstant()
                delay(Duration.between(now, midnight).toMillis().coerceAtLeast(1))
            }
        }
    }
}
