package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Save
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
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.formatMinorAmount
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.components.sanitizeMinorAmountInput
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MissingAmountSheetContent(
    expense: Expense,
    chrome: ReviewSheetChrome,
    onSaveDraft: (Long) -> Unit,
    onSaveAndConfirm: (Long) -> Unit,
) {
    val saving = chrome.saving
    val currency = expense.originalCurrencyCode
    val suggestedMinor = expense.originalAmountMinor?.takeIf { it > 0 }
    val suggestedInput = remember(expense.id, suggestedMinor, currency) {
        formatMinorAmountInput(suggestedMinor, currency)
    }
    var input by remember(expense.id) {
        mutableStateOf("")
    }
    val originalMinor = parseMinorAmount(input, currency)
    val invalid = input.isNotBlank() && (originalMinor == null || originalMinor <= 0)
    val canSave = originalMinor != null && originalMinor > 0 && !saving
    // P1-2: auto-focus the single amount field in the OCR review flow.
    val focusRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    ReviewSheetScaffold(
        title = stringResource(R.string.pending_missing_amount_title),
        subtitle = stringResource(R.string.pending_missing_amount_hint),
        chrome = chrome,
    ) {
        MissingAmountSuggestion(
            suggestedMinor = suggestedMinor,
            currency = currency,
            enabled = !saving && suggestedInput.isNotBlank(),
            onUseSuggestion = { input = suggestedInput },
        )

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
                    input = sanitizeMinorAmountInput(raw, currency)
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

        AppSheetActionRow(
            primary = AppSheetAction(
                text = if (saving) {
                    stringResource(R.string.pending_missing_amount_processing)
                } else {
                    stringResource(R.string.pending_missing_amount_save_and_confirm)
                },
                enabled = canSave,
                icon = Icons.Filled.Check,
                onClick = { originalMinor?.let(onSaveAndConfirm) },
            ),
            secondary = AppSheetAction(
                text = if (saving) stringResource(R.string.common_saving) else stringResource(R.string.pending_missing_amount_save_draft),
                enabled = canSave,
                icon = Icons.Filled.Save,
                onClick = { originalMinor?.let(onSaveDraft) },
            ),
        )
    }
}

@Composable
private fun MissingAmountSuggestion(
    suggestedMinor: Long?,
    currency: CurrencyCode,
    enabled: Boolean,
    onUseSuggestion: () -> Unit,
) {
    if (suggestedMinor == null) return
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth(),
        content = {
            Column(
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = stringResource(R.string.pending_missing_amount_suggestion_label),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
                Text(
                    text = formatMinorAmount(suggestedMinor, currency),
                    style = MaterialTheme.typography.titleLarge.tabularNum(),
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
        },
        action = { actionModifier ->
            QuietOutlinedButton(
                text = stringResource(R.string.pending_missing_amount_use_suggestion),
                modifier = actionModifier,
                enabled = enabled,
                onClick = onUseSuggestion,
            )
        },
    )
}
