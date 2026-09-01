package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatAmountInput
import java.time.LocalDate
import java.time.ZoneId
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Refund/Chargeback/Reversal 纵向片：退回与冲销的**状态与读取**（提交/撤销命令在
 * ExpenseFactViewModelOffsetsCommands.kt / ExpenseFactViewModelOffsetsVoid.kt，
 * detekt 函数数门下的同责拆分）。
 *
 * 事实源唯一：段内一切金额/状态渲染 [ExpenseFactBundle]（服务端 query owner
 * 组装）；客户端不重算金额、FX 或 remaining。`pendingOffsetIntent` 只表达本会话
 * 内刚保存的待提交 intent（持久表达归既有 Outbox surface），不冒充已生效事实。
 *
 * 两条共同冻结纪律：
 *  - command 不依赖 read model：已知 confirmed root + 写权限时 create 永远可打开，
 *    bundle 缺席只意味着不预填 remaining、sheet 明示「暂不可用，服务器核验」。
 *  - root 防倒灌：读路径用 [ExpenseFactViewModel.factBundleLoadGeneration] 只采纳
 *    最后一次读/命令之后发出的响应；采纳 root 再按 rowVersion 单调守卫，绝不让
 *    较旧响应回退 OCC token。
 */

/** 退款/拒付/冲销登记表单态（Reversal 无金额；remaining 只是服务端快照预填/提示）。 */
data class OffsetFormState(
    val open: Boolean = false,
    val kind: StreamOffsetKind = StreamOffsetKind.Refund,
    val amountText: String = "",
    val accountingDate: String = "",
    val reason: String = "",
    val amountError: UiText? = null,
    val dateError: UiText? = null,
    val submitError: UiText? = null,
    val conflictMessage: UiText? = null,
    /** direct 409 后的权威刷新在途/失败期间为 true：禁用提交，不用旧 root token 循环 409。 */
    val refreshingAfterConflict: Boolean = false,
    val saving: Boolean = false,
)

/** 撤销已生效退回/冲销的确认表单态。 */
data class VoidOffsetFormState(
    val open: Boolean = false,
    val target: ExpenseOffsetFact? = null,
    val reason: String = "",
    val submitError: UiText? = null,
    val conflictMessage: UiText? = null,
    /** 同 [OffsetFormState.refreshingAfterConflict]。 */
    val refreshingAfterConflict: Boolean = false,
    val saving: Boolean = false,
)

/**
 * 事实包 = 退回/冲销段的唯一事实源；失败是段内可重试错误，不抢页面、不动已知 root。
 * generation 必须在 launch 之前同步分配：invocation order 才是 authority order，
 * 未调度的旧读不得拿到比 command response 更大的 generation（共同冻结）。
 */
fun ExpenseFactViewModel.loadExpenseFactBundle() {
    val generation = ++factBundleLoadGeneration
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                factBundleLoadState = ExpenseDetailDataLoadState.Loading,
                factBundleMessage = null,
            )
        }
        repository.fetchExpenseFactBundle(expenseId)
            .onSuccess { bundle ->
                if (generation == factBundleLoadGeneration) adoptFactBundle(bundle)
            }
            .onFailure { error ->
                if (generation == factBundleLoadGeneration) {
                    _uiState.update {
                        it.copy(
                            factBundleLoadState = ExpenseDetailDataLoadState.Failed,
                            factBundleMessage = error.toUiText(R.string.expense_fact_offsets_failed),
                        )
                    }
                }
            }
    }
}

/** 命令响应携带的 bundle 是本 lineage 最新事实：先使一切在途读失效，再采纳。 */
internal fun ExpenseFactViewModel.applyFactBundle(bundle: ExpenseFactBundle) {
    factBundleLoadGeneration += 1
    adoptFactBundle(bundle)
}

/**
 * 原子采用（共同冻结）：FactBundle 是单一原子 publication —— 整包采用（含
 * root）或整包丢弃，绝不混装跨版本视图。旧包到达（root.rowVersion 回退）时
 * 保留当前 root + 当前 factBundle；首读即旧包才给可重试出口。
 */
