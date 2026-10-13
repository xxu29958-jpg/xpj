package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.expenseTimeLabel
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun ReviewExpenseSummary(expense: Expense, thumbnail: ProtectedImage? = null, onOpen: (() -> Unit)? = null) {
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth().then(if (onOpen != null) Modifier.clickable(onClick = onOpen) else Modifier)
            .padding(vertical = AppSpacing.smallGap),
        style = AppAdaptiveContentActionStyle(compactAction = true),
        content = {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap), verticalAlignment = Alignment.CenterVertically) {
                if (expense.hasUndeletedImage) AppAsyncImage(thumbnail, layout = AppAsyncImageLayout.ReceiptThumbnail)
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                    Text(expense.merchant?.takeIf(String::isNotBlank) ?: stringResource(R.string.pending_duplicate_sheet_merchant_missing),
                        style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.body.weight)
                    Text(expenseTimeLabel(expense).asString(), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        },
        action = { modifier ->
            val currency = if (expense.originalAmountMinor != null) expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey
                else expense.homeCurrencyCode ?: expense.homeCurrency.storageKey
            Text(stringResource(R.string.pending_review_amount_currency, formatExpensePrimaryAmount(expense), currency),
                modifier = modifier, style = MaterialTheme.typography.titleMedium.tabularNum(), fontWeight = AppTextHierarchy.body.weight)
        },
    )
}
