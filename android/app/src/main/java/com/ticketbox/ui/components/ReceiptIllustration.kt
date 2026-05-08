package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
fun ReceiptIllustration(
    modifier: Modifier = Modifier,
    compact: Boolean = false,
) {
    val visuals = LocalThemeVisuals.current
    val outerSize = if (compact) 116.dp else 142.dp
    val innerSize = if (compact) 86.dp else 108.dp
    val outerRadius = if (compact) 30.dp else 38.dp
    val innerRadius = if (compact) 24.dp else 30.dp

    Box(
        modifier = modifier
            .size(outerSize)
            .clip(RoundedCornerShape(outerRadius))
            .background(
                Brush.radialGradient(
                    listOf(
                        visuals.illustrationTint.copy(alpha = 0.44f),
                        MaterialTheme.colorScheme.surface.copy(alpha = 0.84f),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.70f),
                shape = RoundedCornerShape(outerRadius),
            ),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(innerSize)
                .clip(RoundedCornerShape(innerRadius))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.78f))
                .border(
                    width = 1.dp,
                    color = visuals.illustrationTint.copy(alpha = 0.34f),
                    shape = RoundedCornerShape(innerRadius),
                ),
            contentAlignment = Alignment.Center,
        ) {
            ReceiptStub(compact = true)
        }
    }
}
