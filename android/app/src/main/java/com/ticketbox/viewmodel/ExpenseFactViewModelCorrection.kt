package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.changesAdvisorPayloadAgainst
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.toRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.UiText
import java.time.ZoneId
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1: 显式更正流 —— reason + scalar/items/splits 组合为**一次** correction
 * intent；只提交相对已核对 baseline 发生变化的字段（零变更禁提交）。
 * 接受提交只表示 Room 已保存；真实送达与冲突由持久观察呈现。
 *
 * 责任边界：表单开关与标量字段、diff 汇总与提交四态在本文件；明细/拆账子
 * surface 与其 diff 在 [ExpenseFactViewModelCorrectionLines.kt]（detekt 拆分）。
 * diff 规则与 Web `_web_correction_form.py` 同构：与当前事实不同的才进
 * draft；允许清空的字段通过 changed flag 保留“未提交 / 显式 null”三态。
 */

fun ExpenseFactViewModel.openCorrectionSheet() {
    if (blockReadOnlyWrite()) return
    val state = _uiState.value
    if (!state.canStartCorrection) return
    val expense = state.expense ?: return
    correctionSplitMemberGeneration++
    correctionOriginalItems = state.currentCorrectionItems
    correctionOriginalSplits = state.currentCorrectionSplits
    correctionBaseline = expense
    correctionBinding = state.correctionAccess?.binding
    val zoneId = ZoneId.of(repository.currentTimezoneId())
    _uiState.update {
        it.copy(correction = initialCorrectionFormState(expense, zoneId))
    }
}

fun ExpenseFactViewModel.closeCorrectionSheet() {
    correctionSplitMemberGeneration++
    _uiState.update { it.copy(correction = CorrectionFormState()) }
}

/** 标量字段单一更新入口（屏幕七个动作共用；detekt 函数数门下的合并）。 */
enum class CorrectionScalarField { Reason, Merchant, Category, Tags, Note, Amount, ExpenseTime }

enum class CorrectionScoreField { Value, Regret }

fun ExpenseFactViewModel.updateCorrectionField(field: CorrectionScalarField, value: String) =
    updateCorrection {
        when (field) {
            CorrectionScalarField.Reason -> it.copy(reason = value)
            CorrectionScalarField.Merchant -> it.copy(merchant = value)
            CorrectionScalarField.Category -> it.copy(category = value)
            CorrectionScalarField.Tags -> it.copy(tags = value)
            CorrectionScalarField.Note -> it.copy(note = value)
            CorrectionScalarField.Amount -> it.copy(amountText = value, amountError = null)
            CorrectionScalarField.ExpenseTime -> it.copy(expenseTimeText = value, timeError = null)
        }
    }

fun ExpenseFactViewModel.updateCorrectionCurrency(currency: CurrencyCode) = updateCorrection {
    val switchingFromUnsupported = it.unsupportedCurrencyCode != null && !it.currencyTouched
    it.copy(
        currency = currency,
        currencyTouched = true,
        amountText = if (switchingFromUnsupported) "" else it.amountText,
        amountError = null,
    )
}

fun ExpenseFactViewModel.updateCorrectionScore(field: CorrectionScoreField, value: Int?) =
    updateCorrection {
        when (field) {
            CorrectionScoreField.Value -> it.copy(valueScore = value)
            CorrectionScoreField.Regret -> it.copy(regretScore = value)
        }
    }

internal fun ExpenseFactViewModel.updateCorrection(transform: (CorrectionFormState) -> CorrectionFormState) {
    _uiState.update {
        it.copy(correction = transform(it.correction).copy(submitError = null))
    }
}

private fun ExpenseFactViewModel.rejectCorrection(@StringRes resId: Int): ExpenseCorrectionDraft? {
    _uiState.update {
        it.copy(
            correction = it.correction.copy(
                amountError = UiText.res(resId).takeIf {
                    resId == R.string.expense_correction_amount_invalid ||
                        resId == R.string.expense_correction_currency_unsupported
                },
                timeError = UiText.res(resId).takeIf {
                    resId == R.string.expense_correction_time_invalid
                },
                submitError = UiText.res(resId),
            ),
        )
    }
    return null
}

