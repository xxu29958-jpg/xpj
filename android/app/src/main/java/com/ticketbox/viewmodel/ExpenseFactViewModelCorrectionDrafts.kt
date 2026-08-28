package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.ui.components.parseAmountCents
import kotlin.math.abs

/**
 * A1 更正流的域 draft 构造与 baseline diff（纯函数，无 state）：
 * 与 Web `_web_correction_form.py` 的段落 diff 同义 —— 只在投影变化时进 intent。
 */

internal fun buildCorrectionSplitDrafts(
    expense: Expense,
    members: List<FamilyMember>,
    currentSplits: ExpenseSplits,
): List<EditableSplit> {
    val byMember = currentSplits.splits.associateBy { it.memberId }
    val displayCurrency = expense.editDisplayParseCurrency()
    val rosterDrafts = members.mapNotNull { member ->
        val existing = byMember[member.memberId]
        when {
            !member.isDisabled -> EditableSplit(
                memberId = member.memberId,
                displayName = member.displayName,
                included = existing != null,
                amountText = existing?.amountCents?.let { cents ->
                    com.ticketbox.ui.components.formatMinorAmountInput(abs(cents), displayCurrency)
                }.orEmpty(),
                note = existing?.note,
                baselineAmountCents = existing?.amountCents,
            )
            existing != null -> EditableSplit(
                memberId = member.memberId,
                displayName = member.displayName,
                included = true,
                amountText = com.ticketbox.ui.components.formatMinorAmountInput(
                    abs(existing.amountCents),
                    displayCurrency,
                ),
                disabled = true,
                note = existing.note,
                baselineAmountCents = existing.amountCents,
            )
            else -> null
        }
    }
    // 已停用但仍在拆账上的成员：保留显示只读（历史归属不丢）。
    val orphanDrafts = currentSplits.splits
        .filter { split -> split.disabledAt != null && members.none { it.memberId == split.memberId } }
        .map { split ->
            EditableSplit(
                memberId = split.memberId,
                displayName = split.accountName.ifBlank { "未命名成员" },
                included = true,
                amountText = com.ticketbox.ui.components.formatMinorAmountInput(
                    abs(split.amountCents),
                    displayCurrency,
                ),
                disabled = true,
                note = split.note,
                baselineAmountCents = split.amountCents,
            )
        }
    return rosterDrafts + orphanDrafts
}

private fun parseCorrectionMagnitude(
    amountText: String,
    currency: com.ticketbox.domain.model.CurrencyCode?,
    baselineAmountCents: Long?,
    invalidRes: Int,
): Long? {
    if (amountText.isBlank()) return null
    if (currency == null) {
        val baselineMagnitude = baselineAmountCents?.let(::abs)
        if (amountText.trim() == baselineMagnitude?.toString()) return baselineMagnitude
        throw CorrectionValidationError(R.string.expense_correction_currency_unsupported)
    }
    return parseAmountCents(amountText, currency)
        ?: throw CorrectionValidationError(invalidRes)
}

private fun EditableItem.toCorrectionItemDraft(
    currency: com.ticketbox.domain.model.CurrencyCode?,
): ExpenseItemDraft {
    val magnitude = parseCorrectionMagnitude(
        amountText = amountText,
        currency = currency,
        baselineAmountCents = baselineAmountCents,
        invalidRes = R.string.expense_correction_items_amount_invalid,
    )
    // ADR-0035: discount 行 amount_cents 为负；编辑器记绝对值，kind 决定符号。
    val signed = magnitude?.let { if (kind == ExpenseItemKind.DISCOUNT) -abs(it) else it }
    return ExpenseItemDraft(
        name = name.trim().ifBlank { "未命名" },
        quantityText = quantityText,
        unitPriceCents = unitPriceCents,
        amountCents = signed,
        category = category,
        rawText = rawText,
        confidence = confidence,
        kind = kind,
    )
}

/** 编辑器投影（kind/name/签名金额）：与 baseline 在该投影上比对 —— 只打开未改动不进 intent。 */
private fun itemProjection(
    name: String,
    amountCents: Long?,
    kind: String,
): Triple<String, String, Long?> = Triple(kind, name.trim(), amountCents)

/** 明细 diff：itemsTouched 且投影变化时才返回候选行，否则 null（不进 intent）。 */
internal fun computeCorrectionItemsChange(
    expense: Expense,
    form: CorrectionFormState,
    baseline: ExpenseItems?,
): List<ExpenseItemDraft>? {
    if (!form.itemsTouched) return null
    val currency = expense.editParseCurrency()
    val baselineProjection = (baseline?.items ?: emptyList()).map {
        itemProjection(it.name, it.amountCents, it.kind)
    }
    val candidate = form.itemDrafts
        .filter { it.name.isNotBlank() || it.amountText.isNotBlank() }
        .map { it.toCorrectionItemDraft(currency) }
    val candidateProjection = candidate.map { itemProjection(it.name, it.amountCents, it.kind) }
    return if (candidateProjection != baselineProjection) candidate else null
}

/** 拆账 diff：splitsTouched 且（memberId, 金额）集合变化时才返回候选，否则 null。 */
internal fun computeCorrectionSplitsChange(
    expense: Expense,
    form: CorrectionFormState,
    baseline: ExpenseSplits?,
): List<ExpenseSplitDraft>? {
    if (!form.splitsTouched) return null
    val currency = expense.editParseCurrency()
    val baselineProjection = (baseline?.splits ?: emptyList())
        .map { Triple(it.memberId, it.amountCents, it.note.orEmpty()) }
        .sortedBy { it.first }
    val candidate = form.splitDrafts
        .filter { it.included }
        .map { split ->
            ExpenseSplitDraft(
                memberId = split.memberId,
                amountCents = parseCorrectionMagnitude(
                    amountText = split.amountText,
                    currency = currency,
                    baselineAmountCents = split.baselineAmountCents,
                    invalidRes = R.string.expense_correction_splits_amount_invalid,
                ) ?: throw CorrectionValidationError(R.string.expense_correction_splits_amount_invalid),
                note = split.note,
            )
        }
    val candidateProjection = candidate
        .map { Triple(it.memberId, it.amountCents, it.note.orEmpty()) }
        .sortedBy { it.first }
    return if (candidateProjection != baselineProjection) candidate else null
}
