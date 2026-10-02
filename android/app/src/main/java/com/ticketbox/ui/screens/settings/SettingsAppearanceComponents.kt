package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.ui.appearance.background.BackgroundPreviewStage
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.theme.colorSchemeForSkin

@Composable
internal fun ThemeMoodPreview(
    settings: BackgroundSettings,
    skin: AppSkin,
) {
    // 真实渲染缩略（同一 BackgroundPreviewStage 管线），不再放假 hero 梯度
    // 样卡：这里是「当前背景」的一瞥而非编辑构图 claim，小尺寸裁切是诚实的。
    BackgroundPreviewStage(
        settings = settings,
        skin = skin,
        role = SurfaceRole.Pending,
        modifier = Modifier
            .fillMaxWidth()
            .height(132.dp)
            .clip(RoundedCornerShape(24.dp)),
    ) {
        Text(
            text = stringResource(R.string.appearance_mood_preview_caption),
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(AppSpacing.compactGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy))
                .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.tinyGap),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
internal fun ThemeModeOption(
    mode: AppThemeMode,
    previewSkin: AppSkin,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.large))
            .background(if (selected) scheme.surfaceContainer else Color.Transparent)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.compactGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ThemePalettePreview(skin = previewSkin)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(appThemeModeNameRes(mode)),
                style = MaterialTheme.typography.titleSmall,
                color = scheme.onSurface,
            )
            Text(
                text = stringResource(appThemeModeDescriptionRes(mode)),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
        }
        RadioButton(selected = selected, onClick = null)
    }
}

@Composable
private fun ThemePalettePreview(skin: AppSkin) {
    val scheme = colorSchemeForSkin(skin)
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    Column(
        modifier = Modifier
            .size(56.dp)
            .clip(shape)
            .background(scheme.background)
            .border(1.dp, scheme.outlineVariant, shape)
            .padding(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().height(12.dp)
                .clip(shape).background(scheme.primary),
        )
        PreviewBar(width = 32.dp, color = scheme.onSurface)
        PreviewBar(width = 24.dp, color = scheme.onSurfaceVariant)
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
