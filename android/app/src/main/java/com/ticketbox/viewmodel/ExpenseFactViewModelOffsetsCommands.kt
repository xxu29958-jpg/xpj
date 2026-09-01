package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import java.time.LocalDate
import java.time.format.DateTimeParseException
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Refund/Chargeback/Reversal 纵向片：登记命令、校验与结果发布（表单状态与读取在
 * ExpenseFactViewModelOffsets.kt；撤销在 ExpenseFactViewModelOffsetsVoid.kt）。
 *
 * 纪律（共同冻结点 1）：客户端只校验金额可解析且 > 0；amount eligibility 永远由
 * 服务端 OCC + money owner 裁决，409/422 一律保留草稿。bundle 发布的
 * remainingRefundableOriginalMinor 只用于预填与界面提示，不做客户端硬阻断。
 * offline 由 Outbox owner 持久化 intent，这里只把 Queued 翻译为会话内 pending
 * 表达，绝不本地改 server projection、不造 phantom offset row。
 */

/** 与更正流同一口径（R13）：未声明/已知的原币码返回 null，未知码返回原码。 */
internal fun ExpenseFactViewModel.unsupportedOriginalCurrencyCode(): String? {
    val raw = _uiState.value.expense?.originalCurrencyCodeRaw ?: return null
    if (raw.isBlank()) return null
    return raw.takeIf { CurrencyCode.fromStorageKeyOrNull(it) == null }
}

fun ExpenseFactViewModel.submitOffset() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    val draft = buildOffsetDraftOrMessage() ?: return
    viewModelScope.launch {
        updateOffsetForm { it.copy(saving = true) }
        repository.createExpenseOffsetAllowingOffline(expense, draft)
            .onSuccess { outcome ->
                publishOffsetOutcome(outcome, offsetSuccessRes(draft.kind))
            }
            .onFailure { error -> publishOffsetFailure(error, isVoid = false) }
    }
}

@StringRes
private fun offsetSuccessRes(kind: StreamOffsetKind): Int = when (kind) {
    StreamOffsetKind.Refund -> R.string.expense_offset_success_refund
    StreamOffsetKind.Chargeback -> R.string.expense_offset_success_chargeback
    StreamOffsetKind.Reversal -> R.string.expense_offset_success_reversal
}

/**
 * 计算当前表单的 offset draft；校验失败把消息写进 state 并返回 null。
 * 只校验 reason 必填、金额可解析且 > 0、日期可解析；金额上限等服务端裁决。
 */
internal fun ExpenseFactViewModel.buildOffsetDraftOrMessage(): ExpenseOffsetDraft? {
    val form = _uiState.value.offsetForm
    if (form.reason.isBlank()) return rejectOffset(R.string.expense_offset_reason_required)
    var amountMinor: Long? = null
    if (form.kind.isMoneyEvent) {
        val expense = _uiState.value.expense ?: return null
        val parsed = parseAmountCents(form.amountText, expense.originalCurrencyCode)
        if (parsed == null || parsed <= 0L) {
            return rejectOffset(R.string.expense_offset_amount_invalid)
        }
        amountMinor = parsed
    }
    try {
        LocalDate.parse(form.accountingDate.trim())
    } catch (e: DateTimeParseException) {
        return rejectOffset(R.string.expense_offset_date_invalid)
    }
    return ExpenseOffsetDraft(
        kind = form.kind,
        originalAmountMinor = amountMinor,
        accountingDate = form.accountingDate.trim(),
        reason = form.reason.trim(),
    )
}

private fun ExpenseFactViewModel.rejectOffset(@StringRes resId: Int): ExpenseOffsetDraft? {
    _uiState.update {
        it.copy(
            offsetForm = it.offsetForm.copy(
                amountError = UiText.res(resId)
                    .takeIf { resId == R.string.expense_offset_amount_invalid },
                dateError = UiText.res(resId)
                    .takeIf { resId == R.string.expense_offset_date_invalid },
                submitError = UiText.res(resId),
                saving = false,
            ),
        )
    }
    return null
}

/**
 * Synced/Queued 双态发布：Synced 用返回 bundle 同源替换事实并刷新时间线；
 * Queued 只留会话内 pending chip + 页面级说明（持久队列表达归 Outbox）。
 */
internal fun ExpenseFactViewModel.publishOffsetOutcome(
    outcome: ExpenseOffsetMutationOutcome,
    @StringRes successRes: Int,
) {
    when (outcome) {
        is ExpenseOffsetMutationOutcome.Synced -> {
            _uiState.update {
                it.copy(
                    offsetForm = OffsetFormState(),
                    voidOffsetForm = VoidOffsetFormState(),
                    message = offsetSuccessMessage(outcome, successRes),
                    messageTone = if (outcome.refreshPending) MessageTone.Info else MessageTone.Success,
                    doneAdviceInputsChanged = true,
                )
            }
            applyFactBundle(outcome.bundle)
            loadExpenseRevisions()
        }
        is ExpenseOffsetMutationOutcome.Queued -> {
            _uiState.update {
                it.copy(
                    offsetForm = OffsetFormState(),
                    voidOffsetForm = VoidOffsetFormState(),
                    pendingOffsetIntent = outcome.intent,
                    message = UiText.res(R.string.expense_offset_queued),
                    messageTone = MessageTone.Info,
                    doneAdviceInputsChanged = true,
                )
            }
        }
    }
}

/** 成功回执：撤回回执计数与主文案同条呈现（不另造通知系统）。 */
private fun offsetSuccessMessage(
    outcome: ExpenseOffsetMutationOutcome.Synced,
    @StringRes successRes: Int,
): UiText {
    val base = UiText.res(
        if (outcome.refreshPending) R.string.expense_offset_success_refresh_pending else successRes,
    )
    val cancelled = outcome.bundle.relationshipImpacts.pendingInvitesCancelled.size
    return if (cancelled > 0) {
        UiText.compound(
            listOf(base, UiText.res(R.string.expense_offset_cancelled_invites, cancelled)),
            " ",
        )
    } else {
        base
    }
}

/**
 * 失败发布：direct 409 → conflict banner + 权威刷新 + 保留草稿。刷新期间
 * refreshingAfterConflict 禁用提交（不拿旧 root token 循环 409）；刷新成功由
 * adoptFactBundle 采用 bundle.root 并解禁，失败由 sheet/段落给可重试出口。
 */
internal fun ExpenseFactViewModel.publishOffsetFailure(error: Throwable, isVoid: Boolean) {
    val isConflict = (error as? RepositoryException)?.errorCode == "state_conflict"
    val message = if (isConflict) {
        UiText.res(R.string.expense_offset_conflict)
    } else {
        error.toUiText(R.string.expense_offset_submit_failed)
    }
    _uiState.update {
        if (isVoid) {
            it.copy(
                offsetCommandsBlockedUntilRefresh = it.offsetCommandsBlockedUntilRefresh || isConflict,
                voidOffsetForm = it.voidOffsetForm.copy(
                    conflictMessage = message.takeIf { isConflict },
                    refreshingAfterConflict = isConflict,
                    submitError = message.takeIf { !isConflict },
                    saving = false,
                ),
            )
        } else {
            it.copy(
                offsetCommandsBlockedUntilRefresh = it.offsetCommandsBlockedUntilRefresh || isConflict,
                offsetForm = it.offsetForm.copy(
                    conflictMessage = message.takeIf { isConflict },
                    refreshingAfterConflict = isConflict,
                    submitError = message.takeIf { !isConflict },
                    saving = false,
                ),
            )
        }
    }
    if (isConflict) {
        loadExpenseFactBundle()
    }
}
