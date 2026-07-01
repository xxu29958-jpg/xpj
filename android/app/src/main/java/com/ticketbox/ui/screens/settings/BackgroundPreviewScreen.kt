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
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun BackgroundPreviewScreen(
    initialSettings: BackgroundSettings,
    currentSkin: AppSkin,
    title: String,
    onBack: () -> Unit,
    onApply: (BackgroundSettings) -> Unit,
) {
    var previewSettings by remember(initialSettings) { mutableStateOf(initialSettings) }
    val homeCurrency = LocalCurrencyDisplay.current.homeCurrency
    SettingsPageFrame(
        title = stringResource(R.string.background_preview_page_title),
        subtitle = stringResource(R.string.background_preview_page_subtitle, title),
        onBack = onBack,
    ) {
        ImmersionModePicker(
            selected = previewSettings.immersionMode,
            onSelect = { mode -> previewSettings = previewSettings.copy(immersionMode = mode) },
        )
        PreviewRoleCard(
            title = stringResource(R.string.background_preview_role_pending),
            role = SurfaceRole.Pending,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt(stringResource(R.string.background_preview_pending_meituan_merchant), formatAmount(3680, homeCurrency), stringResource(R.string.background_preview_pending_meituan_note))
            PreviewReceipt(stringResource(R.string.background_preview_pending_ccb_merchant), stringResource(R.string.background_preview_pending_ccb_amount), stringResource(R.string.background_preview_pending_ccb_note))
        }
        PreviewRoleCard(
            title = stringResource(R.string.background_preview_role_ledger),
            role = SurfaceRole.Ledger,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt(stringResource(R.string.background_preview_ledger_openai_merchant), formatAmount(20000, homeCurrency), stringResource(R.string.background_preview_ledger_openai_note))
            PreviewReceipt(stringResource(R.string.background_preview_ledger_meituan_merchant), formatAmount(3680, homeCurrency), stringResource(R.string.background_preview_ledger_meituan_note))
        }
        PreviewRoleCard(
            title = stringResource(R.string.background_preview_role_stats),
            role = SurfaceRole.Stats,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            Text(stringResource(R.string.background_preview_stats_total, formatAmount(428690, homeCurrency)), style = MaterialTheme.typography.titleMedium, fontWeight = AppTextHierarchy.heading.weight)
            Text(stringResource(R.string.background_preview_stats_breakdown, formatAmount(20000, homeCurrency)), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        PreviewRoleCard(
            title = stringResource(R.string.background_preview_role_edit),
            role = SurfaceRole.Edit,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt(stringResource(R.string.background_preview_edit_amount_label), formatAmount(3680, homeCurrency), stringResource(R.string.background_preview_edit_amount_note))
            AppPrimaryButton(
                text = stringResource(R.string.background_preview_edit_confirm_button),
                icon = Icons.Filled.Check,
                modifier = Modifier.fillMaxWidth(),
                onClick = {},
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            AppSecondaryButton(
                text = stringResource(R.string.background_preview_cancel_button),
                modifier = Modifier.weight(1f),
                leadingIcon = Icons.AutoMirrored.Filled.ArrowBack,
                onClick = onBack,
            )
            AppPrimaryButton(
                text = stringResource(R.string.background_preview_apply_button),
                icon = Icons.Filled.Check,
                modifier = Modifier.weight(1f),
                onClick = { onApply(previewSettings) },
            )
        }
    }
}
