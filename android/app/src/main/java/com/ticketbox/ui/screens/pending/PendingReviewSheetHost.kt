package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetActions
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetState
import com.ticketbox.ui.screens.pending.sheets.DuplicateConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.MissingAmountSheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickCategorySheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
import com.ticketbox.ui.screens.pending.sheets.ReviewSheetChrome
import com.ticketbox.viewmodel.PendingSheet

internal data class PendingReviewSheetHostState(
    val sheet: PendingSheet,
    val categoryOptions: List<String>,
    val actionInProgressIds: Set<Long>,
    val readyCount: Int,
    val missingAmountSkip: Int,
    val duplicateSkip: Int,
    val bulkRunning: Boolean,
    val bulkConfirmed: Int,
    val bulkTotal: Int,
    val reviewRemaining: Int,
    val statusMessage: String?,
)

data class PendingReviewSheetHostActions(
    val onSaveQuickCategory: (Long, String) -> Unit,
    val onSaveQuickMerchant: (Long, String) -> Unit,
    val onSaveAmountDraft: (Long, Long) -> Unit,
    val onSaveAmountAndConfirm: (Long, Long) -> Unit,
    val onSkipReviewField: () -> Unit,
    val onKeepBoth: (Expense) -> Unit,
    val onIgnoreCurrent: (Expense) -> Unit,
    val onConfirmReady: () -> Unit,
    val onDismiss: () -> Unit,
)

/**
 * Compact/Medium 宿主：复核内容继续走现有 modal sheet。
 * expanded 由 [PendingReviewPaneHost] 接管，本宿主此时不渲染——
 * 同一复核不得同时以 modal + pane 两种形态出现。
 */
@Composable
@OptIn(ExperimentalMaterial3Api::class)
internal fun PendingReviewSheetHost(
    state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions,
) {
    if (state.sheet == PendingSheet.None) return
    ModalBottomSheet(onDismissRequest = actions.onDismiss) {
        PendingReviewSheetContent(sheet = state.sheet, state = state, actions = actions)
    }
}

/**
 * expanded supporting pane 的版面形状 owner：复核（Review）必须绕过外层页面滚动
 * 容器——AppAdaptiveSupportingPane/AppPageScrollableColumn 的 verticalScroll 给子级
 * 无限高约束，与 AppSheetScaffold 自身 verticalScroll 嵌套即 IllegalStateException
 * （真机点「补金额」崩溃）；复核溢出改由面板槽位的有界高度 + sheet 内部滚动承担。
 * Triage 维持现有外层滚动容器不变。
 */
@Composable
internal fun PendingSupportingPaneBody(
    content: PendingSupportingPaneContent?,
    reviewState: PendingReviewSheetHostState,
    reviewActions: PendingReviewSheetHostActions,
    triageContent: @Composable () -> Unit,
) {
    when (content) {
        is PendingSupportingPaneContent.Review -> PendingReviewPaneHost(
            state = reviewState,
            actions = reviewActions,
        )
        else -> AppAdaptiveSupportingPane(
            role = AppPageRole.Pending,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            triageContent()
        }
    }
}

/**
 * expanded supporting pane 宿主：复用同一份复核内容与现有 state/actions，
 * 只把承载形态从 modal 换成长驻面板。退出权由 [pendingPaneExit] 裁决——
 * 内容内已有取消的 sheet 不再给第二出口；缺少内容内取消的 sheet 补一个
 * 退出，且在该 sheet 在途 mutation 进行中禁用（Back 由调用方始终安装、
 * 按同一模型在禁用时 no-op），不加第二套 dismiss authority。
 *
 * 版面：宿主自身不提供滚动容器。退出 affordance 固定在面板顶部，复核内容
 * 占据剩余有界高度（weight），溢出由 sheet 内部滚动承担——外层不得再套
 * verticalScroll，否则嵌套滚动无限高测量直接崩溃。
 */
@Composable
internal fun PendingReviewPaneHost(
    state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions,
) {
    if (state.sheet == PendingSheet.None) return
    val paneExit = pendingPaneExit(
        sheet = state.sheet,
        actionInProgressIds = state.actionInProgressIds,
        bulkRunning = state.bulkRunning,
    )
    Column(modifier = Modifier.fillMaxHeight()) {
        if (paneExit.showAffordance) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = AppSpacing.screenHorizontal),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(
                    enabled = paneExit.enabled,
                    onClick = actions.onDismiss,
                ) {
                    Text(stringResource(R.string.common_cancel))
                }
            }
        }
        Box(modifier = Modifier.weight(1f)) {
            PendingReviewSheetContent(sheet = state.sheet, state = state, actions = actions)
        }
    }
}

@Composable
private fun PendingReviewSheetContent(
    sheet: PendingSheet,
    state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions,
) {
    // Quick-fix sheets share the same review chrome and saving-state rule.
    fun chromeFor(expenseId: Long) = ReviewSheetChrome(
        saving = expenseId in state.actionInProgressIds,
        remaining = state.reviewRemaining,
        statusMessage = state.statusMessage,
        onSkip = actions.onSkipReviewField,
    )
    when (sheet) {
        is PendingSheet.None -> Unit
        is PendingSheet.QuickCategory -> QuickCategorySheetContent(
            expense = sheet.expense,
            options = state.categoryOptions,
            chrome = chromeFor(sheet.expense.id),
            onSave = { value -> actions.onSaveQuickCategory(sheet.expense.id, value) },
            onDismiss = actions.onDismiss,
        )
        is PendingSheet.QuickMerchant -> QuickMerchantSheetContent(
            expense = sheet.expense,
            chrome = chromeFor(sheet.expense.id),
            onSave = { value -> actions.onSaveQuickMerchant(sheet.expense.id, value) },
            onDismiss = actions.onDismiss,
        )
        is PendingSheet.MissingAmount -> MissingAmountSheetContent(
            expense = sheet.expense,
            chrome = chromeFor(sheet.expense.id),
            onSaveDraft = { cents -> actions.onSaveAmountDraft(sheet.expense.id, cents) },
            onSaveAndConfirm = { cents -> actions.onSaveAmountAndConfirm(sheet.expense.id, cents) },
        )
        is PendingSheet.Duplicate -> DuplicateConfirmSheetContent(
            expense = sheet.expense,
            inProgress = sheet.expense.id in state.actionInProgressIds,
            onKeepBoth = { actions.onKeepBoth(sheet.expense) },
            onIgnoreCurrent = { actions.onIgnoreCurrent(sheet.expense) },
        )
        is PendingSheet.BulkConfirm -> BulkConfirmSheetContent(
            state = BulkConfirmSheetState(
                readyCount = state.readyCount,
                missingAmountSkipCount = state.missingAmountSkip,
                duplicateSkipCount = state.duplicateSkip,
                inProgress = state.bulkRunning,
                confirmedCount = state.bulkConfirmed,
                totalCount = state.bulkTotal,
            ),
            actions = BulkConfirmSheetActions(
                onConfirmReady = actions.onConfirmReady,
                onDismiss = actions.onDismiss,
            ),
        )
    }
}
