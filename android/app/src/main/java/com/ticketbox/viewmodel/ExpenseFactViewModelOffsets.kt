package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.newTaskDate
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.ui.components.formatAmountInput
import java.time.LocalDate
import java.time.ZoneId
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.updateAndGet
import kotlinx.coroutines.launch
import kotlinx.coroutines.CoroutineStart

/**
 * Refund/Chargeback/Reversal 纵向片：退回与冲销的**状态与读取**（提交/撤销命令在
 * ExpenseFactViewModelOffsetsCommands.kt / ExpenseFactViewModelOffsetsVoid.kt，
 * detekt 函数数门下的同责拆分）。
 *
 * 事实源唯一：段内一切金额/状态渲染 [ExpenseFactBundle]（服务端 query owner
 * 组装）；客户端不重算金额、FX 或 remaining。原提交状态归既有 Outbox surface，
 * 排队反馈不冒充已生效事实。
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
    val sourceExpense: Expense? = null,
    val kind: StreamOffsetKind = StreamOffsetKind.Refund,
    val amountText: String = "",
    val accountingDate: String = "",
    val reason: String = "",
    val amountError: UiText? = null,
    val dateError: UiText? = null,
    val submitError: UiText? = null,
    val saving: Boolean = false,
) {
    fun matchesRoot(expense: Expense?): Boolean = sourceExpense != null && expense != null &&
        sourceExpense.id == expense.id && sourceExpense.rowVersion == expense.rowVersion &&
        sourceExpense.originalCurrencyCode == expense.originalCurrencyCode &&
        sourceExpense.originalCurrencyCodeRaw == expense.originalCurrencyCodeRaw
}

/** 撤销已生效退回/冲销的确认表单态。 */
data class VoidOffsetFormState(
    val open: Boolean = false,
    val target: ExpenseOffsetFact? = null,
    val reason: String = "",
    val submitError: UiText? = null,
    val saving: Boolean = false,
)

/**
 * 事实包 = 退回/冲销段的唯一事实源；失败是段内可重试错误，不抢页面、不动已知 root。
 * generation 必须在 launch 之前同步分配：invocation order 才是 authority order，
 * 未调度的旧读不得拿到比 command response 更大的 generation（共同冻结）。
 */
fun ExpenseFactViewModel.loadExpenseFactBundle() {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    val generation = ++factBundleLoadGeneration
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                factBundleLoadState = ExpenseDetailDataLoadState.Loading,
                factBundleMessage = null,
            )
        }
        repository.fetchExpenseFactBundle(expenseId, binding)
            .onSuccess { snapshot ->
                if (generation != factBundleLoadGeneration) return@onSuccess
                if (snapshot.fromCache) _uiState.update {
                    it.copy(factBundle = snapshot.value, factBundleLoadState = ExpenseDetailDataLoadState.Failed,
                        factBundleCachedAt = snapshot.fetchedAt,
                        factBundleMessage = UiText.res(R.string.expense_fact_offsets_stale))
                } else adoptFactBundle(snapshot.value)
            }
            .onFailure { error ->
                if (generation == factBundleLoadGeneration) {
                    if (retireDeniedFactReads(error)) return@onFailure
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

/**
 * 原子采用（共同冻结）：FactBundle 是单一原子 publication —— 整包采用（含
 * root）或整包丢弃，绝不混装跨版本视图。旧包到达（root.rowVersion 回退）时
 * 保留当前 root + 当前 factBundle；首读即旧包才给可重试出口。
 */
private fun ExpenseFactViewModel.adoptFactBundle(bundle: ExpenseFactBundle) {
    val adopted = _uiState.updateAndGet {
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
                factBundleCachedAt = null,
            )
        }
    }
    if (
        adopted.factBundle === bundle && adopted.expense === bundle.root &&
        bundle.root.canInitiateBillSplit(adopted.readOnly)
    ) {
        loadBillSplitSent(onlyIfUnknown = true)
    }
    if (adopted.factBundle === bundle && factInputSession == null && !adopted.factInputsReady) loadFactOriginalInputs()
}

