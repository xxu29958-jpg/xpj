package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Palette
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun AppearanceOverviewSection(
    currentMode: AppThemeMode,
    currentCurrency: CurrencyCode,
    backgroundSettings: BackgroundSettings,
) {
    val summary = remember(backgroundSettings) { appearanceSummaryModel(backgroundSettings) }
    SettingsSection(
        title = stringResource(R.string.appearance_section_overview_title),
        icon = Icons.Filled.Palette,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.appearance_overview_skin_label),
                        value = stringResource(appThemeModeNameRes(currentMode)),
                        caption = stringResource(R.string.appearance_overview_skin_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.appearance_overview_currency_label),
                        value = currentCurrency.storageKey,
                        caption = stringResource(R.string.appearance_overview_currency_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.appearance_overview_background_label),
                        value = backgroundSourceLabel(backgroundSettings),
                        caption = stringResource(backgroundCaptionRes(summary.backgroundKind)),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.appearance_overview_motion_label),
                        value = stringResource(motionLabelRes(summary.motionKind)),
                        caption = stringResource(motionCaptionRes(summary.motionKind)),
                    ),
                ),
            )
        }
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
