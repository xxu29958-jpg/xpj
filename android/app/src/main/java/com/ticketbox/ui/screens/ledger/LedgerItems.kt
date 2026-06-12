@file:OptIn(ExperimentalFoundationApi::class)

package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

private object LedgerItemLayout {
    const val CardContainerAlpha = 0.995f
    const val ListContainerAlpha = 0.99f
    const val TableContainerAlpha = 0.985f
    const val CardCategoryAlpha = 0.72f
    const val TableCategoryAlpha = 0.62f
    const val CategoryMarkAlpha = 0.78f
    const val TableMerchantWeight = 1.35f
    const val TableCategoryWeight = 0.72f
    const val TableAmountWeight = 0.88f
    const val DayHeaderSurfaceAlpha = 0.96f
}

/**
 * Day-group header: date on the left, that day's subtotal on the right. The
 * subtotal uses tabular figures and ink color (金额永远用墨), matching the
 * /web confirmed day-row rhythm. A solid surface background is carried on the
 * header itself so it stays readable when pinned by the sticky-header behavior
 * (otherwise the glass expense cards would show through the translucent pin).
 */
@Composable
internal fun LedgerDayHeader(label: String, dayTotalCents: Long) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = LedgerItemLayout.DayHeaderSurfaceAlpha))
            .padding(
                horizontal = AppSpacing.smallGap,
                vertical = AppSpacing.tinyGap + AppSpacing.tinyGap,
            ),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTypography.cardTitle.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = formatAmount(dayTotalCents),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge.tabularNum(),
            fontWeight = AppTypography.cardTitle.weight,
            maxLines = 1,
        )
    }
}

@Composable
internal fun LedgerExpenseCard(
    expense: Expense,
    onEdit: () -> Unit,
    selectionMode: Boolean = false,
    selected: Boolean = false,
    onToggleSelect: () -> Unit = {},
    onLongPress: () -> Unit = {},
) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(
        modifier = Modifier.combinedClickable(
            onClick = { if (selectionMode) onToggleSelect() else onEdit() },
            onLongClick = onLongPress,
        ),
        containerAlpha = LedgerItemLayout.CardContainerAlpha,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (selectionMode) {
                Checkbox(checked = selected, onCheckedChange = null)
            }
            LedgerCategoryMark(category = expense.category)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.ledger_item_merchant_empty),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = AppTypography.cardTitle.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                )
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
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = expense.amountCents?.let(::formatAmount) ?: stringResource(R.string.ledger_item_amount_pending),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTypography.amountMedium.weight,
                    maxLines = 1,
                )
                Text(
                    text = expense.category,
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.CardCategoryAlpha))
                        .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.miniGap + AppSpacing.tinyGap),
                    color = visuals.primary,
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = AppTypography.chip.weight,
                    maxLines = 1,
                )
            }
        }
    }
}

@Composable
internal fun LedgerExpenseListRow(
    expense: Expense,
    onEdit: () -> Unit,
    selectionMode: Boolean = false,
    selected: Boolean = false,
    onToggleSelect: () -> Unit = {},
    onLongPress: () -> Unit = {},
) {
    AppGlassCard(
        modifier = Modifier.combinedClickable(
            onClick = { if (selectionMode) onToggleSelect() else onEdit() },
            onLongClick = onLongPress,
        ),
        containerAlpha = LedgerItemLayout.ListContainerAlpha,
        radius = RoundedCornerShape(AppRadius.medium),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (selectionMode) {
                Checkbox(checked = selected, onCheckedChange = null)
            }
            LedgerCategoryMark(category = expense.category)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.ledger_item_merchant_empty),
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = AppTypography.cardTitle.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                )
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = expense.amountCents?.let(::formatAmount) ?: stringResource(R.string.ledger_item_amount_pending),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTypography.amountMedium.weight,
                    maxLines = 1,
                )
                Text(
                    text = expense.category,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
internal fun LedgerExpenseTableRow(
    expense: Expense,
    onEdit: () -> Unit,
    selectionMode: Boolean = false,
    selected: Boolean = false,
    onToggleSelect: () -> Unit = {},
    onLongPress: () -> Unit = {},
) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(
        modifier = Modifier.combinedClickable(
            onClick = { if (selectionMode) onToggleSelect() else onEdit() },
            onLongClick = onLongPress,
        ),
        containerAlpha = LedgerItemLayout.TableContainerAlpha,
        radius = RoundedCornerShape(AppRadius.small),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (selectionMode) {
                Checkbox(checked = selected, onCheckedChange = null)
            }
            Column(
                modifier = Modifier.weight(LedgerItemLayout.TableMerchantWeight),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.ledger_item_merchant_empty),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = AppTypography.chip.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                )
            }
            Text(
                text = expense.category,
                modifier = Modifier
                    .weight(LedgerItemLayout.TableCategoryWeight)
                    .clip(CircleShape)
                    .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.TableCategoryAlpha))
                    .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
                color = visuals.primary,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = AppTypography.chip.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.Center,
            )
            Text(
                text = expense.amountCents?.let(::formatAmount) ?: stringResource(R.string.ledger_item_amount_pending),
                modifier = Modifier.weight(LedgerItemLayout.TableAmountWeight),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTypography.amountMedium.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.End,
            )
        }
    }
}

@Composable
private fun LedgerCategoryMark(category: String) {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(42.dp)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.CategoryMarkAlpha)),
        contentAlignment = Alignment.Center,
    ) {
        val markFallback = stringResource(R.string.ledger_item_category_mark_fallback)
        Text(
            text = category.take(1).ifBlank { markFallback },
            color = visuals.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTypography.cardTitle.weight,
            textAlign = TextAlign.Center,
        )
    }
}
