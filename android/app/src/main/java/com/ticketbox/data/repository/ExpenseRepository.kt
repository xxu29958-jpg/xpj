package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.security.SecureTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.time.Instant
import kotlin.system.measureTimeMillis
import okhttp3.ResponseBody

class RepositoryException(message: String) : RuntimeException(message)

class ExpenseRepository(
    private val expenseDao: ExpenseDao,
    private val apiClient: ApiClient,
    private val settingsStore: LocalSettingsStore,
    private val tokenStore: SecureTokenStore,
) {
    private companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }

    private val errorAdapter = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
        .adapter(ErrorDto::class.java)

    private fun api(serverUrlOverride: String? = null, tokenOverride: String? = null): ApiService {
        val serverUrl = serverUrlOverride ?: settingsStore.serverUrl()
        require(!serverUrl.isNullOrBlank()) { "服务器地址未绑定" }
        return apiClient.create(serverUrl) { tokenOverride ?: tokenStore.getToken() }
    }

    private suspend fun <T> safeCall(serverUrlHint: String? = null, block: suspend () -> T): Result<T> {
        return try {
            Result.success(block())
        } catch (error: HttpException) {
            Result.failure(RepositoryException(parseHttpError(error)))
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IOException) {
            val serverUrl = serverUrlHint ?: settingsStore.serverUrl()
            Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, serverUrl), error)
            Result.failure(RepositoryException(userNetworkMessage(error, serverUrl)))
        } catch (error: IllegalArgumentException) {
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: Exception) {
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    private fun parseHttpError(error: HttpException): String {
        return parseErrorMessage(error.code(), error.response()?.errorBody()?.string())
    }

    private fun parseErrorMessage(statusCode: Int, body: String?): String {
        if (!body.isNullOrBlank()) {
            runCatching { errorAdapter.fromJson(body) }
                .getOrNull()
                ?.message
                ?.takeIf { it.isNotBlank() }
                ?.let { return it }
        }
        return when (statusCode) {
            401, 403 -> "Token 无效。"
            404 -> "账单不存在。"
            413 -> "上传文件超过大小限制。"
            else -> "服务器返回错误 $statusCode。"
        }
    }

    private fun readProtectedImage(response: Response<ResponseBody>): ProtectedImage {
        if (!response.isSuccessful) {
            throw RepositoryException(parseErrorMessage(response.code(), response.errorBody()?.string()))
        }
        val body = response.body() ?: throw RepositoryException("图片为空。")
        val contentType = body.contentType()?.toString()
        val bytes = body.use { it.bytes() }
        if (bytes.isEmpty()) {
            throw RepositoryException("图片为空。")
        }
        return ProtectedImage(bytes = bytes, contentType = contentType)
    }

    private fun diagnosticErrorMessage(error: Throwable): String {
        return when (error) {
            is HttpException -> parseHttpError(error)
            is IOException -> {
                Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, settingsStore.serverUrl()), error)
                userNetworkMessage(error, settingsStore.serverUrl())
            }
            is RepositoryException -> error.message ?: "操作失败。"
            is IllegalArgumentException -> error.message ?: "请求参数不正确。"
            else -> error.message ?: "操作失败。"
        }
    }

    suspend fun bindServer(serverUrl: String, appToken: String): Result<Unit> {
        val normalized = serverUrl.trim().trimEnd('/')
        require(normalized.isNotBlank()) { "请输入服务器地址。" }
        require(!isLocalOnlyServerUrl(normalized)) { "请填写公网服务器地址。" }
        require(appToken.isNotBlank()) { "请输入 App Token。" }
        return safeCall(serverUrlHint = normalized) {
            api(normalized, appToken).checkAuth()
            settingsStore.saveServerUrl(normalized)
            tokenStore.saveToken(appToken)
            settingsStore.markUnlocked()
        }
    }

    suspend fun testConnection(): Result<Unit> = safeCall {
        api().checkAuth()
    }

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> = safeCall {
        val service = api()
        val checks = mutableListOf<DiagnosticCheck>()

        suspend fun record(
            name: String,
            successDetail: String,
            block: suspend () -> Unit,
        ) {
            var failure: Throwable? = null
            val elapsedMs = measureTimeMillis {
                try {
                    block()
                } catch (error: Throwable) {
                    failure = error
                }
            }
            val error = failure
            checks += if (error == null) {
                DiagnosticCheck(
                    name = name,
                    status = DiagnosticStatus.Pass,
                    detail = successDetail,
                    elapsedMs = elapsedMs,
                )
            } else {
                DiagnosticCheck(
                    name = name,
                    status = DiagnosticStatus.Fail,
                    detail = diagnosticErrorMessage(error),
                    elapsedMs = elapsedMs,
                )
            }
        }

        var pending = emptyList<Expense>()

        record("身份验证", "访问凭证有效") {
            service.checkAuth()
        }
        record("服务器状态", "状态接口可用") {
            service.serverSettings()
        }
        record("待确认账单", "可以读取待确认账单") {
            pending = service.pendingExpenses().map { it.toDomain() }
        }
        record("已确认账本", "可以同步已确认账单") {
            service.confirmedExpenses(page = 1, pageSize = 1)
        }
        record("月度统计", "可以读取月度统计") {
            service.monthlyStats(null)
        }
        record("分类与月份", "可以读取分类和月份") {
            service.categories()
            service.months()
        }
        record("疑似重复", "可以读取疑似重复账单") {
            service.duplicates()
        }

        val imageCandidate = pending.firstOrNull { it.imagePath != null || it.thumbnailPath != null }
        if (imageCandidate == null) {
            checks += DiagnosticCheck(
                name = "受保护图片",
                status = DiagnosticStatus.Warn,
                detail = "暂无待确认截图，未检查图片接口。",
                elapsedMs = 0,
            )
        } else {
            record("受保护图片", "缩略图接口可用") {
                readProtectedImage(service.expenseThumbnail(imageCandidate.id))
            }
        }

        ConnectionDiagnostics(checks)
    }

    suspend fun fetchPending(): Result<List<Expense>> = safeCall {
        api().pendingExpenses().map { it.toDomain() }
    }

    suspend fun updateExpense(id: Long, draft: ExpenseDraft): Result<Expense> = safeCall {
        val dto = api().updateExpense(id, draft.toRequest())
        if (dto.status == "confirmed") {
            expenseDao.upsertByServerId(dto.toEntity())
        }
        dto.toDomain()
    }

    suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = safeCall {
        require(draft.amountCents != null) { "请先填写金额。" }
        val dto = api().createManualExpense(draft.toRequest())
        if (dto.status == "confirmed") {
            expenseDao.upsertByServerId(dto.toEntity())
        }
        dto.toDomain()
    }

    suspend fun confirmExpense(id: Long): Result<Expense> = safeCall {
        val dto = api().confirmExpense(id)
        if (dto.status == "confirmed") {
            expenseDao.upsertByServerId(dto.toEntity())
        }
        dto.toDomain()
    }

    suspend fun rejectExpense(id: Long): Result<Expense> = safeCall {
        api().rejectExpense(id).toDomain()
    }

    suspend fun retryOcr(id: Long): Result<Expense> = safeCall {
        api().retryOcr(id).toDomain()
    }

    suspend fun markNotDuplicate(id: Long): Result<Expense> = safeCall {
        api().markNotDuplicate(id).toDomain()
    }

    suspend fun fetchDuplicates(): Result<List<Expense>> = safeCall {
        api().duplicates().map { it.toDomain() }
    }

    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = safeCall {
        readProtectedImage(api().expenseThumbnail(id))
    }

    suspend fun fetchImage(id: Long): Result<ProtectedImage> = safeCall {
        readProtectedImage(api().expenseImage(id))
    }

    suspend fun syncConfirmed(month: String? = null, category: String? = null): Result<List<Expense>> = safeCall {
        val collected = mutableListOf<Expense>()
        var page = 1
        val pageSize = 50
        var total = Int.MAX_VALUE
        do {
            val response = api().confirmedExpenses(page = page, pageSize = pageSize, month = month, category = category)
            total = response.total
            expenseDao.upsertAllByServerId(response.items.map { it.toEntity() })
            collected += response.items.map { it.toDomain() }
            page += 1
        } while (collected.size < total)
        settingsStore.saveLastConfirmedSyncAt(Instant.now().toString())
        collected
    }

    suspend fun categories(): Result<List<String>> = safeCall {
        api().categories().items
    }

    suspend fun months(): Result<List<String>> = safeCall {
        api().months().items
    }

    suspend fun exportConfirmedCsv(month: String? = null, category: String? = null): Result<CsvExport> = safeCall {
        val cleanMonth = month?.trim()?.ifBlank { null }
        val cleanCategory = category?.trim()?.ifBlank { null }
        val response = api().exportCsv(month = cleanMonth, category = cleanCategory)
        if (!response.isSuccessful) {
            throw RepositoryException(parseErrorMessage(response.code(), response.errorBody()?.string()))
        }
        val body = response.body() ?: throw RepositoryException("导出内容为空。")
        val fileName = buildString {
            append("ticketbox-expenses")
            if (cleanMonth != null) append("-").append(cleanMonth)
            append(".csv")
        }
        CsvExport(fileName = fileName, bytes = body.use { it.bytes() })
    }

    fun observeConfirmed(): Flow<List<Expense>> {
        return expenseDao.observeConfirmed().map { list -> list.map { it.toDomain() } }
    }

    suspend fun monthlyStats(month: String? = null): Result<MonthlyStats> = safeCall {
        api().monthlyStats(month).toDomain()
    }

    suspend fun lifestyleStats(month: String? = null): Result<LifestyleStats> = safeCall {
        api().lifestyleStats(month).toDomain()
    }

    suspend fun categoryRules(): Result<List<CategoryRule>> = safeCall {
        api().categoryRules().map { it.toDomain() }
    }

    suspend fun createCategoryRule(keyword: String, category: String, priority: Int): Result<CategoryRule> = safeCall {
        val cleanKeyword = keyword.trim()
        val cleanCategory = category.trim()
        require(cleanKeyword.isNotBlank()) { "请输入关键词。" }
        require(cleanCategory.isNotBlank()) { "请输入分类。" }
        api().createCategoryRule(
            CategoryRuleRequest(
                keyword = cleanKeyword,
                category = cleanCategory,
                enabled = true,
                priority = priority,
            ),
        ).toDomain()
    }

    suspend fun updateCategoryRule(
        id: Long,
        keyword: String? = null,
        category: String? = null,
        enabled: Boolean? = null,
        priority: Int? = null,
    ): Result<CategoryRule> = safeCall {
        api().updateCategoryRule(
            id,
            CategoryRuleRequest(
                keyword = keyword,
                category = category,
                enabled = enabled,
                priority = priority,
            ),
        ).toDomain()
    }

    suspend fun deleteCategoryRule(id: Long): Result<Unit> = safeCall {
        api().deleteCategoryRule(id)
        Unit
    }

    suspend fun serverSettings(): Result<ServerSettings> = safeCall {
        api().serverSettings().toDomain()
    }

    fun monthlyBudgetCents(): Long? = settingsStore.monthlyBudgetCents()

    fun lastConfirmedSyncAt(): String? = settingsStore.lastConfirmedSyncAt()

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        settingsStore.saveMonthlyBudgetCents(amountCents)
    }

    suspend fun clearLocalCache() {
        expenseDao.clear()
        settingsStore.clearLastConfirmedSyncAt()
    }

    fun clearBinding() {
        settingsStore.clear()
        tokenStore.clear()
    }
}
