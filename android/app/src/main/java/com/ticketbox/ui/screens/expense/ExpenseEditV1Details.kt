package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatAmount

@Composable
internal fun ExpenseEditV1DetailsSection(
    expenseItems: ExpenseItems?,
    expenseSplits: ExpenseSplits?,
    itemsLoading: Boolean,
    splitsLoading: Boolean,
    itemsMessage: String?,
    splitsMessage: String?,
) {
    ExpenseItemsPanel(
        expenseItems = expenseItems,
        loading = itemsLoading,
        message = itemsMessage,
    )
    ExpenseSplitsPanel(
        expenseSplits = expenseSplits,
        loading = splitsLoading,
        message = splitsMessage,
    )
}

@Composable
private fun ExpenseItemsPanel(
    expenseItems: ExpenseItems?,
    loading: Boolean,
    message: String?,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = "小票明细",
                subtitle = "商品级记录不改变账单金额、统计或导出",
                trailing = expenseItems?.itemsTotalAmountCents?.let(::formatAmount),
            )
            when {
                loading -> DetailMutedText("明细加载中")
                message != null -> DetailMutedText(message)
                expenseItems == null || expenseItems.items.isEmpty() -> DetailMutedText("暂无商品明细")
                else -> {
                    TotalReconcileLine(
                        parentAmountCents = expenseItems.parentAmountCents,
                        detailTotalAmountCents = expenseItems.itemsTotalAmountCents,
                        mismatchCents = expenseItems.mismatchCents,
                    )
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        expenseItems.items.forEach { item ->
                            ExpenseItemRow(item)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ExpenseSplitsPanel(
    expenseSplits: ExpenseSplits?,
    loading: Boolean,
    message: String?,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = "家庭拆账",
                subtitle = "拆账只记录家庭分摊，不改动原始账单金额",
                trailing = expenseSplits?.splitsTotalAmountCents?.let(::formatAmount),
            )
            when {
                loading -> DetailMutedText("拆账加载中")
                message != null -> DetailMutedText(message)
                expenseSplits == null || expenseSplits.splits.isEmpty() -> DetailMutedText("暂无家庭拆账")
                else -> {
                    TotalReconcileLine(
                        parentAmountCents = expenseSplits.parentAmountCents,
                        detailTotalAmountCents = expenseSplits.splitsTotalAmountCents,
                        mismatchCents = expenseSplits.mismatchCents,
                    )
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        expenseSplits.splits.forEach { split ->
                            ExpenseSplitRow(split)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DetailHeader(
    title: String,
    subtitle: String,
    trailing: String?,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(
                text = subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        trailing?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun TotalReconcileLine(
    parentAmountCents: Long?,
    detailTotalAmountCents: Long?,
    mismatchCents: Long?,
) {
    val mismatch = mismatchCents ?: 0L
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusPill(if (mismatch == 0L) "合计一致" else "差额 ${formatAmount(mismatch)}", active = mismatch == 0L)
        Text(
            text = "账单 ${formatAmount(parentAmountCents)} · 明细 ${formatAmount(detailTotalAmountCents)}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ExpenseItemRow(item: ExpenseItem) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = item.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = itemSubtitle(item),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatAmount(item.amountCents),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ExpenseSplitRow(split: ExpenseSplit) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = split.accountName,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = splitSubtitle(split),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatAmount(split.amountCents),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun DetailMutedText(text: String) {
    Text(
        text = text,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
    )
}

private fun itemSubtitle(item: ExpenseItem): String {
    val parts = mutableListOf<String>()
    item.quantityText?.takeIf { it.isNotBlank() }?.let { parts += it }
    item.unitPriceCents?.let { parts += "单价 ${formatAmount(it)}" }
    item.category.takeIf { it.isNotBlank() }?.let { parts += it }
    if (item.isOcrDraft) parts += "OCR草稿"
    return parts.joinToString(" · ").ifBlank { "未补充明细信息" }
}

private fun splitSubtitle(split: ExpenseSplit): String {
    val parts = mutableListOf(ledgerRoleLabel(split.role))
    split.note?.takeIf { it.isNotBlank() }?.let { parts += it }
    if (split.isDisabledMember) parts += "成员已停用"
    return parts.joinToString(" · ")
}
