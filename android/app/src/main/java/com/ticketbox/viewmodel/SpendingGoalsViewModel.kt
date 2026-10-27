package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import com.ticketbox.data.repository.LedgerCalendarReader
import com.ticketbox.data.repository.newTaskMonth
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import java.time.YearMonth
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SpendingGoalsUiState(
    val canModify: Boolean,
    val month: String,
    val goals: List<Goal> = emptyList(),
    val isLoading: Boolean = true,
    val loadError: UiText? = null,
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
    val includeArchived: Boolean = false,
)

class SpendingGoalsViewModel(
    private val reports: ReportsActions,
    private val edits: com.ticketbox.data.repository.GoalEditActions,
    initialMonth: String? = null,
    private val calendars: LedgerCalendarReader? = null,
) : ViewModel() {
    private val _state = MutableStateFlow(
        SpendingGoalsUiState(
            canModify = edits.currentAccess()?.canModify == true,
            month = initialMonth.orEmpty(),
        ),
    )
    val state: StateFlow<SpendingGoalsUiState> = _state.asStateFlow()
    private var monthSelected = !initialMonth.isNullOrBlank()
    private var resolvingMonth = false
    val monthForNewGoal: String? get() = _state.value.month.takeUnless { resolvingMonth || it.isBlank() }
    private var loadJob: Job? = null
    private var loadGeneration = 0L
    private val timezone = java.util.TimeZone.getDefault().id

    private var binding: com.ticketbox.data.repository.LogicalSessionBinding? = null
    init {
        viewModelScope.launch(start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED) {
            reports.readAccessDenials.collect { denial ->
                if (denial.binding != binding || edits.currentAccess()?.binding != denial.binding) return@collect
                loadGeneration += 1
                loadJob?.cancel()
                _state.update { it.copy(goals = emptyList(), fetchedAt = null, fromCache = false, isLoading = false,
                    loadError = denial.failure.toUiText(R.string.spending_goals_load_failed)) }
            }
        }
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                if (binding != access?.binding) {
                    binding = access?.binding
                    loadGeneration += 1
                    loadJob?.cancel()
                    _state.update { it.copy(month = it.month.takeIf { monthSelected }.orEmpty(), goals = emptyList(), fetchedAt = null,
                        fromCache = false, canModify = access?.canModify == true, isLoading = false) }
                    if (access != null) {
                        resolvingMonth = false
                        refresh()
                    }
                } else _state.update { it.copy(canModify = access?.canModify == true) }
            }
        }
    }

    fun refresh() {
        if (resolvingMonth) return
        val origin = edits.currentAccess()?.binding ?: return
        if (_state.value.month.isBlank()) { resolveMonth(origin); return }
        val requestedMonth = _state.value.month
        val includeArchived = _state.value.includeArchived
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update {
            it.copy(
                canModify = edits.currentAccess()?.canModify == true,
                isLoading = true,
                loadError = null,
            )
        }
        loadJob = viewModelScope.launch {
            val result = reports.goals(month = requestedMonth, includeArchived = includeArchived, expectedBinding = origin, timezone = timezone)
            if (generation != loadGeneration || edits.currentAccess()?.binding != origin || _state.value.month != requestedMonth ||
                _state.value.includeArchived != includeArchived) return@launch
            result.fold(
                onSuccess = { read ->
                    _state.update {
                        it.copy(
                            goals = read.value.filter { goal -> goal.isSpendingLimit && (includeArchived || !goal.isArchived) },
                            fetchedAt = read.fetchedAt, fromCache = read.fromCache,
                            isLoading = false,
                            loadError = null,
                        )
                    }
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            loadError = error.toUiText(R.string.spending_goals_load_failed),
                            goals = if (error.isReadAccessDenied()) emptyList() else it.goals,
                            fetchedAt = if (error.isReadAccessDenied()) null else it.fetchedAt,
                            fromCache = !error.isReadAccessDenied() && it.fromCache,
                        )
                    }
                },
            )
        }
    }

    private fun resolveMonth(origin: com.ticketbox.data.repository.LogicalSessionBinding) {
        resolvingMonth = true
        _state.update { it.copy(isLoading = true, loadError = null) }
        viewModelScope.launch {
            val result = calendars.newTaskMonth(origin)
            if (binding != origin || edits.currentAccess()?.binding != origin || monthSelected) return@launch
            resolvingMonth = false
            _state.update { it.copy(month = result.getOrNull().orEmpty(), isLoading = false, loadError = result.monthReadMessage()) }
            if (result.getOrNull() != null) refresh()
        }
    }

    fun acceptArchived(expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding, archived: Goal) {
        if (expectedBinding != binding || expectedBinding != edits.currentAccess()?.binding ||
            archived.ledgerId != expectedBinding.ledgerId || !archived.isArchived) return
        val remaining = _state.value.goals.mapNotNull {
            if (it.publicId == archived.publicId && it.rowVersion <= archived.rowVersion) {
                archived.takeIf { _state.value.includeArchived }
            } else it
        }
        if (remaining == _state.value.goals) return
        loadGeneration += 1
        loadJob?.cancel()
        _state.update { it.copy(goals = remaining, fetchedAt = null, fromCache = false, isLoading = false) }
    }

    fun previousMonth() {
        shiftMonth(-1)
    }

    fun nextMonth() {
        shiftMonth(1)
    }

    fun setIncludeArchived(include: Boolean) {
        if (include == _state.value.includeArchived) return
        _state.update { it.copy(includeArchived = include, goals = emptyList(), fetchedAt = null, fromCache = false, loadError = null) }
        refresh()
    }

    private fun shiftMonth(delta: Long) {
        val month = runCatching { YearMonth.parse(_state.value.month).plusMonths(delta).toString() }.getOrNull() ?: return
        selectMonth(month)
    }

    fun selectMonth(value: String) {
        val month = runCatching { YearMonth.parse(value).toString() }.getOrNull() ?: return
        monthSelected = true
        resolvingMonth = false
        _state.update { it.copy(month = month, goals = emptyList(), fetchedAt = null, fromCache = false, loadError = null) }
        refresh()
    }
}
