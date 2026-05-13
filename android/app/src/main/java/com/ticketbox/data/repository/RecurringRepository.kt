package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.IOException
import java.util.TimeZone

class RecurringRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
) {
    private companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }

    private val errorAdapter = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
        .adapter(ErrorDto::class.java)

    private var cachedServerUrl: String? = null
    private var cachedApi: ApiService? = null

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
                Log.w(NETWORK_LOG_TAG, "Recurring request argument error: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: Exception) {
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Recurring request failed: ${error::class.java.name}: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    private fun parseHttpError(error: HttpException): String {
        val body = error.response()?.errorBody()?.string()
        if (!body.isNullOrBlank()) {
            runCatching { errorAdapter.fromJson(body) }
                .getOrNull()
                ?.let { return backendErrorUserMessage(it.error, it.message) }
        }
        return when (error.code()) {
            401, 403 -> "绑定已失效，请重新绑定账本。"
            404 -> "固定支出不存在。"
            else -> "连接出错（${error.code()}），请稍后再试。"
        }
    }

    suspend fun items(
        status: String? = null,
        includeArchived: Boolean = false,
        month: String? = null,
    ): Result<List<RecurringItem>> =
        safeCall {
            api().recurringItems(
                status = status?.trim()?.ifBlank { null },
                includeArchived = includeArchived,
                month = month?.trim()?.ifBlank { null },
                timezone = currentTimezoneId(),
            ).items.map { it.toDomain() }
        }

    suspend fun detail(publicId: String, month: String? = null): Result<RecurringItem> = safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().recurringItem(
            publicId = publicId.trim(),
            month = month?.trim()?.ifBlank { null },
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String? = null,
    ): Result<RecurringItem> = safeCall {
        api().confirmRecurringCandidate(
            request = candidate.toConfirmRequest(nextExpectedDate = nextExpectedDate?.trim()?.ifBlank { null }),
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    suspend fun pause(publicId: String): Result<RecurringItem> = safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().pauseRecurringItem(publicId.trim()).toDomain()
    }

    suspend fun resume(publicId: String): Result<RecurringItem> = safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().resumeRecurringItem(publicId.trim()).toDomain()
    }

    suspend fun archive(publicId: String): Result<RecurringItem> = safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().archiveRecurringItem(publicId.trim()).toDomain()
    }
}
