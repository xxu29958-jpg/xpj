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
