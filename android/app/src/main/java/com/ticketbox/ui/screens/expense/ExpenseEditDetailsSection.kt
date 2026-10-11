package com.ticketbox.ui.screens.expense

import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState

internal const val TAG_ITEMS_DETAIL_ROW = "expense-edit-items-detail-row"
internal const val TAG_SPLITS_DETAIL_ROW = "expense-edit-splits-detail-row"

/** 折叠行摘要的四态：与 [expenseDetailPanelPresentation] 同一份状态语义。 */
internal enum class ExpenseDetailRowKind {
    Loading,
    Empty,
    Failed,
    Rows,
}

internal fun expenseDetailCollapsedRowKind(
    loading: Boolean,
    loadState: ExpenseDetailDataLoadState,
    rowCount: Int?,
): ExpenseDetailRowKind = when {
    expenseDetailPanelShowsLoading(loading = loading, loadState = loadState) -> ExpenseDetailRowKind.Loading
    loadState == ExpenseDetailDataLoadState.Failed -> ExpenseDetailRowKind.Failed
    // Loaded 却没有模型：既不是真实空也不是行数，按失败呈现，展开后由 message slot 说明。
    rowCount == null -> ExpenseDetailRowKind.Failed
    rowCount == 0 -> ExpenseDetailRowKind.Empty
    else -> ExpenseDetailRowKind.Rows
}

/** 有未确认的合计差额时默认展开——警示不能藏在折叠线后；已确认/无差额默认折叠。 */
internal fun expenseDetailDefaultsExpanded(
    mismatchKnown: Boolean,
    mismatchAcknowledged: Boolean,
): Boolean = mismatchKnown && !mismatchAcknowledged

internal data class ExpenseEditDetailsState(
    val expenseId: Long,
    val expenseItems: ExpenseItems?,
    val expenseSplits: ExpenseSplits?,
    val itemsLoading: Boolean,
    val splitsLoading: Boolean,
    val itemsLoadState: ExpenseDetailDataLoadState,
    val splitsLoadState: ExpenseDetailDataLoadState,
    val itemsMessage: UiText?,
    val splitsMessage: UiText?,
    val itemsMessageTone: MessageTone,
    val splitsMessageTone: MessageTone,
)

internal data class ExpenseEditDetailsActions(
    val onAcknowledgeItemsMismatch: () -> Unit = {},
    val onEditItems: (() -> Unit)? = null,
    val onEditSplits: (() -> Unit)? = null,
)

/**
 * 明细/拆账折叠段：默认收成一行摘要（条数 · 合计 / 还没有 / 加载中 / 加载失败），
 * 展开后是既有面板全量内容（对账行、分组明细、编辑入口、只读说明、差额确认）。
 * 折叠只改呈现密度，不改任何状态声明。
 */
@Composable
internal fun ExpenseEditDetailsSection(
    state: ExpenseEditDetailsState,
    actions: ExpenseEditDetailsActions = ExpenseEditDetailsActions(),
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    // 用户手动展开/收起是覆盖值；未覆盖时默认值随数据推导——明细是异步到达的，
    // 首帧时 mismatch 还未知，若把默认值一次性冻结进 remember，差额警示就会藏在折叠线后。
    var itemsExpandedOverride by rememberSaveable(state.expenseId) { mutableStateOf<Boolean?>(null) }
    val itemsExpanded = itemsExpandedOverride ?: expenseDetailDefaultsExpanded(
        mismatchKnown = state.expenseItems?.mismatchKnown == true,
        mismatchAcknowledged = state.expenseItems?.mismatchAcknowledged == true,
    )
    var splitsExpanded by rememberSaveable(state.expenseId) { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ExpenseItemsCollapsibleRow(
            state = state,
            expanded = itemsExpanded,
            currencyDisplay = currencyDisplay,
            onToggle = { itemsExpandedOverride = !itemsExpanded },
        ) {
            ExpenseItemsPanel(
                expenseItems = state.expenseItems,
                state = DetailLoadState(
                    loading = state.itemsLoading,
                    loadState = state.itemsLoadState,
                    message = state.itemsMessage,
                    messageTone = state.itemsMessageTone,
                ),
                currencyDisplay = currencyDisplay,
                onAcknowledgeMismatch = actions.onAcknowledgeItemsMismatch,
                onEditItems = actions.onEditItems,
            )
        }
        ExpenseSplitsCollapsibleRow(
            state = state,
            expanded = splitsExpanded,
            currencyDisplay = currencyDisplay,
            onToggle = { splitsExpanded = !splitsExpanded },
        ) {
            ExpenseSplitsPanel(
                expenseSplits = state.expenseSplits,
                state = DetailLoadState(
                    loading = state.splitsLoading,
                    loadState = state.splitsLoadState,
                    message = state.splitsMessage,
                    messageTone = state.splitsMessageTone,
                ),
                currencyDisplay = currencyDisplay,
                onEditSplits = actions.onEditSplits,
            )
        }
    }
}

