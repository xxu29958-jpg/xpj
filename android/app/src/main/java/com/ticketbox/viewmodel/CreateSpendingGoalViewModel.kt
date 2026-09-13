package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.Job
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalDraft
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
    val ledgerCurrency: CurrencyCode? = null,
    val pending: PendingGoalCreation? = null,
    val originalSubmissionId: Long? = null,
) {
    val editable: Boolean get() = canModify && !isSubmitting && pending == null && originalSubmissionId == null
    val canSubmit: Boolean
        get() = editable &&
            ledgerCurrency != null &&
            name.trim().isNotEmpty() &&
            (ledgerCurrency.let { parseAmountCents(targetAmountInput, it)?.let { a -> a > 0L } == true })
}

class CreateSpendingGoalViewModel(
    private val edits: GoalEditActions,
) : ViewModel() {
    private val _state = MutableStateFlow(CreateSpendingGoalUiState(canModify = edits.currentAccess()?.canModify == true))
    val state: StateFlow<CreateSpendingGoalUiState> = _state.asStateFlow()

    private var binding: LogicalSessionBinding? = edits.currentAccess()?.binding
    private var generation = 0L
    private var currencyJob: Job? = null
    private var submitJob: Job? = null
    private var observationJob: Job? = null

    init {
        retryCurrency()
        observeCreations()
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                if (binding != access?.binding) {
                    binding = access?.binding
                    generation += 1
                    currencyJob?.cancel()
                    submitJob?.cancel()
                    observeCreations()
                    _state.value = CreateSpendingGoalUiState(canModify = access?.canModify == true)
                    if (access != null) retryCurrency()
                } else _state.update { it.copy(canModify = access?.canModify == true) }
            }
        }
    }

    fun reset(month: String = YearMonth.now().toString(), originalId: Long? = null) {
        if (originalId != null && _state.value.originalSubmissionId != originalId) {
            _state.value = CreateSpendingGoalUiState(canModify = edits.currentAccess()?.canModify == true,
                month = month.cleanGoalMonth(), originalSubmissionId = originalId, isSubmitting = true)
            observeCreations()
            return
        }
        if (_state.value.pending != null) return
        if (_state.value.month == month && (_state.value.name.isNotEmpty() || _state.value.targetAmountInput.isNotEmpty())) return
        generation += 1
        submitJob?.cancel()
        _state.value = CreateSpendingGoalUiState(canModify = edits.currentAccess()?.canModify == true,
            month = month.cleanGoalMonth())
        retryCurrency()
    }

    fun retryCurrency() {
        if (_state.value.originalSubmissionId != null) return
        val origin = binding ?: return
        val revision = generation
        currencyJob?.cancel()
        currencyJob = viewModelScope.launch {
            val result = edits.currency(origin)
            if (binding != origin || edits.currentAccess()?.binding != origin || generation != revision) return@launch
            if (_state.value.originalSubmissionId != null) return@launch
            _state.update { it.copy(ledgerCurrency = result.getOrNull(),
                formError = result.exceptionOrNull()?.toUiText(R.string.currency_unconfirmed_write_blocked)) }
        }
    }

    fun updateName(value: String) {
        if (!_state.value.editable) return
        _state.update { it.copy(name = value, formError = null) }
    }

    fun updateTargetAmount(value: String) {
        if (!_state.value.editable) return
        _state.update {
            // R14-2：币种已解析时即时报解析失败（JPY 下输 "12.50" 不再静默 canSubmit=false）。
            val parseFailed = it.ledgerCurrency != null && value.isNotBlank() &&
                parseAmountCents(value, it.ledgerCurrency) == null
            it.copy(
                targetAmountInput = value,
                formError = if (parseFailed) UiText.res(R.string.expense_edit_amount_invalid) else null,
            )
        }
    }

    fun updateCategory(value: String) {
        if (!_state.value.editable) return
        _state.update { it.copy(category = value, formError = null) }
    }

    fun submit() {
        val current = _state.value
        val origin = binding ?: return
        val revision = generation
        if (current.isSubmitting || current.originalSubmissionId != null || edits.currentAccess()?.binding != origin || edits.currentAccess()?.canModify != true) return
        val currency = current.ledgerCurrency
        if (currency == null) {
            _state.update { it.copy(formError = UiText.res(R.string.currency_unconfirmed_write_blocked)) }
            return
        }
        val amountCents = parseAmountCents(current.targetAmountInput, currency)
        if (current.name.trim().isBlank() || amountCents == null || amountCents <= 0L) {
            _state.update { it.copy(formError = UiText.res(R.string.spending_goal_create_validation)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, formError = null) }
        submitJob = viewModelScope.launch {
            val result = edits.create(origin,
                GoalDraft(
                    name = current.name,
                    month = current.month,
                    targetAmountCents = amountCents,
                    homeCurrencyCode = currency.storageKey,
                    category = current.category,
                ),
            )
            if (binding != origin || edits.currentAccess()?.binding != origin || generation != revision) return@launch
            result.fold(
                onSuccess = { id ->
                    _state.update { it.copy(isSubmitting = false, originalSubmissionId = id) }
                    observeCreations()
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
        _state.update { CreateSpendingGoalUiState(canModify = it.canModify, month = it.month, ledgerCurrency = it.ledgerCurrency) }
    }

    fun shiftMonth(delta: Long) {
        if (!_state.value.editable) return
        _state.update {
            val next = runCatching { YearMonth.parse(it.month).plusMonths(delta) }
                .getOrDefault(YearMonth.now())
                .toString()
            it.copy(month = next, formError = null)
        }
    }

    fun recover(pending: PendingGoalCreation, drop: Boolean) {
        val origin = binding ?: return
        if (_state.value.isSubmitting || _state.value.pending?.row != pending.row) return
        _state.update { it.copy(isSubmitting = true, formError = null) }
        submitJob = viewModelScope.launch {
            val result = edits.recoverCreation(origin, pending, drop)
            if (binding != origin || edits.currentAccess()?.binding != origin) return@launch
            if (result.isSuccess && drop) {
                _state.value = CreateSpendingGoalUiState(canModify = edits.currentAccess()?.canModify == true, month = _state.value.month)
                retryCurrency()
            } else _state.update { it.copy(isSubmitting = false,
                formError = result.exceptionOrNull()?.toUiText(R.string.spending_goal_create_failed)) }
        }
    }

    private fun observeCreations() {
        observationJob?.cancel()
        val origin = binding ?: return
        observationJob = viewModelScope.launch {
            edits.observeCreations(origin).collect { rows ->
                if (binding != origin || edits.currentAccess()?.binding != origin) return@collect
                val selectedId = _state.value.originalSubmissionId
                val original = if (selectedId == null) rows.firstOrNull { !it.isDone } else rows.firstOrNull { it.row.id == selectedId }
                if (original != null) {
                    _state.update { it.withOriginalCreation(original) }
                } else _state.update { it.copy(pending = null, isSubmitting = if (selectedId == null) it.isSubmitting else false,
                    formError = if (selectedId != null) UiText.res(R.string.goal_creation_missing) else it.formError) }
            }
        }
    }

}

private fun String.cleanGoalMonth(): String =
    runCatching { YearMonth.parse(trim()).toString() }.getOrDefault(YearMonth.now().toString())


private fun CreateSpendingGoalUiState.withOriginalCreation(original: PendingGoalCreation): CreateSpendingGoalUiState {
    val request = original.request
    val currency = CurrencyCode.fromStorageKeyOrNull(request?.homeCurrencyCode)
    return copy(pending = original, originalSubmissionId = original.row.id, isSubmitting = false, name = request?.name.orEmpty(), month = request?.month ?: month,
        category = request?.category.orEmpty(), ledgerCurrency = currency,
        targetAmountInput = if (currency != null) formatAmountInput(request?.targetAmountCents, currency)
            else request?.targetAmountCents?.toString().orEmpty(),
        createdPublicId = original.confirmed?.publicId?.takeIf { original.isDone })
}
