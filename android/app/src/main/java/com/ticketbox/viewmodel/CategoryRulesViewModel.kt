package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.CategoryRuleSaveOutcome
import com.ticketbox.data.repository.DeleteOutcome
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CategoryRulesUiState(
    val categoryRules: List<CategoryRule> = emptyList(),
    val ruleApplications: List<RuleApplicationBatch> = emptyList(),
    val confirmedRulesPreview: RuleApplyConfirmedResult? = null,
    val busy: Boolean = false,
    val message: UiText? = null,
    // ADR-0038 undo: the just-(soft-)deleted rule, surfaced as a 5s 撤销
    // affordance. Null when there is nothing to undo.
    val undoableRule: CategoryRule? = null,
)

class CategoryRulesViewModel(
    private val ruleRepository: RuleRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(CategoryRulesUiState())
    val uiState: StateFlow<CategoryRulesUiState> = _uiState.asStateFlow()

    init {
        loadCategoryRules()
        loadRuleApplications()
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    fun loadCategoryRules() {
        viewModelScope.launch {
            ruleRepository.categoryRules()
                .onSuccess { rules -> _uiState.update { it.copy(categoryRules = rules) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.category_rules_load_failed)) } }
        }
    }

    fun loadRuleApplications() {
        viewModelScope.launch {
            ruleRepository.ruleApplications()
                .onSuccess { applications -> _uiState.update { it.copy(ruleApplications = applications) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.category_rules_applications_load_failed)) } }
        }
    }

    fun createCategoryRule(keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.createCategoryRule(keyword = keyword, category = category, priority = priority)
                .onSuccess { rule ->
                    _uiState.update {
                        it.copy(
                            categoryRules = (it.categoryRules + rule).sortedWith(
                                compareByDescending<CategoryRule> { item -> item.enabled }
                                    .thenByDescending { item -> item.priority }
                                    .thenBy { item -> item.keyword },
                            ),
                            busy = false,
                            message = UiText.res(R.string.category_rules_added),
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.category_rules_add_failed)) } }
        }
    }

    fun updateCategoryRule(rule: CategoryRule, keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            // ADR-0038 PR-2g.4: offline-aware save. Network failure
            // → enqueue + optimistic projection; user sees
            // "已离线保存" message and continues. Other errors
            // (4xx / 409 / 5xx) still surface as failure.
            ruleRepository.updateCategoryRuleAllowingOffline(
                baseline = rule,
                keyword = keyword.trim(),
                category = category.trim(),
                priority = priority,
            )
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is CategoryRuleSaveOutcome.Synced -> UiText.res(R.string.category_rules_updated)
                        is CategoryRuleSaveOutcome.Queued -> UiText.res(R.string.category_rules_saved_offline)
                    }
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == outcome.rule.id) outcome.rule else it },
                            busy = false,
                            message = message,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.category_rules_save_failed)) } }
        }
    }

    fun toggleCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.4: offline-aware toggle. See
            // updateCategoryRule above for the rationale.
            ruleRepository.updateCategoryRuleAllowingOffline(
                baseline = rule,
                enabled = !rule.enabled,
            )
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is CategoryRuleSaveOutcome.Synced ->
                            if (outcome.rule.enabled) {
                                UiText.res(R.string.category_rules_enabled)
                            } else {
                                UiText.res(R.string.category_rules_disabled)
                            }
                        is CategoryRuleSaveOutcome.Queued ->
                            if (outcome.rule.enabled) {
                                UiText.res(R.string.category_rules_enabled_offline)
                            } else {
                                UiText.res(R.string.category_rules_disabled_offline)
                            }
                    }
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == outcome.rule.id) outcome.rule else it },
                            message = message,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.category_rules_update_failed)) } }
        }
    }

    fun deleteCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            // ADR-0038 PR-2g.5: offline-aware DELETE. IOException →
            // enqueue + DeleteOutcome.Queued; row removed from UI
            // either way (synced vs queued only changes the message).
            ruleRepository.deleteCategoryRuleAllowingOffline(rule)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        DeleteOutcome.Synced -> UiText.res(R.string.category_rules_deleted)
                        DeleteOutcome.Queued -> UiText.res(R.string.category_rules_deleted_offline)
                    }
                    // ADR-0038 undo: offer 撤销 only after a synced delete (a
                    // queued offline delete has nothing to restore via the API yet).
                    val undoable = if (outcome == DeleteOutcome.Synced) rule else null
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.filterNot { it.id == rule.id },
                            message = message,
                            undoableRule = undoable,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.category_rules_delete_failed)) } }
        }
    }

    fun undoDelete() {
        val target = _uiState.value.undoableRule ?: return
        viewModelScope.launch {
            ruleRepository.undoDeleteRule(target.id)
                .onSuccess { restored ->
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = (state.categoryRules + restored).sortedWith(
                                compareByDescending<CategoryRule> { item -> item.enabled }
                                    .thenByDescending { item -> item.priority }
                                    .thenBy { item -> item.keyword },
                            ),
                            message = UiText.res(R.string.category_rules_restored),
                            undoableRule = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.category_rules_restore_failed),
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
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.previewApplyConfirmedRules()
                .onSuccess { preview ->
                    _uiState.update {
                        it.copy(
                            confirmedRulesPreview = preview,
                            busy = false,
                            message = if (preview.changedCount == 0) {
                                UiText.res(R.string.category_rules_apply_preview_none)
                            } else {
                                UiText.res(R.string.category_rules_apply_preview_found, preview.changedCount)
                            },
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.category_rules_apply_preview_failed)) } }
        }
    }

    fun confirmApplyConfirmedRules() {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            val previewToken = _uiState.value.confirmedRulesPreview?.previewToken
            if (previewToken.isNullOrBlank()) {
                _uiState.update { it.copy(busy = false, message = UiText.res(R.string.category_rules_apply_need_preview)) }
                return@launch
            }
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.confirmApplyConfirmedRules(previewToken)
                .onSuccess { result ->
                    ruleRepository.ruleApplications()
                        .onSuccess { applications ->
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    _uiState.update {
                        it.copy(
                            confirmedRulesPreview = result,
                            busy = false,
                            message = if (result.changedCount == 0) {
                                UiText.res(R.string.category_rules_apply_none_changed)
                            } else {
                                UiText.res(R.string.category_rules_apply_changed, result.changedCount)
                            },
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.category_rules_apply_failed)) } }
        }
    }

    fun rollbackRuleApplication(application: RuleApplicationBatch) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.rollbackRuleApplication(application.publicId)
                .onSuccess { rollback ->
                    ruleRepository.ruleApplications()
                        .onSuccess { applications ->
                            _uiState.update { it.copy(ruleApplications = applications) }
                        }
                    _uiState.update {
                        it.copy(
                            busy = false,
                            message = UiText.res(R.string.category_rules_rollback_done, rollback.changed, rollback.skipped),
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.toUiText(R.string.category_rules_rollback_failed)) } }
        }
    }
}
