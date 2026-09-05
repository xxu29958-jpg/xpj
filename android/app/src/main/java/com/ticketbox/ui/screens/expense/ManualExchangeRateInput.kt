package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.FxContract
import java.math.BigDecimal

private const val MAX_MANUAL_EXCHANGE_RATE_LENGTH = 64
private const val MAX_MANUAL_EXCHANGE_RATE_SCALE = 8
private val MAX_MANUAL_EXCHANGE_RATE = BigDecimal("9999999999.99999999")
private val CANONICAL_POSITIVE_EXCHANGE_RATE = Regex(
    "^(?:[1-9][0-9]*(?:\\.[0-9]+)?|0\\.[0-9]*[1-9][0-9]*)$",
)

internal fun sanitizeManualExchangeRateInput(raw: String): String =
    raw.take(MAX_MANUAL_EXCHANGE_RATE_LENGTH)

internal fun canonicalManualExchangeRateOrNull(raw: String): String? {
    val canonical = raw.trim()
    if (canonical.length > MAX_MANUAL_EXCHANGE_RATE_LENGTH || !CANONICAL_POSITIVE_EXCHANGE_RATE.matches(canonical)) {
        return null
    }
    val decimal = canonical.toBigDecimalOrNull() ?: return null
    if (decimal.stripTrailingZeros().scale() > MAX_MANUAL_EXCHANGE_RATE_SCALE) return null
    if (decimal > MAX_MANUAL_EXCHANGE_RATE) return null
    return canonical
}

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
