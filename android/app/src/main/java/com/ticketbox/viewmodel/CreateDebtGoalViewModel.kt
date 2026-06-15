package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §6 (slice 8b) 新建还债目标：名称 + 欠款多选选择器 → `POST /api/goals`
 * (goal_type=debt_repayment)。
 *
 * 复用 slice 8a 的 `GET /api/debts` 列表（[DebtActions]）作为多选选择器的数据源，复用
 * goal 仓库（[ReportsActions]）的 [ReportsActions.createDebtGoal] 提交。选择器只列**未结清**
 * 欠款：关联一笔已结清欠款会让目标在创建时即达成，关联一笔已作废欠款会立刻进入 §6/F13 复核
 * 死胡同——两者都不是「还债目标」该跟踪的对象，故创建侧收窄到 open 欠款，避免一上来就达成/卡死。
 */
data class CreateDebtGoalUiState(
    val isLoadingDebts: Boolean = false,
    val canModify: Boolean = true,
    /** 可关联的欠款（仅未结清）。 */
    val candidates: List<Debt> = emptyList(),
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
) {
    val canSubmit: Boolean
        get() = name.trim().isNotEmpty() && selectedDebtIds.isNotEmpty() && !isSubmitting
}

class CreateDebtGoalViewModel(
    private val reports: ReportsActions,
    private val debts: DebtActions,
) : ViewModel() {

    private val _state = MutableStateFlow(CreateDebtGoalUiState(canModify = reports.canModifyLedger()))
    val state: StateFlow<CreateDebtGoalUiState> = _state.asStateFlow()

    /**
     * 重新加载未结清欠款候选并重置草稿。每次进入新建页时调用：VM 跨账本切换存活（与
     * DebtGoalRoute 同形），故每次清空 + 重新拉取以保持账本隔离并拉到刚记的新欠款。
     */
    fun reload() {
        _state.value = CreateDebtGoalUiState(
            isLoadingDebts = true,
            canModify = reports.canModifyLedger(),
        )
        viewModelScope.launch {
            debts.listDebts().fold(
                onSuccess = { all ->
                    _state.update {
                        it.copy(
                            isLoadingDebts = false,
                            canModify = reports.canModifyLedger(),
                            candidates = all.filter { debt -> debt.isOpen },
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
        _state.update { it.copy(name = value, formError = null) }
    }

    fun toggleDebt(publicId: String) {
        _state.update {
            val next = it.selectedDebtIds.toMutableSet()
            if (!next.add(publicId)) next.remove(publicId)
            it.copy(selectedDebtIds = next, formError = null)
        }
    }

    fun submit() {
        val current = _state.value
        val cleanName = current.name.trim()
        // Build the id list from candidate order ∩ selection — a stable, candidate-ordered
        // request (NOT selection-insertion order; submitSuccess...InCandidateOrder pins this).
        // selectedDebtIds is always a subset of candidates (toggleDebt only adds candidate ids;
        // reload resets both together), so this never silently drops a live selection.
        val ids = current.candidates.map { it.publicId }.filter { it in current.selectedDebtIds }
        if (cleanName.isEmpty() || ids.isEmpty()) {
            _state.update { it.copy(formError = UiText.res(R.string.debt_goal_create_validation)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, formError = null) }
        viewModelScope.launch {
            reports.createDebtGoal(cleanName, ids).fold(
                onSuccess = { goal ->
                    _state.update { it.copy(isSubmitting = false, createdPublicId = goal.publicId) }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isSubmitting = false, formError = err.toUiText(R.string.debt_goal_create_failed))
                    }
                },
            )
        }
    }

    /** Clear the one-shot create signal once the screen has acted on it. */
    fun consumeCreated() {
        _state.update { it.copy(createdPublicId = null) }
    }
}
