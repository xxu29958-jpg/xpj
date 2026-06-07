package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun BudgetHeader(
    month: String,
    hasBottomBar: Boolean,
    onPreviousMonth: () -> Unit,
    onNextMonth: () -> Unit,
    onBack: (() -> Unit)?,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(
            if (hasBottomBar) AppSpacing.compactGap else AppSpacing.smallGap,
        ),
    ) {
        onBack?.let {
            TextButton(onClick = it) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = stringResource(R.string.budget_back_to_stats),
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(4.dp))
                Text(stringResource(R.string.budget_back_to_stats))
            }
        }
        AppPageHeader(
            title = stringResource(R.string.budget_header_title),
            subtitle = stringResource(R.string.budget_header_subtitle, month),
        ) {
            SafeBadge()
        }
        MonthSwitcher(
            month = month,
            onPreviousMonth = onPreviousMonth,
            onNextMonth = onNextMonth,
        )
    }
}
