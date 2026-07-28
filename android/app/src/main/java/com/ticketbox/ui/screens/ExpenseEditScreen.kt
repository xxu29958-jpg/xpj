package com.ticketbox.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
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
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.canCreateRepaymentDraft
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.domain.model.isUncategorizedExpenseCategory
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.DuplicateNotice
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.BillSplitInviteSheet
import com.ticketbox.ui.screens.expense.BillSplitInviteSheetActions
import com.ticketbox.ui.screens.expense.BillSplitInviteSheetState
import com.ticketbox.ui.screens.expense.EditDraftPreviewCard
import com.ticketbox.ui.screens.expense.EditDraftPreviewActions
import com.ticketbox.ui.screens.expense.EditDraftPreviewState
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanel
import com.ticketbox.ui.screens.expense.ExpenseDateField
import com.ticketbox.ui.screens.expense.ExpenseDateFieldActions
import com.ticketbox.ui.screens.expense.ExpenseDateFieldState
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFieldOptions
import com.ticketbox.ui.screens.expense.ExpenseEditActionBar
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarActions
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarState
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseEditDatePicker
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSection
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSectionActions
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSectionState
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseEditRecognizeTextDialog
import com.ticketbox.ui.screens.expense.ExpenseEditRejectDialog
import com.ticketbox.ui.screens.expense.ExpenseEditSourceInfo
import com.ticketbox.ui.screens.expense.ExpenseEditTimePicker
import com.ticketbox.ui.screens.expense.ExpenseDetailActionButtonRow
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanelActions
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanelState
import com.ticketbox.ui.screens.expense.ExpenseEditV1DetailsActions
import com.ticketbox.ui.screens.expense.ExpenseEditV1DetailsSection
import com.ticketbox.ui.screens.expense.ExpenseEditV1DetailsState
import com.ticketbox.ui.screens.expense.ExpenseRepaymentDraftPanel
import com.ticketbox.ui.screens.expense.initialExpenseAmountInputMinor
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.ItemsEditorSheetState
import com.ticketbox.ui.screens.expense.OcrProgressCard
import com.ticketbox.ui.screens.expense.SplitsEditorSheetActions
import com.ticketbox.ui.screens.expense.SplitsEditorSheet
import com.ticketbox.ui.screens.expense.SplitsEditorSheetState
import com.ticketbox.viewmodel.BillSplitSentLoadState
import com.ticketbox.viewmodel.ExpenseEditUiState

data class ExpenseEditScreenState(
    val expense: Expense,
    val editState: ExpenseEditUiState,
    val actionAvailability: ExpenseEditActionAvailability = ExpenseEditActionAvailability(),
)

data class ExpenseEditActionAvailability(
    val allowConfirm: Boolean = true,
    val allowReject: Boolean = true,
)

data class ExpenseEditScreenActions(
    val primary: ExpenseEditPrimaryActions = ExpenseEditPrimaryActions(),
    val media: ExpenseEditMediaActions = ExpenseEditMediaActions(),
    val related: ExpenseEditRelatedActions = ExpenseEditRelatedActions(),
    val itemization: ExpenseEditItemizationActions = ExpenseEditItemizationActions(),
    val splitEditing: ExpenseEditSplitEditingActions = ExpenseEditSplitEditingActions(),
    val billSplit: ExpenseEditBillSplitActions = ExpenseEditBillSplitActions(),
)

data class ExpenseEditPrimaryActions(
    val onSave: (ExpenseDraft) -> Unit = {},
    val onConfirm: (ExpenseDraft) -> Unit = {},
    val onReject: () -> Unit = {},
    val onDone: () -> Unit = {},
)

data class ExpenseEditMediaActions(
    val onRetryOcr: () -> Unit = {},
    val onRecognizeText: (String) -> Unit = {},
    val onOpenRecognizeText: () -> Unit = {},
    val onDismissRecognizeText: () -> Unit = {},
    val onLoadFullImage: () -> Unit = {},
)

