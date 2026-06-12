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
import com.ticketbox.BuildConfig
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
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun SecurityPrivacyScreen(
    onBack: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
    // Page-header status feedback (this screen used to render none — clearing
    // cache / logging out gave no on-screen signal). The host builds an
    // AppStatusBanner from SettingsViewModel's message + tone and passes it here.
    status: (@Composable () -> Unit)? = null,
) {
    var showClearCacheDialog by remember { mutableStateOf(false) }
    var showClearBindingDialog by remember { mutableStateOf(false) }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text(stringResource(R.string.settings_security_clear_dialog_title)) },
            text = { Text(stringResource(R.string.settings_security_clear_dialog_text)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearCacheDialog = false
                        onClearCache()
                    },
                ) {
                    Text(stringResource(R.string.settings_security_clear_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { showClearCacheDialog = false }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
    if (showClearBindingDialog) {
        AlertDialog(
            onDismissRequest = { showClearBindingDialog = false },
            title = { Text(stringResource(R.string.settings_security_logout_dialog_title)) },
            text = { Text(stringResource(R.string.settings_security_logout_dialog_text)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearBindingDialog = false
                        onBindingCleared()
                    },
                ) {
                    Text(stringResource(R.string.settings_security_logout_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { showClearBindingDialog = false }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.settings_security_page_title),
        subtitle = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
            stringResource(R.string.settings_security_page_subtitle_locked)
        } else {
            stringResource(R.string.settings_security_page_subtitle_unlocked)
        },
        onBack = onBack,
        status = status,
    ) {
        SettingsSection(
            title = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                stringResource(R.string.settings_security_section_unlock_locked)
            } else {
                stringResource(R.string.settings_security_section_unlock_unlocked)
            },
            icon = Icons.Filled.Security,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                            stringResource(R.string.settings_security_unlock_card_title_locked)
                        } else {
                            stringResource(R.string.settings_security_unlock_card_title_unlocked)
                        },
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                            stringResource(R.string.settings_security_unlock_card_body_locked)
                        } else {
                            stringResource(R.string.settings_security_unlock_card_body_unlocked)
                        },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = stringResource(R.string.settings_security_background_privacy),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        SettingsSection(title = stringResource(R.string.settings_security_section_danger), icon = Icons.Filled.DeleteOutline) {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearCacheDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Icon(Icons.Filled.DeleteOutline, contentDescription = stringResource(R.string.settings_security_clear_data_icon_desc), modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.settings_security_button_clear_data))
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearBindingDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = stringResource(R.string.settings_security_logout_icon_desc), modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.settings_security_button_logout))
                }
            }
        }
    }
}