/**
 * 计算当前表单相对 baseline 的更正 draft；校验失败时把消息写进 state 并返回 null。
 * 纯计算 + state 消息，便于单测（reason 门 / 零变更门 / diff 内容）。
 */
internal fun ExpenseFactViewModel.buildCorrectionDraftOrMessage(): ExpenseCorrectionDraft? {
    if (!requireCurrentCorrectionContext()) return null
    val expense = correctionBaseline ?: return null
    val form = _uiState.value.correction
    if (form.reason.isBlank()) return rejectCorrection(R.string.expense_correction_reason_required)
    val scalar = try {
        computeScalarChanges(expense, form, ZoneId.of(repository.currentTimezoneId()))
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    val items = try {
        computeCorrectionItemsChange(expense, form, correctionOriginalItems)
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    val splits = try {
        computeCorrectionSplitsChange(expense, form, correctionOriginalSplits)
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    if (!scalar.hasAny && items == null && splits == null) {
        return rejectCorrection(R.string.expense_correction_no_changes)
    }
    val draft = ExpenseCorrectionDraft(
        reason = form.reason.trim(),
        originalCurrencyCode = scalar.originalCurrencyCode,
        originalAmountMinor = scalar.originalAmountMinor,
        merchant = scalar.merchant,
        category = scalar.category,
        note = scalar.note,
        expenseTime = scalar.expenseTime,
        expenseTimeChanged = scalar.expenseTimeChanged,
        tags = scalar.tags,
        valueScore = scalar.valueScore,
        valueScoreChanged = scalar.valueScoreChanged,
        regretScore = scalar.regretScore,
        regretScoreChanged = scalar.regretScoreChanged,
        items = items,
        splits = splits,
    )
    val knownSplits = correctionOriginalSplits?.takeIf { expense.matchesFactVersion(it.expenseId, it.parentRowVersion) }
    if (wouldOverallocateLoadedSplits(expense, draft, knownSplits)) {
        return rejectCorrection(R.string.error_expense_split_total_exceeds_parent)
    }
    try {
        draft.toRequest(expense.rowVersion)
    } catch (error: RepositoryException) {
        _uiState.update { it.copy(correction = it.correction.copy(submitError = error.toUiText(R.string.expense_correction_failed))) }
        return null
    }
    return draft
}

/** 提交按钮的可用性（屏幕用它做禁用态而不是错误说教）：reason 非空且不在保存中。 */
fun ExpenseFactViewModel.canSubmitCorrection(): Boolean {
    val form = _uiState.value.correction
    return form.open && !form.saving && form.reason.isNotBlank() && correctionContextError() == null
}

fun ExpenseFactViewModel.submitCorrection() {
    if (blockReadOnlyWrite() || !_uiState.value.correction.open || _uiState.value.correction.saving) return
    val expense = correctionBaseline ?: return
    val binding = correctionBinding ?: return
    val draft = buildCorrectionDraftOrMessage() ?: return
    val invalidatesAdvice = draft.changesAdvisorPayloadAgainst(expense)
    updateCorrection { it.copy(saving = true) }
    viewModelScope.launch {
        if (!requireCurrentCorrectionContext()) return@launch
        repository.submitCorrection(binding, expense, draft)
            .onSuccess {
                if (_uiState.value.correctionAccess?.binding != binding) return@onSuccess
                _uiState.update { state -> state.copy(correction = CorrectionFormState(),
                    message = null,
                    messageTone = com.ticketbox.domain.model.MessageTone.Info,
                    doneAdviceInputsChanged = state.doneAdviceInputsChanged || invalidatesAdvice) }
            }
            .onFailure { error ->
                if (_uiState.value.correctionAccess?.binding != binding) return@onFailure
                _uiState.update { state -> state.copy(correction = state.correction.copy(saving = false,
                    submitError = error.toUiText(R.string.expense_correction_failed))) }
            }
    }
}
