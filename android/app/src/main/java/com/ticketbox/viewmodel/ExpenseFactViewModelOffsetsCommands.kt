package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseOffsetDraft
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
    if (blockUnreadyFactWrite()) return
    val state = _uiState.value
    val expense = state.expense ?: return
    if (!state.offsetForm.matchesRoot(expense)) {
        _uiState.update { it.copy(offsetForm = it.offsetForm.copy(
            submitError = UiText.res(R.string.expense_offset_draft_root_changed))) }
        return
    }
    val binding = state.correctionAccess?.binding ?: return
    val draft = buildOffsetDraftOrMessage() ?: return
    viewModelScope.launch {
        if (_uiState.value.correctionAccess?.binding != binding || blockUnreadyFactWrite(expense.rowVersion)) return@launch
        updateOffsetForm { it.copy(saving = true) }
        repository.createExpenseOffsetAllowingOffline(binding, expense, draft)
            .onSuccess {
                if (_uiState.value.correctionAccess?.binding != binding) return@onSuccess
                publishOffsetQueued()
            }
            .onFailure { error ->
                if (_uiState.value.correctionAccess?.binding == binding) publishOffsetFailure(error, isVoid = false)
            }
    }
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
        val expense = form.sourceExpense ?: return null
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

/** Enqueue only acknowledges durable intent. Accepted facts arrive through the authoritative bundle reader. */
internal fun ExpenseFactViewModel.publishOffsetQueued() {
    _uiState.update {
        it.copy(
            offsetForm = OffsetFormState(),
            voidOffsetForm = VoidOffsetFormState(),
            message = UiText.res(R.string.expense_offset_queued),
            messageTone = MessageTone.Info,
        )
    }
}

/** Admission failure keeps the form; submitted-command conflicts belong to Outbox. */
internal fun ExpenseFactViewModel.publishOffsetFailure(error: Throwable, isVoid: Boolean) {
    val message = error.toUiText(R.string.expense_offset_submit_failed)
    _uiState.update {
        if (isVoid) {
            it.copy(
                voidOffsetForm = it.voidOffsetForm.copy(
                    submitError = message,
                    saving = false,
                ),
            )
        } else {
            it.copy(
                offsetForm = it.offsetForm.copy(
                    submitError = message,
                    saving = false,
                ),
            )
        }
    }
}
