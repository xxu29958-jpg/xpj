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

@Composable
internal fun BudgetAdviceRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    originalSubmissionId: Long? = null,
    reportContext: ReportRateContext? = null,
) {
    val viewModel: BudgetAdviceViewModel = viewModel(
        factory = budgetAdviceViewModelFactory(screenFactory.budgetRepository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()
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
            viewModel::saveRate, viewModel::closeRateEditor, viewModel::reviewRate, viewModel::recoverRate),
        onBack = onBack,
    )
}
