package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppSpacing

/** A saved revision stays fully readable, with the event separate from its snapshot. */
@Composable
fun AppHistoryRecord(
    title: String,
    recordedAt: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(recordedAt, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ProvideTextStyle(MaterialTheme.typography.bodyMedium) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap), content = content)
        }
    }
}
