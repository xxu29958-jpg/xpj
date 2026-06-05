package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun StatusPill(
    text: String,
    modifier: Modifier = Modifier,
    active: Boolean = true,
) {
    Text(
        text = text,
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(
                if (active) {
                    MaterialTheme.colorScheme.primaryContainer
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.70f)
                },
            )
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
        color = if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = AppTextHierarchy.body.weight,
    )
}

@Composable
fun AppSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val visuals = LocalThemeVisuals.current
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        enabled = enabled,
        modifier = modifier,
        colors = SwitchDefaults.colors(
            checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
            checkedTrackColor = visuals.primary.copy(alpha = 0.92f),
            checkedBorderColor = visuals.primary.copy(alpha = 0.80f),
            uncheckedThumbColor = MaterialTheme.colorScheme.onSurfaceVariant,
            uncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.74f),
            uncheckedBorderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.62f),
            disabledCheckedThumbColor = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.58f),
            disabledCheckedTrackColor = visuals.primary.copy(alpha = 0.36f),
            disabledUncheckedThumbColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.42f),
            disabledUncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.44f),
        ),
    )
}

@Composable
fun SafeBadge(
    modifier: Modifier = Modifier,
    text: String = "安全",
) {
    StatusPill(text = text, modifier = modifier, active = true)
}
