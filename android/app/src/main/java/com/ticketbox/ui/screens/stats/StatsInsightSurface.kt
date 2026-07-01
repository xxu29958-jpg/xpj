package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.StatsSurfaceTone

@Composable
internal fun StatsInsightSurface(
    modifier: Modifier = Modifier,
    tone: StatsSurfaceTone = StatsSurfaceTone.Section,
    contentPadding: PaddingValues = PaddingValues(AppSpacing.cardPaddingSmall),
    content: @Composable () -> Unit,
) {
    val surfaceTokens = LocalStatsTokens.current.surface
    val tokens = when (tone) {
        StatsSurfaceTone.Hero -> surfaceTokens.hero
        StatsSurfaceTone.Section -> surfaceTokens.section
    }
    val shape = RoundedCornerShape(tokens.radius)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.surface.copy(alpha = tokens.topAlpha),
                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = tokens.bottomAlpha),
                    ),
                ),
            )
            .then(
                if (tokens.borderAlpha > 0f) {
                    Modifier.border(
                        width = 1.dp,
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = tokens.borderAlpha),
                        shape = shape,
                    )
                } else {
                    Modifier
                },
            )
            .padding(contentPadding),
    ) {
        content()
    }
}
