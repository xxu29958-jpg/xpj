package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.asString
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
    itemsMessage: UiText?,
    splitsMessage: UiText?,
    onAcknowledgeItemsMismatch: () -> Unit = {},
    onEditItems: (() -> Unit)? = null,
    onEditSplits: (() -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    ExpenseItemsPanel(
        expenseItems = expenseItems,
        loading = itemsLoading,
        message = itemsMessage,
        currencyDisplay = currencyDisplay,
        onAcknowledgeMismatch = onAcknowledgeItemsMismatch,
        onEditItems = onEditItems,
    )
    ExpenseSplitsPanel(
        expenseSplits = expenseSplits,
        loading = splitsLoading,
        message = splitsMessage,
        currencyDisplay = currencyDisplay,
        onEditSplits = onEditSplits,
    )
}

@Composable
private fun ExpenseItemsPanel(
    expenseItems: ExpenseItems?,
    loading: Boolean,
    message: UiText?,
    currencyDisplay: CurrencyDisplay,
    onAcknowledgeMismatch: () -> Unit,
    onEditItems: (() -> Unit)? = null,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = stringResource(R.string.expense_edit_v1_items_title),
                subtitle = stringResource(R.string.expense_edit_v1_items_subtitle),
                trailing = expenseItems?.itemsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
            )
            if (onEditItems != null && !loading) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onEditItems) {
                        Text(
                            if (expenseItems?.items.isNullOrEmpty()) {
                                stringResource(R.string.expense_edit_v1_items_add_button)
                            } else {
                                stringResource(R.string.expense_edit_v1_items_edit_button)
                            }
                        )
                    }
                }
            }
            when {
                loading -> DetailLoadingState(
                    title = stringResource(R.string.expense_edit_v1_items_loading_title),
                    body = stringResource(R.string.expense_edit_v1_items_loading_body),
                )
                message != null -> DetailEmptyState(message.asString())
                expenseItems == null || expenseItems.items.isEmpty() -> DetailEmptyState(stringResource(R.string.expense_edit_v1_items_empty))
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

@Composable
private fun kindGroupTitle(kind: String): String = when (kind) {
    ExpenseItemKind.PRODUCT -> stringResource(R.string.expense_edit_item_group_product)
    ExpenseItemKind.DISCOUNT -> stringResource(R.string.expense_edit_item_group_discount)
    ExpenseItemKind.TAX -> stringResource(R.string.expense_edit_item_group_tax)
    ExpenseItemKind.SERVICE_FEE -> stringResource(R.string.expense_edit_item_group_service_fee)
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
                text = stringResource(R.string.expense_edit_v1_items_mismatch_title, diff),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.expense_edit_v1_items_mismatch_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = onAcknowledge) {
                Text(stringResource(R.string.expense_edit_v1_items_mismatch_ack_button))
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
                text = stringResource(R.string.expense_edit_v1_items_mismatch_acknowledged, diff),
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
    message: UiText?,
    currencyDisplay: CurrencyDisplay,
    onEditSplits: (() -> Unit)? = null,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = stringResource(R.string.expense_edit_v1_splits_title),
                subtitle = stringResource(R.string.expense_edit_v1_splits_subtitle),
                trailing = expenseSplits?.splitsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
            )
            if (onEditSplits != null && !loading) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onEditSplits) {
                        Text(
                            if (expenseSplits?.splits.isNullOrEmpty()) {
                                stringResource(R.string.expense_edit_v1_splits_add_button)
                            } else {
                                stringResource(R.string.expense_edit_v1_splits_edit_button)
                            }
                        )
                    }
                }
            }
            when {
                loading -> DetailLoadingState(
                    title = stringResource(R.string.expense_edit_v1_splits_loading_title),
                    body = stringResource(R.string.expense_edit_v1_splits_loading_body),
                )
                message != null -> DetailEmptyState(message.asString())
                expenseSplits == null || expenseSplits.splits.isEmpty() -> DetailEmptyState(stringResource(R.string.expense_edit_v1_splits_empty))
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

/**
 * UI/UX 第三波 批 13：跨账本「找家人分摊」卡（发起拆账邀请）。仅在账单可发起拆账时
 * 由 host 渲染（confirmed + 有金额 + 非收到拆账 + 可写）。展示本票已发邀请（invited
 * 行带撤回）+「发起拆账」按钮。文案上与上方「家庭拆账（份额）」卡刻意区分——份额记在
 * 本账本，拆账是发邀请到家人**自己**的账本，接受后两笔互不影响。
 */
@Composable
internal fun ExpenseBillSplitInvitePanel(
    sent: List<BillSplitSent>,
    loading: Boolean,
    message: UiText?,
    onStartInvite: () -> Unit,
    onCancelInvite: (publicId: String) -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            DetailHeader(
                title = stringResource(R.string.expense_edit_bill_split_card_title),
                subtitle = stringResource(R.string.expense_edit_bill_split_card_subtitle),
                trailing = null,
            )
            when {
                loading -> DetailLoadingState(
                    title = stringResource(R.string.expense_edit_bill_split_loading),
                    body = stringResource(R.string.expense_edit_bill_split_card_subtitle),
                )
                message != null -> DetailEmptyState(message.asString())
                sent.isEmpty() -> DetailEmptyState(stringResource(R.string.expense_edit_bill_split_empty))
                else -> BillSplitSentList(
                    sent = sent,
                    currencyDisplay = currencyDisplay,
                    onCancelInvite = onCancelInvite,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                Button(onClick = onStartInvite, enabled = !loading) {
                    Text(stringResource(R.string.expense_edit_bill_split_start_button))
                }
            }
        }
    }
}

