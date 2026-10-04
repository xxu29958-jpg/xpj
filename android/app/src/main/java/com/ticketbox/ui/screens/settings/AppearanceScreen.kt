package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Crop
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
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
        ThemeModePicker(preferences.currentMode, actions.preferences.onThemeModeChange)
        ThemeMoodPreview(appearance.backgroundSettings, preferences.currentSkin)
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(stringResource(R.string.appearance_background_current_label,
                backgroundSourceLabel(appearance.backgroundSettings)), style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.appearance_background_local_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
        AppearanceBackgroundEntries(appearance, actions.background)
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

@Composable
private fun AppearanceBackgroundEntries(
    appearance: AppearanceUiState,
    actions: AppearanceBackgroundActions,
) {
    val hasBackground = appearance.backgroundSettings.source != BackgroundSource.ThemeDefault
    val available = !appearance.importing
    SettingsEntryRow(
        title = stringResource(R.string.appearance_background_open_gallery),
        subtitle = stringResource(R.string.appearance_background_gallery_hint),
        icon = Icons.Filled.Image, onClick = if (available) actions.onOpenGallery else null,
    )
    SettingsEntryRow(
        title = stringResource(R.string.appearance_background_pick_image),
        subtitle = stringResource(R.string.appearance_background_album_hint),
        icon = Icons.Filled.PhotoLibrary, onClick = if (available) actions.onPickCustomImage else null,
    )
    SettingsEntryRow(
        title = stringResource(R.string.appearance_background_edit_composition),
        subtitle = stringResource(if (hasBackground) R.string.appearance_background_composition_hint
            else R.string.appearance_background_choose_first),
        icon = Icons.Filled.Crop,
        onClick = if (available && hasBackground) {
            { actions.onEditBackground(appearance.backgroundSettings) }
        } else null,
    )
    BackgroundActionButton(
        text = stringResource(R.string.appearance_background_restore_theme),
        enabled = available && hasBackground,
        onClick = actions.onClearBackgroundImage,
    )
}
