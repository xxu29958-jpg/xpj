package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingCategoryRuleSubmission
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.repository.asRequest
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CategoryRulesUiState(
    val binding: LogicalSessionBinding? = null,
    val canModify: Boolean = false,
    val pendingSubmissions: List<PendingCategoryRuleSubmission> = emptyList(),
    val selectedSubmissionId: Long? = null,
    val submittedRevision: Int = 0,
    val categoryRules: List<CategoryRule> = emptyList(),
    val ruleApplications: List<RuleApplicationBatch> = emptyList(),
    val confirmedRulesPreview: RuleApplyConfirmedResult? = null,
    val categoryRulesLoading: Boolean = false,
    val ruleApplicationsLoading: Boolean = false,
    val busy: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    // ADR-0038 undo: the just-(soft-)deleted rule, surfaced as a 5s 撤销
    // affordance. Null when there is nothing to undo.
    val undoableRule: CategoryRule? = null,
    // Rule CRUD — only the vocabulary dictionaries need a refresh.
    val changedRevision: Int = 0,
    // Apply/rollback with actual changes — these rewrite the category on
    // confirmed expense rows, so the ledger must re-sync its rows too.
    val applicationRevision: Int = 0,
)

private fun CategoryRulesUiState.afterRuleApplication(result: RuleApplyConfirmedResult): CategoryRulesUiState = copy(
    confirmedRulesPreview = result,
    busy = false,
    message = when {
        result.unavailableCount > 0 -> UiText.res(R.string.category_rule_apply_currency_unavailable,
            result.unavailableCount, result.missingCurrencyCodes.joinToString("、"))
        result.changedCount == 0 -> UiText.res(R.string.category_rules_apply_none_changed)
        else -> UiText.res(R.string.category_rules_apply_changed, result.changedCount)
    },
    messageTone = if (result.changedCount == 0) MessageTone.Info else MessageTone.Success,
    applicationRevision = if (result.changedCount > 0) applicationRevision + 1 else applicationRevision,
)

