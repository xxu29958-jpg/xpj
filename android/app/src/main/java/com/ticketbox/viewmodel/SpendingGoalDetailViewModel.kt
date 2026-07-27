package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import java.time.YearMonth
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

// Goal 不带币种字段（服务端按账本 home 聚合），编辑流上拿不到 homeCurrencyCode，
// 且 AppViewModel 恒以 CurrencyDisplay.Base 提供 display home，故解析/回填口径显式落
// FxContract.HomeCurrency（登记：若日后 Goal 带上服务端 home，改这里）。
private val goalInputCurrency = FxContract.HomeCurrency

enum class SpendingGoalEditField {
    Name,
    Amount,
    Category,
}

data class SpendingGoalDetailUiState(
    val canModify: Boolean,
    val publicId: String = "",
    val goal: Goal? = null,
    val isLoading: Boolean = false,
    val loadError: UiText? = null,
    val isEditing: Boolean = false,
    val name: String = "",
    val month: String = YearMonth.now().toString(),
    val targetAmountInput: String = "",
    val category: String = "",
    val isSaving: Boolean = false,
    val formError: UiText? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val showArchiveDialog: Boolean = false,
    val isArchiving: Boolean = false,
    val archiveCompleted: Boolean = false,
    val mutationRevision: Int = 0,
) {
    val canSave: Boolean
        get() = canModify &&
            !isSaving &&
            name.trim().isNotEmpty() &&
            (parseAmountCents(targetAmountInput, goalInputCurrency)?.let { it > 0L } == true)
}

class SpendingGoalDetailViewModel(
    private val reports: ReportsActions,
) : ViewModel() {
    private val _state = MutableStateFlow(
        SpendingGoalDetailUiState(
            canModify = reports.canModifyLedger(),
        ),
    )
    val state: StateFlow<SpendingGoalDetailUiState> = _state.asStateFlow()
    private var loadJob: Job? = null
    private var loadGeneration = 0L

    fun load(publicId: String = _state.value.publicId) {
        val requestedId = publicId.trim()
        if (requestedId.isEmpty()) return
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update {
            SpendingGoalDetailUiState(
                canModify = reports.canModifyLedger(),
                publicId = requestedId,
                isLoading = true,
            )
        }
        loadJob = viewModelScope.launch {
            val result = reports.goal(requestedId)
            if (generation != loadGeneration || _state.value.publicId != requestedId) return@launch
            result.fold(
                onSuccess = { goal ->
                    _state.update {
                        if (goal.isSpendingLimit) {
                            it.copy(goal = goal, isLoading = false)
                        } else {
                            it.copy(
                                isLoading = false,
                                loadError = UiText.res(R.string.spending_goal_detail_wrong_type),
                            )
                        }
                    }
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            loadError = error.toUiText(R.string.spending_goal_detail_load_failed),
                        )
                    }
                },
            )
        }
    }

    fun beginEdit() {
        val goal = _state.value.goal ?: return
        if (!_state.value.canModify || goal.isArchived) return
        _state.update {
            it.copy(
                isEditing = true,
                name = goal.name,
                month = goal.month,
                targetAmountInput = formatAmountInput(goal.targetAmountCents, goalInputCurrency),
                category = goal.category.orEmpty(),
                formError = null,
                message = null,
            )
        }
    }

    fun cancelEdit() {
        if (!_state.value.isSaving) {
            _state.update { it.copy(isEditing = false, formError = null, message = null) }
        }
    }

    fun updateField(field: SpendingGoalEditField, value: String) {
        _state.update {
            when (field) {
                SpendingGoalEditField.Name -> it.copy(name = value, formError = null)
                SpendingGoalEditField.Amount -> it.copy(targetAmountInput = value, formError = null)
                SpendingGoalEditField.Category -> it.copy(category = value, formError = null)
            }
        }
    }

    fun previousMonth() {
        shiftMonth(-1)
    }

    fun nextMonth() {
        shiftMonth(1)
    }

    fun save() {
        val current = _state.value
        val goal = current.goal ?: return
        if (!current.canModify || current.isSaving || goal.isArchived) return
        val targetAmountCents = parseAmountCents(current.targetAmountInput, goalInputCurrency)
        if (current.name.trim().isEmpty() || targetAmountCents == null || targetAmountCents <= 0L) {
            _state.update { it.copy(formError = UiText.res(R.string.spending_goal_edit_validation)) }
            return
        }
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update { it.copy(isSaving = true, formError = null, message = null) }
        viewModelScope.launch {
            val result = reports.updateGoal(
                publicId = goal.publicId,
                update = GoalUpdate(
                    expectedRowVersion = goal.rowVersion,
                    name = current.name,
                    month = current.month,
                    targetAmountCents = targetAmountCents,
                    category = current.category.trim(),
                ),
            )
            if (generation != loadGeneration || _state.value.publicId != goal.publicId) return@launch
            result.fold(
                onSuccess = { updated ->
                    _state.update {
                        it.copy(
                            goal = updated,
                            isEditing = false,
                            isSaving = false,
                            formError = null,
                            message = UiText.res(R.string.spending_goal_edit_saved),
                            messageTone = MessageTone.Success,
                            mutationRevision = it.mutationRevision + 1,
                        )
                    }
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(
                            isSaving = false,
                            formError = error.toUiText(R.string.spending_goal_edit_failed),
                        )
                    }
                },
            )
        }
    }

    fun requestArchive() {
        val goal = _state.value.goal ?: return
        if (_state.value.canModify && !goal.isArchived) {
            _state.update { it.copy(showArchiveDialog = true, message = null) }
        }
    }

    fun dismissArchive() {
        if (!_state.value.isArchiving) {
            _state.update { it.copy(showArchiveDialog = false) }
        }
    }

    fun archive() {
        val goal = _state.value.goal ?: return
        if (!_state.value.canModify || _state.value.isArchiving || goal.isArchived) return
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update { it.copy(isArchiving = true, formError = null, message = null) }
        viewModelScope.launch {
            val result = reports.archiveGoal(goal.publicId)
            if (generation != loadGeneration || _state.value.publicId != goal.publicId) return@launch
            result.fold(
                onSuccess = { archived ->
                    _state.update {
                        it.copy(
                            goal = archived,
                            isArchiving = false,
                            showArchiveDialog = false,
                            archiveCompleted = true,
                            mutationRevision = it.mutationRevision + 1,
                        )
                    }
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(
                            isArchiving = false,
                            showArchiveDialog = false,
                            message = error.toUiText(R.string.spending_goal_archive_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                },
            )
        }
    }

    private fun shiftMonth(delta: Long) {
        _state.update {
            val nextMonth = runCatching { YearMonth.parse(it.month).plusMonths(delta) }
                .getOrDefault(YearMonth.now())
                .toString()
            it.copy(month = nextMonth, formError = null)
        }
    }
}
