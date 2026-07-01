package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSecondaryPageHeader
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
        AppSecondaryPageHeader(
            title = stringResource(R.string.budget_header_title),
            subtitle = stringResource(R.string.budget_header_subtitle, month),
            backText = stringResource(R.string.budget_back_to_stats),
            onBack = onBack,
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
