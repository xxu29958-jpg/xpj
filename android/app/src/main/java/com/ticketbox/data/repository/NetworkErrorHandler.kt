package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.dto.ErrorDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.IOException

/**
 * Shared safeCall / HTTP error mapping for repositories.
 *
 * Each repository previously duplicated this logic with only the log context
 * label and the 404 fallback message changing. This class is configured per
 * repository via [context] (used in log messages) and [statusMessages]
 * (custom mappings for specific HTTP codes, e.g. 404 → "账单不存在。").
 *
 * The 401/403 fallback is always "绑定已失效，请重新绑定账本。" because that
 * is the same domain rule across all callers.
 */
internal class NetworkErrorHandler(
    private val settingsStore: TicketboxSettingsStore,
    private val context: String,
    private val statusMessages: Map<Int, String> = emptyMap(),
) {
    private val errorAdapter: JsonAdapter<ErrorDto> = MOSHI.adapter(ErrorDto::class.java)

    suspend fun <T> safeCall(
        serverUrlHint: String? = null,
        block: suspend () -> T,
    ): Result<T> {
        return try {
            Result.success(withContext(Dispatchers.IO) { block() })
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            Result.failure(RepositoryException(parseHttpError(error)))
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IOException) {
            val serverUrl = serverUrlHint ?: settingsStore.serverUrl()
            Log.w(LOG_TAG, networkDiagnosticMessage(error, serverUrl), error)
            Result.failure(RepositoryException(userNetworkMessage(error, serverUrl)))
        } catch (error: IllegalArgumentException) {
            if (BuildConfig.DEBUG) {
                Log.w(LOG_TAG, "$context request argument error: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: Exception) {
            if (BuildConfig.DEBUG) {
                Log.w(LOG_TAG, "$context request failed: ${error::class.java.name}: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    fun parseHttpError(error: HttpException): String =
        parseErrorMessage(error.code(), error.response()?.errorBody()?.string())

    fun parseErrorMessage(statusCode: Int, body: String?): String {
        if (!body.isNullOrBlank()) {
            runCatching { errorAdapter.fromJson(body) }
                .getOrNull()
                ?.let { return backendErrorUserMessage(it.error, it.message) }
        }
        statusMessages[statusCode]?.let { return it }
        return when (statusCode) {
            401, 403 -> "绑定已失效，请重新绑定账本。"
            else -> "连接出错（$statusCode），请稍后再试。"
        }
    }

    private companion object {
        const val LOG_TAG = "TicketboxNetwork"
        val MOSHI: Moshi = Moshi.Builder()
            .add(KotlinJsonAdapterFactory())
            .build()
    }
}
