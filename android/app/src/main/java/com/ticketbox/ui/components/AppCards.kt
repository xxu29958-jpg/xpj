package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
@Composable
fun AppGlassCard(
    modifier: Modifier = Modifier,
    containerAlpha: Float = 0.96f,
    radius: RoundedCornerShape = RoundedCornerShape(AppRadius.large),
    content: @Composable () -> Unit,
) {
    val resolvedAlpha = containerAlpha.coerceIn(0.88f, 1f)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(radius)
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.surface.copy(alpha = resolvedAlpha),
                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = (resolvedAlpha * 0.52f).coerceIn(0.42f, 0.78f)),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.72f),
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
        containerAlpha = 0.98f,
        radius = RoundedCornerShape(AppRadius.large),
        content = content,
    )
}

@Composable
fun AppContentCard(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(AppSpacing.cardPadding),
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
fun AppEmptyStateCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 0.94f,
        radius = RoundedCornerShape(AppRadius.large),
        content = content,
    )
}

@Composable
fun AppHeroCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.hero)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(
                Brush.horizontalGradient(
                    listOf(
                        visuals.primary,
                        visuals.primaryDark,
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = visuals.accent.copy(alpha = 0.42f),
                shape = shape,
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.White.copy(alpha = 0.10f),
                            Color.Transparent,
                            Color.Black.copy(alpha = 0.08f),
                        ),
                    ),
                ),
        )
        content()
    }
}

@Composable
fun DeepHeroPanel(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    AppHeroCard(modifier = modifier, content = content)
}

@Composable
fun MetricTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    tint: Color = MaterialTheme.colorScheme.primary,
) {
    Column(
        modifier = modifier
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f))
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = value,
            color = tint,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Black,
        )
    }
}
