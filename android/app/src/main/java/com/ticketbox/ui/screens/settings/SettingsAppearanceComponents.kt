package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
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
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppFilterChip
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
        BackgroundReadabilitySample(Modifier.padding(AppSpacing.contentGap))
    }
}

@Composable
internal fun ThemeModePicker(
    selected: AppThemeMode,
    onSelect: (AppThemeMode) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        FlowRow(
            modifier = Modifier.fillMaxWidth().selectableGroup(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            AppThemeMode.entries.forEach { mode ->
                AppFilterChip(
                    label = stringResource(appThemeModeNameRes(mode)),
                    selected = mode == selected,
                    onClick = { onSelect(mode) },
                )
            }
        }
        Text(
            text = stringResource(appThemeModeDescriptionRes(selected)),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
internal fun BackgroundReadabilitySample(modifier: Modifier = Modifier) {
    AppPaperCard(modifier = modifier) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(stringResource(R.string.appearance_preview_amount_label),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText(
                text = formatAmount(12_345_678L, CurrencyCode.CNY),
                modifier = Modifier.fillMaxWidth(),
                role = AppAmountRole.Hero,
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
