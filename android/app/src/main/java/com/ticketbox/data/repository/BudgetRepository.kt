package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
    suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult>
    suspend fun saveMonthlyBudget(month: String, update: BudgetMonthlyUpdate): Result<BudgetMonthly>
}

class BudgetRepository(
    private val apiProvider: ApiServiceProvider,
) : BudgetActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Budget",
        statusMessages = mapOf(404 to "预算不存在。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerId(): Flow<String?> = apiProvider.observeActiveLedgerId()

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> =
        monthlyBudget(month = month, timezone = currentTimezoneId())

    suspend fun monthlyBudget(month: String, timezone: String): Result<BudgetMonthly> {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.monthlyBudget(
                    month = cleanMonth,
                    timezone = timezone,
                ).toDomain()
            }
        }
    }

    override suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult> {
        if (!canModifyLedger()) {
            return Result.failure(
                RepositoryException(
                    message = "permission_denied",
                    errorCode = "permission_denied",
                ),
            )
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.budgetAdvise(
                    BudgetAdviseRequestDto(
                        month = cleanMonth,
                        timezone = currentTimezoneId(),
                    ),
                ).toDomain()
            }
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
            ledgerRequestGuard.guardedCall { api ->
                api.updateMonthlyBudget(
                    month = cleanMonth,
                    request = update.toRequest(),
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id
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
