package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag

/** UI navigation only. Facts, counts and session binding remain with their existing owners. */
val LocalAccountingDateReview = staticCompositionLocalOf<(() -> Unit)?> { null }

@Composable
fun AccountingDateNotice(count: Int?) {
    if (count == null || count <= 0) return
    Column(Modifier.testTag("accounting-date-incomplete")) {
        Text(stringResource(R.string.calendar_undated_notice, count), style = MaterialTheme.typography.bodySmall)
        AccountingDateReviewEntry()
    }
}

@Composable
fun AccountingDateReviewEntry() {
    val review = LocalAccountingDateReview.current ?: return
    TextButton(onClick = review, modifier = Modifier.testTag("review-accounting-dates")) {
        Text(stringResource(R.string.calendar_review_dates))
    }
}
