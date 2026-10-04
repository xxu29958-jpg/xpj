package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.components.AppPrimaryButton

@Composable
internal fun SettingsPrimaryAction(text: String, enabled: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    AppPrimaryButton(text = text, enabled = enabled, modifier = modifier.fillMaxWidth(),
        trailingIcon = Icons.AutoMirrored.Filled.ArrowForward, onClick = onClick)
}
