package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.DebtActivityQueries
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DebtActivityUiState(
    val debtPublicId: String? = null,
    val binding: LogicalSessionBinding? = null,
    val homeCurrencyCode: String? = null,
    val items: List<DebtActivity> = emptyList(),
    val page: Int = 1,
    val total: Int = 0,
    val hasNext: Boolean = false,
    val isLoading: Boolean = false,
    val error: UiText? = null,
    val focusedRepaymentId: String? = null,
    val actionsCurrent: Boolean = false,
) {
    val hasPrevious: Boolean get() = page > 1
}

class DebtActivityViewModel(private val repository: DebtActivityQueries) : ViewModel() {
    private val _state = MutableStateFlow(DebtActivityUiState())
    val state = _state.asStateFlow()
    private var target: Pair<DebtTask, Long>? = null
    private var requestedPage = 1
    private var requestedRepayment: String? = null
    private var commandRevision = 0L
    private var generation = 0L

    /** Reentry also rereads remote proposals, whose changes need not advance the parent version. */
    fun loadDebt(
        task: DebtTask?,
        rowVersion: Long,
        acknowledgedCommandRevision: Long = 0,
        forceRefresh: Boolean = false,
    ) {
        val next = task?.let { it to rowVersion }
        if (!forceRefresh && target == next && commandRevision == acknowledgedCommandRevision) return
        val sameTask = task != null && target?.first == task
        val newerFactsRequired = target != next || commandRevision != acknowledgedCommandRevision
        target = next
        commandRevision = acknowledgedCommandRevision
        generation++
        requestedPage = 1
        requestedRepayment = null
        // A successful command does not erase a readable page if its follow-up query fails.
        // Another relationship or authority must never inherit that page.
        if (!sameTask) {
            _state.value = DebtActivityUiState(debtPublicId = task?.debtPublicId, binding = task?.binding)
        } else if (newerFactsRequired) {
            _state.update { it.copy(actionsCurrent = false) }
        }
        refresh()
    }

    fun loadPage(page: Int) {
        if (page < 1 || _state.value.isLoading) return
        requestedPage = page
        requestedRepayment = null
        refresh()
    }

    /** The server locates the accepted payment in the complete ordered history, including other pages. */
    fun openRepayment(publicId: String) {
        if (target == null || _state.value.isLoading) return
        requestedRepayment = publicId
        refresh()
    }

    fun refresh() {
        val task = target?.first ?: return
        val page = requestedPage
        val focus = requestedRepayment
        val requestGeneration = ++generation
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listActivity(task, page, focus)
            if (generation != requestGeneration) return@launch
            result.fold(
                onSuccess = { history ->
                    requestedPage = history.page
                    requestedRepayment = null
                    _state.value = DebtActivityUiState(
                        debtPublicId = history.debtPublicId,
                        binding = task.binding,
                        homeCurrencyCode = history.homeCurrencyCode,
                        items = history.items,
                        page = history.page,
                        total = history.total,
                        hasNext = history.page * history.pageSize < history.total,
                        focusedRepaymentId = focus,
                        actionsCurrent = true,
                    )
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(isLoading = false, error = error.toUiText(R.string.debt_activity_load_failed))
                    }
                },
            )
        }
    }
}
