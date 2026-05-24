package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class MerchantAliasUiState(
    val merchantAliases: List<MerchantAlias> = emptyList(),
    val busy: Boolean = false,
    val message: String? = null,
)

class MerchantAliasViewModel(
    private val merchantRepository: MerchantRepository,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MerchantAliasUiState())
    val uiState: StateFlow<MerchantAliasUiState> = _uiState.asStateFlow()

    init {
        loadMerchantAliases()
    }

    private fun canModifyCurrentLedger(): Boolean {
        return ledgerRoleCanModify(repository.currentLedgerRole())
    }

    fun loadMerchantAliases() {
        viewModelScope.launch {
            merchantRepository.merchantAliases()
                .onSuccess { aliases -> _uiState.update { it.copy(merchantAliases = aliases.sortedMerchantAliases()) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "商家别名暂时打不开。") } }
        }
    }

    fun createMerchantAlias(canonicalMerchant: String, alias: String) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(busy = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busy = true, message = null) }
            merchantRepository.createMerchantAlias(canonicalMerchant = canonicalMerchant, alias = alias)
                .onSuccess { created ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = (state.merchantAliases + created).sortedMerchantAliases(),
                            busy = false,
                            message = "商家别名已添加",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(busy = false, message = error.message ?: "没有添加成功，请稍后再试。") } }
        }
    }

    fun toggleMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            merchantRepository.updateMerchantAlias(alias.publicId, enabled = !alias.enabled)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases
                                .map { if (it.publicId == updated.publicId) updated else it }
                                .sortedMerchantAliases(),
                            message = if (updated.enabled) "商家别名已启用" else "商家别名已停用",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有更新成功，请稍后再试。") } }
        }
    }

    fun deleteMerchantAlias(alias: MerchantAlias) {
        if (!canModifyCurrentLedger()) {
            _uiState.update { it.copy(message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            merchantRepository.deleteMerchantAlias(alias.publicId)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(
                            merchantAliases = state.merchantAliases.filterNot { it.publicId == alias.publicId },
                            message = "商家别名已删除",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
    }
}

private fun List<MerchantAlias>.sortedMerchantAliases(): List<MerchantAlias> =
    sortedWith(
        compareByDescending<MerchantAlias> { it.enabled }
            .thenBy { it.canonicalKey }
            .thenBy { it.aliasKey },
    )
