package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

@Composable
internal fun pendingDisplayModeLabel(displayMode: PendingDisplayMode): String {
    return when (displayMode) {
        PendingDisplayMode.Compact -> stringResource(R.string.pending_tools_density_compact)
        PendingDisplayMode.Comfortable -> stringResource(R.string.pending_tools_density_comfortable)
    }
}

@Composable
internal fun PendingToolsSheet(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    onRefresh: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.cardPadding, vertical = AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                text = stringResource(R.string.pending_tools_title),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.pending_tools_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Compact,
                onClick = { onDisplayModeChange(PendingDisplayMode.Compact) },
                label = stringResource(R.string.pending_tools_density_compact),
            )
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Comfortable,
                onClick = { onDisplayModeChange(PendingDisplayMode.Comfortable) },
                label = stringResource(R.string.pending_tools_density_comfortable),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(
                text = if (loading) {
                    stringResource(R.string.pending_tools_refresh_loading)
                } else {
                    stringResource(R.string.pending_tools_refresh)
                },
                modifier = Modifier.weight(1f),
                enabled = !loading,
                onClick = onRefresh,
            )
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text(stringResource(R.string.pending_tools_done))
            }
        }
    }
}
