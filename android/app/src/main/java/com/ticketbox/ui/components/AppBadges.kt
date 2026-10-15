package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.StateTone

/**
 * [tone] (issue #65 slice 5): when non-null, the pill renders in that
 * shared-token [StateTone] (the OutboxStatus visual language — e.g. the ``info``
 * tone for a "待同步" badge) instead of the primary/muted [active] scheme. Lets a
 * caller reuse one pill component across the three-surface design tokens without
 * a per-state component fork.
 */
@Composable
fun StatusPill(
    text: String,
    modifier: Modifier = Modifier,
    active: Boolean = true,
    tone: StateTone? = null,
) {
    val background = tone?.bg ?: if (active) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.70f)
    }
    val foreground = tone?.fg ?: if (active) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(
        text = text,
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(background)
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
        color = foreground,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = AppTextHierarchy.body.weight,
    )
}

@Composable
fun AppSwitch(
    checked: Boolean,
    onCheckedChange: ((Boolean) -> Unit)?,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    contentDescription: String? = null,
) {
    val visuals = LocalThemeVisuals.current
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        enabled = enabled,
        modifier = modifier.then(
            if (contentDescription != null) {
                Modifier.semantics { this.contentDescription = contentDescription }
            } else {
                Modifier
            },
        ),
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
    text: String = stringResource(R.string.components_safe_badge_label),
) {
    StatusPill(text = text, modifier = modifier, active = true)
}
