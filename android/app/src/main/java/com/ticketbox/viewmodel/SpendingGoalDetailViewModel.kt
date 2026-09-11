package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CurrencyCode
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
    val pendingEdits: List<PendingGoalEdit> = emptyList(),
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
) {
    val goalCurrency: CurrencyCode? get() = CurrencyCode.fromStorageKeyOrNull(goal?.homeCurrencyCode)
    val hasPendingEdit: Boolean get() = pendingEdits.any { !it.isDone }
    val canSave: Boolean
        get() = canModify &&
            !isSaving && !hasPendingEdit &&
            goalCurrency != null &&
            name.trim().isNotEmpty() &&
            (goalCurrency?.let { parseAmountCents(targetAmountInput, it)?.let { a -> a > 0L } } == true)
}

class SpendingGoalDetailViewModel(
    private val reports: ReportsActions,
    private val edits: GoalEditActions,
) : ViewModel() {
    private val _state = MutableStateFlow(
        SpendingGoalDetailUiState(
            canModify = edits.currentAccess()?.canModify == true,
        ),
    )
    val state: StateFlow<SpendingGoalDetailUiState> = _state.asStateFlow()
    private var loadJob: Job? = null
    private var loadGeneration = 0L
    private val timezone = java.util.TimeZone.getDefault().id

    private var taskBinding: LogicalSessionBinding? = edits.currentAccess()?.binding
    private var observation: Job? = null
    private var commandJob: Job? = null

    val acceptedArchive: Pair<LogicalSessionBinding, Goal>?
        get() {
            val binding = taskBinding ?: return null
            val goal = _state.value.goal ?: return null
            return (binding to goal).takeIf { _state.value.archiveCompleted && goal.isArchived && matches(binding, goal.publicId) }
        }

    init {
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                val changed = access?.binding != taskBinding
                _state.update { it.copy(canModify = access?.canModify == true) }
                if (changed) {
                    taskBinding = access?.binding
                    commandJob?.cancel()
                    observation?.cancel()
                    loadJob?.cancel()
                    loadGeneration += 1
                    val id = _state.value.publicId
                    _state.value = SpendingGoalDetailUiState(canModify = access?.canModify == true, publicId = id)
                    if (access != null) load(id)
                }
            }
        }
    }

    fun load(publicId: String = _state.value.publicId) {
        val id = publicId.trim().takeIf { it.isNotEmpty() } ?: return
        val binding = edits.currentAccess()?.binding ?: return
        if (id == _state.value.publicId && _state.value.isEditing && taskBinding == binding) return
        val sameTask = id == _state.value.publicId && taskBinding == binding
        taskBinding = binding
        val generation = ++loadGeneration
        loadJob?.cancel()
        observation?.cancel()
        if (!sameTask) _state.value = SpendingGoalDetailUiState(edits.currentAccess()?.canModify == true, publicId = id)
        _state.update { it.copy(isLoading = true, loadError = null) }
        observeSubmission(binding, id)
        loadJob = viewModelScope.launch {
            val result = reports.goal(id, expectedBinding = binding, timezone = timezone)
            if (!matches(binding, id, generation)) return@launch
            result.fold(onSuccess = { read ->
                val goal = read.value
                _state.update { state ->
                    if (!goal.isSpendingLimit || goal.ledgerId != binding.ledgerId) state.copy(isLoading = false,
                        loadError = UiText.res(R.string.spending_goal_detail_wrong_type))
                    else if (state.goal != null && goal.rowVersion < state.goal.rowVersion) state.copy(isLoading = false)
                    else state.copy(isLoading = false, goal = goal, fetchedAt = read.fetchedAt, fromCache = read.fromCache)
                }
            }, onFailure = { error ->
                _state.update { it.withReadFailure(error) }
            })
        }
    }

    private fun observeSubmission(binding: LogicalSessionBinding, id: String) {
        observation = viewModelScope.launch {
            edits.observeEdits(binding, id).collect { rows ->
                if (!matches(binding, id)) return@collect
                val previous = _state.value.pendingEdits.filter { it.isDone }.map { it.row.id }.toSet()
                val accepted = rows.filter { it.isDone && it.row.id !in previous }
                    .mapNotNull { it.confirmed }.maxByOrNull { it.rowVersion }
                val completed = accepted != null
                _state.update { state ->
                    val updated = state.copy(pendingEdits = rows,
                        mutationRevision = state.mutationRevision + if (completed) 1 else 0)
                    if (accepted != null && (state.goal == null || accepted.rowVersion > state.goal.rowVersion)) {
                        updated.copy(goal = accepted, fetchedAt = null, fromCache = false)
                    } else updated
                }
                if (completed && !_state.value.isLoading) load(id)
            }
        }
    }

    private fun matches(binding: LogicalSessionBinding, id: String, generation: Long = loadGeneration): Boolean =
        generation == loadGeneration && taskBinding == binding && edits.currentAccess()?.binding == binding && _state.value.publicId == id

    fun beginEdit() {
        val goal = _state.value.goal ?: return
        if (!_state.value.canModify || goal.isArchived || _state.value.hasPendingEdit) return
        val currency = _state.value.goalCurrency
        if (currency == null) {
            _state.update { it.copy(formError = UiText.res(R.string.currency_unconfirmed_write_blocked)) }
            return
        }
        _state.update {
            it.copy(
                isEditing = true,
                name = goal.name,
                month = goal.month,
                targetAmountInput = formatAmountInput(goal.targetAmountCents, currency),
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
                SpendingGoalEditField.Amount -> {
                    // R14-2：币种已解析时即时报解析失败（同 CreateSpendingGoalViewModel）。
                    val parseFailed = value.isNotBlank() && it.goalCurrency?.let { currency ->
                        parseAmountCents(value, currency) == null
                    } == true
                    it.copy(
                        targetAmountInput = value,
                        formError = if (parseFailed) UiText.res(R.string.expense_edit_amount_invalid) else null,
                    )
                }
                SpendingGoalEditField.Category -> it.copy(category = value, formError = null)
            }
        }
    }

    fun save() {
        val current = _state.value
        val goal = current.goal ?: return
        val binding = taskBinding ?: return
        if (!matches(binding, goal.publicId) || edits.currentAccess()?.canModify != true ||
            current.isSaving || current.hasPendingEdit || goal.isArchived) return
        val currency = current.goalCurrency
        val amount = currency?.let { parseAmountCents(current.targetAmountInput, it) }
        if (currency == null || current.name.trim().isEmpty() || amount == null || amount <= 0) {
            _state.update { it.copy(formError = UiText.res(R.string.spending_goal_edit_validation)) }
            return
        }
        _state.update { it.copy(isSaving = true, formError = null, message = null) }
        commandJob = viewModelScope.launch {
            val result = edits.save(binding, goal, GoalUpdate(goal.rowVersion, current.name, current.month,
                amount, current.category.trim(), currency.storageKey))
            if (!matches(binding, goal.publicId)) return@launch
            result.fold(onSuccess = {
                _state.update { it.copy(isSaving = false, isEditing = false,
                    message = null, messageTone = MessageTone.Info) }
            }, onFailure = { error ->
                _state.update { it.copy(isSaving = false, formError = error.toUiText(R.string.spending_goal_edit_failed)) }
            })
        }
    }

    fun recover(pending: PendingGoalEdit, drop: Boolean) {
        val binding = taskBinding ?: return
        val id = _state.value.publicId
        if (_state.value.isSaving || !matches(binding, id)) return
        _state.update { it.copy(isSaving = true, formError = null) }
        commandJob = viewModelScope.launch {
            val result = edits.recover(binding, pending, drop)
            if (!matches(binding, id)) return@launch
            _state.update { it.copy(isSaving = false,
                formError = result.exceptionOrNull()?.toUiText(R.string.spending_goal_edit_failed),
                message = if (result.isSuccess) UiText.res(if (drop) R.string.spending_goal_submission_dropped
                    else R.string.spending_goal_submission_retrying) else null, messageTone = MessageTone.Info) }
        }
    }

    fun showArchiveConfirmation(show: Boolean) {
        if (_state.value.isArchiving) return
        val goal = _state.value.goal ?: return
        if (!show || _state.value.canModify && !goal.isArchived && !_state.value.hasPendingEdit) {
            _state.update { it.copy(showArchiveDialog = show, message = null) }
        }
    }

    fun archive() {
        val goal = _state.value.goal ?: return
        val binding = taskBinding ?: return
        if (!matches(binding, goal.publicId) || edits.currentAccess()?.canModify != true ||
            _state.value.isArchiving || _state.value.hasPendingEdit || goal.isArchived) return
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update { it.copy(isArchiving = true, formError = null, message = null) }
        viewModelScope.launch {
            val result = reports.archiveGoal(goal.publicId, binding)
            if (!matches(binding, goal.publicId, generation)) return@launch
            result.fold(
                onSuccess = { archived ->
                    _state.update {
                        it.copy(
                            goal = archived,
                            fetchedAt = null, fromCache = false,
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

    fun shiftMonth(delta: Long) {
        _state.update {
            val nextMonth = runCatching { YearMonth.parse(it.month).plusMonths(delta) }
                .getOrDefault(YearMonth.now())
                .toString()
            it.copy(month = nextMonth, formError = null)
        }
    }
}