private fun ExpenseFactViewModel.adoptFactBundle(bundle: ExpenseFactBundle) {
    _uiState.update {
        val current = it.expense
        val rootStale = current != null && current.id == bundle.root.id &&
            bundle.root.rowVersion < current.rowVersion
        when {
            rootStale && it.factBundle != null -> it
            rootStale -> it.copy(
                factBundleLoadState = ExpenseDetailDataLoadState.Failed,
                factBundleMessage = UiText.res(R.string.expense_fact_offsets_failed),
            )
            else -> it.copy(
                expense = bundle.root,
                expenseLoading = false,
                expenseLoadState = ExpenseDetailDataLoadState.Loaded,
                expenseStale = false,
                factBundle = bundle,
                factBundleLoadState = ExpenseDetailDataLoadState.Loaded,
                factBundleMessage = null,
                // 权威刷新完成：解除 conflict 后的提交禁用（banner 由 sheet 按状态收尾）。
                offsetForm = it.offsetForm.copy(refreshingAfterConflict = false),
                voidOffsetForm = it.voidOffsetForm.copy(refreshingAfterConflict = false),
            )
        }
    }
}

fun ExpenseFactViewModel.openOffsetSheet(kind: StreamOffsetKind) {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    // 与更正流同一口径（R13）：未知原币码 fail-closed，不在本端解析金额。
    val unsupported = unsupportedOriginalCurrencyCode()
    if (kind.isMoneyEvent && unsupported != null) {
        _uiState.update {
            it.copy(
                message = UiText.res(R.string.expense_offset_currency_unsupported, unsupported),
                messageTone = MessageTone.Danger,
            )
        }
        return
    }
    // command 不依赖 read model（Product Owner 裁决）：bundle 缺席只意味着不预填
    // remaining，sheet 内明示「可退余额暂不可用」，登记照常可提交。
    val summary = _uiState.value.factBundle?.financialSummary
    val today = LocalDate.now(ZoneId.of(repository.currentTimezoneId())).toString()
    _uiState.update {
        it.copy(
            offsetForm = OffsetFormState(
                open = true,
                kind = kind,
                amountText = if (kind.isMoneyEvent && summary != null) {
                    formatAmountInput(
                        summary.remainingRefundableOriginalMinor,
                        expense.originalCurrencyCode,
                    )
                } else {
                    ""
                },
                accountingDate = today,
            ),
        )
    }
}

fun ExpenseFactViewModel.closeOffsetSheet() {
    _uiState.update { it.copy(offsetForm = OffsetFormState()) }
}

/** sheet 内分段切换：商家退款 ↔ 银行拒付（reversal 走独立入口，无分段）。 */
fun ExpenseFactViewModel.updateOffsetKind(kind: StreamOffsetKind) {
    if (!kind.isMoneyEvent) return
    updateOffsetForm { it.copy(kind = kind, amountError = null) }
}

/** 表单字段单一更新入口（CorrectionScalarField 先例）。 */
enum class OffsetFormField { Amount, AccountingDate, Reason }

fun ExpenseFactViewModel.updateOffsetFormField(field: OffsetFormField, value: String) =
    updateOffsetForm {
        when (field) {
            OffsetFormField.Amount -> it.copy(amountText = value, amountError = null)
            OffsetFormField.AccountingDate -> it.copy(accountingDate = value, dateError = null)
            OffsetFormField.Reason -> it.copy(reason = value)
        }
    }

internal fun ExpenseFactViewModel.updateOffsetForm(transform: (OffsetFormState) -> OffsetFormState) {
    _uiState.update {
        it.copy(offsetForm = transform(it.offsetForm).copy(submitError = null))
    }
}

/**
 * 提交可用性（禁用态而非说教）：reason/日期必填，金额类 kind 还需金额非空；
 * conflict 权威刷新完成前禁用（不用旧 root token 立即重复提交）。
 */
fun ExpenseFactViewModel.canSubmitOffset(): Boolean {
    val form = _uiState.value.offsetForm
    if (!form.open || form.saving || form.refreshingAfterConflict) return false
    if (form.reason.isBlank() || form.accountingDate.isBlank()) return false
    return !form.kind.isMoneyEvent || form.amountText.isNotBlank()
}
