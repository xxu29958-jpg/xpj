package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
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
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.screens.expense.EditDraftPreviewCard
import com.ticketbox.ui.screens.expense.ExpenseDateField
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField
import com.ticketbox.ui.screens.expense.ExpenseEditConfirmActions
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseEditDatePicker
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSection
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseEditPrimaryActions
import com.ticketbox.ui.screens.expense.ExpenseEditRejectDialog
import com.ticketbox.ui.screens.expense.ExpenseEditSourceInfo
import com.ticketbox.ui.screens.expense.ExpenseEditTimePicker
import com.ticketbox.ui.screens.expense.ExpenseEditV1DetailsSection
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.OcrProgressCard
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

    val currentExpense = state.expense ?: expense
    var currency by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.originalCurrencyCode)
    }
    var originalAmountText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(
            formatMinorAmountInput(
                currentExpense.originalAmountMinor ?: currentExpense.amountCents,
                currentExpense.originalCurrencyCode,
            )
        )
    }
    var merchant by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.merchant.orEmpty()) }
    var category by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(normalizeExpenseCategory(currentExpense.category))
    }
    var note by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.note.orEmpty()) }
    var expenseTime by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.expenseTime.orEmpty())
    }
    var tags by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.tags.orEmpty()) }
    var valueScoreText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.valueScore?.toString().orEmpty())
    }
    var regretScoreText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.regretScore?.toString().orEmpty())
    }
    var message by remember { mutableStateOf<String?>(null) }
    var rawTextExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    var moreExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    var showDatePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showTimePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showRejectDialog by remember(currentExpense.id) { mutableStateOf(false) }
    var showLargeImage by remember(currentExpense.id) { mutableStateOf(false) }
    val rawTextDisplay = currentExpense.rawText?.takeIf { it.isNotBlank() } ?: "第一版为空"
    val previewImage = state.fullImage ?: state.thumbnail
    val readOnly = state.readOnly
    val haptics = rememberAppHaptics()

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
            message = "$label 只能填写 1 到 5。"
            return null
        }
        return score
    }

    fun draftOrMessage(): ExpenseDraft? {
        val originalMinor = parseMinorAmount(originalAmountText, currency)
        if (originalAmountText.isNotBlank() && originalMinor == null) {
            message = "金额格式不正确"
            return null
        }
        val valueScore = if (valueScoreText.isBlank()) null else (parseScore(valueScoreText, "值不值评分") ?: return null)
        val regretScore = if (regretScoreText.isBlank()) null else (parseScore(regretScoreText, "后悔指数") ?: return null)
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            merchant = merchant.ifBlank { null },
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = expenseTime.ifBlank { null },
            tags = tags.ifBlank { null },
            valueScore = valueScore,
            regretScore = regretScore,
        )
    }

    AppPageScrollableColumn(
        role = AppPageRole.Edit,
        hasBottomBar = false,
        includeStatusBarPadding = true,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AppPageHeader(
            title = "确认账单",
            subtitle = "识别只是草稿，补全后再正式入账",
            eyebrow = "",
        ) {
            StatusPill(if (currentExpense.status == "pending") "待确认" else "已入账")
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
                    "原图加载中"
                } else {
                    "原图暂时加载失败，截图已保存"
                },
                contentScale = ContentScale.Fit,
                displayHeight = 420.dp,
            )
        }

        if (currentExpense.duplicateStatus == "suspected") {
            DuplicateNotice(reason = currentExpense.duplicateReason)
            if (!readOnly) {
                AppOutlinedButton(onClick = onKeepDuplicate) {
                    Text("不是重复，保留")
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
            onRetryOcr = onRetryOcr,
        )

        message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }

        ExpenseEditPrimaryActions(
            saving = state.saving,
            allowSave = !readOnly,
            onBack = onDone,
            onSave = {
                val draft = draftOrMessage() ?: return@ExpenseEditPrimaryActions
                haptics.tick()
                onSave(draft)
            },
        )

        ExpenseEditConfirmActions(
            saving = state.saving,
            allowConfirm = allowConfirm && !readOnly,
            allowReject = allowReject && !readOnly,
            onConfirm = {
                val draft = draftOrMessage() ?: return@ExpenseEditConfirmActions
                if (draft.originalAmountMinor == null) {
                    message = "请先填写金额。"
                    return@ExpenseEditConfirmActions
                }
                haptics.confirm()
                onConfirm(draft)
            },
            onRequestReject = { showRejectDialog = true },
        )
    }
}
