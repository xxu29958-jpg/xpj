package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.domain.model.normalizeExpenseCategory
import retrofit2.Response
import java.time.YearMonth
import java.util.TimeZone
import java.util.UUID
import kotlinx.coroutines.flow.filterNotNull

interface DashboardCardsActions {
    fun canModifyLedger(): Boolean
    fun dashboardAccess(): LedgerAccessContext?
    suspend fun dashboardCards(
        binding: LogicalSessionBinding,
        surface: DashboardSurface = DashboardSurface.Android,
    ): Result<DashboardCards>
    suspend fun updateDashboardCards(
        binding: LogicalSessionBinding,
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface = DashboardSurface.Android,
    ): Result<DashboardCards>
}

interface ReportsActions : DashboardCardsActions {
    suspend fun goalHistory(publicId: String, beforeVersion: Long?, binding: LogicalSessionBinding):
        Result<ReadSnapshot<com.ticketbox.domain.model.GoalHistoryPage>>
    val readAccessDenials: kotlinx.coroutines.flow.Flow<SnapshotAccessDenial> get() = kotlinx.coroutines.flow.emptyFlow()
    fun observeReportsAccess(): kotlinx.coroutines.flow.Flow<LedgerAccessContext?> = kotlinx.coroutines.flow.flowOf(dashboardAccess())
    suspend fun reportsOverview(query: ReportsOverviewQuery = ReportsOverviewQuery(), expectedBinding: LogicalSessionBinding? = null): Result<ReportsOverview>
    suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery = ReportsOverviewQuery(), expectedBinding: LogicalSessionBinding? = null): Result<CsvExport>
    suspend fun goals(month: String? = null, includeArchived: Boolean = false,
        expectedBinding: LogicalSessionBinding? = null, timezone: String = TimeZone.getDefault().id): Result<ReadSnapshot<List<Goal>>>

    /**
     * ADR-0049 §6 (slice 8b): create a debt_repayment goal linking [debtPublicIds].
     * Direct-only online (no outbox, no Idempotency-Key — the create route has none);
     * viewer role short-circuits before the network. Server enforces the per-type
     * rules (≥1 debt id, no month/target/category) — the repository validates the
     * shape it can (non-blank name, ≥1 id) so a bad form fails fast without a call.
     */
    suspend fun goal(publicId: String, expectedBinding: LogicalSessionBinding? = null,
        timezone: String = TimeZone.getDefault().id): Result<ReadSnapshot<Goal>>
    suspend fun archiveGoal(publicId: String, expectedBinding: LogicalSessionBinding): Result<Goal>

    // ── ADR-0049 §6 (slice 7) debt_repayment goal surface ────────────────────
    /** List the (month-less) debt_repayment goals; [goal] reuses for the detail. */
    suspend fun debtGoals(includeArchived: Boolean = false, expectedBinding: LogicalSessionBinding? = null,
        timezone: String = TimeZone.getDefault().id): Result<ReadSnapshot<List<Goal>>>

    /**
     * Acknowledge ("keep for audit") an achieved debt goal version whose linked set
     * carries a debt-voided Debt (§6/F13) — clears needs_review for the current
     * version. [expectedRowVersion] is the OCC token.
     */
    suspend fun acknowledgeDebtIntegrityReview(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Goal>

}

