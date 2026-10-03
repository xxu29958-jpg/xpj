package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing

internal enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

@Composable
internal fun PendingToolsSheet(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    actions: PendingScreenChromeActions,
    onDismiss: () -> Unit,
) {
    AppSheetScaffold(
        title = stringResource(R.string.pending_tools_title),
        subtitle = stringResource(R.string.pending_tools_subtitle),
    ) {
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
        HorizontalDivider()
        InboxActionLinks(
            onOpenRepaymentReview = {
                onDismiss()
                actions.onOpenRepaymentReview()
            },
            onOpenDataQuality = {
                onDismiss()
                actions.onOpenDataQuality()
            },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(
                text = if (loading) {
                    stringResource(R.string.pending_tools_refresh_loading)
                } else {
                    stringResource(R.string.pending_tools_refresh)
                },
                modifier = Modifier.weight(1f),
                enabled = !loading,
                onClick = actions.onRefresh,
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
