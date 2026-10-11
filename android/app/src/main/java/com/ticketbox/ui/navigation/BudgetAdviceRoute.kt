package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.plan.BudgetAdviceScreen
import com.ticketbox.viewmodel.BudgetAdviceViewModel
import com.ticketbox.viewmodel.budgetAdviceViewModelFactory
import com.ticketbox.viewmodel.*
import androidx.compose.runtime.LaunchedEffect

internal data class BudgetAdviceRouteContext(
    val originalSubmissionId: Long? = null,
    val report: ReportRateContext? = null,
    val correctionContinuation: Boolean = false,
)

@Composable
internal fun BudgetAdviceRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    context: BudgetAdviceRouteContext = BudgetAdviceRouteContext(),
    onOpenBudget: ((String) -> Unit)? = null,
    financialDataRevision: Int = 0,
) {
    val originalSubmissionId = context.originalSubmissionId
    val reportContext = context.report
    val viewModel: BudgetAdviceViewModel = viewModel(
        factory = budgetAdviceViewModelFactory(screenFactory.budgetRepository, screenFactory.repositories.ledgerCalendarRepository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    LaunchedEffect(financialDataRevision) {
        if (state.inputs != null) viewModel.refreshInputs()
    }
    LaunchedEffect(originalSubmissionId) { originalSubmissionId?.let(viewModel::openRateSubmission) }

    LaunchedEffect(reportContext, state.binding) {
        if (reportContext != null && state.binding != null && originalSubmissionId == null) {
            viewModel.openReportRate(reportContext.binding, reportContext.month, reportContext.homeCurrencyCode,
                reportContext.sourceCurrencyCode, reportContext.rateDate)
        }
    }

    BudgetAdviceScreen(
        state = state,
        actions = com.ticketbox.ui.screens.plan.BudgetAdviceActions(viewModel::requestAdvice, viewModel::refreshInputs,
            viewModel::shiftMonth, { viewModel.openRate(it) }, viewModel::editRate, viewModel::updateRateInput,
            viewModel::saveRate, viewModel::closeRateEditor, viewModel::reviewRate, viewModel::recoverRate,
            viewModel::editArrangement, viewModel::trialArrangement, viewModel::saveArrangement,
            viewModel::refreshArrangement, viewModel::loadArrangementHistory, viewModel::reviewArrangement, viewModel::recoverArrangement),
        onBack = onBack,
        correctionContinuation = context.correctionContinuation,
        onOpenBudget = onOpenBudget?.let { open -> { open(state.month) } },
    )
}
