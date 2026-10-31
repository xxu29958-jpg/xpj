package com.ticketbox.ui.screens.pending

import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.BrandArt
import com.ticketbox.ui.components.BrandArtKind
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.presentation.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

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
            imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_info),
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
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = when {
                    pendingCount > 0 -> stringResource(R.string.pending_top_subtitle_queue)
                    state.readOnly -> stringResource(R.string.pending_top_subtitle_empty_readonly)
                    else -> stringResource(R.string.pending_top_subtitle_empty)
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            trailingAction?.invoke()
        }
        if (state.showUploadAction) PendingCaptureHero(state, onUploadScreenshot)
    }
}

internal data class PendingTopState(
    val counts: PendingQueueCounts,
    val uploading: Boolean,
    val readOnly: Boolean,
    val showUploadAction: Boolean,
    val canStartUpload: Boolean = !uploading && !readOnly,
)

@Composable
private fun PendingCaptureHero(
    state: PendingTopState,
    onUploadScreenshot: () -> Unit,
) {
    val text = if (state.uploading) {
        stringResource(R.string.pending_top_cta_uploading)
    } else {
        stringResource(R.string.pending_top_cta_upload)
    }
    Surface(
        color = LocalThemeVisuals.current.brandPrimaryBg,
        shape = RoundedCornerShape(AppRadius.hero),
    ) {
        BoxWithConstraints(Modifier.fillMaxWidth().padding(AppSpacing.cardPaddingSmall)) {
            val showArt = maxWidth / LocalDensity.current.fontScale >= AppAdaptiveBreakpoints.amountRowInlineMinWidth
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(stringResource(R.string.pending_capture_hero_title), style = MaterialTheme.typography.titleLarge)
                    Text(stringResource(R.string.pending_capture_hero_body),
                        color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                    // With a queue, 「开始核对」 is the screen's one primary; upload steps back to tonal.
                    if (state.counts.all > 0) {
                        AppSecondaryButton(text = text, enabled = state.canStartUpload, onClick = onUploadScreenshot)
                    } else {
                        AppPrimaryButton(text = text, enabled = state.canStartUpload, onClick = onUploadScreenshot)
                    }
                }
                if (showArt) BrandArt(BrandArtKind.Pair, Modifier.size(width = 96.dp, height = 84.dp))
            }
        }
    }
}

@Composable
internal fun PendingDisplayModeButton(
    loading: Boolean,
    onClick: () -> Unit,
) {
    IconButton(
        enabled = !loading,
        onClick = onClick,
    ) {
        Icon(
            imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_ellipsis),
            contentDescription = stringResource(R.string.pending_display_options_button),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
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
            imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_info),
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
