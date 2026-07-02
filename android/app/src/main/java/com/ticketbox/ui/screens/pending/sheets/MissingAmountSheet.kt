package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.design.AppSpacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MissingAmountSheetContent(
    expense: Expense,
    chrome: ReviewSheetChrome,
    onSaveDraft: (Long) -> Unit,
    onSaveAndConfirm: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    val currency = expense.originalCurrencyCode
    var input by remember(expense.id) {
        mutableStateOf(formatMinorAmountInput(expense.originalAmountMinor ?: expense.amountCents, currency))
    }
    val originalMinor = parseMinorAmount(input, currency)
    val invalid = input.isNotBlank() && (originalMinor == null || originalMinor <= 0)
    val canSave = originalMinor != null && originalMinor > 0 && !saving
    // P1-2: auto-focus the single amount field so the keyboard pops on open
    // (this is the highest-frequency补录 in the OCR flow).
    val focusRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    ReviewSheetScaffold(
        title = stringResource(R.string.pending_missing_amount_title),
        subtitle = stringResource(R.string.pending_missing_amount_hint),
        chrome = chrome,
    ) {
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.pending_missing_amount_field_label),
                currency = currency,
                value = input,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !saving,
                isError = invalid,
            ),
            actions = AppAmountInputActions(
                onValueChange = { raw ->
                    input = raw
                        .filter { c -> c.isDigit() || (!currency.noFractionDigits && c == '.') }
                        .take(12)
                },
            ),
            focusRequester = focusRequester,
            supportingText = if (invalid) {
                { Text(stringResource(R.string.pending_missing_amount_invalid), color = MaterialTheme.colorScheme.error) }
            } else {
                null
            },
        )

        ReviewSheetStatusMessage(chrome = chrome)

        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(
                text = stringResource(R.string.common_cancel),
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onDismiss,
            )
            AppSecondaryButton(
                text = if (saving) stringResource(R.string.common_saving) else stringResource(R.string.pending_missing_amount_save_draft),
                modifier = Modifier.weight(1f),
                enabled = canSave,
                onClick = { originalMinor?.let(onSaveDraft) },
            )
            Button(
                modifier = Modifier.weight(1.2f),
                enabled = canSave,
                onClick = { originalMinor?.let(onSaveAndConfirm) },
            ) {
                Text(if (saving) stringResource(R.string.pending_missing_amount_processing) else stringResource(R.string.pending_missing_amount_save_and_confirm))
            }
        }

        Text(
            text = stringResource(R.string.pending_missing_amount_footnote),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
