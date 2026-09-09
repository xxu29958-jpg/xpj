package com.ticketbox.ui.navigation

import android.net.Uri
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.domain.model.ReportsOverview

@JsonClass(generateAdapter = true)
internal data class ReportRateContext(val binding: LogicalSessionBinding, val month: String,
    val homeCurrencyCode: String, val sourceCurrencyCode: String? = null, val rateDate: String? = null)

private val reportRateContextAdapter = Moshi.Builder().build().adapter(ReportRateContext::class.java)

internal fun reportRateRoute(binding: LogicalSessionBinding, overview: ReportsOverview, gap: CurrencyProjectionGap?): String {
    val context = ReportRateContext(binding, overview.month, overview.homeCurrencyCode, gap?.sourceCurrencyCode, gap?.rateDate)
    return "${ProductSecondaryPage.BudgetAdvice.route}?report=${Uri.encode(reportRateContextAdapter.toJson(context))}"
}

internal fun readReportRateContext(json: String?): ReportRateContext? =
    json?.let { runCatching { reportRateContextAdapter.fromJson(it) }.getOrNull() }
