package com.ticketbox.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.LocalThemeVisuals

data class AppBottomNavItem(
    val key: String,
    val label: String,
    val icon: ImageVector,
)

@Composable
fun AppBottomNav(
    items: List<AppBottomNavItem>,
    selectedKey: String,
    onSelect: (AppBottomNavItem) -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 8.dp),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(AppRadius.bottomBar),
            color = visuals.solidCard.copy(alpha = 0.995f),
            tonalElevation = 0.dp,
            shadowElevation = 0.dp,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                items.forEach { item ->
                    AppBottomNavItemView(
                        item = item,
                        selected = item.key == selectedKey,
                        onClick = { onSelect(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun AppBottomNavItemView(
    item: AppBottomNavItem,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val background by animateColorAsState(
        targetValue = if (selected) visuals.primary.copy(alpha = 0.90f) else Color.Transparent,
        label = "appBottomNavBackground",
    )
    val content by animateColorAsState(
        targetValue = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        label = "appBottomNavContent",
    )
    if (selected) {
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.large))
                .clickable(onClick = onClick)
                .background(background)
                .padding(horizontal = 11.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = item.icon,
                contentDescription = item.label,
                tint = content,
                modifier = Modifier.size(16.dp),
            )
            Text(
                text = item.label,
                color = content,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Black,
            )
        }
    } else {
        Column(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.large))
                .clickable(onClick = onClick)
                .padding(horizontal = 13.dp, vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Icon(
                imageVector = item.icon,
                contentDescription = item.label,
                tint = content,
                modifier = Modifier.size(18.dp),
            )
            Text(
                text = item.label,
                color = content,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}
