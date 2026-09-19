package com.ticketbox.ui.screens

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import com.ticketbox.ui.screens.expense.toSavedJson
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecentMerchant
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.LocalAppImeVisible
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFieldOptions
import com.ticketbox.ui.screens.expense.ExpenseEditTextField
import com.ticketbox.ui.screens.expense.ExpenseEditTextFieldState

data class ManualExpenseSheetState(
    val categories: List<String>,
    val saving: Boolean,
    val recentMerchants: List<RecentMerchant> = emptyList(),
    val initialCurrency: CurrencyCode,
    val ledgerHomeCurrency: CurrencyCode = initialCurrency,
    val errorMessage: String? = null,
    val editable: Boolean = true,
)

data class ManualExpenseSheetActions(
    val onCreate: (ExpenseDraft) -> Unit,
    val onDismiss: () -> Unit,
)

data class ManualExpenseSheetInitials(
    val merchant: String = "",
    val category: String = DEFAULT_EXPENSE_CATEGORIES.first(),
    val note: String = "",
    val amountMinor: Long? = null,
    val amountText: String? = null,
    val expenseTime: String? = null,
    val timeFormJson: String? = null,
)

data class ManualExpenseSheetDraft(
    val amountText: String,
    val currency: CurrencyCode,
    val merchant: String,
    val category: String,
    val note: String,
    val expenseTime: String,
    val timeFormJson: String? = null,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManualExpenseSheet(
    state: ManualExpenseSheetState,
    actions: ManualExpenseSheetActions,
    initials: ManualExpenseSheetInitials = ManualExpenseSheetInitials(),
    onDraftChange: ((ManualExpenseSheetDraft) -> Unit)? = null,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var amountText by rememberSaveable {
        mutableStateOf(initials.amountText ?: formatMinorAmountInput(initials.amountMinor, state.initialCurrency))
    }
    val homeCurrency by rememberSaveable { mutableStateOf(state.ledgerHomeCurrency) }
    var currency by rememberSaveable { mutableStateOf(state.initialCurrency) }
    var merchant by rememberSaveable { mutableStateOf(initials.merchant) }
    var category by rememberSaveable {
        mutableStateOf(initials.category.ifBlank { DEFAULT_EXPENSE_CATEGORIES.first() })
    }
    var note by rememberSaveable { mutableStateOf(initials.note) }
    val (timeForm, setTimeForm) = com.ticketbox.ui.screens.expense.rememberExpenseTimeForm(
        "manual", initials.expenseTime ?: nowUtcIso(), saved = initials.timeFormJson,
    )
    val expenseTime = timeForm.resolve().instant.orEmpty()
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    val invalidAmountMessage = stringResource(R.string.ledger_manual_amount_invalid)
    val density = LocalDensity.current
    val keyboardVisible = LocalAppImeVisible.current || WindowInsets.ime.getBottom(density) > 0
    LaunchedEffect(amountText, currency, merchant, category, note, timeForm) {
        onDraftChange?.invoke(
            ManualExpenseSheetDraft(
                amountText = amountText,
                currency = currency,
                merchant = merchant,
                category = category,
                note = note,
                expenseTime = expenseTime,
                timeFormJson = timeForm.toSavedJson(),
            ),
        )
    }

    fun draftOrMessage(): ExpenseDraft? {
        val originalMinor = parseMinorAmount(amountText, currency)
        if (originalMinor == null) {
            message = invalidAmountMessage
            return null
        }
        val time = timeForm.resolve()
        if (time.error != null) { message = context.getString(time.error); return null }
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            merchant = merchant.ifBlank { null },
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = time.instant,
            timeInput = time.input,
            tags = null,
            valueScore = null,
            regretScore = null,
            ledgerHomeCurrency = homeCurrency,
        )
    }

    fun submitDraft() {
        submitManualExpenseDraft(state.editable, state.saving, ::draftOrMessage) { draft ->
            message = null
            actions.onCreate(draft)
        }
    }

    val fieldsEnabled = state.editable && !state.saving
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
                    enabled = fieldsEnabled,
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
                    enabled = fieldsEnabled,
                ),
                onValueChange = { merchant = it },
                modifier = Modifier.fillMaxWidth(),
            )
            ManualRecentMerchantsSection(
                recentMerchants = state.recentMerchants,
                selectedMerchant = merchant,
                enabled = fieldsEnabled,
                onPick = { picked ->
                    merchant = picked.merchant
                    category = picked.category
                },
            )
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.ledger_manual_category_label),
                    value = category,
                    enabled = fieldsEnabled,
                ),
                onValueChange = { category = it },
                modifier = Modifier.fillMaxWidth(),
            )
            ManualCategoryChoices(
                categories = state.categories,
                selectedCategory = category,
                enabled = fieldsEnabled,
                onCategoryChange = { category = it },
            )
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.ledger_manual_note_label),
                    value = note,
                    enabled = fieldsEnabled,
                    singleLine = false,
                    minLines = 1,
                ),
                onValueChange = { note = it },
                modifier = Modifier.fillMaxWidth(),
            )
            com.ticketbox.ui.screens.expense.ExpenseTimeEditor(timeForm, setTimeForm, fieldsEnabled)
            ManualExpenseActionSlot(
                feedbackMessage = feedbackMessage,
                saving = state.saving,
                editable = state.editable,
                onDismiss = actions.onDismiss,
                onSubmit = ::submitDraft,
            )
        }
    }
}

private fun submitManualExpenseDraft(
    editable: Boolean,
    saving: Boolean,
    draft: () -> ExpenseDraft?,
    onCreate: (ExpenseDraft) -> Unit,
) {
    if (!editable || saving) return
    val created = draft() ?: return
    onCreate(created)
}

@Composable
private fun ManualExpenseActionSlot(
    feedbackMessage: String?,
    saving: Boolean,
    editable: Boolean,
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
            enabled = editable && !saving,
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
    enabled: Boolean = true,
    onPick: (RecentMerchant) -> Unit,
) {
    if (recentMerchants.isEmpty()) return
    ManualRecentMerchants(
        recentMerchants = recentMerchants,
        selectedMerchant = selectedMerchant,
        enabled = enabled,
        onPick = onPick,
    )
}

@Composable
private fun ManualCategoryChoices(
    categories: List<String>,
    selectedCategory: String,
    enabled: Boolean = true,
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
                    enabled = enabled,
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
    enabled: Boolean = true,
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
                        enabled = enabled,
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
    enabled: Boolean = true,
) {
    AppFilterChip(
        selected = selected,
        onClick = onClick,
        label = label,
        options = AppFilterChipOptions(
            enabled = enabled,
            selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.22f),
        ),
    )
}
