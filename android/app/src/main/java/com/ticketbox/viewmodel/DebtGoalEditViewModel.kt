package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.CreationExtras
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DebtGoalEditUiState(
    val kind: DebtGoalEditKind = DebtGoalEditKind.Links,
    val publicId: String = "",
    val goal: Goal? = null,
    val goalName: String = "",
    val selectedLabels: Map<String, String> = emptyMap(),
    val targetDate: String? = null,
    val candidates: List<Debt> = emptyList(),
    val canModify: Boolean = false,
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val hasDraft: Boolean = false,
    val pending: PendingGoalEdit? = null,
    val error: UiText? = null,
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
) {
    val editable: Boolean get() = canModify && !isSaving && (pending == null || pending.isDone && pending.confirmed != null)
    val unavailableIds: Set<String> get() = if (kind == DebtGoalEditKind.Links)
        selectedLabels.keys - candidates.map { it.publicId }.toSet() else emptySet()
    val canSave: Boolean get() = editable && goal?.isArchived == false && hasDraft && !isLoading &&
        (kind == DebtGoalEditKind.TargetDate || selectedLabels.isNotEmpty() && unavailableIds.isEmpty())
}

/** Date and association tasks share draft continuity; each admits its own explicit command. */
class DebtGoalEditViewModel(
    private val reports: ReportsActions,
    private val edits: GoalEditActions,
    private val debts: DebtActions,
    private val savedState: SavedStateHandle,
    private val kind: DebtGoalEditKind = DebtGoalEditKind.Links,
) : ViewModel() {
    private val store = DebtGoalEditDraftStore(savedState, kind)
    private var binding = edits.currentAccess()?.binding
    private var draft: DebtGoalEditDraft? = null
    private var loadJob: Job? = null
    private var observation: Job? = null
    private var generation = 0L
    private val _state = MutableStateFlow(DebtGoalEditUiState(kind = kind, publicId = savedState["${kind.savedPrefix}.active"] ?: ""))
    val state = _state.asStateFlow()

    init {
        if (state.value.publicId.isNotBlank()) open(state.value.publicId)
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                if (binding != access?.binding) {
                    binding = access?.binding
                    generation++
                    loadJob?.cancel(); observation?.cancel()
                    draft = null
                    _state.value = DebtGoalEditUiState(kind = kind, publicId = state.value.publicId)
                    if (binding != null) open(state.value.publicId)
                } else _state.update { it.copy(canModify = access?.canModify == true && it.goal?.supports(kind) != false) }
            }
        }
        viewModelScope.launch {
            reports.readAccessDenials.collect { denial ->
                if (denial.binding == binding) readFailed(denial.failure)
            }
        }
        viewModelScope.launch {
            debts.observeReadAccessDenials().collect { denial ->
                if (kind == DebtGoalEditKind.Links && denial.binding == binding) readFailed(denial.failure)
            }
        }
        viewModelScope.launch {
            debts.observeResourceDenials().collect { denial ->
                if (denial.binding == binding) _state.update { current ->
                    current.copy(candidates = current.candidates.filterNot { it.publicId == denial.debtPublicId })
                }
            }
        }
    }

    fun open(id: String) {
        val bound = edits.currentAccess()?.binding ?: return
        if (id.isBlank()) return
        binding = bound
        savedState["${kind.savedPrefix}.active"] = id
        draft = store.read(bound, id)
        _state.value = DebtGoalEditUiState(kind = kind, publicId = id, canModify = edits.currentAccess()?.canModify == true)
        showDraft()
        observation?.cancel()
        observation = viewModelScope.launch {
            edits.observeEdits(bound, id).collect { rows ->
                if (!matches(bound, id)) return@collect
                val submitted = rows.filter { it.row.type == kind.mutationType }
                draft?.takeIf { original -> submitted.any(original::matches) }?.let { store.remove(it); draft = null }
                val active = submitted.firstOrNull { !it.isDone }
                val accepted = submitted.filter { it.isDone }.maxByOrNull { it.row.id }
                val delivered = active == null && accepted?.confirmed != null && state.value.pending?.row != accepted.row
                if (active != null) draft?.takeUnless { it.changed }?.let { store.remove(it); draft = null }
                _state.update { it.copy(pending = active ?: accepted.takeIf { draft == null }, hasDraft = draft != null) }
                (active ?: accepted)?.debtEdit?.let { original ->
                    if (draft == null) _state.update { it.copy(goalName = original.goalName,
                        selectedLabels = original.selectedLabels, targetDate = original.dateRequest?.targetDate) }
                }
                if (delivered) refresh()
            }
        }
        refresh()
    }

    fun refresh() {
        val bound = binding ?: return
        val id = state.value.publicId
        if (!matches(bound, id)) return
        val ticket = ++generation
        loadJob?.cancel()
        _state.update { it.copy(isLoading = true, error = null) }
        loadJob = viewModelScope.launch {
            val goal = reports.goal(id, expectedBinding = bound)
            val choices = if (kind == DebtGoalEditKind.Links) debts.listDebts() else null
            if (!matches(bound, id) || generation != ticket) return@launch
            goal.fold(onSuccess = { read ->
                if (!read.value.isDebtRepayment || read.value.ledgerId != bound.ledgerId) {
                    _state.update { it.copy(goal = null, canModify = false,
                        error = UiText.res(R.string.spending_goal_detail_wrong_type)) }
                    return@fold
                }
                _state.update { it.copy(goal = read.value, goalName = draft?.original?.name ?: read.value.name,
                    canModify = edits.currentAccess()?.canModify == true && read.value.supports(kind),
                    fetchedAt = read.fetchedAt, fromCache = read.fromCache) }
                if (draft?.changed != true && state.value.editable) {
                    draft = DebtGoalEditDraft(bound, read.value, read.value.debtRepayment?.linkedDebts.orEmpty()
                        .associate { it.debtPublicId to it.counterpartyLabel.orEmpty() }, kind, read.value.debtRepayment?.targetDate)
                    draft?.let(store::write)
                    showDraft()
                }
            }, onFailure = ::readFailed)
            if (generation != ticket) return@launch
            choices?.fold(onSuccess = { read ->
                _state.update { it.copy(candidates = read.value.debts, fromCache = it.fromCache || read.fromCache) }
            }, onFailure = ::readFailed)
            _state.update { it.copy(isLoading = false) }
        }
    }

    private fun matches(bound: LogicalSessionBinding, id: String): Boolean =
        binding == bound && edits.currentAccess()?.binding == bound && state.value.publicId == id

    private fun readFailed(error: Throwable) {
        if (!error.isReadAccessDenied() && (error as? com.ticketbox.data.repository.RepositoryException)?.httpStatusCode != 404) {
            _state.update { it.copy(error = error.toUiText(R.string.debt_goal_create_load_failed)) }
            return
        }
        generation++
        draft?.takeUnless { it.changed }?.let { store.remove(it); draft = null }
        _state.update { it.copy(goal = null, candidates = emptyList(), canModify = false, isLoading = false,
            fetchedAt = null, fromCache = false, hasDraft = draft != null,
            selectedLabels = draft?.selectedLabels.orEmpty(), targetDate = draft?.targetDate, goalName = draft?.original?.name.orEmpty(),
            error = error.toUiText(R.string.debt_goal_create_load_failed)) }
    }

    fun toggle(id: String) {
        val original = draft ?: return
        if (!state.value.editable) return
        val next = original.selectedLabels.toMutableMap()
        if (next.containsKey(id)) next.remove(id)
        else state.value.candidates.firstOrNull { it.publicId == id }?.let { next[id] = it.counterpartyLabel.orEmpty() }
        draft = original.copy(selectedLabels = next).also(store::write)
        showDraft()
    }

    fun setTargetDate(value: String?) {
        val original = draft ?: return
        if (kind != DebtGoalEditKind.TargetDate || !state.value.editable) return
        draft = original.copy(targetDate = value).also(store::write)
        showDraft()
    }

    fun discard() {
        if (state.value.isSaving) return
        draft?.let(store::remove)
        draft = null
        _state.update { it.copy(hasDraft = false, selectedLabels = emptyMap(), targetDate = null) }
    }

    private fun showDraft() {
        draft?.let { original -> _state.update { it.copy(goalName = original.original.name,
            selectedLabels = original.selectedLabels, targetDate = original.targetDate, hasDraft = true, error = null) } }
    }

    fun save() {
        val original = draft ?: return
        if (!state.value.canSave || !matches(original.binding, original.original.publicId)) return
        _state.update { it.copy(isSaving = true, error = null) }
        viewModelScope.launch {
            val result = edits.save(original.binding, original.original, original.input())
            if (result.isSuccess) store.remove(original)
            if (!matches(original.binding, original.original.publicId)) return@launch
            if (result.isSuccess && draft == original) draft = null
            _state.update { it.copy(isSaving = false, hasDraft = draft != null,
                error = result.exceptionOrNull()?.toUiText(R.string.debt_goal_update_failed)) }
        }
    }

    fun recover(original: PendingGoalEdit, drop: Boolean) {
        val bound = binding ?: return
        val id = state.value.publicId
        if (state.value.isSaving || state.value.pending?.row != original.row) return
        _state.update { it.copy(isSaving = true) }
        viewModelScope.launch {
            if (drop && original.canReviewDebtEdit) {
                reviewSelection(bound, original)
                return@launch
            }
            val result = edits.recover(bound, original, drop)
            if (!matches(bound, id)) return@launch
            _state.update { it.copy(isSaving = false, error = result.exceptionOrNull()?.toUiText(R.string.debt_goal_update_failed)) }
            if (drop && result.isSuccess) refresh()
        }
    }

    /** Reviewing a refused original creates editable input only; saving remains an explicit action. */
    private suspend fun reviewSelection(bound: LogicalSessionBinding, original: PendingGoalEdit) {
        val id = original.row.targetId.removePrefix("goal:")
        val latest = reports.goal(id, expectedBinding = bound).getOrNull()
        if (!matches(bound, id)) return
        if (latest == null || latest.fromCache || latest.value.isArchived || !latest.value.supports(kind)) {
            _state.update { it.copy(isSaving = false, error = UiText.res(R.string.debt_goal_links_review_unavailable)) }
            return
        }
        val result = edits.recover(bound, original, drop = true)
        if (!matches(bound, id)) return
        _state.update { it.copy(isSaving = false, error = result.exceptionOrNull()?.toUiText(R.string.debt_goal_update_failed)) }
        if (result.isFailure) return
        val input = requireNotNull(original.debtEdit)
        draft = DebtGoalEditDraft(bound, latest.value, input.selectedLabels, kind, input.dateRequest?.targetDate).also(store::write)
        _state.update { it.copy(goal = latest.value, pending = null, fetchedAt = latest.fetchedAt, fromCache = false) }
        showDraft()
    }
}

fun debtGoalEditViewModelFactory(reports: ReportsActions, edits: GoalEditActions,
    debts: DebtActions, kind: DebtGoalEditKind = DebtGoalEditKind.Links): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T =
        requireNotNull(modelClass.cast(DebtGoalEditViewModel(reports, edits, debts, extras.createSavedStateHandle(), kind)))
}

private fun Goal.supports(kind: DebtGoalEditKind): Boolean = isDebtRepayment &&
    (kind == DebtGoalEditKind.Links || debtRepayment?.composition == com.ticketbox.domain.model.DebtGoalComposition.External)
