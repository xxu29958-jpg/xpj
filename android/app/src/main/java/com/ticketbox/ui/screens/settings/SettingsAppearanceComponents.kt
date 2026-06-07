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
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SettingsEntryCard
import com.ticketbox.ui.components.AppGlassCard
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
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun ThemeMoodPreview(
    settings: BackgroundSettings,
    skin: AppSkin,
) {
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(132.dp)
            .clip(RoundedCornerShape(24.dp)),
    ) {
        TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = SurfaceRole.Pending)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(resolveGlobalScrim(settings, skin, SurfaceRole.Pending)),
        )
        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .fillMaxWidth(0.88f)
                .height(88.dp)
                .clip(RoundedCornerShape(22.dp))
                .background(
                    Brush.linearGradient(
                        visuals.heroGradient,
                    ),
                )
                .border(
                    width = 1.dp,
                    color = scheme.onPrimary.copy(alpha = 0.22f),
                    shape = RoundedCornerShape(22.dp),
                )
                .padding(AppSpacing.cardPaddingTight),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(
                    text = stringResource(R.string.appearance_mood_preview_caption),
                    color = scheme.onPrimary.copy(alpha = 0.78f),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                Text(
                    text = skin.displayName,
                    color = scheme.onPrimary,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .clip(RoundedCornerShape(18.dp))
                    .background(visuals.glassTint.copy(alpha = 0.84f))
                    .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
            ) {
                Text(
                    text = settings.immersionMode.displayName,
                    color = visuals.primary,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
        }
    }
}

@Composable
internal fun SkinOptionCard(
    modifier: Modifier = Modifier,
    skin: AppSkin,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    val containerColor = if (selected) {
        visuals.glassTint.copy(alpha = 0.86f)
    } else {
        visuals.solidCard.copy(alpha = 0.94f)
    }
    val borderColor = if (selected) visuals.primary else Color.White.copy(alpha = 0.58f)
    val cardShape = RoundedCornerShape(AppRadius.large)

    Box(
        modifier = modifier
            .height(168.dp)
            .shadow(
                elevation = if (selected) AppElevation.softCard else 6.dp,
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
            SkinPreview(skin = skin, scheme = scheme, visuals = visuals)
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = skin.displayName,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                    )
                    if (selected) {
                        SkinPill(text = stringResource(R.string.appearance_skin_pill_current), scheme = scheme, visuals = visuals, emphasized = true)
                    } else if (skin == AppSkin.Paper) {
                        SkinPill(text = stringResource(R.string.appearance_skin_pill_recommended), scheme = scheme, visuals = visuals, emphasized = false)
                    }
                }
                Text(
                    text = skin.description,
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
internal fun SkinPreview(skin: AppSkin, scheme: ColorScheme, visuals: ThemeVisuals) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(92.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(scheme.background),
    ) {
        TicketboxAtmosphereBackground(skin = skin)
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp)
                    .clip(RoundedCornerShape(15.dp))
                    .background(
                        Brush.linearGradient(
                            visuals.heroGradient,
                        ),
                    )
                    .padding(8.dp),
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    PreviewBar(width = 42.dp, color = scheme.onPrimary.copy(alpha = 0.80f))
                    PreviewBar(width = 64.dp, color = scheme.onPrimary.copy(alpha = 0.96f))
                }
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .width(36.dp)
                        .height(18.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(Color.White.copy(alpha = 0.82f)),
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(24.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(visuals.glassTint.copy(alpha = 0.88f))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    PreviewBar(width = 34.dp, color = visuals.primary.copy(alpha = 0.28f))
                    PreviewBar(width = 24.dp, color = visuals.accent.copy(alpha = 0.22f))
                }
            }
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
