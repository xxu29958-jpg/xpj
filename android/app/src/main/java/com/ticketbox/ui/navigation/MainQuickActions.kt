package com.ticketbox.ui.navigation

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.res.vectorResource
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
                imageVector = ImageVector.vectorResource(target.iconRes),
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
                imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_plus),
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
                            imageVector = ImageVector.vectorResource(target.iconRes),
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

private val ShortcutTarget.iconRes: Int
    @DrawableRes get() = when (this) {
        ShortcutTarget.UploadReceipt -> R.drawable.ic_lucide_images
        ShortcutTarget.ManualEntry -> R.drawable.ic_lucide_receipt_text
        ShortcutTarget.ReviewPending -> R.drawable.ic_lucide_inbox
    }
