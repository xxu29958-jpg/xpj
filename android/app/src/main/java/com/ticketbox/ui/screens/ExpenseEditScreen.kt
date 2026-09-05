package com.ticketbox.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.isUncategorizedExpenseCategory
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.DuplicateNotice
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.formatExpenseExchangeMeta
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.components.sanitizeMinorAmountInput
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppAdaptivePaneTokens
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.appAdaptiveSupportingPaneWidth
import com.ticketbox.ui.screens.expense.ExpenseEditActionBar
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarActions
import com.ticketbox.ui.screens.expense.ExpenseEditActionBarState
import com.ticketbox.ui.screens.expense.ExpenseEditAmountCluster
import com.ticketbox.ui.screens.expense.ExpenseEditAmountClusterActions
import com.ticketbox.ui.screens.expense.ExpenseEditAmountClusterState
import com.ticketbox.ui.screens.expense.ExpenseEditCategorySelector
import com.ticketbox.ui.screens.expense.ExpenseEditCategorySelectorActions
import com.ticketbox.ui.screens.expense.ExpenseEditCategorySelectorState
import com.ticketbox.ui.screens.expense.ExpenseEditDatePicker
import com.ticketbox.ui.screens.expense.ExpenseEditTimePicker
import com.ticketbox.ui.screens.expense.ExpenseEditDetailsActions
import com.ticketbox.ui.screens.expense.ExpenseEditDetailsSection
import com.ticketbox.ui.screens.expense.ExpenseEditDetailsState
import com.ticketbox.ui.screens.expense.ExpenseEditEvidenceActions
import com.ticketbox.ui.screens.expense.ExpenseEditEvidenceSection
import com.ticketbox.ui.screens.expense.ExpenseEditEvidenceState
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSection
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSectionActions
import com.ticketbox.ui.screens.expense.ExpenseEditMoreSectionState
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseEditRecognizeTextDialog
import com.ticketbox.ui.screens.expense.ExpenseEditRejectDialog
import com.ticketbox.ui.screens.expense.ExpenseEditSourceInfo
import com.ticketbox.ui.screens.expense.ExpenseEditTimeRow
import com.ticketbox.ui.screens.expense.ExpenseEditTimeRowActions
import com.ticketbox.ui.screens.expense.ExpenseEditTimeRowState
import com.ticketbox.ui.screens.expense.ExpenseDetailActionButtonRow
import com.ticketbox.ui.screens.expense.initialExpenseAmountInputMinor
import com.ticketbox.ui.screens.expense.canonicalManualExchangeRateOrNull
import com.ticketbox.ui.screens.expense.manualExchangeRateEditorVisible
import com.ticketbox.ui.screens.expense.manualExchangeRateNeedsServerReview
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.ItemsEditorSheetState
import com.ticketbox.ui.screens.expense.OcrProgressCard
import com.ticketbox.ui.screens.expense.SplitsEditorSheetActions
import com.ticketbox.ui.screens.expense.SplitsEditorSheet
import com.ticketbox.ui.screens.expense.SplitsEditorSheetState
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

    val handleBack = {
        if (!state.saving) {
            primaryActions.onDone()
        }
    }

    if (state.itemEditorOpen) {
        ItemsEditorSheet(
            state = ItemsEditorSheetState(
                drafts = state.itemDrafts,
                parentAmountCents = state.expenseItems?.parentAmountCents,
                saving = state.itemsSaving,
                display = expense.recordCurrencyDisplay(),
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
                display = expense.recordCurrencyDisplay(),
            ),
            actions = splitEditingActions.editor,
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
    val savedManualExchangeRate = currentExpense.fxRate
        ?.takeIf { currentExpense.fxSource == FxContract.SourceManual }
    var manualExchangeRateText by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(savedManualExchangeRate.orEmpty())
    }
    var manualExchangeRateIsError by rememberSaveable(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(false)
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
    var categorySheetOpen by remember(currentExpense.id) { mutableStateOf(false) }
    var currencyExpanded by rememberSaveable(currentExpense.id) {
        mutableStateOf(currency != FxContract.HomeCurrency)
    }
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
    val manualExchangeRateInvalidMessage = stringResource(R.string.expense_edit_manual_rate_invalid)
    val isPendingExpense = currentExpense.status == "pending"
    val homeCurrencyCode = currentExpense.homeCurrencyCode
        ?.takeIf { it.isNotBlank() }
        ?: currentExpense.homeCurrency.storageKey
    val foreignCurrency = currency.storageKey != homeCurrencyCode
    val fxIdentityChanged = currency != currentExpense.originalCurrencyCode ||
        parseMinorAmount(amountText, currency) != currentExpense.originalAmountMinor ||
        expenseTime != currentExpense.expenseTime.orEmpty()
    val manualExchangeRateVisible = manualExchangeRateEditorVisible(
        pendingExpense = isPendingExpense,
        foreignCurrency = foreignCurrency,
        fxPending = currentExpense.fxStatus == FxContract.StatusPending,
        fxSource = currentExpense.fxSource,
    )
    val manualExchangeRateNeedsReview = manualExchangeRateVisible && manualExchangeRateNeedsServerReview(
        fxPending = currentExpense.fxStatus == FxContract.StatusPending,
        savedManualRate = savedManualExchangeRate,
        draftManualRate = manualExchangeRateText,
        fxIdentityChanged = fxIdentityChanged,
    )
    val exchangeMeta = if (foreignCurrency && !manualExchangeRateNeedsReview && !fxIdentityChanged) {
        formatExpenseExchangeMeta(currentExpense)
    } else {
        null
    }
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
        val trimmedManualRate = manualExchangeRateText.trim()
        val canonicalManualRate = when {
            manualExchangeRateVisible && trimmedManualRate.isBlank() && savedManualExchangeRate != null -> {
                manualExchangeRateIsError = true
                message = manualExchangeRateInvalidMessage
                return null
            }
            !manualExchangeRateVisible || trimmedManualRate.isBlank() -> null
            else -> canonicalManualExchangeRateOrNull(manualExchangeRateText) ?: run {
                manualExchangeRateIsError = true
                message = manualExchangeRateInvalidMessage
                return null
            }
        }
        manualExchangeRateIsError = false
        val valueScore = if (valueScoreText.isBlank()) null else (parseScore(valueScoreText, valueScoreLabel) ?: return null)
        val regretScore = if (regretScoreText.isBlank()) null else (parseScore(regretScoreText, regretScoreLabel) ?: return null)
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            manualExchangeRate = canonicalManualRate?.takeIf { manualExchangeRateNeedsReview },
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

    // 宽屏（pane policy 判定可放辅列，含折叠屏姿态约束）：表单主列 + 证据辅列同屏对照
    // （看票填单不来回滚）；否则保持单栏。与 Stats / Plan / Ledger 用同一份判定。
    val wideTwoColumn = LocalAppAdaptiveLayoutPolicy.current.showsSupportingPane

    val evidenceSections: @Composable () -> Unit = {
        if (currentExpense.imagePath != null) {
            ExpenseEditEvidenceSection(
                state = ExpenseEditEvidenceState(
                    previewImage = previewImage,
                    fullImage = state.fullImage,
                    imageLoading = state.imageLoading,
                    ocrRunning = state.ocrRunning,
                    readOnly = readOnly,
                    showLargeImage = showLargeImage,
                ),
                actions = ExpenseEditEvidenceActions(
                    onToggleLargeImage = {
                        if (!showLargeImage && state.fullImage == null) {
                            mediaActions.onLoadFullImage()
                        }
                        showLargeImage = !showLargeImage
                    },
                    onRetryOcr = mediaActions.onRetryOcr,
                ),
            )
        }
    }

    val formSections: @Composable () -> Unit = {
        ExpenseEditAmountCluster(
            state = ExpenseEditAmountClusterState(
                currency = currency,
                amountText = amountText,
                currencyExpanded = currencyExpanded,
                enabled = !readOnly,
                homeCurrencyCode = homeCurrencyCode,
                exchangeMeta = exchangeMeta,
                manualExchangeRateVisible = manualExchangeRateVisible,
                manualExchangeRateText = manualExchangeRateText,
                manualExchangeRateIsError = manualExchangeRateIsError,
            ),
            actions = ExpenseEditAmountClusterActions(
                onCurrencyChange = { code ->
                    if (currency != code) {
                        manualExchangeRateText = ""
                        manualExchangeRateIsError = false
                    }
                    currency = code
                    amountText = sanitizeMinorAmountInput(amountText, code)
                },
                onAmountChange = { amountText = it },
                onAmountFocusChanged = { amountFocused = it },
                onManualExchangeRateChange = {
                    manualExchangeRateText = it
                    manualExchangeRateIsError = false
                },
                onManualExchangeRateFocusChanged = { amountFocused = it },
                onToggleCurrency = { currencyExpanded = !currencyExpanded },
            ),
        )
        ExpenseEditMerchantField(
            merchant = merchant,
            onMerchantChange = { merchant = it },
            enabled = !readOnly,
        )
        ExpenseEditCategorySelector(
            state = ExpenseEditCategorySelectorState(
                category = category,
                categories = state.categories,
                enabled = !readOnly,
                sheetOpen = categorySheetOpen,
            ),
            actions = ExpenseEditCategorySelectorActions(
                onCategoryChange = { category = it },
                onOpenSheet = { categorySheetOpen = true },
                onDismissSheet = { categorySheetOpen = false },
            ),
        )
        ExpenseEditNoteField(
            note = note,
            onNoteChange = { note = it },
            enabled = !readOnly,
        )
        ExpenseEditTimeRow(
            state = ExpenseEditTimeRowState(
                expenseTime = expenseTime,
                baselineExpenseTime = currentExpense.expenseTime.orEmpty(),
                enabled = !readOnly,
            ),
            actions = ExpenseEditTimeRowActions(
                onPickDate = { showDatePicker = true },
                onPickTime = { showTimePicker = true },
                onUseNow = { expenseTime = nowUtcIso() },
                onUndoChange = { expenseTime = currentExpense.expenseTime.orEmpty() },
            ),
        )
        // 来源 quiet meta：单栏按定稿跟在时间行后；宽屏由证据辅列承载，
        // 主列不再重复（否则 1440 同行信息出现两次）。
        if (!wideTwoColumn) {
            ExpenseEditSourceInfo(
                source = currentExpense.source,
                confidence = currentExpense.confidence,
            )
        }
        ExpenseEditDetailsSection(
            state = ExpenseEditDetailsState(
                expenseId = currentExpense.id,
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
            actions = ExpenseEditDetailsActions(
                onAcknowledgeItemsMismatch = itemizationActions.onAcknowledgeItemsMismatch,
                onEditItems = if (state.readOnly) null else itemizationActions.onEditItems,
                onEditSplits = if (state.readOnly) null else splitEditingActions.onEditSplits,
            ),
        )
        ExpenseEditMoreSection(
            state = ExpenseEditMoreSectionState(
                tags = tags,
                valueScoreText = valueScoreText,
                regretScoreText = regretScoreText,
                valueScoreBaseline = currentExpense.valueScore,
                regretScoreBaseline = currentExpense.regretScore,
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
                onValueScoreUndo = { valueScoreText = currentExpense.valueScore?.toString().orEmpty() },
                onRegretScoreUndo = { regretScoreText = currentExpense.regretScore?.toString().orEmpty() },
                onToggleMore = { moreExpanded = !moreExpanded },
                onToggleRawText = { rawTextExpanded = !rawTextExpanded },
                onRetryOcr = mediaActions.onRetryOcr,
                onRecognizeText = mediaActions.onOpenRecognizeText,
            ),
        )
    }

    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Edit,
            title = headerTitle,
            subtitle = headerSubtitle,
            backText = stringResource(R.string.expense_edit_primary_back_button),
            onBack = handleBack,
            hasBottomBar = false,
            contentWidth = AppAdaptiveContentWidth.Wide,
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
                        allowConfirm = actionAvailability.allowConfirm && !readOnly && !manualExchangeRateNeedsReview,
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

        if (wideTwoColumn) {
            ExpenseEditTwoColumnLayout(form = formSections) {
                evidenceSections()
                ExpenseEditSourceInfo(
                    source = currentExpense.source,
                    confidence = currentExpense.confidence,
                )
            }
        } else {
            evidenceSections()
            formSections()
        }

        // 保存 / 确认入账 / 删除 与校验提示现在浮在底部操作栏（见 bottomBar），
        // 不再钉在长表单滚动末尾。
    }
}

/**
 * 宽屏双列：表单主列吃剩余宽度，证据辅列按实测可用宽度走 [appAdaptiveSupportingPaneWidth]
 * （与 AppAdaptivePaneScaffold 同一份口径：保 primaryMinWidth，gutter 用 paneGutter）。
 */
@Composable
private fun ExpenseEditTwoColumnLayout(
    form: @Composable () -> Unit,
    supporting: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
        val supportingWidth = appAdaptiveSupportingPaneWidth(maxWidth)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppAdaptivePaneTokens.paneGutter),
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                form()
            }
            Column(
                modifier = Modifier.width(supportingWidth),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                supporting()
            }
        }
    }
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
