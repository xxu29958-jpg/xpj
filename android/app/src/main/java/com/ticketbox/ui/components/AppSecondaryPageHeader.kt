package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import com.ticketbox.ui.design.AppSpacing

@Composable
fun AppSecondaryPageHeader(
    title: String,
    subtitle: String?,
    backText: String,
    onBack: (() -> Unit)?,
    actions: @Composable (() -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        onBack?.let {
            AppBackButton(text = backText, onClick = it)
        }
        if (actions == null) {
            AppPageHeader(title = title, subtitle = subtitle)
        } else {
            AppPageHeader(title = title, subtitle = subtitle) {
                actions()
            }
        }
    }
}
