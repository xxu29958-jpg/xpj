package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatMinorAmountInput
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1: 变更记录时间线 —— 真实读取 GET revisions（在线-only；离线展示既有缓存
 * 内容或诚实错误态，不伪造 revision）。
 *
 * 展示规则与 Web `_web_expense_fact.py` 同构：只有用户可写字段产出
 * before→after delta，系统字段（汇率快照/fx_status 等）折叠为一句话；
 * revision id / row_version / actor id 永不进文案。
 */

/** 一条时间线条目的展示模型（Compose 只负责渲染，不再懂快照结构）。 */
data class FactTimelineEntry(
    val isCorrection: Boolean,
    @param:StringRes val kindLabelRes: Int,
    val reason: String,
    val whenText: String,
    val actor: String,
    val changes: List<FactTimelineChange>,
)

data class FactTimelineChange(
    val label: UiText,
    val before: UiText,
    val after: UiText,
)

// 用户可写字段 → 标签。对照 backend expense_revision_service._SCALAR_FIELDS；
// 未列出的快照字段视为系统细节，不进 delta 列表。
private val FACT_FIELD_ORDER: List<Pair<String, Int>> = listOf(
    "amount_cents" to R.string.expense_fact_timeline_field_amount,
    "original_currency_code" to R.string.expense_fact_timeline_field_original_currency,
    "original_amount_minor" to R.string.expense_fact_timeline_field_original_amount,
    "merchant" to R.string.expense_fact_timeline_field_merchant,
    "category" to R.string.expense_fact_timeline_field_category,
    "note" to R.string.expense_fact_timeline_field_note,
    "tags" to R.string.expense_fact_timeline_field_tags,
    "expense_time" to R.string.expense_fact_timeline_field_time,
    "value_score" to R.string.expense_fact_timeline_field_value_score,
    "regret_score" to R.string.expense_fact_timeline_field_regret_score,
    "items" to R.string.expense_fact_timeline_field_items,
    "splits" to R.string.expense_fact_timeline_field_splits,
)

private fun formatFactValue(
    field: String,
    value: Any?,
    snapshot: Map<String, Any?>,
    currency: com.ticketbox.domain.model.CurrencyCode,
): UiText {
    if (value == null || value == "") return UiText.res(R.string.expense_fact_timeline_value_empty)
    return when (field) {
        "amount_cents" -> UiText.raw(formatHomeAmountSnapshot(value, currency))
        "original_amount_minor" -> formatOriginalAmountSnapshot(value, snapshot)
        "expense_time" -> UiText.raw(displayDateTime(value.toString()))
        "items", "splits" -> formatLineCountSnapshot(value)
        else -> UiText.raw(value.toString())
    }
}

private fun formatHomeAmountSnapshot(value: Any, currency: CurrencyCode): String =
    (value as? Number)?.toLong()?.let {
        formatMinorAmountInput(kotlin.math.abs(it), currency)
    } ?: value.toString()

private fun formatOriginalAmountSnapshot(
    value: Any,
    snapshot: Map<String, Any?>,
): UiText {
    val amountMinor = (value as? Number)?.toLong() ?: return UiText.raw(value.toString())
    val rawCurrencyCode = snapshot["original_currency_code"]?.toString()?.trim()?.uppercase()
    val display = CurrencyCode.fromStorageKeyOrNull(rawCurrencyCode)?.let {
        formatMinorAmountInput(kotlin.math.abs(amountMinor), it)
    } ?: listOfNotNull(
        kotlin.math.abs(amountMinor).toString(),
        rawCurrencyCode?.takeIf(String::isNotBlank),
    ).joinToString(" ")
    return UiText.raw(display)
}

private fun formatLineCountSnapshot(value: Any): UiText =
    (value as? List<*>)?.size?.let {
        UiText.res(R.string.expense_fact_timeline_lines_count, it)
    } ?: UiText.raw(value.toString())

