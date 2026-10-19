package com.ticketbox.ui.screens

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun FundsActivityCorrectionFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_void_activity_hint))
    Text(input.activityLabel)
    input.activityParts.forEach { part ->
        Text("${part.accountName}：${money(part.amountMinor, part.currencyCode)}")
    }
    FundsField(stringResource(R.string.funds_credit_void_reason), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}
