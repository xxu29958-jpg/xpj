package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun BudgetProgressBar(progress: Float) {
    val track = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.78f)
    val visuals = LocalThemeVisuals.current
    val stateTokens = LocalStateTokens.current
    val clamped = progress.coerceAtLeast(0f)
    val (start, end) = when {
        clamped <= 0.80f -> visuals.primary.copy(alpha = 0.78f) to visuals.primary.copy(alpha = 0.92f)
        clamped <= 1.00f -> stateTokens.warn.fg.copy(alpha = 0.78f) to stateTokens.warn.fg.copy(alpha = 0.95f)
        else -> stateTokens.danger.fg.copy(alpha = 0.82f) to stateTokens.danger.fg.copy(alpha = 1.0f)
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(track),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(clamped.coerceAtMost(1f))
                .background(Brush.horizontalGradient(listOf(start, end)))
                .padding(vertical = AppSpacing.miniGap),
        )
    }
}
