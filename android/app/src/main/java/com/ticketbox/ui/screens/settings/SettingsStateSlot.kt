package com.ticketbox.ui.screens.settings

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

internal data class SettingsStateSlotCopy(
    val loadingTitle: String,
    val loadingBody: String,
    val emptyText: String,
)

@Composable
internal fun SettingsListStateSlot(
    loading: Boolean,
    hasData: Boolean,
    copy: SettingsStateSlotCopy,
    modifier: Modifier = Modifier,
) {
    if (hasData) return
    if (loading) {
        SettingsInlineEmpty(
            title = copy.loadingTitle,
            body = copy.loadingBody,
            modifier = modifier,
        )
    } else {
        Text(
            modifier = modifier,
            text = copy.emptyText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
