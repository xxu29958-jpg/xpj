package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius

@Composable
fun SettingsEntryIcon(
    icon: ImageVector,
    modifier: Modifier = Modifier,
    background: Color = MaterialTheme.colorScheme.primaryContainer,
    shape: Shape = RoundedCornerShape(AppRadius.extraSmall),
) {
    Box(
        modifier = modifier
            .size(SettingsEntryIconTokens.ContainerSize)
            .clip(shape)
            .background(background),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppIconSize.compact),
        )
    }
}

private object SettingsEntryIconTokens {
    val ContainerSize = 36.dp
}
