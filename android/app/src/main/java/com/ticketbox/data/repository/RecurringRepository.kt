package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import java.util.TimeZone

interface RecurringQueryActions {
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
    suspend fun candidates(expectedBinding: LogicalSessionBinding): Result<List<RecurringCandidate>>
}

interface RecurringManualMutationActions {
    fun observePendingIntents(): Flow<List<RecurringPendingIntent>> = flowOf(emptyList())
    suspend fun createAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        draft: RecurringItemDraft,
    ): Result<RecurringSaveOutcome>
    suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringSaveOutcome>
}

interface RecurringLifecycleActions {
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
    suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem>
}

interface RecurringActions :
    RecurringQueryActions,
    RecurringManualMutationActions,
    RecurringLifecycleActions

class RecurringRepository(
    private val apiProvider: ApiServiceProvider,
    outbox: OutboxRepository? = null,
    createAdapter: JsonAdapter<RecurringItemCreateRequestDto>? = null,
    updateAdapter: JsonAdapter<RecurringItemUpdateRequestDto>? = null,
) : RecurringActions,
    RecurringManualMutationActions by RecurringMutationClient(
        requestGuard = LedgerRequestGuard(apiProvider),
        errorHandler = recurringErrorHandler(apiProvider),
        canModify = { ledgerRoleCanModify(apiProvider.currentLedgerRole()) },
        outbox = outbox,
        createAdapter = createAdapter,
        updateAdapter = updateAdapter,
    ) {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = recurringErrorHandler(apiProvider)

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

    override suspend fun candidates(
        expectedBinding: LogicalSessionBinding,
    ): Result<List<RecurringCandidate>> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.recurringCandidates(timezone = recurringTimezoneId()).items.map { it.toDomain() }
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

    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.restoreRecurringItem(
                    publicId.trim(),
                    com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                ).toDomain()
            }
        }
}

private fun recurringTimezoneId(): String = TimeZone.getDefault().id

private fun recurringErrorHandler(apiProvider: ApiServiceProvider): NetworkErrorHandler =
    NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Recurring",
        statusMessages = mapOf(404 to "固定支出不存在。"),
    )