@Composable
private fun ExpenseItemsCollapsibleRow(
    state: ExpenseEditDetailsState,
    expanded: Boolean,
    currencyDisplay: CurrencyDisplay,
    onToggle: () -> Unit,
    content: @Composable () -> Unit,
) {
    val items = state.expenseItems
    val kind = expenseDetailCollapsedRowKind(
        loading = state.itemsLoading,
        loadState = state.itemsLoadState,
        rowCount = items?.items?.size,
    )
    val showMismatchPill = kind == ExpenseDetailRowKind.Rows &&
        items?.mismatchKnown == true &&
        !items.mismatchAcknowledged
    ExpenseDetailCollapsibleRow(
        model = ExpenseDetailCollapsedRowModel(
            title = stringResource(R.string.expense_edit_v1_items_title),
            icon = R.drawable.ic_lucide_shopping_bag,
            summary = expenseDetailRowSummary(
                kind = kind,
                emptyText = stringResource(R.string.expense_edit_v1_items_empty),
                rowCount = items?.items?.size ?: 0,
                totalCents = items?.itemsTotalAmountCents,
                currencyDisplay = currencyDisplay,
            ),
            pill = if (showMismatchPill) {
                ExpenseDetailReconcileStatus.Diff.label()
            } else {
                null
            },
        ),
        expanded = expanded,
        onToggle = onToggle,
        testTag = TAG_ITEMS_DETAIL_ROW,
        content = content,
    )
}

@Composable
private fun ExpenseSplitsCollapsibleRow(
    state: ExpenseEditDetailsState,
    expanded: Boolean,
    currencyDisplay: CurrencyDisplay,
    onToggle: () -> Unit,
    content: @Composable () -> Unit,
) {
    val splits = state.expenseSplits
    val kind = expenseDetailCollapsedRowKind(
        loading = state.splitsLoading,
        loadState = state.splitsLoadState,
        rowCount = splits?.splits?.size,
    )
    val reconcile = splits?.let {
        resolveExpenseDetailReconcileStatus(mismatchCents = it.mismatchCents, partialIsValid = true)
    }
    val showPill = kind == ExpenseDetailRowKind.Rows && reconcile in SPLITS_ATTENTION_STATUSES
    ExpenseDetailCollapsibleRow(
        model = ExpenseDetailCollapsedRowModel(
            title = stringResource(R.string.expense_edit_v1_splits_title),
            icon = R.drawable.ic_lucide_users,
            summary = expenseDetailRowSummary(
                kind = kind,
                emptyText = stringResource(R.string.expense_edit_v1_splits_empty),
                rowCount = splits?.splits?.size ?: 0,
                totalCents = splits?.splitsTotalAmountCents,
                currencyDisplay = currencyDisplay,
            ),
            pill = if (showPill) reconcile?.label() else null,
        ),
        expanded = expanded,
        onToggle = onToggle,
        testTag = TAG_SPLITS_DETAIL_ROW,
        content = content,
    )
}

/** 折叠行上值得抬到摘要 pill 的拆账对账态；Matched 不打扰。 */
private val SPLITS_ATTENTION_STATUSES = setOf(
    ExpenseDetailReconcileStatus.Diff,
    ExpenseDetailReconcileStatus.Partial,
    ExpenseDetailReconcileStatus.Overallocated,
)

private data class ExpenseDetailCollapsedRowModel(
    val title: String,
    val icon: Int,
    val summary: String,
    val pill: String?,
)

@Composable
private fun ExpenseDetailCollapsibleRow(
    model: ExpenseDetailCollapsedRowModel,
    expanded: Boolean,
    onToggle: () -> Unit,
    testTag: String,
    content: @Composable () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        com.ticketbox.ui.screens.settings.SettingsEntryRow(
            title = model.title,
            subtitle = model.summary,
            icon = model.icon,
            onClick = onToggle,
            options = SettingsEntryRowOptions(expanded = expanded, modifier = Modifier.testTag(testTag), supportingContent = { model.pill?.let { StatusPill(text = it, active = false) } }),
        )
        if (expanded) Column(modifier = Modifier.padding(top = AppSpacing.smallGap)) { content() }
    }
}

@Composable
private fun expenseDetailRowSummary(
    kind: ExpenseDetailRowKind,
    emptyText: String,
    rowCount: Int,
    totalCents: Long?,
    currencyDisplay: CurrencyDisplay,
): String = when (kind) {
    ExpenseDetailRowKind.Loading -> stringResource(R.string.expense_edit_details_row_loading)
    ExpenseDetailRowKind.Empty -> emptyText
    ExpenseDetailRowKind.Failed -> stringResource(R.string.expense_edit_details_row_failed)
    ExpenseDetailRowKind.Rows -> if (totalCents != null) {
        stringResource(
            R.string.expense_edit_details_row_count_total,
            rowCount,
            formatDisplayAmount(totalCents, currencyDisplay),
        )
    } else {
        stringResource(R.string.expense_edit_details_row_count, rowCount)
    }
}
