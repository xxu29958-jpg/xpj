package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

data class AppSheetAction(
    val text: String,
    val onClick: () -> Unit,
    val enabled: Boolean = true,
    val icon: ImageVector = Icons.Filled.Check,
)

@Composable
fun AppSheetScaffold(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    compact: Boolean = LocalAppImeVisible.current,
    content: @Composable ColumnScope.() -> Unit,
) {
    val verticalGap = if (compact) AppSpacing.smallGap else AppSpacing.contentGap
    val topPadding = if (compact) AppSpacing.smallGap else AppSpacing.cardPaddingSmall
    val bottomPadding = if (compact) {
        AppSpacing.compactGap
    } else {
        AppSpacing.bottomContentPadding + AppSpacing.sectionGap
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
fun AppSheetActionRow(
    primary: AppSheetAction,
    modifier: Modifier = Modifier,
    secondary: AppSheetAction? = null,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            if (secondary != null) {
                QuietOutlinedButton(
                    text = secondary.text,
                    modifier = Modifier.weight(1f),
                    enabled = secondary.enabled,
                    onClick = secondary.onClick,
                )
            }
            AppPrimaryButton(
                text = primary.text,
                icon = primary.icon,
                modifier = Modifier.weight(1f),
                enabled = primary.enabled,
                onClick = primary.onClick,
            )
        }
    }
}

@Composable
private fun AppSheetHeader(
    title: String,
    subtitle: String?,
    compact: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = title,
            style = if (compact) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        subtitle?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
}
