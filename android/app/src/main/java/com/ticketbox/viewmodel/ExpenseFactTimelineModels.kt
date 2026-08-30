package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatMinorAmountInput

/**
 * A1 时间线展示模型与 mapper（Compose 只负责渲染，不再懂快照结构）。
 *
 * 展示规则与 Web `_web_expense_fact.py` 同构：只有用户可写字段产出
 * before→after delta，系统字段（汇率快照/fx_status 等）折叠为一句话；
 * revision id / row_version / actor id 永不进文案。
 */

/** 一条时间线条目的展示模型。 */
data class FactTimelineEntry(
    val isCorrection: Boolean,
    @param:StringRes val kindLabelRes: Int,
    val reason: String,
    val whenText: String,
    val actor: String,
    val changes: List<FactTimelineChange>,
    /** items/splits 触及时的完整 Before/After 集合；空表示无集合明细。 */
    val collections: List<FactTimelineCollectionDetail> = emptyList(),
)

data class FactTimelineChange(
    val label: UiText,
    val before: UiText,
    val after: UiText,
)

/** Before/After 集合中的一行：标题 + 平铺事实（数量/单价/金额/分类 或 金额/备注）。 */
data class FactTimelineCollectionRow(
    val title: UiText,
    val facts: List<UiText>,
)

/** 一个集合字段（items/splits）的完整前后对照；行身份不做跨 revision 推断。 */
data class FactTimelineCollectionDetail(
    @param:StringRes val labelRes: Int,
    val beforeRows: List<FactTimelineCollectionRow>,
    val afterRows: List<FactTimelineCollectionRow>,
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
        "amount_cents" -> UiText.raw(formatHomeAmountSnapshot(value, snapshot, currency))
        "original_amount_minor" -> formatOriginalAmountSnapshot(value, snapshot)
        "expense_time" -> UiText.raw(displayDateTime(value.toString()))
        "items", "splits" -> formatLineCountSnapshot(value)
        else -> UiText.raw(value.toString())
    }
}

private fun formatHomeAmountSnapshot(
    value: Any,
    snapshot: Map<String, Any?>,
    fallbackCurrency: CurrencyCode,
): String = (value as? Number)?.toLong()?.let {
    formatSnapshotHomeMinor(kotlin.math.abs(it), snapshot, fallbackCurrency)
} ?: value.toString()

private fun formatSnapshotHomeMinor(
    amountMinor: Long,
    snapshot: Map<String, Any?>,
    fallbackCurrency: CurrencyCode,
): String {
    val rawHomeCurrency = snapshot["home_currency_code"]?.toString()
        ?.trim()
        ?.uppercase()
        ?.takeIf(String::isNotBlank)
        ?: fallbackCurrency.storageKey
    val display = CurrencyDisplay.forRecord(rawHomeCurrency)
    return display.unknownCode?.let { "$amountMinor $it" }
        ?: formatMinorAmountInput(amountMinor, display.homeCurrency)
}

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
    val amount = formatSnapshotHomeMinor(kotlin.math.abs(remaining), snapshot, currency)
    return if (remaining > 0L) {
        UiText.res(R.string.expense_fact_timeline_allocation_remaining, amount)
    } else {
        UiText.res(R.string.expense_fact_timeline_allocation_overallocated, amount)
    }
}

private fun MutableList<FactTimelineChange>.appendAllocationChange(
    @StringRes labelRes: Int,
    before: Map<String, Any?>,
    after: Map<String, Any?>,
    currency: CurrencyCode,
): Boolean {
    val beforeAllocation = snapshotAllocationLabel(before, currency)
    val afterAllocation = snapshotAllocationLabel(after, currency)
    if (beforeAllocation == null || afterAllocation == null || beforeAllocation == afterAllocation) return false
    add(FactTimelineChange(UiText.res(labelRes), beforeAllocation, afterAllocation))
    return true
}

