package com.ticketbox.ui.screens.settings

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.notificationCapture
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.presentation.formatDisplayAmount

/** Shows the saved original payment, not an inferred home-currency expense or a confirmation. */
@Composable
internal fun NotificationCaptureIntentSummary(row: OutboxRow) {
    val original = remember(row.payloadJson) { row.notificationCapture() } ?: return
    Text(stringResource(when (original.kind) { "expense" -> R.string.notification_capture_expense; "repayment" -> R.string.notification_capture_repayment; else -> R.string.payment_capture_review_title }))
    Text(stringResource(R.string.notification_capture_original,
        original.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.notification_draft_created_merchant_missing),
        original.originalAmountMinor?.let { formatDisplayAmount(it, CurrencyDisplay.forRecord(original.originalCurrencyCode)) } ?: stringResource(R.string.payment_capture_amount), original.capturedAt))
    Text(stringResource(R.string.notification_capture_pending_explanation))
}
