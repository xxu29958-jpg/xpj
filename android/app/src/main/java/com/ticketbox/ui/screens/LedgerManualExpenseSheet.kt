package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimeInput
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecentMerchant
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.LocalAppImeVisible
import com.ticketbox.ui.components.datePickerMillisToUtcIso
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.components.selectedHourFromIso
import com.ticketbox.ui.components.selectedMinuteFromIso
import com.ticketbox.ui.components.timePickerToUtcIso
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseDateControl
import com.ticketbox.ui.screens.expense.ExpenseDateControlActions
import com.ticketbox.ui.screens.expense.ExpenseDateControlLabels
import com.ticketbox.ui.screens.expense.ExpenseDateControlState
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFieldOptions
import com.ticketbox.ui.screens.expense.ExpenseEditTextField
import com.ticketbox.ui.screens.expense.ExpenseEditTextFieldState

data class ManualExpenseSheetState(
    val categories: List<String>,
    val saving: Boolean,
    val recentMerchants: List<RecentMerchant> = emptyList(),
    val initialCurrency: CurrencyCode = FxContract.HomeCurrency,
    val errorMessage: String? = null,
)

data class ManualExpenseSheetActions(
    val onCreate: (ExpenseDraft) -> Unit,
    val onDismiss: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManualExpenseSheet(
    state: ManualExpenseSheetState,
    actions: ManualExpenseSheetActions,
) {
    var amountText by rememberSaveable { mutableStateOf("") }
    var currency by rememberSaveable(state.initialCurrency) { mutableStateOf(state.initialCurrency) }
    var merchant by rememberSaveable { mutableStateOf("") }
    var category by rememberSaveable { mutableStateOf(DEFAULT_EXPENSE_CATEGORIES.first()) }
    var note by rememberSaveable { mutableStateOf("") }
    var expenseTime by rememberSaveable { mutableStateOf(nowUtcIso()) }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var showDatePicker by rememberSaveable { mutableStateOf(false) }
    var showTimePicker by rememberSaveable { mutableStateOf(false) }
    val invalidAmountMessage = stringResource(R.string.ledger_manual_amount_invalid)
    val density = LocalDensity.current
    val keyboardVisible = LocalAppImeVisible.current || WindowInsets.ime.getBottom(density) > 0

    if (showDatePicker) {
        val datePickerState = androidx.compose.material3.rememberDatePickerState(
            initialSelectedDateMillis = selectedDateMillisFromIso(expenseTime),
        )
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        datePickerState.selectedDateMillis?.let { selected ->
                            expenseTime = datePickerMillisToUtcIso(selected, expenseTime)
                        }
                        showDatePicker = false
                    },
                ) {
                    Text(stringResource(R.string.common_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        ) {
            DatePicker(
                state = datePickerState,
                title = {
                    Text(
                        stringResource(R.string.ledger_manual_date_picker_title),
                        modifier = Modifier.padding(
                            start = AppSpacing.cardPadding,
                            end = AppSpacing.compactGap,
                            top = AppSpacing.cardPaddingSmall,
                        ),
                    )
                },
            )
        }
    }

    if (showTimePicker) {
        val timePickerState = androidx.compose.material3.rememberTimePickerState(
            initialHour = selectedHourFromIso(expenseTime),
            initialMinute = selectedMinuteFromIso(expenseTime),
            is24Hour = true,
        )
        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            title = { Text(stringResource(R.string.ledger_manual_time_picker_title)) },
            text = { TimeInput(state = timePickerState) },
            confirmButton = {
                TextButton(
                    onClick = {
                        expenseTime = timePickerToUtcIso(
                            hour = timePickerState.hour,
                            minute = timePickerState.minute,
                            currentIso = expenseTime,
                        )
                        showTimePicker = false
                    },
                ) {
                    Text(stringResource(R.string.common_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    fun draftOrMessage(): ExpenseDraft? {
        val originalMinor = parseMinorAmount(amountText, currency)
        if (originalMinor == null) {
            message = invalidAmountMessage
            return null
        }
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            merchant = merchant.ifBlank { null },
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = expenseTime.ifBlank { nowUtcIso() },
            tags = null,
            valueScore = null,
            regretScore = null,
        )
    }

    fun submitDraft() {
        val draft = draftOrMessage() ?: return
        // The sheet closes only after the repository reports success.
        message = null
        actions.onCreate(draft)
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        AppSheetScaffold(
            title = stringResource(R.string.ledger_manual_sheet_title),
            subtitle = stringResource(R.string.ledger_manual_sheet_subtitle),
            compact = keyboardVisible,
        ) {
            ExpenseCurrencyFields(
                    currency = currency,
                    onCurrencyChange = {
                        currency = it
                },
                amountText = amountText,
                onAmountChange = { amountText = it },
                options = ExpenseCurrencyFieldOptions(
                    enabled = !state.saving,
                    autoFocusAmount = false,
                    showFxHint = false,
                    showSectionTitle = false,
                    supportingText = stringResource(R.string.ledger_manual_amount_supporting_text),
                ),
            )
            val feedbackMessage = message ?: state.errorMessage
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.ledger_manual_merchant_label),
                    value = merchant,
                    placeholder = stringResource(R.string.ledger_manual_merchant_placeholder),
                    enabled = !state.saving,
                ),
                onValueChange = { merchant = it },
                modifier = Modifier.fillMaxWidth(),
            )
            ManualRecentMerchantsSection(
                recentMerchants = state.recentMerchants,
                selectedMerchant = merchant,
                onPick = { picked ->
                    merchant = picked.merchant
                    category = picked.category
                },
            )
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.ledger_manual_category_label),
                    value = category,
                    enabled = !state.saving,
                ),
                onValueChange = { category = it },
                modifier = Modifier.fillMaxWidth(),
            )
            ManualCategoryChoices(
                categories = state.categories,
                selectedCategory = category,
                onCategoryChange = { category = it },
            )
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.ledger_manual_note_label),
                    value = note,
                    enabled = !state.saving,
                    singleLine = false,
                    minLines = 1,
                ),
                onValueChange = { note = it },
                modifier = Modifier.fillMaxWidth(),
            )
            ManualExpenseTimeSection(
                expenseTime = expenseTime,
                onPickDate = { showDatePicker = true },
                onPickTime = { showTimePicker = true },
                onUseNow = { expenseTime = nowUtcIso() },
            )
            ManualExpenseActionSlot(
                feedbackMessage = feedbackMessage,
                saving = state.saving,
                onDismiss = actions.onDismiss,
                onSubmit = ::submitDraft,
            )
        }
    }
}

