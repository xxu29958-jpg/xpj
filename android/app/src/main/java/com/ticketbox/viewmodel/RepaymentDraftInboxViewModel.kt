package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.RepaymentDraftActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §杠杆③ (slice 3a) NLS 还款捕获复核箱 —— 列 pending 还款草稿 → 选一笔 open 的外部/手动欠款
 * confirm（记一笔 Repayment）或 dismiss（忽略）。
 *
 * 同时拉两份服务端数据：pending 还款草稿（[RepaymentDraftActions.listPendingDrafts]）与可选的目标欠款
 * （[DebtActions.listDebts] 过滤出 open + 外部手动——只有这类能直接记还款，镜像后端
 * `guard_direct_fact_writable`，否则 confirm 会 409）。两者都按账本作用域，overlay VM 跨账本存活，故
 * [reload] 进入时先清旧账本残留再拉（账本隔离，与 [DebtListViewModel] 同构）。confirm 用所选欠款的
 * row_version 作 §2.1 OCC 令牌。
 */
data class RepaymentDraftInboxUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val drafts: List<RepaymentDraft> = emptyList(),
    val targetDebts: List<Debt> = emptyList(),
    /**
     * §杠杆③ 3b：每条草稿的服务端建议欠款（draft.publicId → 已解析的 [Debt]），仅含「服务端 suggested_debt_public_id
     * 命中本地 [targetDebts] 且按本地剩余金额仍可还得起」的项。UI 据此预选/高亮，并允许一键「确认还到这笔」。
     */
    val suggestedDebtByDraftId: Map<String, Debt> = emptyMap(),
    val error: UiText? = null,
    val pendingActionDraftId: String? = null,
    val flashMessage: UiText? = null,
)

class RepaymentDraftInboxViewModel(
    private val drafts: RepaymentDraftActions,
    private val debts: DebtActions,
) : ViewModel() {

    private val _state = MutableStateFlow(RepaymentDraftInboxUiState(canModify = drafts.canModifyLedger()))
    val state: StateFlow<RepaymentDraftInboxUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    /** 进入 overlay 时调用：先清上一账本残留再拉，避免在新账本下短暂看到旧账本的草稿（账本隔离）。 */
    fun reload() {
        _state.update {
            it.copy(
                drafts = emptyList(),
                targetDebts = emptyList(),
                suggestedDebtByDraftId = emptyMap(),
                error = null,
                canModify = drafts.canModifyLedger(),
            )
        }
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val draftResult = drafts.listPendingDrafts()
            val repayable = debts.listDebts().getOrNull()?.filter(::isRepayableDebt)
            _state.update { current ->
                draftResult.fold(
                    onSuccess = { pending ->
                        current.copy(
                            isLoading = false,
                            canModify = drafts.canModifyLedger(),
                            drafts = pending,
                            // debt 拉取失败(repayable==null)时**清空**候选——绝不保留陈旧的 row_version,否则
                            // 下次对同一债 confirm 会用陈旧 OCC token 触发确定性 409;并报错让用户下拉刷新,
                            // 也避免空候选被误读成「没有欠款」（拉取成功但无可还款债时 repayable 是空列表、不报错）。
                            targetDebts = repayable ?: emptyList(),
                            // 用本地拉到的欠款解析服务端建议（拉取失败 → 空建议，与清空候选一致）。
                            suggestedDebtByDraftId = resolveSuggestions(pending, repayable ?: emptyList()),
                            error = if (repayable == null) {
                                UiText.res(R.string.repayment_draft_debts_load_failed)
                            } else {
                                null
                            },
                        )
                    },
                    onFailure = { err ->
                        current.copy(isLoading = false, error = err.toUiText(R.string.repayment_draft_load_failed))
                    },
                )
            }
        }
    }

    fun confirm(draftPublicId: String, debt: Debt) {
        if (_state.value.pendingActionDraftId != null) return
        _state.update { it.copy(pendingActionDraftId = draftPublicId, error = null) }
        viewModelScope.launch {
            val result = drafts.confirmDraft(
                draftPublicId = draftPublicId,
                targetDebtPublicId = debt.publicId,
                expectedRowVersion = debt.rowVersion,
            )
            finishAction(result, R.string.repayment_draft_confirm_done, R.string.repayment_draft_confirm_failed)
        }
    }

    fun dismiss(draftPublicId: String) {
        if (_state.value.pendingActionDraftId != null) return
        _state.update { it.copy(pendingActionDraftId = draftPublicId, error = null) }
        viewModelScope.launch {
            val result = drafts.dismissDraft(draftPublicId)
            finishAction(result, R.string.repayment_draft_dismiss_done, R.string.repayment_draft_dismiss_failed)
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    private fun finishAction(result: Result<RepaymentDraft>, successRes: Int, failureRes: Int) {
        result.fold(
            onSuccess = {
                _state.update {
                    it.copy(pendingActionDraftId = null, flashMessage = UiText.res(successRes))
                }
                refresh()
            },
            onFailure = { err ->
                _state.update {
                    it.copy(pendingActionDraftId = null, error = err.toUiText(failureRes))
                }
            },
        )
    }

    /** 可作还款对象的欠款：open + 外部手动（镜像后端 `guard_direct_fact_writable`；成员/拆账债走提案流不可直记）。 */
    private fun isRepayableDebt(debt: Debt): Boolean = debt.isOpen && debt.isDirectWritable
}

/**
 * §杠杆③ 3b：把每条草稿的服务端 [RepaymentDraft.suggestedDebtPublicId] 解析成本地 [targetDebts] 里的 [Debt]。
 *
 * 服务端已只建议 open + 外部手动 + 可还得起（remaining≥amount）的欠款，这里再按**本地拉到的剩余金额**复核一次
 * 可行性：两次拉取（草稿列表 / 欠款列表）之间若有一笔还款把剩余压到草稿金额之下，那条建议会被丢弃，而不是显示出来
 * 再在 confirm 时 422。命中的欠款其 row_version 取自本地欠款列表（与手动选债同源，作 §2.1 OCC 令牌）。
 */
private fun resolveSuggestions(
    drafts: List<RepaymentDraft>,
    repayable: List<Debt>,
): Map<String, Debt> {
    if (repayable.isEmpty()) return emptyMap()
    val byPublicId = repayable.associateBy { it.publicId }
    return drafts.mapNotNull { draft ->
        val debt = draft.suggestedDebtPublicId?.let(byPublicId::get) ?: return@mapNotNull null
        if (debt.remainingAmountCents < draft.amountCents) return@mapNotNull null
        draft.publicId to debt
    }.toMap()
}
