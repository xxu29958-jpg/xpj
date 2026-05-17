package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
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
fun ReceiptStub(
    modifier: Modifier = Modifier,
    compact: Boolean = false,
) {
    val palette = LocalThemeVisuals.current.receiptStub
    val width = if (compact) 76.dp else 110.dp
    val height = if (compact) 92.dp else 132.dp
    Box(
        modifier = modifier
            .size(width = width, height = height)
            .clip(MaterialTheme.shapes.medium)
            .background(
                Brush.verticalGradient(
                    listOf(
                        palette.paperTop,
                        palette.paperBottom,
                    ),
                ),
            )
            .border(1.dp, palette.border, MaterialTheme.shapes.medium)
            .padding(horizontal = 14.dp, vertical = 14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(if (compact) 8.dp else 11.dp)) {
            repeat(if (compact) 4 else 7) { index ->
                Box(
                    modifier = Modifier
                        .width(if (index % 3 == 0) width - 34.dp else width - 48.dp)
                        .height(3.dp)
                        .clip(CircleShape)
                        .background(palette.line),
                )
            }
        }
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(0.72f)
                .height(14.dp)
                .clip(CircleShape)
                .background(palette.footer),
        )
    }
}

private fun Color.luminance(): Float {
    return red * 0.299f + green * 0.587f + blue * 0.114f
}