class CategoryRulesViewModel(
    private val ruleRepository: RuleRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(CategoryRulesUiState())
    val uiState: StateFlow<CategoryRulesUiState> = _uiState.asStateFlow()

    private var observation: Job? = null
    private var deliveredIds: Set<Long> = emptySet()
    private var requestedSubmissionId: Long? = null

    init {
        viewModelScope.launch {
            ruleRepository.observeAccess().collect { access ->
                if (_uiState.value.binding != access?.binding) {
                    observation?.cancel()
                    deliveredIds = emptySet()
                    val selected = requestedSubmissionId.takeIf { _uiState.value.binding == null }
                    requestedSubmissionId = null
                    _uiState.value = CategoryRulesUiState(binding = access?.binding, canModify = access?.canModify == true,
                        selectedSubmissionId = selected)
                    if (access != null) {
                        loadCategoryRules(clearMessage = false)
                        loadRuleApplications(clearMessage = false)
                        observation = launch {
                            ruleRepository.observeSubmissions(access.binding).collect { rows ->
                                if (ruleRepository.currentAccess()?.binding == access.binding) acceptSubmissions(rows)
                            }
                        }
                    }
                } else _uiState.update { it.copy(canModify = access?.canModify == true) }
            }
        }
    }

    fun openSubmission(originalSubmissionId: Long) {
        if (_uiState.value.binding == null) requestedSubmissionId = originalSubmissionId
        _uiState.update { it.copy(selectedSubmissionId = originalSubmissionId) }
    }

    private fun acceptSubmissions(rows: List<PendingCategoryRuleSubmission>) {
        val newlyDelivered = rows.filter { it.isDone && it.supported && it.row.id !in deliveredIds }
        deliveredIds = rows.filter { it.isDone && it.supported }.map { it.row.id }.toSet()
        _uiState.update { state ->
            state.copy(pendingSubmissions = rows,
                changedRevision = state.changedRevision + newlyDelivered.size,
                undoableRule = newlyDelivered.lastOrNull { it.row.type == PendingMutationType.DeleteCategoryRule }
                    ?.ruleId?.let { id -> state.categoryRules.find { it.id == id } } ?: state.undoableRule)
        }
        if (newlyDelivered.isNotEmpty()) loadCategoryRules(clearMessage = false)
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    fun loadCategoryRules(clearMessage: Boolean = true) {
        val origin = _uiState.value.binding ?: return
        viewModelScope.launch {
            _uiState.update {
                if (clearMessage) {
                    it.copy(
                        categoryRulesLoading = true,
                        message = null,
                        messageTone = MessageTone.Neutral,
                    )
                } else {
                    it.copy(categoryRulesLoading = true)
                }
            }
            ruleRepository.categoryRules()
                .onSuccess { rules ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    _uiState.update { it.copy(categoryRulesLoading = false, categoryRules = rules) }
                    acceptSubmissions(_uiState.value.pendingSubmissions)
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            categoryRulesLoading = false,
                            message = error.toUiText(R.string.category_rules_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun loadRuleApplications(clearMessage: Boolean = true) {
        val origin = _uiState.value.binding ?: return
        viewModelScope.launch {
            _uiState.update {
                if (clearMessage) {
                    it.copy(
                        ruleApplicationsLoading = true,
                        message = null,
                        messageTone = MessageTone.Neutral,
                    )
                } else {
                    it.copy(ruleApplicationsLoading = true)
                }
            }
            ruleRepository.ruleApplications()
                .onSuccess history@ { applications ->
                            if (ruleRepository.currentAccess()?.binding != origin) return@history
                    _uiState.update {
                        it.copy(ruleApplicationsLoading = false, ruleApplications = applications)
                    }
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            ruleApplicationsLoading = false,
                            message = error.toUiText(R.string.category_rules_applications_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun createCategoryRule(request: CategoryRuleRequest) = submitRule { origin ->
        ruleRepository.createCategoryRule(origin, request)
    }

    fun updateCategoryRule(rule: CategoryRule, request: CategoryRuleRequest) = submitRule { origin ->
        ruleRepository.updateCategoryRule(origin, rule, request)
    }

    fun toggleCategoryRule(rule: CategoryRule) = updateCategoryRule(rule, rule.asRequest().copy(enabled = !rule.enabled))

    fun deleteCategoryRule(rule: CategoryRule) = submitRule { origin -> ruleRepository.deleteCategoryRule(origin, rule) }

    private fun submitRule(command: suspend (LogicalSessionBinding) -> Result<Long>) {
        val origin = _uiState.value.binding ?: return
        if (_uiState.value.busy || ruleRepository.currentAccess()?.binding != origin || !canModifyCurrentLedger()) return
        _uiState.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            val result = command(origin)
            if (_uiState.value.binding != origin || ruleRepository.currentAccess()?.binding != origin) return@launch
            _uiState.update { it.copy(busy = false,
                submittedRevision = it.submittedRevision + if (result.isSuccess) 1 else 0,
                selectedSubmissionId = result.getOrNull() ?: it.selectedSubmissionId,
                message = result.exceptionOrNull()?.toUiText(R.string.category_rules_save_failed)
                    ?: UiText.res(R.string.category_rule_submission_saved),
                messageTone = if (result.isSuccess) MessageTone.Info else MessageTone.Danger) }
        }
    }

    fun recoverSubmission(pending: PendingCategoryRuleSubmission, drop: Boolean) {
        val origin = _uiState.value.binding ?: return
        if (_uiState.value.busy) return
        _uiState.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            val result = ruleRepository.recoverSubmission(origin, pending, drop)
            if (_uiState.value.binding != origin || ruleRepository.currentAccess()?.binding != origin) return@launch
            _uiState.update { it.copy(busy = false,
                message = result.exceptionOrNull()?.toUiText(R.string.category_rules_save_failed), messageTone = MessageTone.Danger) }
        }
    }

    fun undoDelete() {
        val origin = _uiState.value.binding ?: return
        val target = _uiState.value.undoableRule ?: return
        viewModelScope.launch {
            if (ruleRepository.currentAccess()?.binding != origin) return@launch
            ruleRepository.undoDeleteRule(target.id)
                .onSuccess { restored ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = (state.categoryRules + restored).sortedWith(
                                compareByDescending<CategoryRule> { item -> item.enabled }
                                    .thenByDescending { item -> item.priority }
                                    .thenBy { item -> item.keyword },
                            ),
                            message = UiText.res(R.string.category_rules_restored),
                            messageTone = MessageTone.Success,
                            undoableRule = null,
                            changedRevision = state.changedRevision + 1,
                        )
                    }
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.category_rules_restore_failed),
                            messageTone = MessageTone.Danger,
                            undoableRule = null,
                        )
                    }
                }
        }
    }

    /** Clear the undo affordance once its 5s window lapses (or after use). */
    fun dismissUndo() {
        _uiState.update { it.copy(undoableRule = null) }
    }

    fun previewApplyConfirmedRules() {
        val origin = _uiState.value.binding ?: return
        viewModelScope.launch {
            if (ruleRepository.currentAccess()?.binding != origin) return@launch
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            ruleRepository.previewApplyConfirmedRules()
                .onSuccess { preview ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    _uiState.update {
                        it.copy(
                            confirmedRulesPreview = preview,
                            busy = false,
                            message = if (preview.unavailableCount > 0) {
                                UiText.res(R.string.category_rule_apply_currency_unavailable, preview.unavailableCount,
                                    preview.missingCurrencyCodes.joinToString("、"))
                            } else if (preview.changedCount == 0) {
                                UiText.res(R.string.category_rules_apply_preview_none)
                            } else {
                                UiText.res(R.string.category_rules_apply_preview_found, preview.changedCount)
                            },
                            messageTone = MessageTone.Info,
                        )
                    }
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.toUiText(R.string.category_rules_apply_preview_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun confirmApplyConfirmedRules() {
        val origin = _uiState.value.binding ?: return
        if (!canModifyCurrentLedger()) {
            _uiState.update {
                it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            if (ruleRepository.currentAccess()?.binding != origin) return@launch
            val previewToken = _uiState.value.confirmedRulesPreview?.previewToken
            if (previewToken.isNullOrBlank()) {
                _uiState.update {
                    it.copy(
                        busy = false,
                        message = UiText.res(R.string.category_rules_apply_need_preview),
                        messageTone = MessageTone.Danger,
                    )
                }
                return@launch
            }
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            ruleRepository.confirmApplyConfirmedRules(previewToken)
                .onSuccess { result ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    ruleRepository.ruleApplications()
                        .onSuccess history@ { applications ->
                            if (ruleRepository.currentAccess()?.binding != origin) return@history
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    _uiState.update { it.afterRuleApplication(result) }
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.toUiText(R.string.category_rules_apply_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun rollbackRuleApplication(application: RuleApplicationBatch) {
        val origin = _uiState.value.binding ?: return
        if (!canModifyCurrentLedger()) {
            _uiState.update {
                it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            if (ruleRepository.currentAccess()?.binding != origin) return@launch
            _uiState.update { it.copy(busy = true, message = null, messageTone = MessageTone.Neutral) }
            ruleRepository.rollbackRuleApplication(application.publicId)
                .onSuccess { rollback ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    ruleRepository.ruleApplications()
                        .onSuccess history@ { applications ->
                            if (ruleRepository.currentAccess()?.binding != origin) return@history
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    if (ruleRepository.currentAccess()?.binding != origin) return@onSuccess
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = UiText.res(R.string.category_rules_rollback_done, rollback.changed, rollback.skipped),
                            messageTone = MessageTone.Success,
                            applicationRevision = if (rollback.changed > 0) {
                                it.applicationRevision + 1
                            } else {
                                it.applicationRevision
                            },
                        )
                    }
                }
                .onFailure { error ->
                    if (ruleRepository.currentAccess()?.binding != origin) return@onFailure
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = error.toUiText(R.string.category_rules_rollback_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }
}
