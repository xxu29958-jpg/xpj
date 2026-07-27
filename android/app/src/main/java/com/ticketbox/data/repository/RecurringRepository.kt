package com.ticketbox.data.repository

import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import java.util.TimeZone

interface RecurringActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    suspend fun items(
        status: String? = null,
        includeArchived: Boolean = false,
        month: String? = null,
    ): Result<List<RecurringItem>>
    suspend fun items(
        expectedBinding: LogicalSessionBinding,
        status: String? = null,
        includeArchived: Boolean = false,
        month: String? = null,
    ): Result<List<RecurringItem>>
    suspend fun candidates(): Result<List<RecurringCandidate>>
    suspend fun candidates(expectedBinding: LogicalSessionBinding): Result<List<RecurringCandidate>>
    suspend fun detail(publicId: String, month: String? = null): Result<RecurringItem>
    suspend fun confirmCandidate(
        expectedBinding: LogicalSessionBinding,
        candidate: RecurringCandidate,
        nextExpectedDate: String? = null,
    ): Result<RecurringItem>
    suspend fun pause(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem>
    suspend fun resume(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem>
    suspend fun archive(expectedBinding: LogicalSessionBinding, publicId: String): Result<RecurringItem>
}

class RecurringRepository(
    private val apiProvider: ApiServiceProvider,
) : RecurringActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Recurring",
        statusMessages = mapOf(404 to "固定支出不存在。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        apiProvider.observeActiveLedgerAccess()

    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.recurringItems(
                    status = status?.trim()?.ifBlank { null },
                    includeArchived = includeArchived,
                    month = month?.trim()?.ifBlank { null },
                    timezone = recurringTimezoneId(),
                ).items.map { it.toDomain() }
            }
        }

    override suspend fun items(
        expectedBinding: LogicalSessionBinding,
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.recurringItems(
                    status = status?.trim()?.ifBlank { null },
                    includeArchived = includeArchived,
                    month = month?.trim()?.ifBlank { null },
                    timezone = recurringTimezoneId(),
                ).items.map { it.toDomain() }
            }
        }.onSuccess { items ->
            // Only the unfiltered full-ledger refresh (the Plan overview's)
            // delivers the set the advisor consumes; filtered fetches would
            // fingerprint a different set and flap. Fire-and-forget seam, var
            // per the onConfirmedCommitted precedent (constructor baseline).
            if (status == null && month == null && includeArchived) {
                onFullItemsSnapshot(
                    "n=${items.size};" +
                        "rv=${items.maxOfOrNull(RecurringItem::rowVersion) ?: 0};" +
                        "ua=${items.maxOfOrNull(RecurringItem::updatedAt).orEmpty()}",
                )
            }
        }

    /** Fired with a cheap stable stamp after each unfiltered full-ledger items
     *  refresh. Wired in AppContainer to the budget-advice freshness sink. */
    var onFullItemsSnapshot: (stamp: String) -> Unit = {}

    override suspend fun candidates(): Result<List<RecurringCandidate>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.recurringCandidates(timezone = recurringTimezoneId()).items.map { it.toDomain() }
            }
        }

    override suspend fun candidates(
        expectedBinding: LogicalSessionBinding,
    ): Result<List<RecurringCandidate>> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.recurringCandidates(timezone = recurringTimezoneId()).items.map { it.toDomain() }
            }
        }

    override suspend fun detail(publicId: String, month: String?): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            ledgerRequestGuard.guardedCall { api ->
                api.recurringItem(
                    publicId = publicId.trim(),
                    month = month?.trim()?.ifBlank { null },
                    timezone = recurringTimezoneId(),
                ).toDomain()
            }
        }

    override suspend fun confirmCandidate(
        expectedBinding: LogicalSessionBinding,
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.confirmRecurringCandidate(
                    request = candidate.toConfirmRequest(nextExpectedDate = nextExpectedDate?.trim()?.ifBlank { null }),
                    timezone = recurringTimezoneId(),
                ).toDomain()
            }
        }

    override suspend fun pause(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.pauseRecurringItem(
                    publicId.trim(),
                    com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                ).toDomain()
            }
        }

    override suspend fun resume(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.resumeRecurringItem(
                    publicId.trim(),
                    com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                ).toDomain()
            }
        }

    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.archiveRecurringItem(publicId.trim()).toDomain()
            }
        }
}

private fun recurringTimezoneId(): String = TimeZone.getDefault().id
