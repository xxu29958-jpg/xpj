package com.ticketbox.data.remote

import com.ticketbox.data.remote.api.AuthApi
import com.ticketbox.data.remote.api.ExpenseListApi
import com.ticketbox.data.remote.api.ExpenseDetailApi
import com.ticketbox.data.remote.api.BillSplitApi
import com.ticketbox.data.remote.api.ExpenseStateApi
import com.ticketbox.data.remote.api.ExpenseMediaApi
import com.ticketbox.data.remote.api.CategoryRuleApi
import com.ticketbox.data.remote.api.MerchantApi
import com.ticketbox.data.remote.api.TagApi
import com.ticketbox.data.remote.api.ServerSettingsApi
import com.ticketbox.data.remote.api.ReportsApi
import com.ticketbox.data.remote.api.GoalsApi
import com.ticketbox.data.remote.api.DebtApi
import com.ticketbox.data.remote.api.DebtProposalApi
import com.ticketbox.data.remote.api.RepaymentDraftApi
import com.ticketbox.data.remote.api.DashboardApi
import com.ticketbox.data.remote.api.BudgetApi
import com.ticketbox.data.remote.api.IncomePlanApi
import com.ticketbox.data.remote.api.RecurringApi
import com.ticketbox.data.remote.api.LedgerApi
import com.ticketbox.data.remote.api.InvitationApi
import com.ticketbox.data.remote.api.LedgerDeviceApi
import com.ticketbox.data.remote.api.RecycleBinApi
import com.ticketbox.data.remote.api.BackgroundTaskApi
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query
import retrofit2.http.Streaming

interface ApiService :
    AuthApi,
    ExpenseListApi,
    ExpenseDetailApi,
    BillSplitApi,
    ExpenseStateApi,
    ExpenseMediaApi,
    CategoryRuleApi,
    MerchantApi,
    TagApi,
    ServerSettingsApi,
    ReportsApi,
    GoalsApi,
    DebtApi,
    DebtProposalApi,
    RepaymentDraftApi,
    DashboardApi,
    BudgetApi,
    IncomePlanApi,
    RecurringApi,
    LedgerApi,
    InvitationApi,
    LedgerDeviceApi,
    RecycleBinApi,
    BackgroundTaskApi {
    @GET("api/expenses/confirmed")
    suspend fun confirmedExpenses(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
        @Query("month") month: String? = null,
        @Query("category") category: String? = null,
        @Query("tag") tag: String? = null,
        @Query("timezone") timezone: String? = null,
    ): PaginatedExpensesDto

    @GET("api/reports/overview")
    suspend fun reportsOverview(
        @Query("month") month: String? = null,
        @Query("granularity") granularity: String = "day",
        @Query("top_n") topN: Int = 8,
        @Query("merchant_category") merchantCategory: String? = null,
        @Query("ranking_metric") rankingMetric: String = "amount",
        @Query("timezone") timezone: String? = null,
    ): ReportsOverviewDto

    @GET("api/reports/overview.csv")
    @Streaming
    suspend fun reportsOverviewCsv(
        @Query("month") month: String? = null,
        @Query("granularity") granularity: String = "day",
        @Query("top_n") topN: Int = 8,
        @Query("merchant_category") merchantCategory: String? = null,
        @Query("ranking_metric") rankingMetric: String = "amount",
        @Query("timezone") timezone: String? = null,
    ): Response<ResponseBody>
}
