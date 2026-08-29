package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.screens.expense.fact.ExpenseFactScreen
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.consumeOpenRepaymentDraftPublicId
import com.ticketbox.viewmodel.expenseFactViewModelFactory

/**
 * A1: confirmed 账单事实/更正的独立 Owner 路由（由 [ExpenseEditRoute] 按
 * 状态分流而来）。挂自己的 [ExpenseFactViewModel]；旧编辑 VM 不渲染 confirmed。
 */
@Composable
internal fun ExpenseFactRoute(
    expenseId: Long,
    initialExpense: Expense,
    screenFactory: MainScreenFactory,
    onExit: (adviceInputsChanged: Boolean) -> Unit,
    onOpenRepaymentDrafts: (String) -> Unit,
) {
    val factViewModel: ExpenseFactViewModel = viewModel(
        key = "expense-fact-$expenseId",
        factory = expenseFactViewModelFactory(
            expenseId = expenseId,
            repository = screenFactory.repository,
            initialExpense = initialExpense,
        ),
    )
    val factState by factViewModel.uiState.collectAsStateWithLifecycle()

    FactRepaymentDraftOpenEffect(factState, factViewModel, onOpenRepaymentDrafts)

    ExpenseFactScreen(
        state = factState,
        viewModel = factViewModel,
        onBack = {
            // 更正改变了金额/分类/时间等建议输入时，返回路径同步失效建议缓存
            // （与编辑页 onCompleted 同一合同）。
            onExit(factViewModel.consumeDoneAdviceInputsChanged())
        },
    )
}

@Composable
private fun FactRepaymentDraftOpenEffect(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
    onOpenRepaymentDrafts: (String) -> Unit,
) {
    LaunchedEffect(state.openRepaymentDraftPublicId) {
        val draftPublicId = viewModel.consumeOpenRepaymentDraftPublicId()
        if (draftPublicId != null) {
            onOpenRepaymentDrafts(draftPublicId)
        }
    }
}
