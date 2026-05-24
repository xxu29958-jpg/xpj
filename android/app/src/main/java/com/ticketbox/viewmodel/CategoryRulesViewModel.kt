package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
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
    val message: String? = null,
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
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "分类规则暂时打不开。") } }
        }
    }

    fun loadRuleApplications() {
        viewModelScope.launch {
            ruleRepository.ruleApplications()
                .onSuccess { applications -> _uiState.update { it.copy(ruleApplications = applications) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "规则应用记录暂时打不开。") } }
        }
    }

    fun createCategoryRule(keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
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
                            message = "分类规则已添加",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有添加成功，请稍后再试。") } }
        }
    }

    fun updateCategoryRule(rule: CategoryRule, keyword: String, category: String, priority: Int) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            ruleRepository.updateCategoryRule(
                id = rule.id,
                keyword = keyword.trim(),
                category = category.trim(),
                priority = priority,
            )
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == updated.id) updated else it },
                            busy = false,
                            message = "分类规则已更新",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun toggleCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            ruleRepository.updateCategoryRule(rule.id, enabled = !rule.enabled)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.map { if (it.id == updated.id) updated else it },
                            message = if (updated.enabled) "分类规则已启用" else "分类规则已停用",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有更新成功，请稍后再试。") } }
        }
    }

    fun deleteCategoryRule(rule: CategoryRule) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            ruleRepository.deleteCategoryRule(rule.id)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(
                            categoryRules = state.categoryRules.filterNot { it.id == rule.id },
                            message = "分类规则已删除",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
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
                                "已确认账单暂无可更新分类。"
                            } else {
                                "找到 ${preview.changedCount} 笔可更新账单。"
                            },
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有完成预览，请稍后再试。") } }
        }
    }

    fun confirmApplyConfirmedRules() {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            val previewToken = _uiState.value.confirmedRulesPreview?.previewToken
            if (previewToken.isNullOrBlank()) {
                _uiState.update { it.copy(busy = false, message = "请先预览影响范围。") }
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
                            message = if (result.changedCount == 0) "没有账单需要更新。" else "已更新 ${result.changedCount} 笔账单分类。",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有应用成功，请稍后再试。") } }
        }
    }

    fun rollbackRuleApplication(application: RuleApplicationBatch) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
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
                            message = "已回退 ${rollback.changed} 笔分类，跳过 ${rollback.skipped} 笔。",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有回退成功，请稍后再试。") } }
        }
    }
}
