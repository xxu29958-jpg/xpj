package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.FxContract

internal fun manualExchangeRateNeedsServerReview(
    fxPending: Boolean,
    savedManualRate: String?,
    draftManualRate: String,
    fxIdentityChanged: Boolean,
): Boolean =
    fxPending || fxIdentityChanged || draftManualRate.trim() != savedManualRate.orEmpty()

internal fun manualExchangeRateEditorVisible(
    pendingExpense: Boolean,
    foreignCurrency: Boolean,
    fxPending: Boolean,
    fxSource: String?,
): Boolean =
    pendingExpense && foreignCurrency && (fxPending || fxSource == FxContract.SourceManual)

/** Blank new quote and attempted clearing of a saved quote are distinct edit states. */
internal data class ManualExchangeRateEditValue(val rate: String?, val invalid: Boolean = false)

internal fun manualExchangeRateEditValue(visible: Boolean, raw: String, savedRate: String?): ManualExchangeRateEditValue {
    if (!visible) return ManualExchangeRateEditValue(null)
    if (raw.isBlank()) return ManualExchangeRateEditValue(null, invalid = savedRate != null)
    val rate = com.ticketbox.domain.model.canonicalManualExchangeRateOrNull(raw)
    return ManualExchangeRateEditValue(rate, invalid = rate == null)
}
