package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveContentActionMode
import com.ticketbox.ui.components.resolveAppAdaptiveContentActionMode
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun MonthSwitcher(
    month: String,
    onPreviousMonth: () -> Unit,
    onNextMonth: () -> Unit,
    enabled: Boolean = true,
) {
    BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
        val stacked = resolveAppAdaptiveContentActionMode(
            maxWidth, LocalDensity.current.fontScale, compactAction = true,
        ) == AppAdaptiveContentActionMode.Stacked
        if (stacked) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                MonthSwitcherLabel(month)
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = onPreviousMonth, enabled = enabled) { Text(stringResource(R.string.budget_month_previous)) }
                    TextButton(onClick = onNextMonth, enabled = enabled) { Text(stringResource(R.string.budget_month_next)) }
                }
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onPreviousMonth, enabled = enabled) { Text(stringResource(R.string.budget_month_previous)) }
                MonthSwitcherLabel(month)
                TextButton(onClick = onNextMonth, enabled = enabled) { Text(stringResource(R.string.budget_month_next)) }
            }
        }
    }
}

@Composable
private fun MonthSwitcherLabel(month: String) {
    Text(
        text = month,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = AppTextHierarchy.heading.weight,
    )
}