data class ExpenseEditRelatedActions(
    val onKeepDuplicate: () -> Unit = {},
    val onCreateRepaymentDraft: () -> Unit = {},
)

data class ExpenseEditItemizationActions(
    val onAcknowledgeItemsMismatch: () -> Unit = {},
    val onEditItems: () -> Unit = {},
    val editor: ItemsEditorSheetActions = noopItemsEditorSheetActions(),
)

data class ExpenseEditSplitEditingActions(
    val onEditSplits: () -> Unit = {},
    val editor: SplitsEditorSheetActions = noopSplitsEditorSheetActions(),
)

data class ExpenseEditBillSplitActions(
    val onStartInvite: () -> Unit = {},
    val onCancelInvite: (publicId: String) -> Unit = {},
    val onSelectMember: (memberId: Long) -> Unit = {},
    val onUpdateAmount: (amountText: String) -> Unit = {},
    val onSend: () -> Unit = {},
    val onDismissSheet: () -> Unit = {},
)

private fun noopItemsEditorSheetActions(): ItemsEditorSheetActions = ItemsEditorSheetActions(
    onUpdate = { _, _, _, _ -> },
    onAddRow = {},
    onRemoveRow = {},
    onSave = {},
    onDismiss = {},
)

private fun noopSplitsEditorSheetActions(): SplitsEditorSheetActions = SplitsEditorSheetActions(
    onToggleMember = { _, _ -> },
    onUpdateAmount = { _, _ -> },
    onEvenSplit = {},
    onSave = {},
    onDismiss = {},
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseEditScreen(
    screenState: ExpenseEditScreenState,
    actions: ExpenseEditScreenActions,
) {
    val expense = screenState.expense
    val state = screenState.editState
    val actionAvailability = screenState.actionAvailability
    val primaryActions = actions.primary
    val mediaActions = actions.media
    val relatedActions = actions.related
    val itemizationActions = actions.itemization
    val splitEditingActions = actions.splitEditing
    val billSplitActions = actions.billSplit

    val handleBack = {
        if (!state.saving && !state.repaymentDraftCreating) {
            primaryActions.onDone()
        }
    }

    if (state.itemEditorOpen) {
        ItemsEditorSheet(
            state = ItemsEditorSheetState(
                drafts = state.itemDrafts,
                parentAmountCents = state.expenseItems?.parentAmountCents,
                saving = state.itemsSaving,
                display = expense?.recordCurrencyDisplay() ?: CurrencyDisplay.Base,
            ),
            actions = itemizationActions.editor,
        )
    }

    if (state.splitEditorOpen) {
        SplitsEditorSheet(
            state = SplitsEditorSheetState(
                drafts = state.splitDrafts,
                parentAmountCents = state.expenseSplits?.parentAmountCents,
                saving = state.splitsSaving,
                loading = state.splitMembersLoading,
                display = expense?.recordCurrencyDisplay() ?: CurrencyDisplay.Base,
            ),
            actions = splitEditingActions.editor,
        )
    }

    if (state.billSplitInviteSheetOpen) {
        BillSplitInviteSheet(
            state = BillSplitInviteSheetState(
                members = state.billSplitInviteMembers,
                membersLoading = state.billSplitInviteMembersLoading,
                selectedMemberId = state.billSplitInviteSelectedMemberId,
                amountText = state.billSplitInviteAmountText,
                sending = state.billSplitInviteSending,
                message = state.billSplitInviteMessage,
                messageTone = state.billSplitInviteMessageTone,
                display = expense?.recordCurrencyDisplay() ?: CurrencyDisplay.Base,
            ),
            remainingCents = billSplitRemainingCents(state),
            remainingUnavailable = state.billSplitSentLoadState != BillSplitSentLoadState.Loaded,
            actions = BillSplitInviteSheetActions(
                onSelectMember = billSplitActions.onSelectMember,
                onUpdateAmount = billSplitActions.onUpdateAmount,
                onSend = billSplitActions.onSend,
                onDismiss = billSplitActions.onDismissSheet,
            ),
        )
    }

    if (state.recognizeTextDialogOpen && !state.readOnly) {
        ExpenseEditRecognizeTextDialog(
            onRecognize = mediaActions.onRecognizeText,
            onDismiss = mediaActions.onDismissRecognizeText,
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
    // R13-4：original 原码严格解析 —— record 原码在支持集外时，按 lossy 枚举（CNY）改金额
    // 会 100× 缩放；禁金额承载编辑（选择器显式改币种的除外：用户已重新声明口径）。
    val originalRawCode = currentExpense.originalCurrencyCodeRaw
    val originalUnsupported = !originalRawCode.isNullOrBlank() &&
        CurrencyCode.fromStorageKeyOrNull(originalRawCode) == null
    val initialAmountText = remember(currentExpense.id, currentExpense.updatedAt) {
        formatMinorAmountInput(
            initialExpenseAmountInputMinor(currentExpense),
            currentExpense.originalCurrencyCode,
        )
    }
    var amountText by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(initialAmountText)
    }
    var merchant by rememberSaveable(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.merchant.orEmpty()) }
    var category by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(editInitialCategory(currentExpense))
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
    var amountFocused by remember(currentExpense.id) { mutableStateOf(false) }
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
    val currencyUnsupportedMessage = stringResource(R.string.expense_edit_currency_unsupported)
    val isPendingExpense = currentExpense.status == "pending"
    val headerTitle = stringResource(
        if (isPendingExpense) {
            R.string.expense_edit_header_title
        } else {
            R.string.expense_edit_header_title_confirmed
        }
    )
    val headerSubtitle = stringResource(
        if (isPendingExpense) {
            R.string.expense_edit_header_subtitle
        } else {
            R.string.expense_edit_header_subtitle_confirmed
        }
    )

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
            isConfirmedExpense = currentExpense.status == "confirmed",
            onConfirm = primaryActions.onReject,
            onDismiss = { showRejectDialog = false },
        )
    }

    LaunchedEffect(state.done) {
        if (state.done) primaryActions.onDone()
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
        // R13-4：original 原码未知且金额被改动过（未改=元数据/原值回写，放行）→ 禁写+明示。
        if (originalUnsupported && currency == currentExpense.originalCurrencyCode && amountText != initialAmountText) {
            message = currencyUnsupportedMessage
            return null
        }
        val originalMinor = parseMinorAmount(amountText, currency)
        if (amountText.isNotBlank() && originalMinor == null) {
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
            // Blank category submits as null (NOT 其他): the PATCH is
            // exclude_unset, so a row whose category is genuinely missing
            // keeps that fact instead of being silently recategorized to the
            // display fallback on any unrelated edit (PR #230 round 12).
            category = category.trim().ifBlank { null }?.let { normalizeExpenseCategory(it) },
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
        primaryActions.onSave(draft)
    }

    fun submitConfirm() {
        val draft = draftOrMessage() ?: return
        if (draft.originalAmountMinor == null) {
            message = amountRequiredMessage
            return
        }
        haptics.confirm()
        primaryActions.onConfirm(draft)
    }

    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Edit,
            title = headerTitle,
            subtitle = headerSubtitle,
            backText = stringResource(R.string.expense_edit_primary_back_button),
            onBack = handleBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ),
        // 操作栏浮在底部：底部空间由实测栏高让出（见 AppPageScrollableColumn），
        // 不走静态 BottomBarHeight 估算，故 hasBottomBar = false 避免双重预留。
        slots = AppSecondaryPageSlots(
            actions = {
                StatusPill(
                    if (isPendingExpense) {
                        stringResource(R.string.expense_edit_status_pending)
                    } else {
                        stringResource(R.string.expense_edit_status_confirmed)
                    }
                )
            },
            bottomBar = {
                ExpenseEditActionBar(
                    state = ExpenseEditActionBarState(
                        saving = state.saving,
                        allowSave = !readOnly,
                        allowConfirm = actionAvailability.allowConfirm && !readOnly,
                        allowReject = actionAvailability.allowReject && !readOnly,
                        validationMessage = message,
                        statusMessage = state.message?.asString(),
                        statusTone = state.messageTone,
                        forceCompact = amountFocused,
                    ),
                    actions = ExpenseEditActionBarActions(
                        onBack = handleBack,
                        onSave = ::submitSave,
                        onConfirm = ::submitConfirm,
                        onRequestReject = { showRejectDialog = true },
                    ),
                )
            },
        ),
    ) {
        if (currentExpense.duplicateStatus == DuplicateStatusValues.SUSPECTED) {
            DuplicateNotice(reason = currentExpense.duplicateReason)
            if (!readOnly) {
                ExpenseDetailActionButtonRow(
                    text = stringResource(R.string.expense_edit_keep_duplicate_button),
                    icon = Icons.Filled.Check,
                    onClick = relatedActions.onKeepDuplicate,
                )
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
            amountText = amountText,
            onAmountChange = { amountText = it },
            options = ExpenseCurrencyFieldOptions(
                enabled = !readOnly,
                autoFocusAmount = false,
                onAmountFocusChanged = { amountFocused = it },
                showSectionTitle = false,
            ),
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
            state = ExpenseDateFieldState(
                expenseTime = expenseTime,
                enabled = !readOnly,
            ),
            actions = ExpenseDateFieldActions(
                onPickDate = { showDatePicker = true },
                onPickTime = { showTimePicker = true },
                onUseNow = { expenseTime = nowUtcIso() },
                onClear = { expenseTime = "" },
            ),
        )
        ExpenseEditSourceInfo(
            source = currentExpense.source,
            confidence = currentExpense.confidence,
        )

        EditDraftPreviewCard(
            state = EditDraftPreviewState(
                expense = currentExpense,
                previewImage = previewImage,
                imageLoading = state.imageLoading,
                ocrRunning = state.ocrRunning,
                readOnly = readOnly,
                showLargeImage = showLargeImage,
            ),
            actions = EditDraftPreviewActions(
                onToggleLargeImage = {
                    if (!showLargeImage && state.fullImage == null) {
                        mediaActions.onLoadFullImage()
                    }
                    showLargeImage = !showLargeImage
                },
                onRetryOcr = mediaActions.onRetryOcr,
            ),
        )

        if (showLargeImage && currentExpense.imagePath != null) {
            AppAsyncImage(
                image = state.fullImage ?: previewImage,
                presentation = AppAsyncImagePresentation(
                    placeholder = if (state.imageLoading) {
                        stringResource(R.string.expense_edit_large_image_loading)
                    } else {
                        stringResource(R.string.expense_edit_large_image_failed)
                    },
                    contentDescription = stringResource(R.string.components_async_image_content_description),
                    contentScale = ContentScale.Fit,
                ),
                layout = AppAsyncImageLayout(displayHeight = 420.dp),
            )
        }

        ExpenseEditV1DetailsSection(
            state = ExpenseEditV1DetailsState(
                expenseItems = state.expenseItems,
                expenseSplits = state.expenseSplits,
                itemsLoading = state.itemsLoading,
                splitsLoading = state.splitsLoading,
                itemsLoadState = state.itemsLoadState,
                splitsLoadState = state.splitsLoadState,
                itemsMessage = state.itemsMessage,
                splitsMessage = state.splitsMessage,
                itemsMessageTone = state.itemsMessageTone,
                splitsMessageTone = state.splitsMessageTone,
            ),
            actions = ExpenseEditV1DetailsActions(
                onAcknowledgeItemsMismatch = itemizationActions.onAcknowledgeItemsMismatch,
                onEditItems = if (state.readOnly) null else itemizationActions.onEditItems,
                onEditSplits = if (state.readOnly) null else splitEditingActions.onEditSplits,
            ),
        )

        // 已入账流水进入还款复核箱；不在详情页直接抵扣欠款。
        if (currentExpense.canCreateRepaymentDraft(state.readOnly)) {
            ExpenseRepaymentDraftPanel(
                creating = state.repaymentDraftCreating,
                onCreate = relatedActions.onCreateRepaymentDraft,
            )
        }

        // 批 13：跨账本「找家人分摊」卡——仅已确认 + 有金额 + 非收到拆账 + 可写时出现。
        if (currentExpense.canInitiateBillSplit(state.readOnly)) {
            ExpenseBillSplitInvitePanel(
                state = ExpenseBillSplitInvitePanelState(
                    sent = state.billSplitSent,
                    loadState = state.billSplitSentLoadState,
                    loading = state.billSplitLoading,
                    message = state.billSplitMessage,
                    messageTone = state.billSplitMessageTone,
                ),
                actions = ExpenseBillSplitInvitePanelActions(
                    onStartInvite = billSplitActions.onStartInvite,
                    onCancelInvite = billSplitActions.onCancelInvite,
                ),
            )
        }

        ExpenseEditMoreSection(
            state = ExpenseEditMoreSectionState(
                tags = tags,
                valueScoreText = valueScoreText,
                regretScoreText = regretScoreText,
                rawTextDisplay = rawTextDisplay,
                moreExpanded = moreExpanded,
                rawTextExpanded = rawTextExpanded,
                ocrRunning = state.ocrRunning,
                saving = state.saving,
                readOnly = readOnly,
                canRecognize = expense.status == "pending",
            ),
            actions = ExpenseEditMoreSectionActions(
                onTagsChange = { tags = it },
                onValueScoreChange = { valueScoreText = it },
                onRegretScoreChange = { regretScoreText = it },
                onToggleMore = { moreExpanded = !moreExpanded },
                onToggleRawText = { rawTextExpanded = !rawTextExpanded },
                onRetryOcr = mediaActions.onRetryOcr,
                onRecognizeText = mediaActions.onOpenRecognizeText,
            ),
        )

        // 保存 / 确认入账 / 删除 与校验提示现在浮在底部操作栏（见 bottomBar），
        // 不再钉在长表单滚动末尾。
    }
}

