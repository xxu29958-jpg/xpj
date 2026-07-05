package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay

internal data class ExpenseBillSplitInvitePanelState(
    val sent: List<BillSplitSent>,
    val loading: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

internal data class ExpenseBillSplitInvitePanelActions(
    val onStartInvite: () -> Unit,
    val onCancelInvite: (publicId: String) -> Unit,
)

@Composable
internal fun ExpenseEditV1DetailsSection(
    expenseItems: ExpenseItems?,
    expenseSplits: ExpenseSplits?,
    itemsLoading: Boolean,
    splitsLoading: Boolean,
    itemsMessage: UiText?,
    splitsMessage: UiText?,
    itemsMessageTone: MessageTone,
    splitsMessageTone: MessageTone,
    onAcknowledgeItemsMismatch: () -> Unit = {},
    onEditItems: (() -> Unit)? = null,
    onEditSplits: (() -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val itemsState = DetailLoadState(itemsLoading, itemsMessage, itemsMessageTone)
    val splitsState = DetailLoadState(splitsLoading, splitsMessage, splitsMessageTone)

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ExpenseItemsPanel(
            expenseItems = expenseItems,
            state = itemsState,
            currencyDisplay = currencyDisplay,
            onAcknowledgeMismatch = onAcknowledgeItemsMismatch,
            onEditItems = onEditItems,
        )
        ExpenseDetailDivider()
        ExpenseSplitsPanel(
            expenseSplits = expenseSplits,
            state = splitsState,
            currencyDisplay = currencyDisplay,
            onEditSplits = onEditSplits,
        )
        ExpenseDetailDivider()
    }
}

@Composable
private fun ExpenseItemsPanel(
    expenseItems: ExpenseItems?,
    state: DetailLoadState,
    currencyDisplay: CurrencyDisplay,
    onAcknowledgeMismatch: () -> Unit,
    onEditItems: (() -> Unit)? = null,
) {
    val canEditItems = onEditItems != null
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        DetailHeader(
            title = stringResource(R.string.expense_edit_v1_items_title),
            subtitle = stringResource(R.string.expense_edit_v1_items_subtitle),
            trailing = expenseItems?.itemsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
        )
        if (onEditItems != null && !state.loading) {
            ExpenseDetailActionButtonRow(
                text = if (expenseItems?.items.isNullOrEmpty()) {
                    stringResource(R.string.expense_edit_v1_items_add_button)
                } else {
                    stringResource(R.string.expense_edit_v1_items_edit_button)
                },
                icon = if (expenseItems?.items.isNullOrEmpty()) Icons.Filled.Add else Icons.Filled.Edit,
                onClick = onEditItems,
            )
        }
        if (!canEditItems) {
            AppDataAuthorityStrip(
                title = stringResource(R.string.components_data_authority_readonly_title),
                body = stringResource(R.string.expense_edit_v1_items_readonly_body),
                tone = DataAuthorityTone.ReadOnly,
            )
        }
        val loadedItems = expenseItems?.takeIf { it.items.isNotEmpty() }
        DetailStateSlot(
            state = state,
            hasData = loadedItems != null,
            copy = DetailStateCopy(
                loadingTitle = stringResource(R.string.expense_edit_v1_items_loading_title),
                loadingBody = stringResource(R.string.expense_edit_v1_items_loading_body),
                emptyText = stringResource(R.string.expense_edit_v1_items_empty),
            ),
        )
        loadedItems?.let { items ->
            TotalReconcileLine(
                parentAmountCents = items.parentAmountCents,
                detailTotalAmountCents = items.itemsTotalAmountCents,
                mismatchCents = items.mismatchCents,
                itemsSumStatus = items.itemsSumStatus,
                currencyDisplay = currencyDisplay,
            )
            // ADR-0035 mismatch banner
            if (items.mismatchKnown) {
                ItemsSumMismatchBanner(
                    mismatchCents = items.mismatchCents,
                    currencyDisplay = currencyDisplay,
                    onAcknowledge = if (canEditItems) onAcknowledgeMismatch else null,
                )
            } else if (items.mismatchAcknowledged) {
                ItemsSumAcknowledgedBanner(
                    mismatchCents = items.mismatchCents,
                    currencyDisplay = currencyDisplay,
                )
            }
            // ADR-0035: group items by kind (product / discount / tax / service_fee)
            val grouped = items.items.groupBy { it.kind }
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
                    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
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
                    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                        rows.forEach { item -> ExpenseItemRow(item, currencyDisplay) }
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
    onAcknowledge: (() -> Unit)?,
) {
    val diff = mismatchCents?.let { formatDisplayAmount(kotlin.math.abs(it), currencyDisplay) }
    val bannerCopy: @Composable () -> Unit = {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = stringResource(R.string.expense_edit_v1_items_mismatch_title),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.expense_edit_v1_items_mismatch_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    AppEmptyStateCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            if (diff == null) {
                bannerCopy()
            } else {
                AppAdaptiveEditAmountRow(amount = diff) {
                    bannerCopy()
                }
            }
            onAcknowledge?.let {
                ExpenseDetailActionButtonRow(
                    text = stringResource(R.string.expense_edit_v1_items_mismatch_ack_button),
                    icon = Icons.Filled.Check,
                    onClick = it,
                )
            }
        }
    }
}

@Composable
private fun ItemsSumAcknowledgedBanner(
    mismatchCents: Long?,
    currencyDisplay: CurrencyDisplay,
) {
    val diff = mismatchCents?.let { formatDisplayAmount(kotlin.math.abs(it), currencyDisplay) }
    AppEmptyStateCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            if (diff == null) {
                Text(
                    text = stringResource(R.string.expense_edit_v1_items_mismatch_acknowledged),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                AppAdaptiveEditAmountRow(amount = diff) {
                    Text(
                        text = stringResource(R.string.expense_edit_v1_items_mismatch_acknowledged),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun ExpenseSplitsPanel(
    expenseSplits: ExpenseSplits?,
    state: DetailLoadState,
    currencyDisplay: CurrencyDisplay,
    onEditSplits: (() -> Unit)? = null,
) {
    val editSplitsAction = onEditSplits?.takeUnless { state.loading }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        DetailHeader(
            title = stringResource(R.string.expense_edit_v1_splits_title),
            subtitle = stringResource(R.string.expense_edit_v1_splits_subtitle),
            trailing = expenseSplits?.splitsTotalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) },
        )
        editSplitsAction?.let {
            ExpenseDetailActionButtonRow(
                text = if (expenseSplits?.splits.isNullOrEmpty()) {
                    stringResource(R.string.expense_edit_v1_splits_add_button)
                } else {
                    stringResource(R.string.expense_edit_v1_splits_edit_button)
                },
                icon = if (expenseSplits?.splits.isNullOrEmpty()) Icons.Filled.Add else Icons.Filled.Edit,
                onClick = it,
            )
        }
        if (onEditSplits == null) {
            AppDataAuthorityStrip(
                title = stringResource(R.string.components_data_authority_readonly_title),
                body = stringResource(R.string.expense_edit_v1_splits_readonly_body),
                tone = DataAuthorityTone.ReadOnly,
            )
        }
        val loadedSplits = expenseSplits?.takeIf { it.splits.isNotEmpty() }
        DetailStateSlot(
            state = state,
            hasData = loadedSplits != null,
            copy = DetailStateCopy(
                loadingTitle = stringResource(R.string.expense_edit_v1_splits_loading_title),
                loadingBody = stringResource(R.string.expense_edit_v1_splits_loading_body),
                emptyText = stringResource(R.string.expense_edit_v1_splits_empty),
            ),
        )
        loadedSplits?.let { splits ->
            TotalReconcileLine(
                parentAmountCents = splits.parentAmountCents,
                detailTotalAmountCents = splits.splitsTotalAmountCents,
                mismatchCents = splits.mismatchCents,
                currencyDisplay = currencyDisplay,
            )
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                splits.splits.forEach { split ->
                    ExpenseSplitRow(split, currencyDisplay)
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
    state: ExpenseBillSplitInvitePanelState,
    actions: ExpenseBillSplitInvitePanelActions,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        DetailHeader(
            title = stringResource(R.string.expense_edit_bill_split_card_title),
            subtitle = stringResource(R.string.expense_edit_bill_split_card_subtitle),
            trailing = null,
        )
        DetailStateSlot(
            state = DetailLoadState(state.loading, state.message, state.messageTone),
            hasData = state.sent.isNotEmpty(),
            copy = DetailStateCopy(
                loadingTitle = stringResource(R.string.expense_edit_bill_split_loading),
                loadingBody = stringResource(R.string.expense_edit_bill_split_card_subtitle),
                emptyText = stringResource(R.string.expense_edit_bill_split_empty),
            ),
        )
        if (state.sent.isNotEmpty()) {
            BillSplitSentList(
                sent = state.sent,
                currencyDisplay = currencyDisplay,
                actionsEnabled = !state.loading,
                onCancelInvite = actions.onCancelInvite,
            )
        }
        ExpenseDetailActionButtonRow(
            text = stringResource(R.string.expense_edit_bill_split_start_button),
            icon = Icons.Filled.GroupAdd,
            enabled = !state.loading,
            onClick = actions.onStartInvite,
        )
        ExpenseDetailDivider()
    }
}

@Composable
private fun BillSplitSentList(
    sent: List<BillSplitSent>,
    currencyDisplay: CurrencyDisplay,
    actionsEnabled: Boolean,
    onCancelInvite: (publicId: String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        sent.forEach { row ->
            BillSplitSentRow(
                row = row,
                currencyDisplay = currencyDisplay,
                actionsEnabled = actionsEnabled,
                onCancel = { onCancelInvite(row.publicId) },
            )
        }
    }
}

@Composable
private fun BillSplitSentRow(
    row: BillSplitSent,
    currencyDisplay: CurrencyDisplay,
    actionsEnabled: Boolean,
    onCancel: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppAdaptiveEditAmountRow(
            amount = formatDisplayAmount(row.amountCents, currencyDisplay),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
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
        }
        if (row.status == BillSplitStatusValues.INVITED) {
            ExpenseDetailActionButtonRow(
                text = stringResource(R.string.expense_edit_bill_split_row_cancel),
                icon = Icons.Filled.Close,
                enabled = actionsEnabled,
                onClick = onCancel,
            )
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
    if (trailing == null) {
        AppSectionHeader(
            title = title,
            subtitle = subtitle,
        )
        return
    }
    AppAdaptiveEditAmountRow(amount = trailing) {
        AppSectionHeader(
            title = title,
            subtitle = subtitle,
        )
    }
}

@Composable
private fun TotalReconcileLine(
    parentAmountCents: Long?,
    detailTotalAmountCents: Long?,
    mismatchCents: Long?,
    itemsSumStatus: String? = null,
    currencyDisplay: CurrencyDisplay,
) {
    val reconcileStatus = resolveExpenseDetailReconcileStatus(
        mismatchCents = mismatchCents,
        itemsSumStatus = itemsSumStatus,
    )
    val parentLabel = stringResource(R.string.expense_edit_v1_reconcile_parent_label)
    val detailLabel = stringResource(R.string.expense_edit_v1_reconcile_detail_label)
    val diffLabel = stringResource(R.string.expense_edit_v1_reconcile_diff_label)
    val amountRows = buildList {
        add(
            parentLabel to
                formatDisplayAmount(parentAmountCents, currencyDisplay),
        )
        add(
            detailLabel to
                formatDisplayAmount(detailTotalAmountCents, currencyDisplay),
        )
        if (reconcileStatus == ExpenseDetailReconcileStatus.Diff && mismatchCents != null) {
            add(
                diffLabel to
                    formatDisplayAmount(mismatchCents, currencyDisplay),
            )
        }
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.Top,
    ) {
        StatusPill(
            text = reconcileStatus.label(),
            active = reconcileStatus == ExpenseDetailReconcileStatus.Matched,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            amountRows.forEach { (label, amount) ->
                ReconcileAmountLine(label = label, amount = amount)
            }
        }
    }
}

@Composable
private fun ExpenseDetailReconcileStatus.label(): String = stringResource(
    when (this) {
        ExpenseDetailReconcileStatus.Matched -> R.string.expense_edit_v1_reconcile_match_pill
        ExpenseDetailReconcileStatus.Diff -> R.string.expense_edit_v1_reconcile_diff_pill
        ExpenseDetailReconcileStatus.Unknown -> R.string.expense_edit_v1_reconcile_unknown_pill
    },
)

@Composable
private fun ReconcileAmountLine(label: String, amount: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        AppEndAlignedAmountText(
            modifier = Modifier.weight(1f),
            text = amount,
            role = AppAmountRole.Compact,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ExpenseItemRow(item: ExpenseItem, currencyDisplay: CurrencyDisplay) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppAdaptiveEditAmountRow(
            amount = formatDisplayAmount(item.amountCents, currencyDisplay),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    text = item.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                itemSubtitle(item)?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        item.unitPriceCents?.let {
            ReconcileAmountLine(
                label = stringResource(R.string.expense_edit_item_subtitle_unit_price),
                amount = formatDisplayAmount(it, currencyDisplay),
            )
        }
    }
}

@Composable
private fun ExpenseSplitRow(split: ExpenseSplit, currencyDisplay: CurrencyDisplay) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppAdaptiveEditAmountRow(
            amount = formatDisplayAmount(split.amountCents, currencyDisplay),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
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
        }
    }
}

private data class DetailStateCopy(
    val loadingTitle: String,
    val loadingBody: String,
    val emptyText: String,
)

private data class DetailLoadState(
    val loading: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

@Composable
private fun DetailStateSlot(
    state: DetailLoadState,
    hasData: Boolean,
    copy: DetailStateCopy,
) {
    AppContentStateSlot(
        state = AppContentStateSpec(
            loading = state.loading,
            hasData = hasData,
            copy = AppContentStateCopy(
                loadingTitle = copy.loadingTitle,
                loadingBody = copy.loadingBody,
                emptyText = copy.emptyText,
            ),
            message = state.message,
            messageTone = state.messageTone,
            presentation = AppContentStatePresentation.Card,
            showLoadingWithData = true,
        ),
    )
}

@Composable
private fun itemSubtitle(item: ExpenseItem): String? {
    val parts = mutableListOf<String>()
    item.quantityText?.takeIf { it.isNotBlank() }?.let { parts += it }
    item.category.takeIf { it.isNotBlank() }?.let { parts += it }
    if (item.isOcrDraft) parts += stringResource(R.string.expense_edit_item_subtitle_ocr_draft)
    return parts.joinToString(" · ").ifBlank {
        if (item.unitPriceCents == null) stringResource(R.string.expense_edit_item_subtitle_empty) else null
    }
}

@Composable
private fun splitSubtitle(split: ExpenseSplit): String {
    val parts = mutableListOf(ledgerRoleLabel(split.role))
    split.note?.takeIf { it.isNotBlank() }?.let { parts += it }
    if (split.isDisabledMember) parts += stringResource(R.string.expense_edit_split_subtitle_member_disabled)
    return parts.joinToString(" · ")
}

@Composable
private fun ExpenseDetailDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
}
