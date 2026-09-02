package com.ticketbox.data.remote

import com.ticketbox.data.remote.api.AuthApi
import com.ticketbox.data.remote.api.ExpenseListApi
import com.ticketbox.data.remote.api.ExpenseDetailApi
import com.ticketbox.data.remote.api.ExpenseCorrectionApi
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
import com.ticketbox.data.remote.api.DebtRepaymentApi
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
import retrofit2.http.QueryMap
import retrofit2.http.Streaming

interface ApiService :
    AuthApi,
    ExpenseListApi,
    ExpenseDetailApi,
    ExpenseCorrectionApi,
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
    DebtRepaymentApi,
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
        @QueryMap query: Map<String, String>,
    ): PaginatedExpensesDto

    @GET("api/reports/overview")
    suspend fun reportsOverview(
        @QueryMap query: Map<String, String>,
    ): ReportsOverviewDto

    @GET("api/reports/overview.csv")
    @Streaming
    suspend fun reportsOverviewCsv(
        @QueryMap query: Map<String, String>,
    ): Response<ResponseBody>
}
