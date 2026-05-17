package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions {
    fun canModifyLedger(): Boolean
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
    suspend fun saveMonthlyBudget(month: String, update: BudgetMonthlyUpdate): Result<BudgetMonthly>
}

class BudgetRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) : BudgetActions {
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Budget",
        statusMessages = mapOf(404 to "预算不存在。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            api().monthlyBudget(
                month = cleanMonth,
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun saveMonthlyBudget(
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            api().updateMonthlyBudget(
                month = cleanMonth,
                request = update.toRequest(),
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    private fun api() = apiProvider.current()
}

private val MONTH_PATTERN = Regex("^\\d{4}-\\d{2}$")

private fun validatedMonth(month: String): Result<String> {
    return runCatching { requireMonth(month) }
        .fold(
            onSuccess = { Result.success(it) },
            onFailure = { Result.failure(RepositoryException(it.message ?: "预算月份不正确。")) },
        )
}

private fun requireMonth(month: String): String {
    val cleanMonth = month.trim()
    require(MONTH_PATTERN.matches(cleanMonth)) { "预算月份不正确。" }
    require(runCatching { YearMonth.parse(cleanMonth) }.isSuccess) { "预算月份不正确。" }
    return cleanMonth
}
