package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun EmptyPendingState(
    state: EmptyPendingStateModel,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        PendingStateTitle(
            title = stringResource(R.string.pending_empty_card_title),
            body = stringResource(if (state.readOnly) R.string.pending_empty_card_body_readonly else R.string.pending_empty_card_body),
        )
        PendingEmptyActions(state, onToggleGuide, onRefresh)
        if (state.showUploadGuide && !state.readOnly) PendingUploadGuide()
    }
}

internal data class EmptyPendingStateModel(
    val uploading: Boolean,
    val loading: Boolean = false,
    val readOnly: Boolean,
    val showUploadGuide: Boolean,
)

@Composable
private fun PendingUploadGuide() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.pending_empty_guide_title),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step1))
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step2))
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step3))
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PendingEmptyActions(
    state: EmptyPendingStateModel,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap, Alignment.CenterHorizontally),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        if (!state.readOnly) {
            PendingInlineAction(
                text = if (state.showUploadGuide) {
                    stringResource(R.string.pending_empty_guide_collapse)
                } else {
                    stringResource(R.string.pending_empty_guide_expand)
                },
                enabled = !state.loading,
                onClick = onToggleGuide,
            )
        }
        PendingInlineAction(
            text = stringResource(R.string.pending_empty_refresh_button),
            enabled = !state.uploading && !state.loading,
            onClick = onRefresh,
        )
    }
}

@Composable
private fun PendingInlineAction(
    text: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    TextButton(
        enabled = enabled,
        onClick = onClick,
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurfaceVariant),
        contentPadding = PaddingValues(
            horizontal = AppSpacing.smallGap,
            vertical = AppSpacing.tinyGap,
        ),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun PendingGuideStep(text: String) {
    Text(
        text = text,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun PendingStateTitle(
    title: String,
    body: String,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
        )
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}
