package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtRepaymentQueries
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DebtRepaymentHistoryUiState(
    val debtPublicId: String? = null,
    val homeCurrencyCode: String? = null,
    val items: List<DebtRepayment> = emptyList(),
    val page: Int = 1,
    val total: Int = 0,
    val hasNext: Boolean = false,
    val isLoading: Boolean = false,
    val error: UiText? = null,
) {
    val hasPrevious: Boolean get() = page > 1
}

class DebtRepaymentHistoryViewModel(private val repository: DebtRepaymentQueries) : ViewModel() {
    private val _state = MutableStateFlow(DebtRepaymentHistoryUiState())
    val state = _state.asStateFlow()
    private var target: Pair<String, Long>? = null
    private var requestedPage = 1
    private var generation = 0L

    /** A canonical parent change invalidates the old history; no local balance folding. */
    fun loadDebt(publicId: String, rowVersion: Long) {
        val next = publicId to rowVersion
        if (target == next) return
        target = next
        requestedPage = 1
        _state.value = DebtRepaymentHistoryUiState()
        refresh()
    }

    fun loadPage(page: Int) {
        if (page < 1 || _state.value.isLoading) return
        requestedPage = page
        refresh()
    }

    fun refresh() {
        val publicId = target?.first ?: return
        val page = requestedPage
        val requestGeneration = ++generation
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listRepayments(publicId, page)
            if (generation != requestGeneration) return@launch
            result.fold(
                onSuccess = { history ->
                    _state.value = DebtRepaymentHistoryUiState(
                        debtPublicId = history.debtPublicId,
                        homeCurrencyCode = history.homeCurrencyCode,
                        items = history.items,
                        page = history.page,
                        total = history.total,
                        hasNext = history.page * history.pageSize < history.total,
                    )
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(isLoading = false, error = error.toUiText(R.string.debt_repayment_history_load_failed))
                    }
                },
            )
        }
    }
}
