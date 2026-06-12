package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.DuplicateNotice
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.screens.expense.EditDraftPreviewCard
import com.ticketbox.ui.screens.expense.ExpenseDateField
import com.ticketbox.ui.screens.expense.ExpenseEditActionBar
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarActions
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarState
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseEditDatePicker
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSection
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseEditRecognizeTextDialog
import com.ticketbox.ui.screens.expense.ExpenseEditRejectDialog
import com.ticketbox.ui.screens.expense.ExpenseEditSourceInfo
import com.ticketbox.ui.screens.expense.ExpenseEditTimePicker
import com.ticketbox.ui.screens.expense.ExpenseEditV1DetailsSection
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.OcrProgressCard
import com.ticketbox.ui.screens.expense.SplitsEditorSheet
import com.ticketbox.viewmodel.ExpenseEditUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseEditScreen(
    expense: Expense,
    state: ExpenseEditUiState,
    onSave: (ExpenseDraft) -> Unit,
    onConfirm: (ExpenseDraft) -> Unit,
    onReject: () -> Unit,
    onRetryOcr: () -> Unit,
    onRecognizeText: (String) -> Unit = {},
    onOpenRecognizeText: () -> Unit = {},
    onDismissRecognizeText: () -> Unit = {},
    onLoadFullImage: () -> Unit,
    onKeepDuplicate: () -> Unit,
    onDone: () -> Unit,
    onAcknowledgeItemsMismatch: () -> Unit = {},
    onEditItems: () -> Unit = {},
    onUpdateItemDraft: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit = { _, _, _, _ -> },
    onAddItemRow: () -> Unit = {},
    onRemoveItemRow: (index: Int) -> Unit = {},
    onSaveItems: () -> Unit = {},
    onDismissItemsEditor: () -> Unit = {},
    onEditSplits: () -> Unit = {},
    onToggleSplitMember: (memberId: Long, included: Boolean) -> Unit = { _, _ -> },
    onUpdateSplitAmount: (memberId: Long, amountText: String) -> Unit = { _, _ -> },
    onEvenSplit: () -> Unit = {},
    onSaveSplits: () -> Unit = {},
    onDismissSplitsEditor: () -> Unit = {},
    allowConfirm: Boolean = true,
    allowReject: Boolean = true,
) {
    BackHandler {
        if (!state.saving) {
            onDone()
        }
    }

    if (state.itemEditorOpen) {
        ItemsEditorSheet(
            drafts = state.itemDrafts,
            parentAmountCents = state.expenseItems?.parentAmountCents,
            saving = state.itemsSaving,
            onUpdate = onUpdateItemDraft,
            onAddRow = onAddItemRow,
            onRemoveRow = onRemoveItemRow,
            onSave = onSaveItems,
            onDismiss = onDismissItemsEditor,
        )
    }

    if (state.splitEditorOpen) {
        SplitsEditorSheet(
            drafts = state.splitDrafts,
            parentAmountCents = state.expenseSplits?.parentAmountCents,
            saving = state.splitsSaving,
            loading = state.splitMembersLoading,
            onToggleMember = onToggleSplitMember,
            onUpdateAmount = onUpdateSplitAmount,
            onEvenSplit = onEvenSplit,
            onSave = onSaveSplits,
            onDismiss = onDismissSplitsEditor,
        )
    }

    if (state.recognizeTextDialogOpen && !state.readOnly) {
        ExpenseEditRecognizeTextDialog(
            onRecognize = onRecognizeText,
            onDismiss = onDismissRecognizeText,
        )
    }

    val currentExpense = state.expense ?: expense
    // rememberSaveable (not remember): without Manifest configChanges, a
    // rotation / dark-mode switch / process death recreates the activity and a
    // plain remember silently resets every unsaved field back to server values
    // — saving then writes stale data. Same fields in ManualExpenseSheet are
    // already saveable; CurrencyCode is an enum (Bundle-safe, proven there).
    var currency by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.originalCurrencyCode)
    }
    var originalAmountText by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(
            formatMinorAmountInput(
                currentExpense.originalAmountMinor ?: currentExpense.amountCents,
                currentExpense.originalCurrencyCode,
            )
        )
    }
    var merchant by rememberSaveable(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.merchant.orEmpty()) }
    var category by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(normalizeExpenseCategory(currentExpense.category))
    }
    var note by rememberSaveable(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.note.orEmpty()) }
    var expenseTime by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.expenseTime.orEmpty())
    }
    var tags by rememberSaveable(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.tags.orEmpty()) }
    var valueScoreText by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.valueScore?.toString().orEmpty())
    }
    var regretScoreText by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.regretScore?.toString().orEmpty())
    }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var rawTextExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    var moreExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    var showDatePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showTimePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showRejectDialog by remember(currentExpense.id) { mutableStateOf(false) }
    var showLargeImage by remember(currentExpense.id) { mutableStateOf(false) }
    val rawTextDisplay = currentExpense.rawText?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.expense_edit_raw_text_empty)
    val previewImage = state.fullImage ?: state.thumbnail
    val readOnly = state.readOnly
    val haptics = rememberAppHaptics()
    // ADR-0044: stringResource is @Composable-only, but the validation messages
    // below are assigned inside non-composable local functions / onClick lambdas.
    // Hoist the resolved strings (the out-of-range one as a format template) here.
    val valueScoreLabel = stringResource(R.string.expense_edit_score_value_label)
    val regretScoreLabel = stringResource(R.string.expense_edit_score_regret_label)
    val scoreOutOfRangeTemplate = stringResource(R.string.expense_edit_score_out_of_range)
    val amountInvalidMessage = stringResource(R.string.expense_edit_amount_invalid)
    val amountRequiredMessage = stringResource(R.string.expense_edit_amount_required)

    if (showDatePicker) {
        ExpenseEditDatePicker(
            expenseTime = expenseTime,
            onSetExpenseTime = { expenseTime = it },
            onDismiss = { showDatePicker = false },
        )
    }
    if (showTimePicker) {
        ExpenseEditTimePicker(
            expenseTime = expenseTime,
            onSetExpenseTime = { expenseTime = it },
            onDismiss = { showTimePicker = false },
        )
    }
    if (showRejectDialog) {
        ExpenseEditRejectDialog(
            onConfirm = onReject,
            onDismiss = { showRejectDialog = false },
        )
    }

    LaunchedEffect(state.done) {
        if (state.done) onDone()
    }

    fun parseScore(raw: String, label: String): Int? {
        if (raw.isBlank()) return null
        val score = raw.toIntOrNull()
        if (score == null || score !in 1..5) {
            message = scoreOutOfRangeTemplate.format(label)
            return null
        }
        return score
    }

    fun draftOrMessage(): ExpenseDraft? {
        val originalMinor = parseMinorAmount(originalAmountText, currency)
        if (originalAmountText.isNotBlank() && originalMinor == null) {
            message = amountInvalidMessage
            return null
        }
        val valueScore = if (valueScoreText.isBlank()) null else (parseScore(valueScoreText, valueScoreLabel) ?: return null)
        val regretScore = if (regretScoreText.isBlank()) null else (parseScore(regretScoreText, regretScoreLabel) ?: return null)
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            // Blank merchant/tags submit as "" (NOT null): Moshi omits null
            // keys and the backend PATCH is exclude_unset, so null silently
            // means "unchanged" — clearing a field then never took effect.
            // The backend's _clean_optional_text("") / normalize_tags("")
            // already treat "" as an explicit clear.
            merchant = merchant,
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = expenseTime.ifBlank { null },
            tags = tags,
            valueScore = valueScore,
            regretScore = regretScore,
        )
    }

    // 操作栏的保存/确认入账点击逻辑用具名局部函数（普通 return），避免在
    // 构造器实参 lambda 里玩 return@label。
    fun submitSave() {
        val draft = draftOrMessage() ?: return
        haptics.tick()
        onSave(draft)
    }

    fun submitConfirm() {
        val draft = draftOrMessage() ?: return
        if (draft.originalAmountMinor == null) {
            message = amountRequiredMessage
            return
        }
        haptics.confirm()
        onConfirm(draft)
    }

    AppPageScrollableColumn(
        role = AppPageRole.Edit,
        // 操作栏浮在底部：底部空间由实测栏高让出（见 AppPageScrollableColumn），
        // 不走静态 BottomBarHeight 估算，故 hasBottomBar = false 避免双重预留。
        hasBottomBar = false,
        includeStatusBarPadding = true,
        verticalArrangement = Arrangement.spacedBy(12.dp),
        bottomBar = {
            ExpenseEditActionBar(
                state = ExpenseEditActionBarState(
                    saving = state.saving,
                    allowSave = !readOnly,
                    allowConfirm = allowConfirm && !readOnly,
                    allowReject = allowReject && !readOnly,
                    validationMessage = message,
                    statusMessage = state.message?.asString(),
                ),
                actions = ExpenseEditActionBarActions(
                    onBack = onDone,
                    onSave = ::submitSave,
                    onConfirm = ::submitConfirm,
                    onRequestReject = { showRejectDialog = true },
                ),
            )
        },
    ) {
        AppPageHeader(
            title = stringResource(R.string.expense_edit_header_title),
            subtitle = stringResource(R.string.expense_edit_header_subtitle),
            eyebrow = "",
        ) {
            StatusPill(
                if (currentExpense.status == "pending") {
                    stringResource(R.string.expense_edit_status_pending)
                } else {
                    stringResource(R.string.expense_edit_status_confirmed)
                }
            )
        }

        EditDraftPreviewCard(
            expense = currentExpense,
            previewImage = previewImage,
            imageLoading = state.imageLoading,
            ocrRunning = state.ocrRunning,
            readOnly = readOnly,
            showLargeImage = showLargeImage,
            onToggleLargeImage = {
                if (!showLargeImage && state.fullImage == null) {
                    onLoadFullImage()
                }
                showLargeImage = !showLargeImage
            },
            onRetryOcr = onRetryOcr,
        )

        if (showLargeImage && currentExpense.imagePath != null) {
            AppAsyncImage(
                image = state.fullImage ?: previewImage,
                placeholder = if (state.imageLoading) {
                    stringResource(R.string.expense_edit_large_image_loading)
                } else {
                    stringResource(R.string.expense_edit_large_image_failed)
                },
                contentScale = ContentScale.Fit,
                displayHeight = 420.dp,
            )
        }

        if (currentExpense.duplicateStatus == "suspected") {
            DuplicateNotice(reason = currentExpense.duplicateReason)
            if (!readOnly) {
                AppOutlinedButton(onClick = onKeepDuplicate) {
                    Text(stringResource(R.string.expense_edit_keep_duplicate_button))
                }
            }
        }

        AnimatedVisibility(visible = state.ocrRunning) {
            OcrProgressCard()
        }

        ExpenseCurrencyFields(
            currency = currency,
            onCurrencyChange = {
                currency = it
            },
            originalAmountText = originalAmountText,
            onOriginalAmountChange = { originalAmountText = it },
            enabled = !readOnly,
        )
        ExpenseEditMerchantField(
            merchant = merchant,
            onMerchantChange = { merchant = it },
            enabled = !readOnly,
        )
        ExpenseEditCategoryField(
            category = category,
            categories = state.categories,
            onCategoryChange = { category = it },
            enabled = !readOnly,
        )
        ExpenseEditNoteField(
            note = note,
            onNoteChange = { note = it },
            enabled = !readOnly,
        )
        ExpenseDateField(
            expenseTime = expenseTime,
            onPickDate = { showDatePicker = true },
            onPickTime = { showTimePicker = true },
            onUseNow = { expenseTime = nowUtcIso() },
            onClear = { expenseTime = "" },
            enabled = !readOnly,
        )
        ExpenseEditSourceInfo(
            source = currentExpense.source,
            confidence = currentExpense.confidence,
        )

        ExpenseEditV1DetailsSection(
            expenseItems = state.expenseItems,
            expenseSplits = state.expenseSplits,
            itemsLoading = state.itemsLoading,
            splitsLoading = state.splitsLoading,
            itemsMessage = state.itemsMessage,
            splitsMessage = state.splitsMessage,
            onAcknowledgeItemsMismatch = onAcknowledgeItemsMismatch,
            onEditItems = if (state.readOnly) null else onEditItems,
            onEditSplits = if (state.readOnly) null else onEditSplits,
        )

        ExpenseEditMoreSection(
            tags = tags,
            onTagsChange = { tags = it },
            valueScoreText = valueScoreText,
            onValueScoreChange = { valueScoreText = it },
            regretScoreText = regretScoreText,
            onRegretScoreChange = { regretScoreText = it },
            rawTextDisplay = rawTextDisplay,
            moreExpanded = moreExpanded,
            onToggleMore = { moreExpanded = !moreExpanded },
            rawTextExpanded = rawTextExpanded,
            onToggleRawText = { rawTextExpanded = !rawTextExpanded },
            ocrRunning = state.ocrRunning,
            saving = state.saving,
            readOnly = readOnly,
            canRecognize = expense.status == "pending",
            onRetryOcr = onRetryOcr,
            onRecognizeText = onOpenRecognizeText,
        )

        // 保存 / 确认入账 / 删除 与校验提示现在浮在底部操作栏（见 bottomBar），
        // 不再钉在长表单滚动末尾。
    }
}
