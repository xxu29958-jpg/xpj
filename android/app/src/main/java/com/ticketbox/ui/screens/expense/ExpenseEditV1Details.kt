package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay

@Composable
internal fun ExpenseEditV1DetailsSection(
    expenseItems: ExpenseItems?,
    expenseSplits: ExpenseSplits?,
    itemsLoading: Boolean,
    splitsLoading: Boolean,
    itemsMessage: String?,
    splitsMessage: String?,
    onAcknowledgeItemsMismatch: () -> Unit = {},
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    ExpenseItemsPanel(
        expenseItems = expenseItems,
        loading = itemsLoading,
        message = itemsMessage,
        currencyDisplay = currencyDisplay,
        onAcknowledgeMismatch = onAcknowledgeItemsMismatch,
    )
    ExpenseSplitsPanel(
        expenseSplits = expenseSplits,
        loading = splitsLoading,
        message = splitsMessage,
        currencyDisplay = currencyDisplay,
    )
}

@Composable
private fun ExpenseItemsPanel(
    expenseItems: ExpenseItems?,
    loading: Boolean,
    message: String?,
    currencyDisplay: CurrencyDisplay,
    onAcknowledgeMismatch: () -> Unit,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = "小票明细",
                subtitle = "商品级记录不改变账单金额、统计或导出",
                trailing = expenseItems?.itemsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
            )
            when {
                loading -> DetailLoadingState(
                    title = "明细加载中",
                    body = "商品级记录加载完成后会显示在这里。",
                )
                message != null -> DetailEmptyState(message)
                expenseItems == null || expenseItems.items.isEmpty() -> DetailEmptyState("暂无商品明细")
                else -> {
                    TotalReconcileLine(
                        parentAmountCents = expenseItems.parentAmountCents,
                        detailTotalAmountCents = expenseItems.itemsTotalAmountCents,
                        mismatchCents = expenseItems.mismatchCents,
                        currencyDisplay = currencyDisplay,
                    )
                    // ADR-0035 mismatch banner
                    if (expenseItems.mismatchKnown) {
                        ItemsSumMismatchBanner(
                            mismatchCents = expenseItems.mismatchCents,
                            currencyDisplay = currencyDisplay,
                            onAcknowledge = onAcknowledgeMismatch,
                        )
                    } else if (expenseItems.mismatchAcknowledged) {
                        ItemsSumAcknowledgedBanner(
                            mismatchCents = expenseItems.mismatchCents,
                            currencyDisplay = currencyDisplay,
                        )
                    }
                    // ADR-0035: group items by kind (product / discount / tax / service_fee)
                    val grouped = expenseItems.items.groupBy { it.kind }
                    val orderedKinds = listOf(
                        ExpenseItemKind.PRODUCT,
                        ExpenseItemKind.DISCOUNT,
                        ExpenseItemKind.TAX,
                        ExpenseItemKind.SERVICE_FEE,
                    )
                    orderedKinds.forEach { kind ->
                        val rows = grouped[kind].orEmpty()
                        if (rows.isNotEmpty()) {
                            Text(
                                text = kindGroupTitle(kind),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                rows.forEach { item ->
                                    ExpenseItemRow(item, currencyDisplay)
                                }
                            }
                        }
                    }
                    // Catch-all: unknown kinds (forward compatibility for v1.x)
                    grouped
                        .filterKeys { it !in orderedKinds }
                        .forEach { (kind, rows) ->
                            Text(
                                text = kind,
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                rows.forEach { item -> ExpenseItemRow(item, currencyDisplay) }
                            }
                        }
                }
            }
        }
    }
}

private fun kindGroupTitle(kind: String): String = when (kind) {
    ExpenseItemKind.PRODUCT -> "商品"
    ExpenseItemKind.DISCOUNT -> "优惠 / 折扣"
    ExpenseItemKind.TAX -> "税"
    ExpenseItemKind.SERVICE_FEE -> "服务费"
    else -> kind
}

@Composable
private fun ItemsSumMismatchBanner(
    mismatchCents: Long?,
    currencyDisplay: CurrencyDisplay,
    onAcknowledge: () -> Unit,
) {
    val diff = mismatchCents?.let { formatDisplayAmount(kotlin.math.abs(it), currencyDisplay) } ?: ""
    AppEmptyStateCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "明细合计与账单金额相差 $diff",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "检查商品行，或如果原小票本身就是这个金额，可以确认差异。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = onAcknowledge) {
                Text("原小票如此")
            }
        }
    }
}

@Composable
private fun ItemsSumAcknowledgedBanner(
    mismatchCents: Long?,
    currencyDisplay: CurrencyDisplay,
) {
    val diff = mismatchCents?.let { formatDisplayAmount(kotlin.math.abs(it), currencyDisplay) } ?: ""
    AppEmptyStateCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = "已确认原小票合计与明细存在 $diff 差异",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ExpenseSplitsPanel(
    expenseSplits: ExpenseSplits?,
    loading: Boolean,
    message: String?,
    currencyDisplay: CurrencyDisplay,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = "家庭拆账",
                subtitle = "拆账只记录家庭分摊，不改动原始账单金额",
                trailing = expenseSplits?.splitsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
            )
            when {
                loading -> DetailLoadingState(
                    title = "拆账加载中",
                    body = "家庭成员分摊加载完成后会显示在这里。",
                )
                message != null -> DetailEmptyState(message)
                expenseSplits == null || expenseSplits.splits.isEmpty() -> DetailEmptyState("暂无家庭拆账")
                else -> {
                    TotalReconcileLine(
                        parentAmountCents = expenseSplits.parentAmountCents,
                        detailTotalAmountCents = expenseSplits.splitsTotalAmountCents,
                        mismatchCents = expenseSplits.mismatchCents,
                        currencyDisplay = currencyDisplay,
                    )
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        expenseSplits.splits.forEach { split ->
                            ExpenseSplitRow(split, currencyDisplay)
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
                fontWeight = AppTextHierarchy.heading.weight,
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
    currencyDisplay: CurrencyDisplay,
) {
    val mismatch = mismatchCents ?: 0L
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusPill(
            if (mismatch == 0L) "合计一致" else "差额 ${formatDisplayAmount(mismatch, currencyDisplay)}",
            active = mismatch == 0L,
        )
        Text(
            text = "账单 ${formatDisplayAmount(parentAmountCents, currencyDisplay)} · 明细 ${formatDisplayAmount(detailTotalAmountCents, currencyDisplay)}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ExpenseItemRow(item: ExpenseItem, currencyDisplay: CurrencyDisplay) {
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
                    text = itemSubtitle(item, currencyDisplay),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatDisplayAmount(item.amountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ExpenseSplitRow(split: ExpenseSplit, currencyDisplay: CurrencyDisplay) {
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
                text = formatDisplayAmount(split.amountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun DetailLoadingState(
    title: String,
    body: String,
) {
    AppLoadingState(
        title = title,
        body = body,
    )
}

@Composable
private fun DetailEmptyState(text: String) {
    AppEmptyStateCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = text,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

private fun itemSubtitle(item: ExpenseItem, currencyDisplay: CurrencyDisplay): String {
    val parts = mutableListOf<String>()
    item.quantityText?.takeIf { it.isNotBlank() }?.let { parts += it }
    item.unitPriceCents?.let { parts += "单价 ${formatDisplayAmount(it, currencyDisplay)}" }
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
