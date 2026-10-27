package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import java.time.YearMonth

/** An explicit choice when the ledger cannot supply a default month. */
@Composable
fun FinancialMonthInput(onSelectMonth: (String) -> Unit, enabled: Boolean = true, initialValue: String = "") {
    var value by rememberSaveable { mutableStateOf(initialValue) }
    val month = value.trim().takeIf { it.length == 7 }?.let { runCatching { YearMonth.parse(it).toString() }.getOrNull() }
    Column {
        AppTextInput(
            state = AppTextInputState(label = stringResource(R.string.financial_month_label), value = value,
                placeholder = stringResource(R.string.financial_month_format), enabled = enabled),
            actions = AppTextInputActions(onValueChange = { value = it }),
        )
        TextButton(onClick = { month?.let(onSelectMonth) }, enabled = enabled && month != null) {
            Text(stringResource(R.string.common_confirm))
        }
    }
}