private fun snapshotAllocationLabel(
    snapshot: Map<String, Any?>,
    currency: CurrencyCode,
): UiText? {
    val amountCents = (snapshot["amount_cents"] as? Number)?.toLong() ?: return null
    val splits = (snapshot["splits"] as? List<*>)?.takeIf { it.isNotEmpty() } ?: return null
    var splitTotal = 0L
    for (rawSplit in splits) {
        val split = rawSplit as? Map<*, *> ?: return null
        val splitAmount = (split["amount_cents"] as? Number)?.toLong() ?: return null
        splitTotal = runCatching { Math.addExact(splitTotal, splitAmount) }.getOrNull() ?: return null
    }
    val remaining = runCatching { Math.subtractExact(amountCents, splitTotal) }.getOrNull() ?: return null
    if (remaining == 0L) return UiText.res(R.string.expense_fact_timeline_allocation_complete)
    val amount = formatMinorAmountInput(kotlin.math.abs(remaining), currency)
    return if (remaining > 0L) {
        UiText.res(R.string.expense_fact_timeline_allocation_remaining, amount)
    } else {
        UiText.res(R.string.expense_fact_timeline_allocation_overallocated, amount)
    }
}

private fun ExpenseRevision.toTimelineEntry(
    currency: com.ticketbox.domain.model.CurrencyCode,
): FactTimelineEntry {
    val isCorrection = changeKind == "correction"
    val changes = if (!isCorrection) {
        emptyList()
    } else {
        val before = before ?: emptyMap()
        val deltas = buildList {
            FACT_FIELD_ORDER
                .filter { (field, _) -> field in changedFields }
                .forEach { (field, labelRes) ->
                    add(
                        FactTimelineChange(
                            label = UiText.res(labelRes),
                            before = formatFactValue(field, before[field], before, currency),
                            after = formatFactValue(field, after[field], after, currency),
                        ),
                    )
                    if (field == "amount_cents" && "splits" !in changedFields) {
                        val beforeAllocation = snapshotAllocationLabel(before, currency)
                        val afterAllocation = snapshotAllocationLabel(after, currency)
                        if (
                            beforeAllocation != null &&
                            afterAllocation != null &&
                            beforeAllocation != afterAllocation
                        ) {
                            add(
                                FactTimelineChange(
                                    label = UiText.res(R.string.expense_fact_timeline_field_splits),
                                    before = beforeAllocation,
                                    after = afterAllocation,
                                ),
                            )
                        }
                    }
                }
            }
        deltas.ifEmpty {
            listOf(
                FactTimelineChange(
                    label = UiText.res(R.string.expense_fact_timeline_system_touched),
                    before = UiText.raw(""),
                    after = UiText.raw(""),
                )
            )
        }
    }
    return FactTimelineEntry(
        isCorrection = isCorrection,
        kindLabelRes = if (isCorrection) {
            R.string.expense_fact_timeline_kind_correction
        } else {
            R.string.expense_fact_timeline_kind_confirmed
        },
        reason = reason,
        whenText = displayDateTime(createdAt),
        actor = listOfNotNull(actorAccountName, actorDeviceName).filter { it.isNotBlank() }.joinToString(" · "),
        changes = changes,
    )
}

/** 时间线展示模型：newest-first（服务端已按 revision_number desc 返回）。 */
internal fun List<ExpenseRevision>.toTimelineEntries(
    currency: com.ticketbox.domain.model.CurrencyCode,
): List<FactTimelineEntry> = map { it.toTimelineEntry(currency) }

fun ExpenseFactViewModel.loadExpenseRevisions() {
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                revisionsLoading = true,
                revisionsLoadState = ExpenseDetailDataLoadState.Loading,
            )
        }
        repository.fetchExpenseRevisions(expenseId)
            .onSuccess { page ->
                _uiState.update {
                    it.copy(
                        revisions = page.items,
                        revisionsTotal = page.total,
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Failed,
                        revisions = emptyList(),
                        revisionsTotal = 0,
                        message = error.toUiText(R.string.expense_fact_revisions_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

fun ExpenseFactViewModel.toggleTimelineExpanded() {
    _uiState.update { it.copy(timelineExpanded = !it.timelineExpanded) }
}
