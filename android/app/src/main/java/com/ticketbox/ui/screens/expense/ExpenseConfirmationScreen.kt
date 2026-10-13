package com.ticketbox.ui.screens.expense

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ReceiptLong
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ExpenseConfirmationReceiptDto
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppBackButton
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.asTextStyle

@Composable
internal fun ExpenseConfirmationScreen(receipt: ExpenseConfirmationReceiptDto, ledgerName: String,
    onOpenBill: () -> Unit, onCompleted: () -> Unit) {
    BackHandler(onBack = onCompleted)
    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(AppPageChrome(AppPageRole.Edit, hasBottomBar = false),
            contentWidth = AppAdaptiveContentWidth.Secondary,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)),
        bottomBar = { AppFloatingActionBar {
            AppPrimaryButton(stringResource(R.string.expense_confirmation_return), modifier = Modifier.fillMaxWidth(), onClick = onCompleted)
        } },
    ) {
        AppBackButton(stringResource(R.string.expense_edit_loading_back_button), onClick = onCompleted)
        Column(Modifier.fillMaxWidth().padding(vertical = AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)) {
            Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer) {
                Box(Modifier.size(80.dp), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(36.dp))
                }
            }
            Text(stringResource(R.string.expense_confirmation_title), style = AppTextHierarchy.hero.asTextStyle(), textAlign = TextAlign.Center)
            Text(listOfNotNull(receipt.merchant?.takeIf(String::isNotBlank), ledgerName.takeIf(String::isNotBlank)).joinToString(" · "),
                style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        }
        ExpenseConfirmationAmount(receipt)
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(stringResource(R.string.expense_confirmation_view), leadingIcon = Icons.Filled.ReceiptLong,
                modifier = Modifier.fillMaxWidth(), onClick = onOpenBill)
            Text(stringResource(R.string.expense_confirmation_current), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ExpenseConfirmationAmount(receipt: ExpenseConfirmationReceiptDto) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(AppRadius.hero), color = MaterialTheme.colorScheme.primaryContainer) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
            Text(stringResource(R.string.expense_confirmation_amount, receipt.homeCurrency), color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText(formatDisplayAmount(receipt.amountCents, CurrencyDisplay.forRecord(receipt.homeCurrency)), role = AppAmountRole.Display)
            if (receipt.originalCurrencyCode != receipt.homeCurrency) {
                Text(stringResource(R.string.expense_confirmation_original, receipt.originalCurrencyCode,
                    formatDisplayAmount(receipt.originalAmountMinor, CurrencyDisplay.forRecord(receipt.originalCurrencyCode))))
            }
            Text(listOfNotNull(receipt.accountingTime?.accountingDate, receipt.category).joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
