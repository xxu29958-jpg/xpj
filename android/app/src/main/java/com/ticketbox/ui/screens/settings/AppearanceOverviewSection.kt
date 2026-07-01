package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun AppearanceOverviewSection(
    currentSkin: AppSkin,
    currentCurrency: CurrencyCode,
    backgroundSettings: BackgroundSettings,
) {
    val summary = remember(backgroundSettings) { appearanceSummaryModel(backgroundSettings) }
    SettingsSection(
        title = stringResource(R.string.appearance_section_overview_title),
        icon = Icons.Filled.Palette,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                AppearanceOverviewMetric(
                    label = stringResource(R.string.appearance_overview_skin_label),
                    value = stringResource(appSkinNameRes(currentSkin)),
                    caption = stringResource(R.string.appearance_overview_skin_caption),
                    modifier = Modifier.weight(1f),
                )
                AppearanceOverviewMetric(
                    label = stringResource(R.string.appearance_overview_currency_label),
                    value = currentCurrency.storageKey,
                    caption = stringResource(R.string.appearance_overview_currency_caption),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                AppearanceOverviewMetric(
                    label = stringResource(R.string.appearance_overview_background_label),
                    value = backgroundSourceLabel(backgroundSettings),
                    caption = stringResource(backgroundCaptionRes(summary.backgroundKind)),
                    modifier = Modifier.weight(1f),
                )
                AppearanceOverviewMetric(
                    label = stringResource(R.string.appearance_overview_motion_label),
                    value = stringResource(motionLabelRes(summary.motionKind)),
                    caption = stringResource(motionCaptionRes(summary.motionKind)),
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun AppearanceOverviewMetric(
    label: String,
    value: String,
    caption: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@StringRes
private fun backgroundCaptionRes(kind: AppearanceBackgroundKind): Int = when (kind) {
    AppearanceBackgroundKind.ThemeDefault -> R.string.appearance_overview_background_caption_theme
    AppearanceBackgroundKind.BuiltIn -> R.string.appearance_overview_background_caption_builtin
    AppearanceBackgroundKind.CustomImage -> R.string.appearance_overview_background_caption_custom
}

@StringRes
private fun motionLabelRes(kind: AppearanceMotionKind): Int = when (kind) {
    AppearanceMotionKind.Dynamic -> R.string.appearance_overview_motion_dynamic
    AppearanceMotionKind.Static -> R.string.appearance_overview_motion_static
    AppearanceMotionKind.Reduced -> R.string.appearance_overview_motion_reduced
}

@StringRes
private fun motionCaptionRes(kind: AppearanceMotionKind): Int = when (kind) {
    AppearanceMotionKind.Dynamic -> R.string.appearance_overview_motion_caption_dynamic
    AppearanceMotionKind.Static -> R.string.appearance_overview_motion_caption_static
    AppearanceMotionKind.Reduced -> R.string.appearance_overview_motion_caption_reduced
}
