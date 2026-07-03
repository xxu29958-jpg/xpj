package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun StatsMerchantRankBar(progress: Float) {
    val visuals = LocalThemeVisuals.current
    val track = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(AppSpacing.miniGap)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(track),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(progress.coerceIn(0f, 1f))
                .height(AppSpacing.miniGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(visuals.primary.copy(alpha = AppAlpha.opaque)),
        )
    }
}
