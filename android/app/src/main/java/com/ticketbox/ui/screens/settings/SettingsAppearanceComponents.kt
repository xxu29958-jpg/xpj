package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.appearance.background.BackgroundPreviewStage
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.SettingsColors
import com.ticketbox.ui.design.settingsEntrySurface
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.formatAmount

@Composable
internal fun ThemeMoodPreview(
    settings: BackgroundSettings,
    skin: AppSkin,
) {
    // A labelled component sample over the same renderer; the editor alone owns full-window composition.
    BackgroundPreviewStage(
        settings = settings,
        skin = skin,
        role = SurfaceRole.Stats,
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp)),
    ) {
        BackgroundReadabilitySample()
    }
}

@Composable
internal fun ThemeModePicker(
    selected: AppThemeMode,
    onSelect: (AppThemeMode) -> Unit,
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth().selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppThemeMode.entries.forEach { mode ->
            val description = stringResource(appThemeModeDescriptionRes(mode))
            Box(
                modifier = Modifier
                    .clip(CircleShape)
                    .background(if (mode == selected) settingsEntrySurface(SettingsColors.generalEntry)
                        else MaterialTheme.colorScheme.surface)
                    .selectable(selected = mode == selected, role = Role.RadioButton, onClick = { onSelect(mode) })
                    .semantics { contentDescription = description }
                    .heightIn(min = 48.dp)
                    .padding(horizontal = 16.dp, vertical = AppSpacing.smallGap),
                contentAlignment = Alignment.Center,
            ) {
                Text(stringResource(appThemeModeNameRes(mode)), style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

@Composable
internal fun BackgroundReadabilitySample(modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        color = settingsEntrySurface(SettingsColors.bindingIntroduction),
    ) {
        Column(
            modifier = Modifier.heightIn(min = 176.dp).padding(28.dp),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(stringResource(R.string.appearance_preview_amount_label),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText(
                text = formatAmount(12_345_678L, CurrencyCode.CNY),
                modifier = Modifier.fillMaxWidth(),
                role = AppAmountRole.Hero,
                maxFontSize = 42.sp,
            )
            Text(stringResource(R.string.appearance_preview_sample_note),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
internal fun PreviewBar(
    width: Dp,
    color: Color,
) {
    Box(
        modifier = Modifier
            .width(width)
            .height(5.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(color),
    )
}

@Composable
internal fun SkinPill(
    text: String,
    scheme: ColorScheme,
    visuals: ThemeVisuals,
    emphasized: Boolean,
) {
    val background = if (emphasized) visuals.primary else visuals.chipSelected.copy(alpha = 0.86f)
    val content = if (emphasized) scheme.onPrimary else scheme.onSurfaceVariant
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(background)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (emphasized) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = content,
                modifier = Modifier.size(12.dp),
            )
        }
        Text(text = text, color = content, style = MaterialTheme.typography.labelSmall)
    }
}