/**
 * 批 13：本笔还可分摊的金额 = 账单金额 − 已活跃（invited/accepted）拆账总额。
 * 仅作 sheet 内的非阻塞提示；金额上限的权威校验在 VM + 后端 split_total_exceeds_parent。
 * 账单无金额时返回 null（卡片本就不会出现，此处只为安全）。
 */
internal fun billSplitRemainingCents(state: ExpenseEditUiState): Long? {
    if (state.billSplitSentLoadState != BillSplitSentLoadState.Loaded) return null
    val parent = state.expense?.amountCents ?: return null
    val active = state.billSplitSent
        .filter { it.status == BillSplitStatusValues.INVITED || it.status == BillSplitStatusValues.ACCEPTED }
        .sumOf { it.amountCents }
    return (parent - active).coerceAtLeast(0L)
}

// Category init for the edit form reads the SERVER-STORED value: a row whose
// raw category is blank / a dirty token (未分类/未分類/none/null) starts with
// an EMPTY field — the display-normalized 「其他」 must not masquerade as a
// real category, or any unrelated save would silently recategorize the row
// (PR #230 round 12). Valid raw values initialize to the display
// (alias-normalized) category.
internal fun editInitialCategory(expense: Expense): String {
    val raw = expense.serverCategory ?: expense.category
    return if (isUncategorizedExpenseCategory(raw)) "" else expense.category
}
