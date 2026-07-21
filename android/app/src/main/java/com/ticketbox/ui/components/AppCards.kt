package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun AppGlassCard(
    modifier: Modifier = Modifier,
    containerAlpha: Float = 0.96f,
    radius: RoundedCornerShape = RoundedCornerShape(AppRadius.medium),
    content: @Composable () -> Unit,
) {
    val resolvedAlpha = containerAlpha.coerceIn(0.92f, 1f)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(radius)
            .background(MaterialTheme.colorScheme.surface.copy(alpha = resolvedAlpha))
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.opaque),
                shape = radius,
            ),
    ) {
        content()
    }
}

@Composable
fun AppSolidCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    // Solid cards are for edit, settings, and other input-heavy surfaces that
    // need stronger separation from the immersive background.
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 1f,
        radius = RoundedCornerShape(AppRadius.medium),
        content = content,
    )
}

@Composable
fun AppContentCard(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(AppSpacing.cardPaddingSmall),
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.contentGap),
    content: @Composable ColumnScope.() -> Unit,
) {
    AppSolidCard(modifier = modifier) {
        Column(
            modifier = Modifier.padding(contentPadding),
            verticalArrangement = verticalArrangement,
            content = content,
        )
    }
}

@Composable
fun AppSectionGroup(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(vertical = AppSpacing.contentGap),
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.compactGap),
    showTopDivider: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val dividerColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium)
    Column(modifier = modifier.fillMaxWidth()) {
        if (showTopDivider) {
            HorizontalDivider(color = dividerColor)
        }
        Column(
            modifier = Modifier.padding(contentPadding),
            verticalArrangement = verticalArrangement,
            content = content,
        )
        HorizontalDivider(color = dividerColor)
    }
}

@Composable
fun AppListRow(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    settled: Boolean = false,
    showDivider: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    val dividerColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium)
    val clickModifier = if (onClick == null) Modifier else Modifier.clickable(onClick = onClick)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .then(if (settled) Modifier.alpha(AppAlpha.opaque) else Modifier),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .then(clickModifier)
                .padding(vertical = AppSpacing.contentGap),
            verticalAlignment = Alignment.Top,
            content = content,
        )
        if (showDivider) {
            HorizontalDivider(color = dividerColor)
        }
    }
}

@Composable
fun AppEmptyStateCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 1f,
        radius = RoundedCornerShape(AppRadius.medium),
        content = content,
    )
}
