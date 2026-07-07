package com.ticketbox.data.remote

private const val DEFAULT_CONFIRMED_PAGE = 1
private const val DEFAULT_CONFIRMED_PAGE_SIZE = 50
private const val DEFAULT_REPORT_GRANULARITY = "day"
private const val DEFAULT_REPORT_TOP_N = 8
private const val DEFAULT_REPORT_RANKING_METRIC = "amount"

data class PageQuery(
    val page: Int = DEFAULT_CONFIRMED_PAGE,
    val pageSize: Int = DEFAULT_CONFIRMED_PAGE_SIZE,
)

data class ExpenseListFilterQuery(
    val month: String? = null,
    val category: String? = null,
    val tag: String? = null,
)

data class ConfirmedExpensesApiQuery(
    val page: PageQuery = PageQuery(),
    val filters: ExpenseListFilterQuery = ExpenseListFilterQuery(),
    val timezone: String? = null,
) {
    fun toQueryMap(): Map<String, String> = buildMap {
        put("page", page.page.toString())
        put("page_size", page.pageSize.toString())
        putIfPresent("month", filters.month)
        putIfPresent("category", filters.category)
        putIfPresent("tag", filters.tag)
        putIfPresent("timezone", timezone)
    }
}

data class ReportsWindowQuery(
    val month: String? = null,
    val timezone: String? = null,
)

data class ReportsOverviewBreakdownQuery(
    val granularity: String = DEFAULT_REPORT_GRANULARITY,
    val topN: Int = DEFAULT_REPORT_TOP_N,
    val merchantCategory: String? = null,
    val rankingMetric: String = DEFAULT_REPORT_RANKING_METRIC,
)

data class ReportsOverviewApiQuery(
    val window: ReportsWindowQuery = ReportsWindowQuery(),
    val breakdown: ReportsOverviewBreakdownQuery = ReportsOverviewBreakdownQuery(),
) {
    fun toQueryMap(): Map<String, String> = buildMap {
        putIfPresent("month", window.month)
        put("granularity", breakdown.granularity)
        put("top_n", breakdown.topN.toString())
        putIfPresent("merchant_category", breakdown.merchantCategory)
        put("ranking_metric", breakdown.rankingMetric)
        putIfPresent("timezone", window.timezone)
    }
}

private fun MutableMap<String, String>.putIfPresent(key: String, value: String?) {
    if (value != null) {
        put(key, value)
    }
}
