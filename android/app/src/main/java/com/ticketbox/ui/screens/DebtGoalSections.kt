package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun DebtGoalOpenSection(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.compactGap),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppSectionHeader(title = title, subtitle = subtitle)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.miniGap),
            verticalArrangement = verticalArrangement,
            content = content,
        )
    }
}

@Composable
internal fun DebtGoalRowDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
}
