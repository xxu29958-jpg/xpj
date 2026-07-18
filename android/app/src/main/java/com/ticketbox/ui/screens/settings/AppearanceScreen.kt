package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.TicketboxBackgroundLayer
import com.ticketbox.ui.appearance.background.resolveCardContainerAlpha
import com.ticketbox.ui.appearance.background.resolveGlobalScrim
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.AppearanceUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class AppearanceScreenState(
    val appearance: AppearanceUiState,
    val preferences: AppearancePreferenceState,
)

data class AppearancePreferenceState(
    val currentSkin: AppSkin,
    val currentCurrency: CurrencyCode,
)

data class AppearanceScreenActions(
    val onBack: () -> Unit,
    val preferences: AppearancePreferenceActions,
    val background: AppearanceBackgroundActions,
    val immersion: AppearanceImmersionActions,
)

data class AppearancePreferenceActions(
    val onSkinChange: (AppSkin) -> Unit,
    val onCurrencyChange: (CurrencyCode) -> Unit,
)

data class AppearanceBackgroundActions(
    val onOpenGallery: () -> Unit,
    val onPickCustomImage: () -> Unit,
    val onPreviewThemeDefault: () -> Unit,
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
        AppearanceOverviewSection(
            currentSkin = preferences.currentSkin,
            currentCurrency = preferences.currentCurrency,
            backgroundSettings = appearance.backgroundSettings,
        )
        SettingsSection(title = stringResource(R.string.appearance_section_skin_title), icon = Icons.Filled.Palette) {
            AppSkin.entries.chunked(2).forEach { rowSkins ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                ) {
                    rowSkins.forEach { skin ->
                        SkinOptionCard(
                            modifier = Modifier.weight(1f),
                            skin = skin,
                            selected = skin == preferences.currentSkin,
                            onClick = { actions.preferences.onSkinChange(skin) },
                        )
                    }
                    if (rowSkins.size == 1) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }
        CurrencySection(
            currentCurrency = preferences.currentCurrency,
        )
        SettingsSection(title = stringResource(R.string.appearance_section_background_title), icon = Icons.Filled.Image) {
            SettingsOpenPanel(
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                    ThemeMoodPreview(
                        settings = appearance.backgroundSettings,
                        skin = preferences.currentSkin,
                    )
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
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_follow_theme),
                            modifier = Modifier.weight(1f),
                            onClick = actions.background.onPreviewThemeDefault,
                        )
                        BackgroundActionButton(
                            text = stringResource(R.string.appearance_background_clear_image),
                            modifier = Modifier.weight(1f),
                            enabled = appearance.backgroundSettings.source == BackgroundSource.CustomImage &&
                                appearance.backgroundSettings.customImagePath != null,
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
    }
}
