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
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
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
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun BackgroundCropScreen(
    sourcePath: String,
    onBack: () -> Unit,
    onComplete: (BackgroundCropMode) -> Unit,
) {
    var cropMode by remember { mutableStateOf(BackgroundCropMode.Center) }
    val visuals = LocalThemeVisuals.current
    val density = LocalDensity.current
    val previewOffsetPx = with(density) { cropMode.previewOffsetDp.toPx() }
    SettingsPageFrame(
        title = "调整背景",
        subtitle = "避开顶部标题和底部导航区域，保证账单内容清晰可读。",
        onBack = onBack,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(9f / 16f)
                .clip(RoundedCornerShape(AppRadius.large))
                .background(visuals.solidCard.copy(alpha = 0.92f)),
        ) {
            val bitmap = rememberLocalImage(sourcePath)
            if (bitmap != null) {
                Image(
                    bitmap = bitmap,
                    contentDescription = "背景裁剪预览",
                    modifier = Modifier
                        .fillMaxSize()
                        .graphicsLayer {
                            scaleX = 1.14f
                            scaleY = 1.14f
                            translationY = previewOffsetPx
                        },
                    contentScale = ContentScale.Crop,
                    alignment = when (cropMode) {
                        BackgroundCropMode.Top -> Alignment.TopCenter
                        BackgroundCropMode.Center -> Alignment.Center
                        BackgroundCropMode.Bottom -> Alignment.BottomCenter
                    },
                )
            }
            CropSafeZones()
            CropSelectionBadge(
                cropMode = cropMode,
                modifier = Modifier
                    .align(cropMode.previewBadgeAlignment)
                    .padding(AppSpacing.cardPaddingTight),
            )
        }
        SettingsSection(title = "构图位置", icon = Icons.Filled.Tune) {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                BackgroundCropMode.entries.forEach { mode ->
                    AppFilterChip(
                        modifier = Modifier.weight(1f),
                        selected = cropMode == mode,
                        onClick = { cropMode = mode },
                        label = mode.displayName,
                    )
                }
            }
            Text(
                text = cropMode.description,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                onClick = onBack,
            ) {
                Text("取消")
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = { onComplete(cropMode) },
            ) {
                Text("完成，去预览")
            }
        }
    }
}

private val BackgroundCropMode.previewOffsetDp
    get() = when (this) {
        BackgroundCropMode.Top -> 42.dp
        BackgroundCropMode.Center -> 0.dp
        BackgroundCropMode.Bottom -> (-42).dp
    }

private val BackgroundCropMode.previewBadgeAlignment: Alignment
    get() = when (this) {
        BackgroundCropMode.Top -> Alignment.TopCenter
        BackgroundCropMode.Center -> Alignment.Center
        BackgroundCropMode.Bottom -> Alignment.BottomCenter
    }

@Composable
private fun CropSelectionBadge(
    cropMode: BackgroundCropMode,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.82f))
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
    ) {
        Text(
            text = "当前保留：${cropMode.displayName}",
            color = MaterialTheme.colorScheme.onPrimary,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
    }
}
