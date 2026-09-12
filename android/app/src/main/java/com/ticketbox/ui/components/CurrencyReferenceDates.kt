package com.ticketbox.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyReferenceRate

@Composable
internal fun CurrencyReferenceDates(rates: List<CurrencyReferenceRate>) {
    rates.forEach { rate ->
        Text(stringResource(R.string.projection_reference_date, rate.sourceCurrencyCode, rate.homeCurrencyCode, rate.rateDate),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
