package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText

internal data class TimelineCollectionContext(
    val before: Map<String, Any?>,
    val after: Map<String, Any?>,
    val currency: CurrencyCode,
    val memberNames: Map<Long, String>?,
)

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

internal fun timelineCollectionDetail(
    field: String,
    @StringRes labelRes: Int,
    context: TimelineCollectionContext,
): FactTimelineCollectionDetail {
    val rowsOf: (Map<String, Any?>) -> List<FactTimelineCollectionRow> = { snapshot ->
        if (field == "items") {
            itemSnapshotRows(snapshot[field], snapshot, context.currency)
        } else {
            splitSnapshotRows(snapshot[field], snapshot, context.currency, context.memberNames)
        }
    }
    return FactTimelineCollectionDetail(
        labelRes = labelRes,
        beforeRows = rowsOf(context.before),
        afterRows = rowsOf(context.after),
    )
}