@Composable
private fun BillSplitSentList(
    sent: List<BillSplitSent>,
    currencyDisplay: CurrencyDisplay,
    onCancelInvite: (publicId: String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        sent.forEach { row ->
            BillSplitSentRow(
                row = row,
                currencyDisplay = currencyDisplay,
                onCancel = { onCancelInvite(row.publicId) },
            )
        }
    }
}

@Composable
private fun BillSplitSentRow(
    row: BillSplitSent,
    currencyDisplay: CurrencyDisplay,
    onCancel: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            val receiverName = row.receiverDisplayNameSnapshot?.takeIf { it.isNotBlank() }
            Text(
                text = if (receiverName != null) {
                    stringResource(R.string.expense_edit_bill_split_row_to, receiverName)
                } else {
                    stringResource(R.string.expense_edit_bill_split_row_to_unknown)
                },
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = billSplitSentStatusLabel(row.status),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text(
            text = formatDisplayAmount(row.amountCents, currencyDisplay),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            TextButton(onClick = onCancel) {
                Text(stringResource(R.string.expense_edit_bill_split_row_cancel))
            }
        }
    }
}

@Composable
private fun billSplitSentStatusLabel(status: String): String = stringResource(
    when (status) {
        BillSplitStatusValues.INVITED -> R.string.expense_edit_bill_split_status_invited
        BillSplitStatusValues.ACCEPTED -> R.string.expense_edit_bill_split_status_accepted
        BillSplitStatusValues.REJECTED -> R.string.expense_edit_bill_split_status_rejected
        BillSplitStatusValues.CANCELLED -> R.string.expense_edit_bill_split_status_cancelled
        else -> R.string.expense_edit_bill_split_status_expired
    },
)

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
                color = MaterialTheme.colorScheme.onSurface,
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
            if (mismatch == 0L) {
                stringResource(R.string.expense_edit_v1_reconcile_match_pill)
            } else {
                stringResource(R.string.expense_edit_v1_reconcile_diff_pill, formatDisplayAmount(mismatch, currencyDisplay))
            },
            active = mismatch == 0L,
        )
        Text(
            text = stringResource(
                R.string.expense_edit_v1_reconcile_amounts,
                formatDisplayAmount(parentAmountCents, currencyDisplay),
                formatDisplayAmount(detailTotalAmountCents, currencyDisplay),
            ),
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

@Composable
private fun itemSubtitle(item: ExpenseItem, currencyDisplay: CurrencyDisplay): String {
    val parts = mutableListOf<String>()
    item.quantityText?.takeIf { it.isNotBlank() }?.let { parts += it }
    item.unitPriceCents?.let {
        parts += stringResource(R.string.expense_edit_item_subtitle_unit_price, formatDisplayAmount(it, currencyDisplay))
    }
    item.category.takeIf { it.isNotBlank() }?.let { parts += it }
    if (item.isOcrDraft) parts += stringResource(R.string.expense_edit_item_subtitle_ocr_draft)
    return parts.joinToString(" · ").ifBlank { stringResource(R.string.expense_edit_item_subtitle_empty) }
}

@Composable
private fun splitSubtitle(split: ExpenseSplit): String {
    val parts = mutableListOf(ledgerRoleLabel(split.role))
    split.note?.takeIf { it.isNotBlank() }?.let { parts += it }
    if (split.isDisabledMember) parts += stringResource(R.string.expense_edit_split_subtitle_member_disabled)
    return parts.joinToString(" · ")
}
