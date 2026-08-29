package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.changesAdvisorPayloadAgainst
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.UiText
import java.time.ZoneId
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1: 显式更正流 —— reason + scalar/items/splits 组合为**一次** correction
 * intent；只提交相对 baseline 发生变化的字段（零变更禁提交）；四态
 * （Synced / Queued / validation / conflict）都有用户可继续的表达。
 *
 * 责任边界：表单开关与标量字段、diff 汇总与提交四态在本文件；明细/拆账子
 * surface 与其 diff 在 [ExpenseFactViewModelCorrectionLines.kt]（detekt 拆分）。
 * diff 规则与 Web `_web_correction_form.py` 同构：与当前事实不同的才进
 * draft；允许清空的字段通过 changed flag 保留“未提交 / 显式 null”三态。
 */

fun ExpenseFactViewModel.openCorrectionSheet() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    val zoneId = ZoneId.of(repository.currentTimezoneId())
    _uiState.update {
        it.copy(correction = initialCorrectionFormState(expense, zoneId))
    }
}

fun ExpenseFactViewModel.closeCorrectionSheet() {
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
    val expense = _uiState.value.expense ?: return null
    val form = _uiState.value.correction
    if (form.reason.isBlank()) return rejectCorrection(R.string.expense_correction_reason_required)
    val scalar = try {
        computeScalarChanges(expense, form, ZoneId.of(repository.currentTimezoneId()))
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    val items = try {
        computeCorrectionItemsChange(expense, form, _uiState.value.expenseItems)
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    val splits = try {
        computeCorrectionSplitsChange(expense, form, _uiState.value.expenseSplits)
    } catch (e: CorrectionValidationError) {
        return rejectCorrection(e.resId)
    }
    if (!scalar.hasAny && items == null && splits == null) {
        return rejectCorrection(R.string.expense_correction_no_changes)
    }
    return ExpenseCorrectionDraft(
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
}

/** 提交按钮的可用性（屏幕用它做禁用态而不是错误说教）：reason 非空且不在保存中。 */
fun ExpenseFactViewModel.canSubmitCorrection(): Boolean {
    val form = _uiState.value.correction
    return form.open && !form.saving && form.reason.isNotBlank()
}

fun ExpenseFactViewModel.submitCorrection() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense ?: return
    val draft = buildCorrectionDraftOrMessage() ?: return
    val invalidatesAdvice = draft.changesAdvisorPayloadAgainst(expense)
    viewModelScope.launch {
        updateCorrection { it.copy(saving = true) }
        repository.correctExpenseAllowingOffline(expense, draft)
            .onSuccess { outcome -> publishCorrectionOutcome(outcome, draft, invalidatesAdvice) }
            .onFailure { error ->
                val isConflict = (error as? RepositoryException)?.errorCode == "state_conflict"
                if (isConflict) {
                    // direct 409：刷新权威事实 + 时间线，保留用户已填表单，
                    // 用 banner 说明而不是静默吞掉。
                    _uiState.update {
                        it.copy(
                            correction = it.correction.copy(
                                conflictMessage = UiText.res(R.string.expense_correction_conflict),
                                saving = false,
                            ),
                        )
                    }
                    refreshAuthoritativeFact()
                } else {
                    _uiState.update {
                        it.copy(
                            correction = it.correction.copy(
                                saving = false,
                                submitError = error.toUiText(R.string.expense_correction_failed),
                            ),
                        )
                    }
                }
            }
    }
}

private fun ExpenseFactViewModel.refreshAuthoritativeFact() {
    viewModelScope.launch {
        repository.fetchExpense(expenseId)
            .onSuccess { expense ->
                _uiState.update {
                    it.copy(
                        expense = expense,
                        expenseLoading = false,
                        expenseLoadState = ExpenseDetailDataLoadState.Loaded,
                        expenseStale = false,
                        expenseLoadMessage = null,
                    )
                }
                loadExpenseItems()
                loadExpenseSplits()
                loadExpenseRevisions()
            }
    }
}
