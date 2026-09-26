package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import com.ticketbox.data.repository.MonthlyArrangementDraft
import com.ticketbox.data.repository.MonthlyArrangementRead
import com.ticketbox.domain.model.CurrencyCode
import java.math.BigDecimal

internal fun MonthlyArrangementDto.draft() = MonthlyArrangementDraft(homeCurrencyCode,
    BigDecimal.valueOf(savingsTargetCents, requireNotNull(CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)).minorUnitDigits).toPlainString(),
    BigDecimal.valueOf(reservedBufferCents, requireNotNull(CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)).minorUnitDigits).toPlainString(), rowVersion)

/** Refresh replaces a saved projection, while an edited original continues to own the trial. */
internal fun BudgetAdviceUiState.arrangementRefreshed(read: Result<MonthlyArrangementRead>): BudgetAdviceUiState {
    val preserveDraft = arrangementDraft?.edited == true
    val retireTrial = !preserveDraft && trialRequest != null
    val record = read.getOrNull()?.response?.arrangement
    return copy(arrangementLoading = false, arrangementRead = read.getOrNull() ?: arrangementRead,
        arrangementDraft = if (preserveDraft) arrangementDraft else record?.draft() ?: arrangementDraft,
        trialRequest = if (preserveDraft) trialRequest else null,
        result = if (retireTrial) null else result,
        loadState = if (retireTrial) BudgetAdviceLoadState.Idle else loadState,
        arrangementMessage = read.exceptionOrNull()?.toUiText(R.string.arrangement_load_failed))
}
