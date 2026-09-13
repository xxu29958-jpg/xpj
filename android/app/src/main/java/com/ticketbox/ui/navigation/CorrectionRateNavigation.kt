package com.ticketbox.ui.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.LogicalSessionBinding
import java.time.LocalDate
import java.time.YearMonth

internal const val CORRECTION_RATE_ROUTE = "product/plans/budget-advice/correction?report={report}"

internal fun correctionRateRoute(binding: LogicalSessionBinding, gap: MissingExchangeRateDto): String {
    require(gap.canEnterManualRate())
    val date = requireNotNull(gap.rateDate)
    val context = ReportRateContext(binding, YearMonth.from(LocalDate.parse(date)).toString(), gap.homeCurrencyCode, gap.sourceCurrencyCode, date)
    return "${CORRECTION_RATE_ROUTE.substringBefore('?')}?report=${encodeRateContext(context)}"
}

/** Registered in both real navigation containers; Back returns to the unchanged original card. */
internal fun NavGraphBuilder.addCorrectionRateRoute(screenFactory: MainScreenFactory, onBack: () -> Unit) {
    composable(CORRECTION_RATE_ROUTE, arguments = listOf(navArgument("report") { type = NavType.StringType })) { entry ->
        val context = readReportRateContext(entry.arguments?.getString("report")) ?: return@composable
        BudgetAdviceRoute(screenFactory, onBack, reportContext = context, correctionContinuation = true)
    }
}
