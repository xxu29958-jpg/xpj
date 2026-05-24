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
import androidx.compose.ui.unit.dp
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
                    contentDescription = "返回统计",
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(4.dp))
                Text("返回统计")
            }
        }
        AppPageHeader(
            title = "预算",
            subtitle = "$month 月度可花额度",
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
