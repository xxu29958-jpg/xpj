package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.viewmodel.AppearanceUiState

data class AppearanceScreenState(
    val appearance: AppearanceUiState,
    val preferences: AppearancePreferenceState,
)

data class AppearancePreferenceState(
    val currentSkin: AppSkin,
    val currentMode: AppThemeMode,
    val currentCurrency: CurrencyCode,
)

data class AppearanceScreenActions(
    val onBack: () -> Unit,
    val preferences: AppearancePreferenceActions,
    val background: AppearanceBackgroundActions,
    val immersion: AppearanceImmersionActions,
)

data class AppearancePreferenceActions(
    val onThemeModeChange: (AppThemeMode) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
)

data class AppearanceBackgroundActions(
    val onOpenGallery: () -> Unit,
    val onPickCustomImage: () -> Unit,
    // 全局背景批:进入统一编辑面调整当前背景构图/沉浸;draft 由 VM 持有。
    val onEditBackground: (BackgroundSettings) -> Unit,
    // 「恢复主题背景」:一次发布回 ThemeDefault 并清掉自定义图(成功后才删旧文件)。
    val onClearBackgroundImage: () -> Unit,
)

data class AppearanceImmersionActions(
    val onModeChange: (ImmersionMode) -> Unit,
    val onParallaxChange: (Boolean) -> Unit,
    val onReduceMotionChange: (Boolean) -> Unit,
)

@Composable
fun AppearanceScreen(
    state: AppearanceScreenState,
    actions: AppearanceScreenActions,
) {
    val appearance = state.appearance
    val preferences = state.preferences
    SettingsPageFrame(
        title = stringResource(R.string.appearance_page_title),
        subtitle = stringResource(R.string.appearance_page_subtitle),
        onBack = actions.onBack,
        status = { AppStatusBanner(message = appearance.message, tone = appearance.messageTone) },
    ) {
        SettingsSection(title = stringResource(R.string.appearance_section_skin_title), icon = Icons.Filled.Palette) {
            Column(modifier = Modifier.selectableGroup()) {
                AppThemeMode.entries.forEach { mode ->
                    ThemeModeOption(
                        mode = mode,
                        previewSkin = mode.resolveSkin(isSystemInDarkTheme()),
                        selected = mode == preferences.currentMode,
                        onClick = { actions.preferences.onThemeModeChange(mode) },
                    )
                }
            }
        }
        SettingsSection(title = stringResource(R.string.appearance_section_background_title), icon = Icons.Filled.Image) {
            SettingsOpenPanel(
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                    if (appearance.backgroundSettings.source != BackgroundSource.ThemeDefault) {
                        ThemeMoodPreview(
                            settings = appearance.backgroundSettings,
                            skin = preferences.currentSkin,
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text(stringResource(R.string.appearance_background_current_label), style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = backgroundSourceLabel(appearance.backgroundSettings),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        SkinPill(
                            text = stringResource(immersionModeNameRes(appearance.backgroundSettings.immersionMode)),
                            scheme = MaterialTheme.colorScheme,
                            visuals = themeVisualsForSkin(preferences.currentSkin),
                            emphasized = false,
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_open_gallery),
                            modifier = Modifier.weight(1f),
                            onClick = actions.background.onOpenGallery,
                        )
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_pick_image),
                            modifier = Modifier.weight(1f),
                            onClick = actions.background.onPickCustomImage,
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                        val hasBackground = appearance.backgroundSettings.source != BackgroundSource.ThemeDefault
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_edit_composition),
                            modifier = Modifier.weight(1f),
                            enabled = hasBackground,
                            onClick = { actions.background.onEditBackground(appearance.backgroundSettings) },
                        )
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_restore_theme),
                            modifier = Modifier.weight(1f),
                            enabled = hasBackground,
                            onClick = actions.background.onClearBackgroundImage,
                        )
                    }
                    Text(
                        text = stringResource(R.string.appearance_background_local_hint),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
            }
        }
        SettingsSection(title = stringResource(R.string.appearance_section_immersion_title), icon = Icons.Filled.Tune) {
            ImmersionModePicker(
                selected = appearance.backgroundSettings.immersionMode,
                onSelect = actions.immersion.onModeChange,
            )
            BackgroundSwitchLine(
                title = stringResource(R.string.appearance_parallax_title),
                subtitle = stringResource(R.string.appearance_parallax_subtitle),
                checked = appearance.backgroundSettings.enableParallax && !appearance.backgroundSettings.reduceMotion,
                enabled = !appearance.backgroundSettings.reduceMotion,
                onCheckedChange = actions.immersion.onParallaxChange,
            )
            BackgroundSwitchLine(
                title = stringResource(R.string.appearance_reduce_motion_title),
                subtitle = stringResource(R.string.appearance_reduce_motion_subtitle),
                checked = appearance.backgroundSettings.reduceMotion,
                enabled = true,
                onCheckedChange = actions.immersion.onReduceMotionChange,
            )
        }
        CurrencySection(
            currentCurrency = preferences.currentCurrency,
            onCurrencyChange = actions.preferences.onCurrencyChange,
        )
    }
}
