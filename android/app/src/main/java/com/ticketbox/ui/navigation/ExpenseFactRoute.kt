package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.expense.fact.ExpenseFactScreen
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.refreshOriginalFact
import com.ticketbox.viewmodel.loadExpenseFactBundle
import com.ticketbox.viewmodel.loadExpenseRevisions
import com.ticketbox.viewmodel.consumeOpenRepaymentDraftPublicId
import com.ticketbox.viewmodel.expenseFactViewModelFactory
import com.ticketbox.viewmodel.leaveFactPage

internal data class ExpenseFactNavigation(val onOpenRepaymentDrafts: (String) -> Unit,
    val onRepairRate: com.ticketbox.ui.screens.expense.fact.CorrectionRateAction)

/**
 * A1: confirmed 账单事实/更正的独立 Owner 路由（由 [ExpenseEditRoute] 按
 * 状态分流而来）。挂自己的 [ExpenseFactViewModel]；旧编辑 VM 不渲染 confirmed。
 */
@Composable
internal fun ExpenseFactRoute(
    expenseId: Long,
    screenFactory: MainScreenFactory,
    onExit: (adviceInputsChanged: Boolean) -> Unit,
    related: ExpenseFactNavigation,
    financialDataRevision: Int = 0,
) {
    val factViewModel: ExpenseFactViewModel = viewModel(
        key = "expense-fact-$expenseId",
        factory = expenseFactViewModelFactory(
            expenseId = expenseId,
            repository = screenFactory.repository,
            preferLocalCache = true,
            originalBinding = LocalNotificationTask.current?.binding,
            calendars = screenFactory.repositories.ledgerCalendarRepository,
        ),
    )
    val factState by factViewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(financialDataRevision) {
        if (financialDataRevision > 0) {
            factViewModel.loadExpenseFactBundle()
            factViewModel.loadExpenseRevisions()
        }
    }

    FactRepaymentDraftOpenEffect(factState, factViewModel, related.onOpenRepaymentDrafts)

    val leave = { factViewModel.leaveFactPage { onExit(factViewModel.consumeDoneAdviceInputsChanged()) } }
    androidx.activity.compose.BackHandler { leave() }

    ExpenseFactScreen(
        state = factState,
        viewModel = factViewModel,
        originalContent = { OriginalAttachmentRoute(expenseId, screenFactory, factViewModel::refreshOriginalFact) },
        onRepairCorrectionRate = related.onRepairRate,
        onBack = leave,
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