class ReportsRepository(
    private val apiProvider: ApiServiceProvider,
    expenseDao: com.ticketbox.data.local.ExpenseDao,
    sessionCoordinator: LocalLedgerSessionCoordinator,
) : ReportsActions {
    override suspend fun goalHistory(publicId: String, beforeVersion: Long?, binding: LogicalSessionBinding) =
        goalQueries.history(publicId, beforeVersion, binding)
    override val readAccessDenials = sessionCoordinator.snapshotAccessDenials.filterNotNull()
    internal val goalQueries = GoalQueryReader(apiProvider, expenseDao, sessionCoordinator)
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Reports",
        statusMessages = mapOf(404 to "没有找到目标。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeReportsAccess(): kotlinx.coroutines.flow.Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override suspend fun reportsOverview(query: ReportsOverviewQuery, expectedBinding: LogicalSessionBinding?): Result<ReportsOverview> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val request = expectedBinding?.let(ledgerRequestGuard::bindExact) ?: ledgerRequestGuard.bind()
            request.call { api ->
                api.reportsOverview(
                    query = cleanQuery.toReportsOverviewApiQuery(timezone = currentTimezoneId()).toQueryMap(),
                ).toDomain().also { result ->
                    val matchesMonth = cleanQuery.month == null || result.month == cleanQuery.month
                    val matchesHome = cleanQuery.homeCurrencyCode == null || result.homeCurrencyCode == cleanQuery.homeCurrencyCode
                    val knownHome = com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(result.homeCurrencyCode) != null
                    if (!matchesMonth || !matchesHome || !knownHome) throw RepositoryException("")
                }
            }
        }
    }

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery, expectedBinding: LogicalSessionBinding?): Result<CsvExport> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val request = expectedBinding?.let(ledgerRequestGuard::bindExact) ?: ledgerRequestGuard.bind()
            request.call { api ->
                val response = api.reportsOverviewCsv(
                    query = cleanQuery.toReportsOverviewApiQuery(timezone = currentTimezoneId()).toQueryMap(),
                )
                val bytes = readExportBody(response)
                CsvExport(
                    fileName = "ticketbox-reports-overview-${cleanQuery.month ?: "current"}-${cleanQuery.granularity.apiValue}.csv",
                    bytes = bytes,
                )
            }
        }
    }

    override suspend fun goals(month: String?, includeArchived: Boolean, expectedBinding: LogicalSessionBinding?,
        timezone: String): Result<ReadSnapshot<List<Goal>>> = goalQueries.goals(month, includeArchived, expectedBinding, timezone)

    override suspend fun goal(publicId: String, expectedBinding: LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<Goal>> =
        goalQueries.goal(publicId, expectedBinding, timezone)

    override suspend fun archiveGoal(publicId: String, expectedBinding: LogicalSessionBinding): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return goalCommand(expectedBinding) { api ->
            api.archiveGoal(
                publicId = cleanPublicId,
                timezone = currentTimezoneId(),
            )
        }
    }

    override suspend fun debtGoals(includeArchived: Boolean, expectedBinding: LogicalSessionBinding?,
        timezone: String): Result<ReadSnapshot<List<Goal>>> = goalQueries.debtGoals(includeArchived, expectedBinding, timezone)

    override suspend fun acknowledgeDebtIntegrityReview(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return goalCommand { api ->
            api.acknowledgeGoalIntegrityReview(
                publicId = cleanPublicId,
                request = DebtGoalIntegrityReviewRequestDto(expectedRowVersion),
                idempotencyKey = UUID.randomUUID().toString(),
                timezone = currentTimezoneId(),
            )
        }
    }

    private suspend fun goalCommand(
        expectedBinding: LogicalSessionBinding? = null,
        command: suspend (ApiService) -> GoalDto,
    ): Result<Goal> = errorHandler.safeCall {
        val binding = expectedBinding ?: requireNotNull(ledgerRequestGuard.captureLogicalBinding()) { "请重新绑定账本。" }
        val accepted = ledgerRequestGuard.bindExact(binding).call { command(it).toDomain() }
        goalQueries.invalidate(binding)
        accepted
    }

    /** Runs under the original dispatch lease; never takes the session coordinator lock. */
    internal suspend fun invalidateGoalReadsAfterDelivery(row: OutboxRow) {
        val binding = requireNotNull(ledgerRequestGuard.captureLogicalBinding()) { "请重新绑定账本。" }
        require(row.ledgerId == binding.ledgerId && row.ownerKey == binding.ownerKey &&
            canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
            "账本已切换，请重新操作。"
        }
        goalQueries.invalidate(binding)
    }

    override fun dashboardAccess(): LedgerAccessContext? = ledgerRequestGuard.captureLogicalBinding()?.let {
        LedgerAccessContext(binding = it, canModify = canModifyLedger())
    }

    override suspend fun dashboardCards(
        binding: LogicalSessionBinding,
        surface: DashboardSurface,
    ): Result<DashboardCards> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.dashboardCards(surface = surface.apiValue).toDomain()
            }
        }

    override suspend fun updateDashboardCards(
        binding: LogicalSessionBinding,
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanUpdates = updates.validatedDashboardUpdates()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.updateDashboardCards(
                    request = cleanUpdates.toRequest(),
                    surface = surface.apiValue,
                ).toDomain()
            }
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    private fun readExportBody(response: Response<okhttp3.ResponseBody>): ByteArray {
        if (!response.isSuccessful) {
            throw errorHandler.httpFailure(retrofit2.HttpException(response))
        }
        val body = response.body() ?: throw RepositoryException("导出内容为空。")
        return body.use { it.bytes() }
    }
}

private val REPORTS_MONTH_PATTERN = Regex("^\\d{4}-\\d{2}$")


private fun ReportsOverviewQuery.validated(): Result<ReportsOverviewQuery> {
    return runCatching {
        copy(
            month = month.cleanMonthOrThrow("报表月份不正确。"),
            topN = topN.coerceIn(1, 20),
            merchantCategory = merchantCategory?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
        )
    }.mapError()
}


internal fun GoalUpdate.validatedGoalUpdate(): Result<GoalUpdate> {
    return runCatching {
        if (name != null) {
            require(name.trim().isNotBlank()) { "请输入目标名称。" }
        }
        if (targetAmountCents != null) {
            require(targetAmountCents > 0L) { "目标金额必须大于 0。" }
        }
        copy(
            name = name?.trim(),
            month = month?.let { requireMonth(it, "目标月份不正确。") },
            category = category?.trim()?.let { if (it.isEmpty()) "" else normalizeExpenseCategory(it) },
        )
    }.mapError()
}

private fun List<DashboardCardUpdate>.validatedDashboardUpdates(): Result<List<DashboardCardUpdate>> {
    return runCatching {
        val clean = map {
            val key = it.key.trim()
            require(key.isNotBlank()) { "卡片类型不正确。" }
            require(it.position >= 0) { "卡片顺序不正确。" }
            it.copy(key = key)
        }
        require(clean.map { it.key }.distinct().size == clean.size) { "卡片不能重复。" }
        clean
    }.mapError()
}

private fun String.cleanPublicId(): Result<String> {
    return runCatching {
        trim().also { require(it.isNotBlank()) { "请选择一个目标。" } }
    }.mapError()
}

private fun String?.cleanMonthOrThrow(errorMessage: String): String? {
    val cleanMonth = this?.trim()?.takeIf { it.isNotBlank() } ?: return null
    return requireMonth(cleanMonth, errorMessage)
}

private fun requireMonth(month: String, errorMessage: String): String {
    val cleanMonth = month.trim()
    require(REPORTS_MONTH_PATTERN.matches(cleanMonth)) { errorMessage }
    require(runCatching { YearMonth.parse(cleanMonth) }.isSuccess) { errorMessage }
    return cleanMonth
}

private fun <T> Result<T>.mapError(): Result<T> = fold(
    onSuccess = { Result.success(it) },
    onFailure = { Result.failure(RepositoryException(it.message ?: "请求参数不正确。")) },
)
