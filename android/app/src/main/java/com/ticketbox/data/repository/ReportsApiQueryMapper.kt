package com.ticketbox.data.repository

import com.ticketbox.data.remote.ReportsOverviewApiQuery
import com.ticketbox.data.remote.ReportsOverviewBreakdownQuery
import com.ticketbox.data.remote.ReportsWindowQuery
import com.ticketbox.domain.model.ReportsOverviewQuery

internal fun ReportsOverviewQuery.toReportsOverviewApiQuery(timezone: String): ReportsOverviewApiQuery =
    ReportsOverviewApiQuery(
        window = ReportsWindowQuery(month = month, timezone = timezone),
        breakdown = ReportsOverviewBreakdownQuery(
            granularity = granularity.apiValue,
            topN = topN,
            merchantCategory = merchantCategory,
            rankingMetric = rankingMetric.apiValue,
        ),
    )
