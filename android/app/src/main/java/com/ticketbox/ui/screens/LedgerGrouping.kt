package com.ticketbox.ui.screens

import android.content.res.Resources
import com.ticketbox.R
import com.ticketbox.domain.model.ConfirmedStreamItem
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

data class LedgerStreamGroup(
    val key: String,
    val label: String,
    val items: List<ConfirmedStreamItem>,
) {
    /**
     * Day-header subtotal: sums ONLY the server-owned signed contribution
     * ([ConfirmedStreamItem.streamAmountCents]). Refund/chargeback rows
     * contribute negative amounts, a reversal event and its reversed root both
     * contribute 0 — the client adds, it never recomputes direction or FX.
     * Pure derivation — unit-tested through [groupConfirmedStream].
     */
    val dayTotalCents: Long get() = items.sumOf { it.streamAmountCents }
    val itemCount: Int get() = items.size
}

internal fun ledgerDayPreviewLabels(items: List<ConfirmedStreamItem>, limit: Int): List<String> {
    return items
        .mapNotNull { item -> item.previewLabel()?.let { LedgerDayPreviewCandidate(it, item.previewWeightCents()) } }
        .groupBy { it.label }
        .map { (label, candidates) -> LedgerDayPreviewCandidate(label, candidates.maxOf { it.amountCents }) }
        .sortedWith(compareByDescending<LedgerDayPreviewCandidate> { it.amountCents }.thenBy { it.label })
        .take(limit)
        .map { it.label }
}

/**
 * Groups the confirmed stream into day sections. The server owns both the
 * ordering (stream_date desc, then intra-day order) and the per-row
 * [ConfirmedStreamItem.streamDate], so grouping preserves encounter order and
 * parses the plain calendar date — no device-timezone conversion anywhere.
 */
fun groupConfirmedStream(resources: Resources, items: List<ConfirmedStreamItem>): List<LedgerStreamGroup> {
    return items
        .groupBy { it.streamDate }
        .map { (key, groupItems) ->
            LedgerStreamGroup(
                key = key,
                label = ledgerDayLabel(resources, key.toLocalDateOrNull()),
                items = groupItems,
            )
        }
}

private fun String.toLocalDateOrNull(): LocalDate? =
    runCatching { LocalDate.parse(this) }.getOrNull()

private fun ConfirmedStreamItem.previewLabel(): String? {
    val merchant = root.merchant?.trim()?.takeIf { it.isNotBlank() }
    if (merchant != null) return merchant
    return when (this) {
        is ConfirmedStreamItem.ExpenseRow -> root.category.trim().takeIf { it.isNotBlank() }
        is ConfirmedStreamItem.OffsetRow -> offset.category.trim().takeIf { it.isNotBlank() }
    }
}

/** Salience weight for folded-day previews: the row's own magnitude (gross for
 *  a bill, the offset's home magnitude for an event), never a recomputed net. */
private fun ConfirmedStreamItem.previewWeightCents(): Long = when (this) {
    is ConfirmedStreamItem.ExpenseRow -> root.amountCents ?: 0L
    is ConfirmedStreamItem.OffsetRow -> offset.amountCents
}

fun ledgerDayLabel(resources: Resources, date: LocalDate?): String {
    if (date == null) return resources.getString(R.string.ledger_day_no_date)
    val today = LocalDate.now()
    return when (date) {
        today -> resources.getString(R.string.ledger_day_today)
        today.minusDays(1) -> resources.getString(R.string.ledger_day_yesterday)
        // Date format pattern (not UI copy): 月/日 are DateTimeFormatter literal
        // delimiters, left as-is to keep the formatted output byte-identical.
        else -> date.format(DateTimeFormatter.ofPattern("M月d日 E", Locale.CHINA))
    }
}

private data class LedgerDayPreviewCandidate(
    val label: String,
    val amountCents: Long,
)
