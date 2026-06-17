package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §2 (slice 8) 欠款列表 — Android 生活流：卡片列 → 页头 CTA → 底部抽屉新建外部欠款。
 *
 * UI 形态镜像 [IncomePlanViewModel]（list + draft + submit），ViewModel 持草稿+校验态让底部
 * 抽屉保持纯渲染。债务读取按账本作用域，overlay VM 缓存且跨账本存活，故 [reload] 在每次进入时
 * 先清上一账本的欠款再拉（账本隔离，与 DebtGoalViewModel.refresh(clearStale = true) 同构）。
 */
data class DebtListUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val debts: List<Debt> = emptyList(),
    val error: UiText? = null,
    val addDraft: DebtDraftUi = DebtDraftUi(),
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
)

data class DebtDraftUi(
    val direction: String = DebtDirections.I_OWE,
    val counterpartyLabel: String = "",
    val amountYuanInput: String = "",
    val validationError: UiText? = null,
) {
    val isValid: Boolean
        get() = counterpartyLabel.trim().isNotEmpty() && parsedAmountCents() != null

    // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额）；本金须 > 0（符号保持，分空间判等价）。
    fun parsedAmountCents(): Long? = parseAmountCents(amountYuanInput)?.takeIf { it > 0 }
}

class DebtListViewModel(
    private val repository: DebtActions,
) : ViewModel() {

    private val _state = MutableStateFlow(DebtListUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<DebtListUiState> = _state.asStateFlow()

    // Monotonic load token (mirrors DebtGoalViewModel): a refresh applies its result only if it is
    // still the latest. Overlapping refreshes — init + reload on overlay (re-)entry + the refresh
    // after a create — each bump it, so a slow earlier list fetch can't overwrite newer data (the
    // just-created debt, or a switched ledger's debts). Every bump is a refresh, so a superseded
    // load is always replaced by a newer refresh that owns the loading flag — it just drops.
    private var loadGeneration = 0L

    init {
        refresh()
    }

    /**
     * 进入 overlay 时调用：先清掉上一账本残留的欠款再拉，避免在新账本下短暂看到旧账本的欠款
     * （账本隔离；overlay VM 跨账本切换存活，见 DebtGoalViewModel.refresh(clearStale = true)）。
     */
    fun reload() {
        _state.update {
            it.copy(debts = emptyList(), error = null, canModify = repository.canModifyLedger())
        }
        refresh()
    }

    fun refresh() {
        val gen = ++loadGeneration
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listDebts()
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration) return@launch
            result.fold(
                onSuccess = { debts ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            debts = debts,
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.debt_list_load_failed))
                    }
                },
            )
        }
    }

    fun updateDraftDirection(value: String) {
        _state.update { it.copy(addDraft = it.addDraft.copy(direction = value, validationError = null)) }
    }

    fun updateDraftCounterparty(value: String) {
        _state.update { it.copy(addDraft = it.addDraft.copy(counterpartyLabel = value, validationError = null)) }
    }

    fun updateDraftAmount(value: String) {
        _state.update { it.copy(addDraft = it.addDraft.copy(amountYuanInput = value, validationError = null)) }
    }

    fun resetDraft() {
        _state.update { it.copy(addDraft = DebtDraftUi(), isSubmitting = false) }
    }

    fun submitDraft() {
        val draft = _state.value.addDraft
        val amount = draft.parsedAmountCents()
        val label = draft.counterpartyLabel.trim()
        if (label.isEmpty() || amount == null) {
            _state.update {
                it.copy(
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.debt_create_validation_error),
                    ),
                )
            }
            return
        }
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.createDebt(
                DebtDraft(
                    direction = draft.direction,
                    counterpartyLabel = label,
                    principalAmountCents = amount,
                ),
            )
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = DebtDraftUi(),
                            flashMessage = UiText.res(R.string.debt_create_added),
                        )
                    }
                    refresh()
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = it.addDraft.copy(
                                validationError = err.toUiText(R.string.debt_create_failed),
                            ),
                        )
                    }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }
}
