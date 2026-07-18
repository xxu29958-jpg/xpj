package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import java.time.YearMonth
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CreateSpendingGoalUiState(
    val canModify: Boolean = true,
    val name: String = "",
    val month: String = YearMonth.now().toString(),
    val targetAmountInput: String = "",
    val category: String = "",
    val isSubmitting: Boolean = false,
    val formError: UiText? = null,
    val createdPublicId: String? = null,
    val homeCurrency: CurrencyCode = CurrencyCode.LegacyFallback,
) {
    val canSubmit: Boolean
        get() = canModify &&
            !isSubmitting &&
            name.trim().isNotEmpty() &&
            (parseAmountCents(targetAmountInput, homeCurrency)?.let { it > 0L } == true)
}

class CreateSpendingGoalViewModel(
    private val reports: ReportsActions,
) : ViewModel() {
    private val _state = MutableStateFlow(
        CreateSpendingGoalUiState(
            canModify = reports.canModifyLedger(),
            homeCurrency = reports.currentHomeCurrency(),
        ),
    )
    val state: StateFlow<CreateSpendingGoalUiState> = _state.asStateFlow()

    fun reset(month: String = YearMonth.now().toString()) {
        _state.value = CreateSpendingGoalUiState(
            canModify = reports.canModifyLedger(),
            month = month.cleanGoalMonth(),
            homeCurrency = reports.currentHomeCurrency(),
        )
    }

    fun updateName(value: String) {
        _state.update { it.copy(name = value, formError = null) }
    }

    fun updateTargetAmount(value: String) {
        _state.update { it.copy(targetAmountInput = value, formError = null) }
    }

    fun updateCategory(value: String) {
        _state.update { it.copy(category = value, formError = null) }
    }

    fun previousMonth() {
        shiftMonth(-1)
    }

    fun nextMonth() {
        shiftMonth(1)
    }

    fun submit() {
        val current = _state.value
        val amountCents = parseAmountCents(current.targetAmountInput, current.homeCurrency)
        if (current.name.trim().isBlank() || amountCents == null || amountCents <= 0L) {
            _state.update { it.copy(formError = UiText.res(R.string.spending_goal_create_validation)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, formError = null) }
        viewModelScope.launch {
            reports.createGoal(
                GoalDraft(
                    name = current.name,
                    month = current.month,
                    targetAmountCents = amountCents,
                    category = current.category,
                ),
            ).fold(
                onSuccess = { goal ->
                    _state.update { it.copy(isSubmitting = false, createdPublicId = goal.publicId) }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            formError = err.toUiText(R.string.spending_goal_create_failed),
                        )
                    }
                },
            )
        }
    }

    fun consumeCreated() {
        _state.update { it.copy(createdPublicId = null) }
    }

    private fun shiftMonth(delta: Long) {
        _state.update {
            val next = runCatching { YearMonth.parse(it.month).plusMonths(delta) }
                .getOrDefault(YearMonth.now())
                .toString()
            it.copy(month = next, formError = null)
        }
    }
}

private fun String.cleanGoalMonth(): String =
    runCatching { YearMonth.parse(trim()).toString() }.getOrDefault(YearMonth.now().toString())
