package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.CategoryReferenceDto
import com.ticketbox.domain.model.CategoryReference
import com.ticketbox.domain.model.CategoryReferenceKind
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
    private val serverUrlProvider: () -> String?,
    private val context: String,
    private val statusMessages: Map<Int, String> = emptyMap(),
) {
    private val errorAdapter: JsonAdapter<ErrorDto> by lazy {
        MOSHI.adapter(ErrorDto::class.java)
    }

    suspend fun <T> safeCall(
        serverUrlHint: String? = null,
        block: suspend () -> T,
    ): Result<T> {
        return try {
            Result.success(withContext(Dispatchers.IO) { block() })
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            Result.failure(httpFailure(error))
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IOException) {
            val serverUrl = serverUrlHint ?: serverUrlProvider()
            logNetworkWarning("operation=$context ${networkDiagnosticMessage(error, serverUrl)}", error)
            Result.failure(RepositoryException(userNetworkMessage(error, serverUrl), cause = error))
        } catch (error: IllegalArgumentException) {
            logNetworkWarning("operation=$context request argument error", error)
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。", cause = error))
        } catch (error: Exception) {
            logNetworkWarning("operation=$context request failed", error)
            Result.failure(RepositoryException(error.message ?: "操作失败。", cause = error))
        }
    }

    fun parseHttpError(error: HttpException): ParsedError {
        val body = try {
            error.response()?.errorBody()?.string()
        } catch (readError: IOException) {
            logNetworkWarning("operation=$context HTTP error body read failed", readError)
            null
        }
        return parseErrorMessage(error.code(), body, error.response()?.headers()?.get("X-Request-ID"), error)
    }

    fun httpFailure(error: HttpException): RepositoryException {
        val parsed = parseHttpError(error)
        return RepositoryException(parsed.message, parsed.errorCode, conflict = parsed.conflict,
            httpStatusCode = error.code(), cause = error, requestId = parsed.requestId)
    }

    fun parseErrorMessage(
        statusCode: Int,
        body: String?,
        headerRequestId: String? = null,
        cause: Throwable? = null,
    ): ParsedError {
        val dto = body?.takeIf { it.isNotBlank() }?.let { runCatching { errorAdapter.fromJson(it) }.getOrNull() }
        val bodyId = safeRequestId(dto?.requestId)
        val headerId = safeRequestId(headerRequestId)
        // The envelope identifies the decoded error; a proxy/header disagreement stays visible.
        val requestId = bodyId ?: headerId
        val parsed = decodedError(statusCode, dto).copy(requestId = requestId)
        val code = parsed.errorCode?.takeIf { Regex("[a-z][a-z0-9_]{0,79}").matches(it) } ?: "unavailable"
        val conflict = if (bodyId != null && headerId != null && bodyId != headerId) {
            " request_id_mismatch=true header_request_id=$headerId"
        } else ""
        logNetworkWarning("operation=$context HTTP status=$statusCode code=$code request_id=${requestId ?: "absent"}$conflict", cause)
        return parsed
    }

    private fun decodedError(statusCode: Int, dto: ErrorDto?): ParsedError {
        dto?.let {
            return ParsedError(
                backendErrorUserMessage(it.error, it.message.orEmpty()),
                it.error.trim(),
                conflict = it.toConflictDetails(),
                expenseId = it.expenseId,
                missingExchangeRate = it.homeCurrencyCode?.let { home ->
                    com.ticketbox.data.remote.dto.MissingExchangeRateDto(it.currencyCode, home, it.rateDate)
                },
            )
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
        val expenseId: Long? = null,
        val missingExchangeRate: com.ticketbox.data.remote.dto.MissingExchangeRateDto? = null,
        val requestId: String? = null,
    ) {
        val conflictTagPublicId: String? get() = conflict.tag.publicId
        val conflictTagRowVersion: Long? get() = conflict.tag.rowVersion
        val conflictMerchantPublicId: String? get() = conflict.merchant.publicId
        val conflictMerchantRowVersion: Long? get() = conflict.merchant.rowVersion
        val conflictAliasPublicId: String? get() = conflict.alias.publicId
        val conflictAliasRowVersion: Long? get() = conflict.alias.rowVersion
        val conflictRecurringPublicId: String? get() = conflict.recurring.publicId
        val conflictRecurringStatus: String? get() = conflict.recurring.status
    }

    private companion object {
        // LOG_TAG used to live here; codex round-9 moved Log.w
        // calls into [logNetworkWarning] which owns the tag.
        val MOSHI: Moshi by lazy {
            Moshi.Builder()
                .add(KotlinJsonAdapterFactory())
                .build()
        }
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
        recurring = RecurringConflictDetails(
            publicId = resourcePublicId,
            status = status,
        ),
        categoryReferences = categoryReferences.mapNotNull(CategoryReferenceDto::toDomain),
    )

private fun CategoryReferenceDto.toDomain(): CategoryReference? {
    val target = id?.takeIf { it.isNotBlank() } ?: return null
    val title = label?.takeIf { it.isNotBlank() } ?: return null
    val type = when (kind) {
        "rule" -> CategoryReferenceKind.Rule.takeIf { target.toLongOrNull()?.let { id -> id > 0 } == true }
        "budget" -> CategoryReferenceKind.Budget.takeIf { runCatching { java.time.YearMonth.parse(target) }.isSuccess }
        "goal" -> CategoryReferenceKind.SpendingGoal
        else -> null
    } ?: return null
    return CategoryReference(type, target, title)
}
