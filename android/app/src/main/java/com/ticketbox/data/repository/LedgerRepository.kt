package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.IOException

/**
 * Repository for v0.4-alpha1 multi-ledger management.
 *
 * Owns the small surface that is **not** about expenses: listing the
 * ledgers an account belongs to, creating a new ledger, and switching
 * the active session token to a different ledger.
 *
 * Ownership is decided server-side; this repository never persists or
 * trusts a client-supplied role beyond display purposes.
 */
class LedgerRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val expenseDao: ExpenseDao,
) {
    private val moshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
    private val errorAdapter = moshi.adapter(ErrorDto::class.java)
    private val ledgerListType = Types.newParameterizedType(
        List::class.java,
        LedgerDto::class.java,
    )
    private val ledgerListAdapter = moshi.adapter<List<LedgerDto>>(ledgerListType)

    private fun api() = apiClient.create(
        requireNotNull(settingsStore.serverUrl()) { "账本地址未绑定" },
    ) { tokenStore.getToken() }

    suspend fun refreshLedgers(): Result<List<LedgerSummary>> = wrap {
        val response = api().listLedgers()
        val summaries = response.ledgers.map { it.toSummary() }
        settingsStore.saveAvailableLedgersJson(ledgerListAdapter.toJson(response.ledgers))
        summaries
    }

    fun cachedLedgers(): List<LedgerSummary> {
        val raw = settingsStore.availableLedgersJson()?.takeIf { it.isNotBlank() }
            ?: return emptyList()
        return runCatching {
            ledgerListAdapter.fromJson(raw)?.map { it.toSummary() } ?: emptyList()
        }.getOrElse { emptyList() }
    }

    fun activeLedgerId(): String? = settingsStore.activeLedgerId()

    suspend fun createLedger(name: String): Result<LedgerSummary> = wrap {
        val cleanName = name.trim()
        require(cleanName.isNotEmpty()) { "请填写账本名称。" }
        require(cleanName.length <= LEDGER_NAME_MAX_LEN) { "账本名称最多 60 个字。" }
        val dto = api().createLedger(LedgerCreateRequestDto(name = cleanName))
        // Refresh the cache so the new ledger appears in the picker.
        runCatching { refreshLedgers() }
        dto.toSummary()
    }

    /**
     * Switch the active session token to [ledgerId]. The previous token is
     * revoked server-side, so we must persist the freshly issued token
     * before doing any post-switch network calls. The local confirmed-cache
     * for the *new* ledger is wiped so the next sync repopulates it
     * exclusively with rows belonging to [ledgerId].
     */
    suspend fun switchLedger(ledgerId: String): Result<LedgerSummary> = wrap {
        val response = api().switchLedger(ledgerId)
        // Persist the new token *first*; the old one is now revoked.
        tokenStore.saveToken(response.sessionToken)
        settingsStore.saveActiveLedger(
            ledgerId = response.ledger.ledgerId,
            ledgerName = response.ledger.name,
        )
        // Wipe stale cache for the target ledger so the upcoming sync
        // produces a clean view.
        expenseDao.clearForLedger(response.ledger.ledgerId)
        response.ledger.toSummary()
    }

    private suspend fun <T> wrap(block: suspend () -> T): Result<T> {
        return try {
            Result.success(withContext(Dispatchers.IO) { block() })
        } catch (error: HttpException) {
            val body = error.response()?.errorBody()?.string()
            val parsed = body
                ?.let { runCatching { errorAdapter.fromJson(it) }.getOrNull() }
            val message = parsed
                ?.let { backendErrorUserMessage(it.error, it.message) }
                ?: defaultHttpMessage(error.code())
            Result.failure(RepositoryException(message))
        } catch (error: IOException) {
            Result.failure(RepositoryException("网络连接失败，请检查电脑端服务。"))
        } catch (error: IllegalArgumentException) {
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        }
    }

    private fun defaultHttpMessage(code: Int): String = when (code) {
        401, 403 -> "绑定已失效，请重新绑定账本。"
        404 -> "账本不存在。"
        else -> "操作失败（$code），请稍后再试。"
    }

    private companion object {
        const val LEDGER_NAME_MAX_LEN = 60
    }
}

private fun LedgerDto.toSummary(): LedgerSummary = LedgerSummary(
    ledgerId = ledgerId,
    name = name,
    role = role,
    isDefault = isDefault,
    createdAt = createdAt,
    archivedAt = archivedAt,
)
