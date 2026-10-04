package com.ticketbox.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.VpnKey
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.PageRole
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.ScanQrButton
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.navigation.parsePairingQrLink

/**
 * BuildConfig-derived server-URL entry rules shared by the unbound auth
 * screens (pairing-code bind and cold-start invitation join). [showInput]
 * follows the long-standing bind-screen rule: advanced builds or a blank
 * packaged default expose the field; gray builds with a packaged default
 * keep it hidden and silently use [defaultUrl].
 */
data class ServerUrlEntryConfig(
    val defaultUrl: String,
    val showInput: Boolean,
)

data class BindServerActions(
    val onBind: (String, String) -> Unit,
    val onJoinWithInvitation: () -> Unit,
    val onAbandonPendingEnrollment: () -> Unit,
)

@Composable
fun BindServerScreen(
    loading: Boolean,
    message: UiText?,
    hasPendingEnrollment: Boolean,
    serverUrlEntry: ServerUrlEntryConfig,
    actions: BindServerActions,
) {
    var serverUrl by rememberSaveable(serverUrlEntry.defaultUrl) { mutableStateOf(serverUrlEntry.defaultUrl) }
    var pairingCode by rememberSaveable { mutableStateOf("") }
    var confirmAbandonPending by remember { mutableStateOf(false) }
    var scannedOrigin by rememberSaveable { mutableStateOf<String?>(null) }
    var scanInvalid by remember { mutableStateOf(false) }
    val canBind = !loading && serverUrl.isNotBlank() && pairingCode.length == BindingCodeLength
    val submitBind = {
        if (canBind) actions.onBind(serverUrl, pairingCode)
    }

    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(
            page = AppPageChrome(
                role = PageRole.Auth,
                hasBottomBar = false,
            ),
            // 绑定是单一主任务焦点内容：中宽以上窗口居中封顶焦点宽度。
            contentWidth = AppAdaptiveContentWidth.Focus,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
    ) {
        AppPageHeader(
            title = stringResource(R.string.bind_server_header_title),
            subtitle = stringResource(R.string.bind_server_header_subtitle),
        )
        AppStatusBanner(message = message, tone = MessageTone.Danger)
        BindingIntroduction()
        ScanQrButton(
            label = stringResource(R.string.qr_scan_pairing), enabled = !loading && !hasPendingEnrollment,
            onResult = { raw ->
                val scanned = parsePairingQrLink(raw)
                scanInvalid = scanned == null
                if (scanned != null) {
                    serverUrl = scanned.serverUrl
                    pairingCode = scanned.pairingCode
                    scannedOrigin = scanned.serverUrl
                }
            },
        )
        if (scanInvalid) Text(stringResource(R.string.qr_pairing_invalid))
        scannedOrigin?.let { Text(stringResource(R.string.qr_pairing_ready, it)) }
        Text(
            text = if (serverUrlEntry.showInput) {
                stringResource(R.string.bind_server_hint_with_url)
            } else {
                stringResource(R.string.bind_server_hint_no_url)
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (serverUrlEntry.showInput) {
            AppTextInput(
                state = AppTextInputState(
                    label = stringResource(R.string.bind_server_field_url_label),
                    value = serverUrl,
                    placeholder = stringResource(R.string.bind_server_field_url_placeholder),
                    enabled = !loading,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                ),
                actions = AppTextInputActions(onValueChange = {
                    serverUrl = it
                    scannedOrigin = null
                }),
                decorations = AppTextInputDecorations(
                    trailingContent = { Icon(Icons.Filled.Link, contentDescription = null) },
                ),
            )
        } else {
            Text(stringResource(R.string.bind_server_configured_url, serverUrl),
                style = MaterialTheme.typography.bodyMedium)
        }
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.bind_server_field_code_label),
                value = pairingCode,
                placeholder = stringResource(R.string.bind_server_field_code_placeholder),
                enabled = !loading,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.NumberPassword,
                    imeAction = ImeAction.Done,
                ),
            ),
            actions = AppTextInputActions(
                onValueChange = { pairingCode = it.filter(Char::isDigit).take(BindingCodeLength) },
                keyboardActions = KeyboardActions(onDone = { submitBind() }),
            ),
            decorations = AppTextInputDecorations(
                trailingContent = { Icon(Icons.Filled.VpnKey, contentDescription = null) },
            ),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Icon(Icons.Filled.Info, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.bind_server_continuity_title),
                    style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.bind_server_continuity_body),
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppPrimaryButton(
                text = if (loading) {
                    stringResource(R.string.bind_server_button_binding)
                } else {
                    stringResource(R.string.bind_server_button_bind)
                },
                icon = Icons.AutoMirrored.Filled.ArrowForward,
                enabled = canBind,
                modifier = Modifier.fillMaxWidth(),
                onClick = submitBind,
            )
            AppSecondaryButton(
                text = stringResource(R.string.bind_server_button_join_with_invitation),
                enabled = !loading,
                modifier = Modifier.fillMaxWidth(),
                onClick = actions.onJoinWithInvitation,
            )
            if (hasPendingEnrollment) {
                AppSecondaryButton(
                    text = stringResource(R.string.bind_server_button_abandon_pending),
                    enabled = !loading,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { confirmAbandonPending = true },
                )
            }
        }
    }
    if (confirmAbandonPending) {
        AlertDialog(
            onDismissRequest = { confirmAbandonPending = false },
            title = {
                Text(text = stringResource(R.string.bind_server_abandon_pending_title))
            },
            text = {
                Text(text = stringResource(R.string.bind_server_abandon_pending_body))
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmAbandonPending = false
                        actions.onAbandonPendingEnrollment()
                    },
                ) {
                    Text(text = stringResource(R.string.bind_server_abandon_pending_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmAbandonPending = false }) {
                    Text(text = stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

private const val BindingCodeLength = 8

@Composable
private fun BindingIntroduction() {
    val panelColor = if (MaterialTheme.colorScheme.surface.luminance() < 0.5f) {
        MaterialTheme.colorScheme.secondaryContainer
    } else {
        Color(0xFFEAF0D6)
    }
    Row(
        modifier = Modifier.fillMaxWidth()
            .background(panelColor, RoundedCornerShape(24.dp))
            .padding(AppSpacing.cardPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.bind_server_intro_title),
                style = MaterialTheme.typography.titleLarge, fontWeight = AppTextHierarchy.heading.weight)
            Text(stringResource(R.string.bind_server_intro_body),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
        Image(painterResource(R.drawable.receipt_tray), contentDescription = null,
            modifier = Modifier.size(width = 108.dp, height = 110.dp))
    }
}
