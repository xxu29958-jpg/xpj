package com.ticketbox.ui.screens.expense.fact

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.viewmodel.OffsetFormState

/** Input error and remaining-balance text shared by the offset sheet. */
@Composable
internal fun offsetFieldErrorText(error: UiText?): (@Composable () -> Unit)? {
    val text = error ?: return null
    return {
        Text(
            text = text.asString(),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun offsetAmountSupportingText(
    form: OffsetFormState,
    summary: ExpenseFinancialSummary?,
    currency: CurrencyCode,
): (@Composable () -> Unit)? {
    offsetFieldErrorText(form.amountError)?.let { return it }
    val hint = if (summary != null) {
        stringResource(
            R.string.expense_offset_remaining_hint,
            formatAmountInput(summary.remainingRefundableOriginalMinor, currency),
        )
    } else {
        stringResource(R.string.expense_offset_remaining_unavailable)
    }
    return {
        Text(
            text = hint,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
