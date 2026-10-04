package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton

@Composable
internal fun SettingsPrimaryAction(text: String, enabled: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    AppPrimaryButton(text = text, enabled = enabled, modifier = modifier.fillMaxWidth(),
        icons = AppButtonIcons(trailing = ImageVector.vectorResource(R.drawable.ic_lucide_arrow_right)), onClick = onClick)
}
