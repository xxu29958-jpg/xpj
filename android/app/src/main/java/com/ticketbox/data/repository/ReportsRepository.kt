package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.time.YearMonth
import java.util.TimeZone

interface ReportsActions {
    fun canModifyLedger(): Boolean
    suspend fun reportsOverview(query: ReportsOverviewQuery = ReportsOverviewQuery()): Result<ReportsOverview>
    suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery = ReportsOverviewQuery()): Result<CsvExport>
    suspend fun goals(month: String? = null, includeArchived: Boolean = false): Result<List<Goal>>
    suspend fun createGoal(draft: GoalDraft): Result<Goal>
    suspend fun goal(publicId: String): Result<Goal>
    suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal>
    suspend fun archiveGoal(publicId: String): Result<Goal>
    suspend fun dashboardCards(surface: DashboardSurface = DashboardSurface.Android): Result<DashboardCards>
    suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface = DashboardSurface.Android,
    ): Result<DashboardCards>
}

class ReportsRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
) : ReportsActions {
    private companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }

    private val errorAdapter = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
        .adapter(ErrorDto::class.java)

    private var cachedServerUrl: String? = null
    private var cachedApi: ApiService? = null

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun reportsOverview(query: ReportsOverviewQuery): Result<ReportsOverview> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().reportsOverview(
                month = cleanQuery.month,
                granularity = cleanQuery.granularity.apiValue,
                topN = cleanQuery.topN,
                merchantCategory = cleanQuery.merchantCategory,
                rankingMetric = cleanQuery.rankingMetric.apiValue,
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery): Result<CsvExport> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            val response = api().reportsOverviewCsv(
                month = cleanQuery.month,
                granularity = cleanQuery.granularity.apiValue,
                topN = cleanQuery.topN,
                merchantCategory = cleanQuery.merchantCategory,
                rankingMetric = cleanQuery.rankingMetric.apiValue,
                timezone = currentTimezoneId(),
            )
            val bytes = readExportBody(response)
            CsvExport(
                fileName = "ticketbox-reports-overview-${cleanQuery.month ?: "current"}-${cleanQuery.granularity.apiValue}.csv",
                bytes = bytes,
            )
        }
    }

    override suspend fun goals(month: String?, includeArchived: Boolean): Result<List<Goal>> {
        val cleanMonth = month.cleanMonthOrNull()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().goals(
                month = cleanMonth,
                includeArchived = includeArchived,
                timezone = currentTimezoneId(),
            ).items.map { it.toDomain() }
        }
    }

    override suspend fun createGoal(draft: GoalDraft): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanDraft = draft.validated()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().createGoal(
                request = cleanDraft.toRequest(),
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun goal(publicId: String): Result<Goal> {
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().goal(
                publicId = cleanPublicId,
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        val cleanUpdate = update.validated()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().updateGoal(
                publicId = cleanPublicId,
                request = cleanUpdate.toRequest(),
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun archiveGoal(publicId: String): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().archiveGoal(
                publicId = cleanPublicId,
                timezone = currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> = safeCall {
        api().dashboardCards(surface = surface.apiValue).toDomain()
    }

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanUpdates = updates.validatedDashboardUpdates()
            .getOrElse { return Result.failure(it) }
        return safeCall {
            api().updateDashboardCards(
                request = cleanUpdates.toRequest(),
                surface = surface.apiValue,
            ).toDomain()
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    private fun api(): ApiService {
        val serverUrl = settingsStore.serverUrl()
        require(!serverUrl.isNullOrBlank()) { "账本地址未绑定" }
        val cached = cachedApi
        if (cached != null && cachedServerUrl == serverUrl) {
            return cached
        }
        return apiClient.create(serverUrl) { tokenStore.getToken() }
            .also { service ->
                cachedServerUrl = serverUrl
                cachedApi = service
            }
    }

    private suspend fun <T> safeCall(block: suspend () -> T): Result<T> {
        return try {
            Result.success(withContext(Dispatchers.IO) { block() })
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            Result.failure(RepositoryException(parseHttpError(error)))
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IOException) {
            val serverUrl = settingsStore.serverUrl()
            Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, serverUrl), error)
            Result.failure(RepositoryException(userNetworkMessage(error, serverUrl)))
        } catch (error: IllegalArgumentException) {
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Reports request argument error: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: Exception) {
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Reports request failed: ${error::class.java.name}: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    private fun parseHttpError(error: HttpException): String =
        parseErrorMessage(error.code(), error.response()?.errorBody()?.string())

    private fun parseErrorMessage(statusCode: Int, body: String?): String {
        if (!body.isNullOrBlank()) {
            runCatching { errorAdapter.fromJson(body) }
                .getOrNull()
                ?.let { return backendErrorUserMessage(it.error, it.message) }
        }
        return when (statusCode) {
            401, 403 -> "绑定已失效，请重新绑定账本。"
            404 -> "没有找到目标。"
            else -> "连接出错（$statusCode），请稍后再试。"
        }
    }

    private fun readExportBody(response: Response<okhttp3.ResponseBody>): ByteArray {
        if (!response.isSuccessful) {
            throw RepositoryException(parseErrorMessage(response.code(), response.errorBody()?.string()))
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

private fun GoalDraft.validated(): Result<GoalDraft> {
    return runCatching {
        val cleanName = name.trim()
        require(cleanName.isNotBlank()) { "请输入目标名称。" }
        require(targetAmountCents > 0L) { "目标金额必须大于 0。" }
        copy(
            name = cleanName,
            month = requireMonth(month, "目标月份不正确。"),
            category = category?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
        )
    }.mapError()
}

private fun GoalUpdate.validated(): Result<GoalUpdate> {
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
            category = category?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
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

private fun String?.cleanMonthOrNull(): Result<String?> {
    return runCatching { cleanMonthOrThrow("月份不正确。") }.mapError()
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
