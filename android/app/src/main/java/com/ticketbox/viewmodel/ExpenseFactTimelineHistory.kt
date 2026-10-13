package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount

/** Readable evidence from immutable monetary snapshots, separate from today's summary. */
internal fun historicalAmount(snapshot: Map<String, Any?>): UiText? {
    val original = snapshot["original_amount_minor"] as? Number
    val amount = (original ?: snapshot["amount_cents"] as? Number)?.toLong() ?: return null
    val code = snapshot[if (original != null) "original_currency_code" else "home_currency_code"]
        ?.toString()?.takeIf(String::isNotBlank)
        ?: return UiText.res(R.string.correction_submission_unknown_currency, amount)
    val display = CurrencyDisplay.forRecord(code)
    val value = formatDisplayAmount(amount, display)
    return UiText.raw(if (display.unknownCode == null) "$code $value" else value)
}

internal fun ExpenseRevision.offsetTimelineEntry(currency: CurrencyCode): FactTimelineEntry {
    val kind = when (after["kind"]) {
        "refund" -> R.string.expense_offset_kind_refund
        "chargeback" -> R.string.expense_offset_kind_chargeback
        else -> R.string.expense_offset_kind_reversal
    }
    val label = when (changeKind) {
        "correction" -> R.string.expense_offset_history_correction
        "void" -> R.string.expense_offset_history_void
        else -> kind
    }
    val changed = listOf("original_currency_code", "original_amount_minor", "amount_cents", "category",
        if (after.containsKey("accounting_time")) "accounting_time" else "accounting_date")
        .filter { before?.get(it) != after[it] }
    val changes = if (changeKind == "correction") copy(changedFields = changed)
        .correctionTimelineContent(currency, null).changes else emptyList()
    return FactTimelineEntry(
        isCorrection = changeKind == "correction", kindLabelRes = label, reason = reason,
        whenText = displayDateTime(createdAt),
        actor = listOfNotNull(actorAccountName, actorDeviceName).filter(String::isNotBlank).joinToString(" · "),
        changes = changes,
        summary = UiText.compound(listOfNotNull(
            UiText.res(kind).takeIf { label != kind }, historicalAmount(after).takeIf { after["kind"] != "reversal" },
            after["accounting_date"]?.toString()?.let(UiText::raw)), " · "),
    )
}

