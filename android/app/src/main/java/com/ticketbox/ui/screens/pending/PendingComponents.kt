package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing

/** Optional, quiet action that belongs to the message immediately beside it. */
internal data class PendingMessageCardAction(
    val label: String,
    val enabled: Boolean,
    val onClick: () -> Unit,
)

@Composable
internal fun PendingMessageCard(
    message: String,
    action: PendingMessageCardAction? = null,
) {
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
        action?.let {
            AppSecondaryButton(
                text = it.label,
                enabled = it.enabled,
                onClick = it.onClick,
            )
        }
    }
}

@Composable
internal fun PendingTop(
    state: PendingTopState,
    onUploadScreenshot: () -> Unit,
    trailingAction: (@Composable () -> Unit)? = null,
) {
    val pendingCount = state.counts.all
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.Top,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = stringResource(R.string.pending_top_title),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleLarge,
                )
                Text(
                    text = when {
                        pendingCount > 0 -> stringResource(R.string.pending_top_subtitle_count, pendingCount)
                        state.readOnly -> stringResource(R.string.pending_top_subtitle_empty_readonly)
                        else -> stringResource(R.string.pending_top_subtitle_empty)
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            trailingAction?.invoke()
        }

        if (!state.readOnly) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PendingUploadAction(
                    uploading = state.uploading,
                    onUploadScreenshot = onUploadScreenshot,
                )
                Spacer(modifier = Modifier.weight(1f))
            }
        }
    }
}

internal data class PendingTopState(
    val counts: PendingQueueCounts,
    val uploading: Boolean,
    val readOnly: Boolean,
)

@Composable
private fun PendingUploadAction(
    uploading: Boolean,
    onUploadScreenshot: () -> Unit,
) {
    val text = if (uploading) {
        stringResource(R.string.pending_top_cta_uploading)
    } else {
        stringResource(R.string.pending_top_cta_upload)
    }
    TextButton(
        onClick = onUploadScreenshot,
        modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
        enabled = !uploading,
        shape = RoundedCornerShape(AppRadius.small),
    ) {
        Icon(
            imageVector = Icons.Filled.AddPhotoAlternate,
            contentDescription = null,
            modifier = Modifier.size(AppIconSize.compact),
        )
        Text(
            text = text,
            modifier = Modifier.padding(start = AppSpacing.smallGap),
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
internal fun PendingDisplayModeButton(
    loading: Boolean,
    onClick: () -> Unit,
) {
    AppSecondaryButton(
        text = if (loading) {
            stringResource(R.string.pending_display_mode_button_loading)
        } else {
            stringResource(R.string.pending_display_options_button)
        },
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
