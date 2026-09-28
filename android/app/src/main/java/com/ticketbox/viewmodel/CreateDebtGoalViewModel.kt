package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtWriteActions
import com.ticketbox.data.repository.DebtWriteObservation
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job

/**
 * ADR-0049 §6 (slice 8b) 新建还债目标：名称 + 欠款多选选择器 → `POST /api/goals`
 * (goal_type=debt_repayment)。
 *
 * 复用 slice 8a 的 `GET /api/debts` 列表（[DebtActions]）作为多选选择器的数据源，复用
 * 既有 GoalEditActions 原创建协议提交。选择器只列**未结清**
 * 欠款：关联一笔已结清欠款会让目标在创建时即达成，关联一笔已作废欠款会立刻进入 §6/F13 复核
 * 死胡同——两者都不是「还债目标」该跟踪的对象，故创建侧收窄到 open 欠款，避免一上来就达成/卡死。
 */
data class CreateDebtGoalUiState(
    val isLoadingDebts: Boolean = false,
    val canModify: Boolean = true,
    /** 可关联的欠款（仅未结清）。 */
    val candidates: List<Debt> = emptyList(),
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
    val selectedDebtIds: Set<String> = emptySet(),
    val name: String = "",
    val isSubmitting: Boolean = false,
    /** 加载欠款失败（与表单错误分开，便于分别提示）。 */
    val loadError: UiText? = null,
    /** 校验 / 创建失败。 */
    val formError: UiText? = null,
    /**
     * 一次性信号：创建成功后置为新目标的 public_id；屏幕消费它（关闭新建页 + 重新拉取目标列表）
     * 后调用 [consumeCreated]。
     */
    val createdPublicId: String? = null,
    val pending: PendingGoalCreation? = null,
    val originalSubmissionId: Long? = null,
    val creationKey: String? = null,
    val hasDraft: Boolean = false,
    val acceptanceUncertain: Boolean = false,
    val checkingOriginal: Boolean = false,
    val isViewingOriginal: Boolean = false,
) {
    val unavailableSelectedDebtIds: Set<String>
        get() = selectedDebtIds - candidates.map { it.publicId }.toSet()
    val editable: Boolean get() = canModify && !isSubmitting && !checkingOriginal && !acceptanceUncertain &&
        pending == null && originalSubmissionId == null && !isViewingOriginal
    val canDiscardDraft: Boolean get() = hasDraft && !isViewingOriginal && !isSubmitting && !checkingOriginal
    val canStartSubmission: Boolean
        get() = editable && !isLoadingDebts && loadError == null
    val canSubmit: Boolean
        get() = canStartSubmission && name.trim().isNotEmpty() && selectedDebtIds.isNotEmpty() &&
            unavailableSelectedDebtIds.isEmpty()
}

