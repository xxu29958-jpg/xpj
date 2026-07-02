package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun QuickMerchantSheetContent(
    expense: Expense,
    chrome: ReviewSheetChrome,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    var value by remember(expense.id) { mutableStateOf(expense.merchant.orEmpty()) }
    val cleaned = value.trim()
    // P1-2: single-field sheet — auto-focus so the keyboard pops on open.
    val focusRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    ReviewSheetScaffold(
        title = stringResource(R.string.pending_quick_merchant_title),
        subtitle = stringResource(R.string.pending_quick_merchant_hint),
        chrome = chrome,
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = { value = it.take(40) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
            label = { Text(stringResource(R.string.pending_quick_merchant_label)) },
            placeholder = { Text(stringResource(R.string.pending_quick_merchant_placeholder)) },
            modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
            enabled = !saving,
            isError = value.isNotEmpty() && cleaned.isEmpty(),
            supportingText = if (value.isNotEmpty() && cleaned.isEmpty()) {
                { Text(stringResource(R.string.pending_quick_merchant_blank_error), color = MaterialTheme.colorScheme.error) }
            } else null,
        )

        ReviewSheetStatusMessage(chrome = chrome)

        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(
                text = stringResource(R.string.common_cancel),
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onDismiss,
            )
            Button(
                modifier = Modifier.weight(1f),
                enabled = !saving && cleaned.isNotEmpty(),
                onClick = { onSave(cleaned) },
            ) {
                Text(if (saving) stringResource(R.string.common_saving) else stringResource(R.string.pending_quick_merchant_save_button))
            }
        }
    }
}
