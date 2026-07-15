package com.ticketbox.ui.screens.settings

import android.content.ClipData
import android.os.PersistableBundle
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import kotlinx.coroutines.launch

@Composable
internal fun CreatedPairingCodeResult(
    code: DevicePairingCode,
    onDismissResult: () -> Unit,
) {
    val clipboard = LocalClipboard.current
    val coroutineScope = rememberCoroutineScope()
    val clipboardLabel = stringResource(R.string.my_devices_clipboard_label)
    val clipboardEntry = remember(code.pairingCode, clipboardLabel) {
        sensitivePairingCodeClip(clipboardLabel, code.pairingCode)
    }
    Text(
        text = code.recoveryDeviceName?.let {
            stringResource(R.string.my_devices_recovery_code_title, it)
        } ?: stringResource(R.string.my_devices_add_code_title),
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Text(
        text = code.pairingCode,
        style = MaterialTheme.typography.headlineSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Text(
        text = stringResource(R.string.my_devices_add_code_expires_at, displayTime(code.expiresAt)),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Text(
        text = code.recoveryDeviceName?.let {
            stringResource(R.string.my_devices_recovery_code_once_hint, it)
        } ?: stringResource(R.string.my_devices_add_code_once_hint),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(
            onClick = { coroutineScope.launch { clipboard.setClipEntry(clipboardEntry) } },
            modifier = Modifier.weight(1f),
        ) {
            Text(stringResource(R.string.my_devices_add_code_copy))
        }
        TextButton(onClick = onDismissResult) {
            Text(stringResource(R.string.my_devices_add_code_dismiss))
        }
    }
}

private fun sensitivePairingCodeClip(label: String, value: String): ClipEntry {
    val data = ClipData.newPlainText(label, value).apply {
        description.extras = PersistableBundle().apply {
            putBoolean("android.content.extra.IS_SENSITIVE", true)
        }
    }
    return ClipEntry(data)
}