class CreateDebtGoalViewModel(
    internal val edits: GoalEditActions,
    private val debts: DebtActions,
    internal val writes: DebtWriteActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {

    private var adjustmentBinding = writes.currentAccess()?.binding
    internal var writeObservation: DebtWriteObservation? = null

    internal val store = DebtGoalCreationDraftStore(savedStateHandle)
    internal var binding: LogicalSessionBinding? = edits.currentAccess()?.binding
    internal var task: DebtGoalCreationDraft? = null
    internal var generation = 0L
    internal var observationJob: Job? = null
    internal var lookupJob: Job? = null
    internal var submitJob: Job? = null
    internal var submittingKey: String? = null
    internal val _state = MutableStateFlow(CreateDebtGoalUiState(canModify = edits.currentAccess()?.canModify == true))
    val state: StateFlow<CreateDebtGoalUiState> = _state.asStateFlow()

    private var loadGeneration = 0L

    init {
        activateDebtGoalDraft()
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                if (binding != access?.binding) {
                    binding = access?.binding
                    generation++
                    loadGeneration++
                    lookupJob?.cancel(); observationJob?.cancel()
                    activateDebtGoalDraft()
                    refreshCandidates()
                } else _state.update { it.copy(canModify = access?.canModify == true) }
            }
        }
        viewModelScope.launch {
            debts.observeReadAccessDenials().collect { denial ->
                if (denial.binding != writes.currentAccess()?.binding) return@collect
                loadGeneration++
                _state.update { it.copy(candidates = emptyList(), fetchedAt = null, fromCache = false,
                    isLoadingDebts = false, canModify = false,
                    loadError = denial.failure.toUiText(R.string.debt_goal_create_load_failed)) }
            }
        }
        viewModelScope.launch {
            debts.observeResourceDenials().collect { denial ->
                if (denial.binding != writes.currentAccess()?.binding) return@collect
                val wasLoading = _state.value.isLoadingDebts
                loadGeneration++
                _state.update { it.copy(isLoadingDebts = false,
                    candidates = it.candidates.filterNot { debt -> debt.publicId == denial.debtPublicId }) }
                if (wasLoading) refreshCandidates()
            }
        }
        viewModelScope.launch {
            writes.observeWrites().collect { change ->
                val changedBinding = adjustmentBinding != change.binding
                adjustmentBinding = change.binding
                writeObservation = change
                if (change.binding == null) {
                    loadGeneration++
                    _state.update { it.copy(candidates = emptyList(), canModify = false, isLoadingDebts = false) }
                } else if (changedBinding) reload() else if (change.requiresRefresh) refreshCandidates()
                else _state.update { state -> state.copy(candidates = state.candidates.filterNot {
                    "debt:${it.publicId}" in change.unresolvedTargetIds
                }) }
            }
        }
    }

    /**
     * Reenter the original task without replacing its raw draft or published intent.
     */
    fun reload(originalSubmissionId: Long? = null) {
        val accessBinding = edits.currentAccess()?.binding
        if (binding != accessBinding) {
            binding = accessBinding
            generation++
            loadGeneration++
            activateDebtGoalDraft()
        }
        val current = task
        if (current != null && current.viewingOriginalId != originalSubmissionId) {
            generation++
            store.write(current.copy(viewingOriginalId = originalSubmissionId, viewFailure = null))
        }
        activateDebtGoalDraft()
        refreshCandidates()
    }

    fun openOriginal(id: Long) = reload(id)

    /** Refresh or retry within the open form, preserving its name and explicit selection. */
    fun refreshCandidates() {
        val observation = writeObservation
        if (observation?.binding == null) {
            _state.update { it.copy(isLoadingDebts = writes.currentAccess() != null) }
            return
        }
        val generation = ++loadGeneration
        _state.update { it.copy(isLoadingDebts = true, loadError = null) }
        viewModelScope.launch {
            val result = debts.listDebts()
            if (generation != loadGeneration || observation.binding != writes.currentAccess()?.binding ||
                observation.binding != binding) return@launch
            val currentObservation = writeObservation ?: return@launch
            result.fold(
                onSuccess = { snapshot ->
                    val page = snapshot.value
                    if (!page.debts.filterNot { "debt:${it.publicId}" in observation.unresolvedTargetIds }
                            .all(observation::acceptsCanonical)) {
                        _state.update { it.copy(isLoadingDebts = false,
                            loadError = UiText.res(R.string.debt_write_canonical_refresh_required)) }
                        return@launch
                    }
                    _state.update {
                        it.copy(
                            isLoadingDebts = false,
                            canModify = edits.currentAccess()?.canModify == true,
                            candidates = page.debts.filter { debt -> debt.isOpen &&
                                "debt:${debt.publicId}" !in currentObservation.unresolvedTargetIds },
                            fetchedAt = snapshot.fetchedAt,
                            fromCache = snapshot.fromCache,
                            loadError = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isLoadingDebts = false,
                            loadError = err.toUiText(R.string.debt_goal_create_load_failed),
                        )
                    }
                },
            )
        }
    }

    fun updateName(value: String) {
        if (state.value.editable) updateDebtGoalDraft { it.copy(name = value, failure = null) }
    }

    fun toggleDebt(publicId: String) {
        if (!state.value.editable) return
        updateDebtGoalDraft {
            val next = it.selectedIds.toMutableSet()
            if (!next.remove(publicId) && state.value.candidates.any { debt -> debt.publicId == publicId }) next.add(publicId)
            it.copy(selectedIds = next.toList(), failure = null)
        }
    }

    fun removeUnavailableSelections() {
        if (state.value.editable) updateDebtGoalDraft {
            it.copy(selectedIds = it.selectedIds - state.value.unavailableSelectedDebtIds, failure = null)
        }
    }

    fun submit() {
        val current = _state.value
        val original = task ?: return
        val binding = writeObservation?.binding ?: return
        if (binding != original.binding || binding != writes.currentAccess()?.binding ||
            edits.currentAccess()?.binding != binding || !current.canStartSubmission) return
        val cleanName = current.name.trim()
        // Build the id list from candidate order ∩ selection — a stable, candidate-ordered
        // request (NOT selection-insertion order; submitSuccess...InCandidateOrder pins this).
        // Background delivery may remove a selected debt from the open candidates. Keep the
        // original selection visible for review until the user explicitly removes unavailable ids.
        val ids = current.candidates.map { it.publicId }.filter { it in current.selectedDebtIds }
        if (current.unavailableSelectedDebtIds.isNotEmpty()) {
            updateDebtGoalDraft { it.copy(failure = DebtGoalCreationFailure(resource = R.string.debt_goal_create_selection_changed)) }
            return
        }
        if (cleanName.isEmpty() || ids.isEmpty()) {
            updateDebtGoalDraft { it.copy(failure = DebtGoalCreationFailure(resource = R.string.debt_goal_create_validation)) }
            return
        }
        updateDebtGoalDraft { it.copy(failure = null) }
        submittingKey = original.creationKey
        _state.update { it.copy(isSubmitting = true, formError = null) }
        val generation = loadGeneration
        submitJob = viewModelScope.launch {
            val currentObservation = writeObservation ?: return@launch
            if (generation != loadGeneration || binding != writes.currentAccess()?.binding ||
                ids.any { "debt:$it" in currentObservation.unresolvedTargetIds }) {
                _state.update { it.copy(isSubmitting = false) }
                submittingKey = null
                return@launch
            }
            submitDebtGoalTask(original, cleanName, ids)
        }
    }

    /** Clear the one-shot create signal once the screen has acted on it. */
    fun consumeCreated() {
        val current = task ?: return
        if (state.value.createdPublicId == null) return
        if (current.viewingOriginalId != null) store.write(current.copy(viewingOriginalId = null, viewFailure = null))
        else store.remove(current)
        generation++
        activateDebtGoalDraft()
    }

    fun retryOriginal() {
        if (state.value.isSubmitting || state.value.checkingOriginal) return
        observeDebtGoalCreations()
        if (task?.viewingOriginalId == null) lookupDebtGoalCreation()
    }

    /** Confirmation belongs to the caller; this removes SavedState only. */
    fun discardDraft() {
        val current = task ?: return
        if (!state.value.canDiscardDraft) return
        generation++
        lookupJob?.cancel()
        store.remove(current)
        activateDebtGoalDraft()
    }

    fun recover(pending: PendingGoalCreation, drop: Boolean) {
        if (state.value.isSubmitting || state.value.checkingOriginal || state.value.pending?.row != pending.row ||
            task?.binding != edits.currentAccess()?.binding ||
            (if (drop) !pending.canDrop else !pending.canRetry || edits.currentAccess()?.canModify != true)) return
        recoverDebtGoalOriginal(pending, drop)
    }

}
