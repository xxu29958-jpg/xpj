package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens

@Immutable
data class AppSheetActionFeedbackState(
    val validationMessage: String? = null,
    val statusMessage: String? = null,
    val statusTone: MessageTone = MessageTone.Neutral,
)

@Composable
fun AppSheetActionFeedback(
    primary: AppSheetAction,
    modifier: Modifier = Modifier,
    secondary: AppSheetAction? = null,
    state: AppSheetActionFeedbackState = AppSheetActionFeedbackState(),
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        state.validationMessage?.takeIf { it.isNotBlank() }?.let {
            AppSheetActionMessage(text = it, color = LocalStateTokens.current.danger.fg)
        }
        state.statusMessage?.takeIf { it.isNotBlank() }?.let {
            AppSheetActionMessage(text = it, color = LocalStateTokens.current.forTone(state.statusTone).fg)
        }
        AppActionRow(primary = primary, secondary = secondary)
    }
}

@Composable
private fun AppSheetActionMessage(
    text: String,
    color: Color,
) {
    Text(
        text = text,
        color = color,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.fillMaxWidth(),
    )
}
