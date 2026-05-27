package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.JsonAdapter
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import okhttp3.ResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.time.Instant
import java.util.TimeZone

internal class ExpenseRepositoryCore(
    val expenseDao: ExpenseDao,
    val settingsStore: TicketboxSettingsStore,
    val tokenStore: SessionTokenStore,
    val deviceNameProvider: () -> String,
    val apiProvider: ApiServiceProvider,
    val sessionCoordinator: LocalLedgerSessionCoordinator,
    /**
     * ADR-0038 PR-2g.3: outbox surface for the call sites that
     * route through it on network failure. ``null`` keeps every
     * pre-existing test that didn't wire the outbox at the old
     * behaviour — the IOException catch in
     * [ExpensePendingRepository.updateExpense] no-ops when either
     * the outbox OR the matching payload adapter is missing.
     */
    val outbox: OutboxRepository? = null,
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>? = null,
) {
    val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Repository",
        statusMessages = mapOf(
            404 to "账单不存在。",
            413 to "上传文件超过大小限制。",
        ),
    )
    val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)

    fun currentTimezoneId(): String = TimeZone.getDefault().id

    fun currentLedgerRole(): String? = settingsStore.role()

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    fun currentActiveLedgerId(): String? = settingsStore.activeLedgerId()

    fun api(serverUrl: String, token: String): ApiService =
        apiProvider.temporary(serverUrl, token)

    fun readProtectedImage(response: Response<ResponseBody>): ProtectedImage {
        if (!response.isSuccessful) {
            val errorBody = response.errorBody()?.string()
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Protected image request failed: code=${response.code()} body=${errorBody?.take(160)}")
            }
            throw RepositoryException(errorHandler.parseErrorMessage(response.code(), errorBody))
        }
        val body = response.body() ?: throw RepositoryException("图片为空。")
        val contentType = body.contentType()?.toString()
        val bytes = body.use { it.bytes() }
        if (bytes.isEmpty()) {
            throw RepositoryException("图片为空。")
        }
        if (BuildConfig.DEBUG) {
            Log.d(NETWORK_LOG_TAG, "Protected image loaded: contentType=$contentType bytes=${bytes.size}")
        }
        return ProtectedImage(bytes = bytes, contentType = contentType)
    }

    fun diagnosticErrorMessage(error: Throwable): String {
        return when (error) {
            is HttpException -> errorHandler.parseHttpError(error)
            is IOException -> {
                Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, settingsStore.serverUrl()), error)
                userNetworkMessage(error, settingsStore.serverUrl())
            }
            is RepositoryException -> error.message ?: "操作失败。"
            is IllegalArgumentException -> error.message ?: "请求参数不正确。"
            else -> error.message ?: "操作失败。"
        }
    }

    suspend fun persistAuthCheck(
        check: AuthCheckDto,
        expectedSnapshot: LedgerSessionSnapshot,
    ) {
        val expectedLedgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() }
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            identity = LedgerSessionIdentity(
                accountName = check.accountName,
                ledgerId = check.ledgerId,
                ledgerName = check.ledgerName,
                deviceName = check.deviceName,
                role = check.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
            cacheInvalidation = if (check.ledgerId != expectedLedgerId) {
                LedgerCacheInvalidation.TargetLedger
            } else {
                LedgerCacheInvalidation.None
            },
        )
    }

    suspend fun persistServerSettings(
        settings: ServerSettingsDto,
        expectedSnapshot: LedgerSessionSnapshot,
        expectedLedgerId: String?,
    ) {
        val expected = expectedLedgerId ?: return
        val ledgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() } ?: return
        if (ledgerId != expected) return
        if (settings.ledgerId != null && settings.ledgerId != expected) return
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            identity = LedgerSessionIdentity(
                accountName = settings.accountName,
                ledgerId = ledgerId,
                ledgerName = settings.ledgerName,
                deviceName = settings.deviceName,
                role = settings.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
        )
    }

    suspend fun cacheIfConfirmed(dto: ExpenseDto, ledgerIdAtRequest: String): ExpenseDto {
        if (dto.status == "confirmed" && activeLedgerIdOrLegacy() == ledgerIdAtRequest) {
            expenseDao.upsertByServerIdForLedger(ledgerIdAtRequest, dto.toEntity(ledgerIdAtRequest))
        }
        return dto
    }

    suspend fun syncConfirmedFromService(
        service: ApiService,
        ledgerIdAtRequest: String = activeLedgerIdOrLegacy(),
        month: String? = null,
        category: String? = null,
        tag: String? = null,
        replaceCache: Boolean = false,
        recordSyncTimestamp: Boolean = true,
    ): List<Expense> {
        val isFullLedgerSync = month == null && category == null && tag == null
        val collectedDtos = mutableListOf<ExpenseDto>()
        var page = 1
        val pageSize = 50
        var total = Int.MAX_VALUE
        do {
            if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
                return emptyList()
            }
            val response = service.confirmedExpenses(
                page = page,
                pageSize = pageSize,
                month = month,
                category = category,
                tag = tag,
                timezone = currentTimezoneId(),
            )
            total = response.total
            collectedDtos += response.items
            if (response.items.isEmpty() && collectedDtos.size < total) {
                throw RepositoryException("账本同步分页异常，请稍后再试。")
            }
            page += 1
        } while (collectedDtos.size < total)

        val collected = collectedDtos.map { it.toDomain() }
        if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
            return emptyList()
        }

        val entities = collectedDtos.map { it.toEntity(ledgerIdAtRequest) }
        expenseDao.applyConfirmedSyncForLedger(
            ledgerId = ledgerIdAtRequest,
            expenses = entities,
            replaceCache = replaceCache,
            pruneMissing = !replaceCache && isFullLedgerSync,
        )
        if (recordSyncTimestamp && isFullLedgerSync) {
            settingsStore.saveLastConfirmedSyncAtForLedger(ledgerIdAtRequest, Instant.now().toString())
        }
        return collected
    }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    fun observeConfirmed(): Flow<List<Expense>> =
        settingsStore.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: LedgerRequestGuard.LEGACY_LEDGER_ID }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    fun activeLedgerIdOrLegacy(): String = ledgerRequestGuard.activeLedgerIdOrLegacy()

    suspend fun clearLocalCache() {
        expenseDao.clear()
        settingsStore.clearLastConfirmedSyncAt()
    }

    suspend fun clearBinding() {
        // ADR-0038 PR-2g.3 codex round-9 P1 (round-10 follow-up):
        // outbox.clearAll() MUST run BEFORE clearing the apiProvider
        // / settings / token. clearAll() bumps the
        // [OutboxRepository] session-boundary epoch; the drain
        // engine's post-claim check reads that epoch to decide
        // whether to skip a dispatch. If we clear the API binding
        // first, a concurrent drain that has already passed the
        // epoch check (epoch still old) would resolve apiProvider()
        // inside dispatch under whatever the user binds next →
        // wrong-session replay. Order:
        //   1) outbox.clearAll  (epoch bumps, queue wiped)
        //   2) apiProvider/settings/token cleared
        // After step 1, no new drain can pass the post-claim check
        // for an old row. The drains in flight that already passed
        // it dispatch under the still-old credentials (step 2 hasn't
        // run yet) — old-session in-flight, not wrong-session
        // replay. Acceptable until Room v10 binding columns.
        outbox?.clearAll()
        apiProvider.clear()
        expenseDao.clear()
        settingsStore.clear()
        tokenStore.clear()
    }

    companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }
}
