package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.forTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens

@Composable
internal fun LedgerInlineStatusMessage(
    message: UiText?,
    tone: MessageTone,
) {
    val text = message?.asString()?.takeIf { it.isNotBlank() } ?: return
    val palette = LocalStateTokens.current.forTone(tone)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = text,
            color = palette.fg,
            style = MaterialTheme.typography.bodySmall,
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.20f))
    }
}