@Composable
private fun ManualExpenseTimeSection(
    expenseTime: String,
    onPickDate: () -> Unit,
    onPickTime: () -> Unit,
    onUseNow: () -> Unit,
) {
    ExpenseDateControl(
        state = ExpenseDateControlState(
            title = stringResource(R.string.ledger_manual_time_section_title),
            expenseTime = expenseTime,
        ),
        labels = ExpenseDateControlLabels(
            pickDate = stringResource(R.string.ledger_manual_pick_date_button),
            pickTime = stringResource(R.string.ledger_manual_pick_time_button),
            useNow = stringResource(R.string.ledger_manual_now_button),
        ),
        actions = ExpenseDateControlActions(
            onPickDate = onPickDate,
            onPickTime = onPickTime,
            onUseNow = onUseNow,
        ),
    )
}

@Composable
private fun ManualExpenseActionSlot(
    feedbackMessage: String?,
    saving: Boolean,
    onDismiss: () -> Unit,
    onSubmit: () -> Unit,
) {
    AppSheetActionFeedback(
        state = AppSheetActionFeedbackState(
            statusMessage = feedbackMessage,
            statusTone = MessageTone.Danger,
        ),
        primary = AppSheetAction(
            text = if (saving) {
                stringResource(R.string.ledger_manual_saving_button)
            } else {
                stringResource(R.string.ledger_manual_save_button)
            },
            icon = Icons.Filled.Check,
            enabled = !saving,
            onClick = onSubmit,
        ),
        secondary = AppSheetAction(
            text = stringResource(R.string.common_cancel),
            enabled = !saving,
            onClick = onDismiss,
        ),
    )
}

@Composable
private fun ManualRecentMerchantsSection(
    recentMerchants: List<RecentMerchant>,
    selectedMerchant: String,
    onPick: (RecentMerchant) -> Unit,
) {
    if (recentMerchants.isEmpty()) return
    ManualRecentMerchants(
        recentMerchants = recentMerchants,
        selectedMerchant = selectedMerchant,
        onPick = onPick,
    )
}

@Composable
private fun ManualCategoryChoices(
    categories: List<String>,
    selectedCategory: String,
    onCategoryChange: (String) -> Unit,
) {
    if (categories.isEmpty()) return
    AppCompactChips {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            categories.forEach { item ->
                SelectableFilterChip(
                    selected = selectedCategory == item,
                    label = item,
                    onClick = { onCategoryChange(item) },
                )
            }
        }
    }
}

/**
 * Quick-fill chips of the user's recently-used merchants on the manual-entry
 * sheet. One tap fills the merchant field and carries the category last paired
 * with it (see [recentLedgerMerchants]). Tapping is an explicit manual action,
 * so this is not an AI/OCR auto-fill of a blank field.
 */
@Composable
private fun ManualRecentMerchants(
    recentMerchants: List<RecentMerchant>,
    selectedMerchant: String,
    onPick: (RecentMerchant) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(R.string.ledger_manual_recent_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        AppCompactChips {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                recentMerchants.forEach { recent ->
                    SelectableFilterChip(
                        selected = selectedMerchant == recent.merchant,
                        label = recent.merchant,
                        onClick = { onPick(recent) },
                    )
                }
            }
        }
    }
}

@Composable
fun CategoryFilterRow(
    categories: List<String>,
    selectedCategory: String,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(R.string.ledger_category_filter_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        AppCompactChips {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                SelectableFilterChip(
                    selected = selectedCategory.isBlank(),
                    label = stringResource(R.string.ledger_category_filter_all),
                    onClick = { onCategoryChange("") },
                )
                categories.forEach { category ->
                    SelectableFilterChip(
                        selected = selectedCategory == category,
                        label = category,
                        onClick = { onCategoryChange(category) },
                    )
                }
            }
        }
    }
}

@Composable
fun SelectableFilterChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
) {
    AppFilterChip(
        selected = selected,
        onClick = onClick,
        label = label,
        selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.22f),
    )
}
