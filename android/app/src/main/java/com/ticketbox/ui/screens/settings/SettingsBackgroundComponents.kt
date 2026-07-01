package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.draw.shadow
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
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.TicketboxBackgroundLayer
import com.ticketbox.ui.appearance.background.resolveCardContainerAlpha
import com.ticketbox.ui.appearance.background.resolveGlobalScrim
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SettingsEntryCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun BuiltInBackgroundCard(
    modifier: Modifier = Modifier,
    background: BuiltInBackground,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val skin = background.preferredSkin ?: AppSkin.Default
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    val cardShape = RoundedCornerShape(AppRadius.large)
    val containerColor = if (selected) {
        visuals.glassTint.copy(alpha = 0.88f)
    } else {
        visuals.solidCard.copy(alpha = 0.94f)
    }
    val borderColor = if (selected) {
        visuals.primary.copy(alpha = 0.72f)
    } else {
        Color.White.copy(alpha = 0.54f)
    }

    Box(
        modifier = modifier
            .height(184.dp)
            .shadow(
                elevation = if (selected) AppElevation.softCard else 7.dp,
                shape = cardShape,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = if (selected) 0.18f else 0.08f),
                spotColor = visuals.shadowTint.copy(alpha = if (selected) 0.14f else 0.06f),
            )
            .clip(cardShape)
            .background(containerColor)
            .border(width = 1.dp, color = borderColor, shape = cardShape)
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(AppSpacing.compactPadding),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            GradientPreview(
                colors = background.gradientColors,
                scheme = scheme,
                visuals = visuals,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(100.dp),
            )
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = stringResource(builtInBackgroundNameRes(background)),
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                    )
                    if (selected) {
                        SkinPill(text = stringResource(R.string.appearance_builtin_pill_current), scheme = scheme, visuals = visuals, emphasized = true)
                    } else if (skin == AppSkin.Paper) {
                        SkinPill(text = stringResource(R.string.appearance_builtin_pill_recommended), scheme = scheme, visuals = visuals, emphasized = false)
                    }
                }
                Text(
                    text = stringResource(
                        R.string.appearance_builtin_background_meta,
                        stringResource(builtInBackgroundCategoryNameRes(background.category)),
                        stringResource(appSkinNameRes(skin)),
                        stringResource(builtInBackgroundDescriptionRes(background)),
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
internal fun GradientPreview(
    colors: List<Long>,
    scheme: ColorScheme,
    visuals: ThemeVisuals,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(Brush.linearGradient(colors.map { Color(it) }))
            .padding(10.dp),
    ) {
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(82.dp)
                .background(
                    Brush.radialGradient(
                        listOf(visuals.heroGlow.copy(alpha = 0.42f), Color.Transparent),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(42.dp)
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.Transparent,
                            visuals.coolMist.copy(alpha = 0.24f),
                            Color.White.copy(alpha = 0.34f),
                        ),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .fillMaxWidth(0.78f)
                .height(48.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(
                    Brush.linearGradient(
                        listOf(
                            visuals.heroGradientStart.copy(alpha = 0.92f),
                            visuals.heroGradientEnd.copy(alpha = 0.88f),
                        ),
                    ),
                )
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.24f),
                    shape = RoundedCornerShape(14.dp),
                )
                .padding(horizontal = 9.dp, vertical = 8.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PreviewBar(width = 36.dp, color = scheme.onPrimary.copy(alpha = 0.70f))
                PreviewBar(width = 58.dp, color = scheme.onPrimary.copy(alpha = 0.90f))
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .width(28.dp)
                    .height(11.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(Color.White.copy(alpha = 0.78f)),
            )
        }
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth(0.70f)
                .height(30.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(visuals.glassTint.copy(alpha = 0.70f))
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.32f),
                    shape = RoundedCornerShape(12.dp),
                )
                .padding(horizontal = 8.dp, vertical = 6.dp),
        ) {
            PreviewBar(width = 42.dp, color = visuals.primaryDark.copy(alpha = 0.38f))
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .width(24.dp)
                    .height(8.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(visuals.chipSelected.copy(alpha = 0.86f)),
            )
        }
    }
}

@Composable
internal fun ImmersionModePicker(
    selected: ImmersionMode,
    onSelect: (ImmersionMode) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ImmersionMode.entries.forEach { mode ->
                AppFilterChip(
                    modifier = Modifier.weight(1f),
                    selected = selected == mode,
                    onClick = { onSelect(mode) },
                    label = stringResource(immersionModeNameRes(mode)),
                )
            }
        }
        Text(
            text = stringResource(immersionModeDescriptionRes(selected)),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun BackgroundSwitchLine(
    title: String,
    subtitle: String,
    checked: Boolean,
    enabled: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(
                text = subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        AppSwitch(
            checked = checked,
            enabled = enabled,
            onCheckedChange = onCheckedChange,
        )
    }
}

@Composable
internal fun CropSafeZones() {
    Column(modifier = Modifier.fillMaxSize()) {
        SafeZoneBand(stringResource(R.string.appearance_crop_safezone_top), 0.15f)
        Box(
            modifier = Modifier
                .weight(0.70f)
                .fillMaxWidth()
                .border(1.dp, Color.White.copy(alpha = 0.55f), RoundedCornerShape(18.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = stringResource(R.string.appearance_crop_safezone_reading),
                color = Color.White.copy(alpha = 0.82f),
                style = MaterialTheme.typography.labelMedium,
            )
        }
        SafeZoneBand(stringResource(R.string.appearance_crop_safezone_bottom), 0.15f)
    }
}

@Composable
internal fun ColumnScope.SafeZoneBand(
    text: String,
    weight: Float,
) {
    Box(
        modifier = Modifier
            .weight(weight)
            .fillMaxWidth()
            .background(Color.Black.copy(alpha = 0.30f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = text, color = Color.White, style = MaterialTheme.typography.labelMedium)
    }
}
