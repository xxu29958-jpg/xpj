package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.exclude
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

private const val LongPairedActionLabelLength = 8
private const val LongPairedActionTotalLength = 13

data class AppAction(
    val text: String,
    val onClick: () -> Unit,
    val enabled: Boolean = true,
    val icon: ImageVector = Icons.Filled.Check,
)

typealias AppSheetAction = AppAction

@Composable
fun AppSheetScaffold(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    compact: Boolean = LocalAppImeVisible.current,
    content: @Composable ColumnScope.() -> Unit,
) {
    val verticalGap = if (compact) AppSpacing.smallGap else AppSpacing.compactGap
    val topPadding = if (compact) AppSpacing.smallGap else AppSpacing.compactGap
    val bottomPadding = if (compact) {
        AppSpacing.compactGap
    } else {
        AppSpacing.bottomContentPadding
    }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .imePadding()
            .windowInsetsPadding(WindowInsets.navigationBars.exclude(WindowInsets.ime))
            .verticalScroll(rememberScrollState())
            .padding(
                start = AppSpacing.screenHorizontal,
                top = topPadding,
                end = AppSpacing.screenHorizontal,
                bottom = bottomPadding,
            ),
        verticalArrangement = Arrangement.spacedBy(verticalGap),
    ) {
        AppSheetHeader(title = title, subtitle = subtitle, compact = compact)
        content()
    }
}

@Composable
fun AppActionRow(
    primary: AppAction,
    modifier: Modifier = Modifier,
    secondary: AppAction? = null,
    showDivider: Boolean = true,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        if (showDivider) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
        }
        if (secondary == null) {
            SheetPrimaryAction(action = primary, modifier = Modifier.fillMaxWidth())
        } else {
            BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
                if (shouldStackSheetActions(maxWidth = maxWidth, primary = primary, secondary = secondary)) {
                    StackedSheetActions(primary = primary, secondary = secondary)
                } else {
                    InlineSheetActions(primary = primary, secondary = secondary)
                }
            }
        }
    }
}

@Composable
fun AppSheetActionRow(
    primary: AppSheetAction,
    modifier: Modifier = Modifier,
    secondary: AppSheetAction? = null,
) {
    AppActionRow(primary = primary, modifier = modifier, secondary = secondary)
}

private fun shouldStackSheetActions(
    maxWidth: Dp,
    primary: AppAction,
    secondary: AppAction,
): Boolean {
    val hasLongCopy = primary.text.length >= LongPairedActionLabelLength ||
        secondary.text.length >= LongPairedActionLabelLength ||
        primary.text.length + secondary.text.length >= LongPairedActionTotalLength
    return maxWidth < AppAdaptiveBreakpoints.pairedActionInlineMinWidth ||
        hasLongCopy && maxWidth < AppAdaptiveBreakpoints.editActionInlineMinWidth
}

@Composable
private fun StackedSheetActions(
    primary: AppAction,
    secondary: AppAction,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        SheetSecondaryAction(action = secondary, modifier = Modifier.fillMaxWidth())
        SheetPrimaryAction(action = primary, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun InlineSheetActions(
    primary: AppAction,
    secondary: AppAction,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
    ) {
        SheetSecondaryAction(action = secondary, modifier = Modifier.weight(1f))
        SheetPrimaryAction(action = primary, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun SheetSecondaryAction(
    action: AppAction,
    modifier: Modifier,
) {
    QuietOutlinedButton(
        text = action.text,
        modifier = modifier,
        enabled = action.enabled,
        onClick = action.onClick,
    )
}

@Composable
private fun SheetPrimaryAction(
    action: AppAction,
    modifier: Modifier,
) {
    AppPrimaryButton(
        text = action.text,
        icon = action.icon,
        modifier = modifier,
        enabled = action.enabled,
        onClick = action.onClick,
    )
}

@Composable
private fun AppSheetHeader(
    title: String,
    subtitle: String?,
    compact: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(if (compact) AppSpacing.tinyGap else AppSpacing.miniGap)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        subtitle?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
}
