package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun PendingMessageCard(message: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
        Text(
            text = message,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
internal fun PendingTop(
    counts: PendingQueueCounts,
    uploading: Boolean,
    readOnly: Boolean,
    onUploadScreenshot: () -> Unit,
    trailingAction: (@Composable () -> Unit)? = null,
) {
    val pendingCount = counts.all
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        AppPageHeader(
            title = stringResource(R.string.pending_top_title),
            subtitle = when {
                pendingCount > 0 -> stringResource(R.string.pending_top_subtitle_has_items)
                readOnly -> stringResource(R.string.pending_top_subtitle_empty_readonly)
                else -> stringResource(R.string.pending_top_subtitle_empty)
            },
        ) {
            trailingAction?.invoke()
        }

        if (pendingCount > 0) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingSmall),
                verticalAlignment = Alignment.Bottom,
            ) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text(
                        text = pendingCount.toString(),
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = AppTextHierarchy.hero.weight,
                        maxLines = 1,
                    )
                    Text(
                        text = stringResource(R.string.pending_top_metric_caption),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = AppTextHierarchy.caption.weight,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (counts.readyToConfirm > 0 || counts.needsAmount > 0 || counts.duplicate > 0) {
                    Column(
                        horizontalAlignment = Alignment.End,
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                    ) {
                        PendingTopMetric(
                            visible = counts.readyToConfirm > 0,
                            value = counts.readyToConfirm,
                            label = stringResource(R.string.pending_filter_label_ready_to_confirm),
                        )
                        PendingTopMetric(
                            visible = counts.needsAmount > 0,
                            value = counts.needsAmount,
                            label = stringResource(R.string.pending_filter_label_needs_amount),
                        )
                        PendingTopMetric(
                            visible = counts.duplicate > 0,
                            value = counts.duplicate,
                            label = stringResource(R.string.pending_top_duplicate_caption),
                        )
                    }
                }
            }
        }

        if (!readOnly) {
            PrimaryCtaButton(
                modifier = Modifier.fillMaxWidth(),
                enabled = !uploading,
                icon = Icons.Filled.AddPhotoAlternate,
                text = if (uploading) {
                    stringResource(R.string.pending_top_cta_uploading)
                } else {
                    stringResource(R.string.pending_top_cta_upload)
                },
                onClick = onUploadScreenshot,
            )
        }
    }
}

@Composable
private fun PendingTopMetric(
    visible: Boolean,
    value: Int,
    label: String,
) {
    if (!visible) return
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = value.toString(),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTextHierarchy.caption.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
internal fun PendingDisplayModeButton(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onClick: () -> Unit,
) {
    AppSecondaryButton(
        text = if (loading) stringResource(R.string.pending_display_mode_button_loading) else pendingDisplayModeLabel(displayMode),
        enabled = !loading,
        onClick = onClick,
    )
}

@Composable
internal fun PendingUndoRejectBanner(
    expense: Expense,
    onUndo: () -> Unit,
) {
    val merchant = expense.merchant?.trim()?.takeIf { it.isNotEmpty() }
    val amount = expense.amountCents?.let { formatExpensePrimaryAmount(expense) }
    val descriptor = listOfNotNull(merchant, amount).joinToString(" · ")
    val label = if (descriptor.isNotEmpty()) {
        stringResource(R.string.pending_undo_banner_label_with_descriptor, descriptor)
    } else {
        stringResource(R.string.pending_undo_banner_label)
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppSecondaryButton(text = stringResource(R.string.pending_undo_banner_action), onClick = onUndo)
    }
}
