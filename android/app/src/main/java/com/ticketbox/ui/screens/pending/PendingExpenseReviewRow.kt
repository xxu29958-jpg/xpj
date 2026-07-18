package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveContentActionStateRow
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppEndAlignedAmountStatusText
import com.ticketbox.ui.components.appTapWithoutDrag
import com.ticketbox.ui.components.displayCompactTime
import com.ticketbox.ui.components.formatExpenseExchangeMeta
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppDensity
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone

@Immutable
internal data class PendingExpenseReviewItem(
    val expense: Expense,
    val thumbnail: ProtectedImage?,
    val compact: Boolean,
    val showInlineActions: Boolean,
    val busy: Boolean,
)

@Immutable
internal data class PendingExpenseReviewActions(
    val canMutate: Boolean,
    val onEdit: () -> Unit,
    val onPrimaryAction: () -> Unit,
    val onReject: () -> Unit,
    val onKeepDuplicate: () -> Unit,
)

@Composable
internal fun PendingExpenseReviewRow(
    item: PendingExpenseReviewItem,
    actions: PendingExpenseReviewActions,
    modifier: Modifier = Modifier,
) {
    val metrics = AppDensity.rowMetrics(
        if (item.compact) AppListDensity.Compact else AppListDensity.Standard,
    )
    Column(
        modifier = modifier
            .fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(
                horizontal = if (item.compact) AppSpacing.miniGap else metrics.rowPadding,
                vertical = if (item.compact) AppSpacing.smallGap else metrics.rowPadding,
            ),
            verticalArrangement = Arrangement.spacedBy(metrics.contentGap),
        ) {
            AppAdaptiveContentActionStateRow(
                wideActionWeight = AppAdaptiveAmountRowDefaults.reviewTrailingWeight,
                verticalAlignment = Alignment.CenterVertically,
                content = {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .appTapWithoutDrag(enabled = !item.busy, onTap = actions.onEdit),
                        horizontalArrangement = Arrangement.spacedBy(metrics.itemSpacing),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PendingExpenseLeadingMark(item)
                        PendingExpenseTextBlock(item)
                    }
                },
                action = { amountModifier, stacked ->
                    PendingExpenseAmountBlock(
                        expense = item.expense,
                        actions = actions,
                        modifier = if (stacked) {
                            amountModifier
                        } else {
                            amountModifier.widthIn(
                                min = AppAdaptiveAmountRowDefaults.statusMinWidth,
                                max = AppAdaptiveAmountRowDefaults.secondaryMetaInlineMaxWidth,
                            )
                        },
                        stacked = stacked,
                    )
                },
            )
            if (item.showInlineActions) {
                PendingExpenseInlineActions(item.expense, actions)
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun PendingExpenseLeadingMark(item: PendingExpenseReviewItem) {
    val size = if (item.compact) DpSize(40.dp, 52.dp) else DpSize(46.dp, 60.dp)
    if (item.expense.imagePath != null) {
        AppAsyncImage(
            image = item.thumbnail,
            presentation = AppAsyncImagePresentation(
                placeholder = stringResource(R.string.pending_row_image_placeholder),
                contentDescription = stringResource(R.string.components_async_image_content_description),
                shape = RoundedCornerShape(AppRadius.small),
                contentScale = ContentScale.Crop,
            ),
            layout = AppAsyncImageLayout(compact = true, compactSize = size),
        )
    } else {
        PendingCategoryMark(item.expense.category, size)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RowScope.PendingExpenseTextBlock(item: PendingExpenseReviewItem) {
    val expense = item.expense
    val merchant = pendingMerchantPresentation(expense)
    Column(
        modifier = Modifier.weight(1f),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = merchant.primaryText
                ?: stringResource(R.string.pending_row_merchant_placeholder),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(
                R.string.pending_row_meta,
                displayCompactTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            PendingExpenseSignals(expense)
        }
        if (!item.compact) {
            expense.note?.takeIf { it.isNotBlank() }?.let {
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
}

@Composable
private fun PendingExpenseAmountBlock(
    expense: Expense,
    actions: PendingExpenseReviewActions,
    modifier: Modifier = Modifier,
    stacked: Boolean = false,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        PendingAmountValue(expense = expense)
        PendingExpenseExchangeMetaText(expense = expense, stacked = stacked)
        TextButton(
            enabled = actions.canMutate,
            onClick = actions.onPrimaryAction,
            modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
            contentPadding = PaddingValues(horizontal = AppSpacing.smallGap, vertical = AppSpacing.none),
        ) {
            Text(
                text = stringResource(pendingPrimaryActionLabelRes(expense)),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun PendingAmountValue(expense: Expense) {
    val amount = expense.amountCents?.let { formatExpensePrimaryAmount(expense) }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .widthIn(min = AppAdaptiveAmountRowDefaults.statusMinWidth),
        contentAlignment = Alignment.CenterEnd,
    ) {
        if (amount == null) {
            AppEndAlignedAmountStatusText(
                modifier = Modifier.fillMaxWidth(),
                text = stringResource(R.string.pending_row_amount_missing),
                role = AppAmountRole.Compact,
            )
        } else {
            AppEndAlignedAmountText(
                modifier = Modifier.fillMaxWidth(),
                text = amount,
                role = AppAmountRole.Compact,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

@Composable
private fun PendingExpenseExchangeMetaText(expense: Expense, stacked: Boolean) {
    formatExpenseExchangeMeta(
        expense = expense,
        pendingRateLabel = stringResource(R.string.expense_exchange_rate_pending_label),
    )?.let {
        Text(
            text = it,
            modifier = if (stacked) {
                Modifier.fillMaxWidth()
            } else {
                Modifier.widthIn(max = AppAdaptiveAmountRowDefaults.secondaryMetaInlineMaxWidth)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = if (stacked) 2 else 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
        )
    }
}

@Composable
private fun PendingExpenseSignals(expense: Expense) {
    val tones = LocalStateTokens.current
    if (expense.pendingSync) PendingSignalText(stringResource(R.string.pending_row_signal_pending_sync), tones.info)
    if (expense.amountCents == null) PendingSignalText(stringResource(R.string.pending_row_signal_amount), tones.warn)
    if (pendingMerchantPresentation(expense).needsReview) {
        PendingSignalText(stringResource(R.string.pending_row_signal_merchant), tones.warn)
    }
    if (expense.category.isBlank()) PendingSignalText(stringResource(R.string.pending_row_signal_category), tones.warn)
    if (expense.duplicateStatus == DuplicateStatusValues.SUSPECTED) {
        PendingSignalText(stringResource(R.string.pending_row_signal_duplicate), tones.info)
    }
    if ((expense.confidence ?: 1.0) < 0.62) PendingSignalText(stringResource(R.string.pending_row_signal_review), tones.warn)
}

@Composable
private fun PendingExpenseInlineActions(
    expense: Expense,
    actions: PendingExpenseReviewActions,
) {
    val hasDuplicateAction = expense.duplicateStatus == DuplicateStatusValues.SUSPECTED
    val actionCount = if (hasDuplicateAction) 4 else 3
    AppAdaptiveEditActionLayout(actionCount = actionCount, compact = false) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                PendingExpenseInlineActionButtons(
                    expense = expense,
                    actions = actions,
                    hasDuplicateAction = hasDuplicateAction,
                    buttonModifier = Modifier.fillMaxWidth(),
                )
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PendingExpenseInlineActionButtons(
                    expense = expense,
                    actions = actions,
                    hasDuplicateAction = hasDuplicateAction,
                    buttonModifier = Modifier,
                )
            }
        }
    }
}

@Composable
private fun PendingExpenseInlineActionButtons(
    expense: Expense,
    actions: PendingExpenseReviewActions,
    hasDuplicateAction: Boolean,
    buttonModifier: Modifier,
) {
    TextButton(modifier = buttonModifier, onClick = actions.onEdit) {
        Text(stringResource(R.string.pending_row_action_edit))
    }
    TextButton(
        modifier = buttonModifier,
        onClick = actions.onPrimaryAction,
        enabled = actions.canMutate,
    ) {
        Text(stringResource(pendingPrimaryActionLabelRes(expense)))
    }
    TextButton(
        modifier = buttonModifier,
        onClick = actions.onReject,
        enabled = actions.canMutate,
    ) {
        Text(stringResource(R.string.pending_row_action_ignore))
    }
    if (hasDuplicateAction) {
        TextButton(
            modifier = buttonModifier,
            onClick = actions.onKeepDuplicate,
            enabled = actions.canMutate,
        ) {
            Text(stringResource(R.string.pending_row_action_keep_duplicate))
        }
    }
}

@Composable
private fun PendingCategoryMark(category: String, size: DpSize) {
    val text = category.take(1).ifBlank { stringResource(R.string.pending_row_category_fallback) }
    Text(
        text = text,
        modifier = Modifier
            .size(size)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.74f))
            .padding(top = AppSpacing.contentGap),
        color = MaterialTheme.colorScheme.primary,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = AppTextHierarchy.heading.weight,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun PendingSignalText(text: String, tone: StateTone) {
    Text(
        text = text,
        color = tone.fg,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = AppTextHierarchy.caption.weight,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}
