package com.ticketbox.ui.navigation

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing

/** In-app access to the same three user tasks already owned by launcher shortcuts. */
@Composable
internal fun MainQuickActionsButton(
    canModify: Boolean,
    onAction: (ShortcutTarget) -> Unit,
    modifier: Modifier = Modifier,
) {
    val targets = quickActionTargets(canModify)
    if (!canModify) {
        val target = targets.single()
        IconButton(
            onClick = { onAction(target) },
            modifier = modifier.size(AppSpacing.controlMinHeight),
        ) {
            Icon(
                imageVector = target.icon,
                contentDescription = stringResource(R.string.shortcut_review_long_label),
            )
        }
        return
    }

    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        IconButton(
            onClick = { expanded = true },
            modifier = Modifier.size(AppSpacing.controlMinHeight),
        ) {
            Icon(
                imageVector = Icons.Default.Add,
                contentDescription = stringResource(R.string.navigation_quick_actions),
            )
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            targets.forEach { target ->
                DropdownMenuItem(
                    text = { Text(stringResource(target.labelRes)) },
                    leadingIcon = {
                        Icon(
                            imageVector = target.icon,
                            contentDescription = null,
                        )
                    },
                    onClick = {
                        expanded = false
                        onAction(target)
                    },
                )
            }
        }
    }
}

internal fun quickActionTargets(canModify: Boolean): List<ShortcutTarget> =
    if (canModify) ShortcutTarget.entries else listOf(ShortcutTarget.ReviewPending)

private val ShortcutTarget.labelRes: Int
    @StringRes get() = when (this) {
        ShortcutTarget.UploadReceipt -> R.string.shortcut_upload_short_label
        ShortcutTarget.ManualEntry -> R.string.shortcut_manual_short_label
        ShortcutTarget.ReviewPending -> R.string.shortcut_review_short_label
    }

private val ShortcutTarget.icon: ImageVector
    get() = when (this) {
        ShortcutTarget.UploadReceipt -> Icons.Default.PhotoLibrary
        ShortcutTarget.ManualEntry -> Icons.AutoMirrored.Filled.ReceiptLong
        ShortcutTarget.ReviewPending -> Icons.Default.Inbox
    }