private fun ExpenseRevision.toTimelineEntry(
    currency: com.ticketbox.domain.model.CurrencyCode,
    memberNames: Map<Long, String>?,
): FactTimelineEntry {
    val isCorrection = changeKind == "correction"
    val collections = mutableListOf<FactTimelineCollectionDetail>()
    val changes = if (!isCorrection) {
        emptyList()
    } else {
        val before = before ?: emptyMap()
        val deltas = buildList {
            FACT_FIELD_ORDER
                .filter { (field, _) -> field in changedFields }
                .forEach { (field, labelRes) ->
                    if (field == "splits") {
                        val beforeCount = formatFactValue(field, before[field], before, currency)
                        val afterCount = formatFactValue(field, after[field], after, currency)
                        val allocationChanged = appendAllocationChange(labelRes, before, after, currency)
                        if (beforeCount != afterCount || !allocationChanged) {
                            add(FactTimelineChange(UiText.res(labelRes), beforeCount, afterCount))
                        }
                        collections += collectionDetail(field, labelRes, before, after, currency, memberNames)
                        return@forEach
                    }
                    add(
                        FactTimelineChange(
                            label = UiText.res(labelRes),
                            before = formatFactValue(field, before[field], before, currency),
                            after = formatFactValue(field, after[field], after, currency),
                        ),
                    )
                    if (field == "items") {
                        collections += collectionDetail(field, labelRes, before, after, currency, memberNames)
                    }
                    if (field == "amount_cents" && "splits" !in changedFields) {
                        appendAllocationChange(
                            R.string.expense_fact_timeline_field_splits,
                            before,
                            after,
                            currency,
                        )
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
        collections = collections,
    )
}

/** 时间线展示模型：newest-first（服务端已按 revision_number desc 返回）。 */
internal fun List<ExpenseRevision>.toTimelineEntries(
    currency: com.ticketbox.domain.model.CurrencyCode,
    memberNames: Map<Long, String>? = null,
): List<FactTimelineEntry> = map { it.toTimelineEntry(currency, memberNames) }

/** items 快照集合行：只呈现 snapshot 已有字段（name/数量/单价/金额/分类）。 */
private fun itemSnapshotRows(
    value: Any?,
    snapshot: Map<String, Any?>,
    currency: CurrencyCode,
): List<FactTimelineCollectionRow> {
    val rows = value as? List<*> ?: return emptyList()
    return rows.mapNotNull { raw ->
        val row = raw as? Map<*, *> ?: return@mapNotNull null
        val name = (row["name"] as? String)?.trim()?.takeIf(String::isNotEmpty)
        val facts = buildList {
            (row["quantity_text"] as? String)?.trim()?.takeIf(String::isNotEmpty)?.let { add(UiText.raw(it)) }
            (row["unit_price_cents"] as? Number)?.toLong()?.let {
                add(
                    UiText.res(
                        R.string.expense_fact_timeline_item_unit_price,
                        formatSnapshotHomeMinor(it, snapshot, currency),
                    ),
                )
            }
            (row["amount_cents"] as? Number)?.toLong()?.let {
                add(
                    UiText.res(
                        R.string.expense_fact_timeline_item_amount,
                        formatSnapshotHomeMinor(it, snapshot, currency),
                    ),
                )
            }
            (row["category"] as? String)?.trim()?.takeIf(String::isNotEmpty)?.let { add(UiText.raw(it)) }
        }
        FactTimelineCollectionRow(
            title = name?.let(UiText::raw) ?: UiText.res(R.string.expense_fact_timeline_item_unnamed),
            facts = facts,
        )
    }
}

/**
 * splits 快照集合行。member_id 是身份事实；显示名只是当前成员目录投影——
 * 命中目录显示当前名；目录已加载但 id 缺失才显示「已移除的成员」；
 * 目录不可用（null）时退化为中性标签，不谎称移除。
 */
private fun splitSnapshotRows(
    value: Any?,
    snapshot: Map<String, Any?>,
    currency: CurrencyCode,
    memberNames: Map<Long, String>?,
): List<FactTimelineCollectionRow> {
    val rows = value as? List<*> ?: return emptyList()
    val directoryAvailable = memberNames != null
    return rows.mapNotNull { raw ->
        val row = raw as? Map<*, *> ?: return@mapNotNull null
        val displayName = (row["member_id"] as? Number)?.toLong()?.let { memberNames?.get(it) }
        val title = when {
            displayName != null -> UiText.raw(displayName)
            directoryAvailable -> UiText.res(R.string.expense_fact_timeline_member_removed)
            else -> UiText.res(R.string.expense_fact_timeline_member_unknown)
        }
        val facts = buildList {
            (row["amount_cents"] as? Number)?.toLong()?.let {
                add(UiText.raw(formatSnapshotHomeMinor(it, snapshot, currency)))
            }
            (row["note"] as? String)?.trim()?.takeIf(String::isNotEmpty)?.let { add(UiText.raw(it)) }
        }
        FactTimelineCollectionRow(title = title, facts = facts)
    }
}

private fun collectionDetail(
    field: String,
    @StringRes labelRes: Int,
    before: Map<String, Any?>,
    after: Map<String, Any?>,
    currency: CurrencyCode,
    memberNames: Map<Long, String>?,
): FactTimelineCollectionDetail {
    val rowsOf: (Map<String, Any?>) -> List<FactTimelineCollectionRow> = { snapshot ->
        if (field == "items") {
            itemSnapshotRows(snapshot[field], snapshot, currency)
        } else {
            splitSnapshotRows(snapshot[field], snapshot, currency, memberNames)
        }
    }
    return FactTimelineCollectionDetail(
        labelRes = labelRes,
        beforeRows = rowsOf(before),
        afterRows = rowsOf(after),
    )
}
