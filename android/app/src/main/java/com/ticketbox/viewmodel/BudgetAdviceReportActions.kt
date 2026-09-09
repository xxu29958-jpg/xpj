package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import java.time.YearMonth

/** Enter the existing rate owner with the report's original month, projection and selected historical gap. */
fun BudgetAdviceViewModel.openReportRate(binding: LogicalSessionBinding, month: String,
    homeCurrencyCode: String, sourceCurrencyCode: String?, rateDate: String?) {
    if (_state.value.binding != binding) {
        _state.update { it.copy(rateMessage = UiText.res(R.string.reports_binding_changed)) }
        return
    }
    if (runCatching { YearMonth.parse(month).toString() == month }.getOrDefault(false).not() ||
        CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) == null) return
    requestGeneration += 1
    _state.update { it.copy(month = month, reportingHomeCurrencyCode = homeCurrencyCode, inputs = null, result = null,
        loadState = BudgetAdviceLoadState.Idle, rateEditor = null, selectedRateSubmissionId = null) }
    refreshInputs()
    if (sourceCurrencyCode != null && rateDate != null) openRate(MissingExchangeRateDto(sourceCurrencyCode, homeCurrencyCode, rateDate))
}