fun ExpenseFactViewModel.openOffsetSheet(kind: StreamOffsetKind) {
    if (blockReadOnlyWrite() || factInputUnavailable()) return
    if (blockUnreadyFactWrite()) return
    val inputKey = if (kind.isMoneyEvent) "refund" else "reversal"
    factInputSession?.draft(inputKey)?.let { draft ->
        _uiState.update { it.copy(offsetForm = draft.offsetForm().copy(open = true)) }
        return
    }
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
    val summary = _uiState.value.factBundle?.takeIf { it.matchesRoot(expense) }?.financialSummary
    val today = if (calendars == null) LocalDate.now(clock.withZone(ZoneId.of(repository.currentTimezoneId()))).toString() else ""
    _uiState.update { state ->
        state.copy(
            offsetForm = OffsetFormState(
                open = true,
                sourceExpense = expense,
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
    keepOffsetInput()
    resolveNewOffsetDate(_uiState.value.offsetForm)
}

private fun ExpenseFactViewModel.resolveNewOffsetDate(form: OffsetFormState) {
    if (calendars == null) return
    val session = factInputSession ?: return
    val binding = _uiState.value.correctionAccess?.binding ?: return
    viewModelScope.launch(start = CoroutineStart.UNDISPATCHED) {
        val date = calendars.newTaskDate(binding, clock) ?: return@launch
        // A late rule must not overwrite typed input, a closed sheet or a replacement identity.
        if (factInputSession !== session || _uiState.value.correctionAccess?.binding != binding ||
            _uiState.value.offsetForm !== form) return@launch
        _uiState.update { it.copy(offsetForm = form.copy(accountingDate = date.toString())) }
        keepOffsetInput()
    }
}

fun ExpenseFactViewModel.closeOffsetSheet() {
    if (_uiState.value.offsetForm.saving) return
    _uiState.update { it.copy(offsetForm = it.offsetForm.copy(open = false)) }
}

/** A new reviewed draft; the old command is never rebased or silently reinterpreted. */
fun ExpenseFactViewModel.reviewOffsetDraft() {
    if (blockUnreadyFactWrite()) return
    val state = _uiState.value
    val expense = state.expense ?: return
    val form = state.offsetForm
    if (!form.open || factInputOperationBusy() || form.kind.isMoneyEvent && unsupportedOriginalCurrencyCode() != null) return
    _uiState.update { it.copy(offsetForm = form.copy(sourceExpense = expense,
        amountText = form.amountText.takeIf { form.sourceExpense?.originalCurrencyCode == expense.originalCurrencyCode }.orEmpty(),
        amountError = null, dateError = null, submitError = null)) }
    keepOffsetInput(review = true)
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
    if (!canEditFactInput(_uiState.value.offsetForm.inputKey())) return
    _uiState.update {
        it.copy(offsetForm = transform(it.offsetForm).copy(submitError = null))
    }
    keepOffsetInput()
}

/**
 * 提交可用性（禁用态而非说教）：reason/日期必填，金额类 kind 还需金额非空；
 * 当前表单必须已核对当前账单版本，后续提交冲突由持久队列处理。
 */
fun ExpenseFactViewModel.canSubmitOffset(): Boolean {
    val state = _uiState.value
    val form = state.offsetForm
    if (state.readOnly || !state.authoritativeRootReady) return false
    if (factInputSession?.original(form.inputKey())?.binding != state.correctionAccess?.binding) return false
    if (!form.matchesRoot(state.expense)) return false
    if (!form.open || factInputOperationBusy()) return false
    if (form.reason.isBlank() || form.accountingDate.isBlank()) return false
    return !form.kind.isMoneyEvent || form.amountText.isNotBlank()
}
