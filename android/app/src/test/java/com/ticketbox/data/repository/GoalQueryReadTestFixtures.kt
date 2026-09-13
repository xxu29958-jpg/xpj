package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import java.net.ConnectException

internal class GoalReadApi : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
    var offline = false
    var failure: Throwable? = null
    var goals = listOf(readGoalDto())
    var listResponder: (suspend () -> GoalListResponseDto)? = null
    var statsResponder: (suspend () -> MonthlyStatsDto)? = null
    override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
        checkTransport()
        return listResponder?.invoke() ?: GoalListResponseDto(goals)
    }
    override suspend fun goal(publicId: String, timezone: String?): GoalDto {
        checkTransport()
        return goals.single { it.publicId == publicId }
    }
    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?): MonthlyStatsDto {
        checkTransport()
        return statsResponder?.invoke() ?: MonthlyStatsDto("JPY", month = "2026-09", totalAmountCents = 12, count = 1,
            byCategory = listOf(com.ticketbox.data.remote.dto.CategoryStatsDto("购物", 12, 1)))
    }
    private fun checkTransport() {
        if (offline) throw ConnectException("offline")
        failure?.let { throw it }
    }
}

internal class GoalReadFixture(decorate: (ApiService) -> ApiService = { it }) {
    val dao = FakeExpenseDao()
    val api = GoalReadApi()
    val session = TestSessionFixture().apply { saveToken("session-token") }
    private val settings = boundSettingsStore()
    private val service = decorate(api)
    private val factory = object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }
    val provider = testApiServiceProvider(factory, session)
    val coordinator = LocalLedgerSessionCoordinator(settings, session.sessionStore, dao)
    val repository get() = ReportsRepository(provider, dao, coordinator)
    val stats = expenseRepositoryFixture(dao, testServerSessionBinding(factory, settings, session), coordinator)
    val binding get() = requireNotNull(repository.dashboardAccess()).binding
}

internal fun readGoalDto() = GoalDto(
    publicId = "goal-jpy", ledgerId = "owner", name = "旅行限额", goalType = "spending_limit", period = "monthly",
    month = "2026-09", category = null, targetAmountCents = 1200, spentAmountCents = null,
    remainingAmountCents = null, progressPercent = null, progressState = "unavailable", status = "active",
    createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 2,
    archivedAt = null, homeCurrencyCode = "JPY",
)
