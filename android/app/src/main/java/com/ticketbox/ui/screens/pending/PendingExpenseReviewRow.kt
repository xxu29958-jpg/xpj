package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.formatExpenseExchangeMeta
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppDensity
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.ui.design.tabularNum

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
) {
    val metrics = AppDensity.rowMetrics(
        if (item.compact) AppListDensity.Compact else AppListDensity.Standard,
    )
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !item.busy, onClick = actions.onEdit),
    ) {
        Column(
            modifier = Modifier.padding(metrics.rowPadding),
            verticalArrangement = Arrangement.spacedBy(metrics.contentGap),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(metrics.itemSpacing),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PendingExpenseLeadingMark(item)
                PendingExpenseTextBlock(item)
                PendingExpenseAmountBlock(item.expense, actions)
            }
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
            placeholder = stringResource(R.string.pending_row_image_placeholder),
            compact = true,
            compactSize = size,
            shape = RoundedCornerShape(AppRadius.small),
            contentScale = ContentScale.Crop,
        )
    } else {
        PendingCategoryMark(item.expense.category, size)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RowScope.PendingExpenseTextBlock(item: PendingExpenseReviewItem) {
    val expense = item.expense
    Column(
        modifier = Modifier.weight(1f),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = expense.merchant?.takeIf { it.isNotBlank() }
                ?: stringResource(R.string.components_expense_card_merchant_placeholder),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(
                R.string.pending_row_meta,
                displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
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
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val amount = expense.amountCents?.let { formatExpensePrimaryAmount(expense, currencyDisplay) }
        ?: stringResource(R.string.pending_row_amount_missing)
    Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = amount,
            modifier = Modifier.widthIn(min = 118.dp),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall
                .copy(letterSpacing = 0.sp)
                .tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Clip,
            textAlign = TextAlign.End,
        )
        formatExpenseExchangeMeta(expense)?.let {
            Text(
                text = it,
                modifier = Modifier.widthIn(max = 132.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.End,
            )
        }
        TextButton(
            enabled = actions.canMutate,
            onClick = actions.onPrimaryAction,
            modifier = Modifier.heightIn(min = 32.dp),
            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
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
private fun PendingExpenseSignals(expense: Expense) {
    val tones = LocalStateTokens.current
    if (expense.pendingSync) PendingSignalText(stringResource(R.string.pending_row_signal_pending_sync), tones.info)
    if (expense.amountCents == null) PendingSignalText(stringResource(R.string.pending_row_signal_amount), tones.warn)
    if (expense.merchant.isNullOrBlank()) PendingSignalText(stringResource(R.string.pending_row_signal_merchant), tones.warn)
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = actions.onEdit) {
            Text(stringResource(R.string.pending_row_action_edit))
        }
        TextButton(onClick = actions.onPrimaryAction, enabled = actions.canMutate) {
            Text(stringResource(pendingPrimaryActionLabelRes(expense)))
        }
        TextButton(onClick = actions.onReject, enabled = actions.canMutate) {
            Text(stringResource(R.string.pending_row_action_ignore))
        }
        if (expense.duplicateStatus == DuplicateStatusValues.SUSPECTED) {
            TextButton(onClick = actions.onKeepDuplicate, enabled = actions.canMutate) {
                Text(stringResource(R.string.pending_row_action_keep_duplicate))
            }
        }
    }
}

@Composable
private fun PendingCategoryMark(category: String, size: DpSize) {
    val text = category.take(1).ifBlank { stringResource(R.string.components_expense_card_category_fallback) }
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

@StringRes
private fun pendingPrimaryActionLabelRes(expense: Expense): Int = when {
    expense.amountCents == null -> R.string.pending_row_action_amount
    expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> R.string.pending_row_action_duplicate
    expense.category.isBlank() -> R.string.pending_row_action_category
    expense.merchant.isNullOrBlank() -> R.string.pending_row_action_merchant
    else -> R.string.pending_row_action_confirm
}
