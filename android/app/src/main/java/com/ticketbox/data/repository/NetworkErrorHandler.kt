package com.ticketbox.data.repository

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
            val parsed = parseHttpError(error)
            Result.failure(
                RepositoryException(
                    parsed.message,
                    parsed.errorCode,
                    conflict = parsed.conflict,
                )
            )
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IOException) {
            val serverUrl = serverUrlHint ?: settingsStore.serverUrl()
            // codex round-9 follow-up: route through
            // [logNetworkWarning] (catches the android.util.Log
            // stub exception in pure-JVM unit tests). Letting Log.w
            // throw here broke ExpensePendingRepositoryOutboxFallbackTest's
            // ability to assert Result.failure on the IOException
            // path — that's a real contract (chained confirm
            // depends on it failing) we need to keep testable.
            logNetworkWarning(networkDiagnosticMessage(error, serverUrl), error)
            Result.failure(RepositoryException(userNetworkMessage(error, serverUrl)))
        } catch (error: IllegalArgumentException) {
            if (BuildConfig.DEBUG) {
                logNetworkWarning("$context request argument error: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: Exception) {
            if (BuildConfig.DEBUG) {
                logNetworkWarning("$context request failed: ${error::class.java.name}: ${error.message}", error)
            }
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    fun parseHttpError(error: HttpException): ParsedError =
        parseErrorMessage(error.code(), error.response()?.errorBody()?.string())

    fun parseErrorMessage(statusCode: Int, body: String?): ParsedError {
        if (!body.isNullOrBlank()) {
            runCatching { errorAdapter.fromJson(body) }
                .getOrNull()
                ?.let {
                    return ParsedError(
                        backendErrorUserMessage(it.error, it.message),
                        it.error.trim(),
                        conflict = it.toConflictDetails(),
                    )
                }
        }
        statusMessages[statusCode]?.let { return ParsedError(it, errorCode = null) }
        val fallback = when (statusCode) {
            401, 403 -> "绑定已失效，请重新绑定账本。"
            else -> "现在连不上，稍后再试。"
        }
        return ParsedError(fallback, errorCode = null)
    }

    /** Decoded backend error: localized user-facing [message] + machine-readable
     *  [errorCode], plus the optional ADR-0043 `tag_conflict` merge hint. */
    data class ParsedError(
        val message: String,
        val errorCode: String?,
        val conflict: RepositoryConflictDetails = RepositoryConflictDetails(),
    ) {
        val conflictTagPublicId: String? get() = conflict.tag.publicId
        val conflictTagRowVersion: Long? get() = conflict.tag.rowVersion
        val conflictMerchantPublicId: String? get() = conflict.merchant.publicId
        val conflictMerchantRowVersion: Long? get() = conflict.merchant.rowVersion
        val conflictAliasPublicId: String? get() = conflict.alias.publicId
        val conflictAliasRowVersion: Long? get() = conflict.alias.rowVersion
    }

    private companion object {
        // LOG_TAG used to live here; codex round-9 moved Log.w
        // calls into [logNetworkWarning] which owns the tag.
        val MOSHI: Moshi = Moshi.Builder()
            .add(KotlinJsonAdapterFactory())
            .build()
    }
}

private fun ErrorDto.toConflictDetails(): RepositoryConflictDetails =
    RepositoryConflictDetails(
        tag = TagConflictDetails(
            publicId = conflictTagPublicId,
            rowVersion = conflictTagRowVersion,
        ),
        merchant = MerchantConflictDetails(
            publicId = conflictMerchantPublicId,
            rowVersion = conflictMerchantRowVersion,
            displayName = conflictMerchantDisplayName,
            status = conflictMerchantStatus,
            deleted = conflictMerchantDeleted,
        ),
        alias = AliasConflictDetails(
            publicId = conflictAliasPublicId,
            rowVersion = conflictAliasRowVersion,
            enabled = conflictAliasEnabled,
            deleted = conflictAliasDeleted,
        ),
    )
