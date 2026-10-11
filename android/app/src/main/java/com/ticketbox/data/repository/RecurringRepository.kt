package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import java.util.TimeZone

interface RecurringQueryActions {
    val readAccessDenials: Flow<SnapshotAccessDenial>
    suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?):
        Result<ReadSnapshot<com.ticketbox.data.remote.dto.RecurringHistoryPageDto>>
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
    ): Result<ReadSnapshot<List<RecurringItem>>>
    suspend fun candidates(expectedBinding: LogicalSessionBinding): Result<List<RecurringCandidate>>
}

interface RecurringManualMutationActions {
    suspend fun confirmCandidate(
        expectedBinding: LogicalSessionBinding,
        candidate: RecurringCandidate,
        nextExpectedDate: String? = null,
    ): Result<RecurringPendingIntent>
    fun observePendingIntents(): Flow<List<RecurringPendingIntent>> = flowOf(emptyList())
    fun describeManualIntent(row: OutboxRow): RecurringPendingIntent?
    suspend fun recoverManualIntent(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit>
    suspend fun createAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        draft: RecurringItemDraft,
    ): Result<RecurringPendingIntent>
    suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringPendingIntent>
}

interface RecurringLifecycleActions {
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

class RecurringRepository internal constructor(
    private val apiProvider: ApiServiceProvider,
    outbox: OutboxRepository? = null,
    adapters: OutboxAdapterGraph? = null,
    private val queryReader: RecurringQueryReader,
) : RecurringActions,
    RecurringManualMutationActions by RecurringMutationClient(
        requestGuard = LedgerRequestGuard(apiProvider),
        errorHandler = recurringErrorHandler(apiProvider),
        canModify = { ledgerRoleCanModify(apiProvider.currentLedgerRole()) },
        outbox = outbox,
        adapters = adapters,
    ) {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = recurringErrorHandler(apiProvider)
    override val readAccessDenials = queryReader.readAccessDenials
    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?) =
        queryReader.history(binding, publicId, beforeVersion)
    val occurrences: RecurringOccurrenceActions by lazy {
        RecurringOccurrenceRepository(apiProvider, requireNotNull(outbox), requireNotNull(adapters).recurringOccurrenceAdapter, queryReader)
    }

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        apiProvider.observeActiveLedgerAccess()

    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> =
        errorHandler.safeCall {
            val binding = requireNotNull(ledgerRequestGuard.captureLogicalBinding()) { "请重新绑定账本。" }
            queryReader.freshQuery(binding, { recurringItems(status?.trim()?.ifBlank { null }, includeArchived,
                month?.trim()?.ifBlank { null }, recurringTimezoneId()) }) { page ->
                require(page.items.all { it.ledgerId == binding.ledgerId }) { "固定支出所属账本不匹配。" }
            }.getOrThrow().items.map { it.toDomain() }
        }

    override suspend fun items(
        expectedBinding: LogicalSessionBinding,
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<ReadSnapshot<List<RecurringItem>>> =
        queryReader.items(expectedBinding, status?.trim()?.ifBlank { null }, includeArchived, month?.trim()?.ifBlank { null })
            .onSuccess { snapshot ->
                if (!snapshot.fromCache && status == null && month == null && includeArchived) {
                    val items = snapshot.value
                    onFullItemsSnapshot("n=${items.size};" +
                        "rv=${items.maxOfOrNull(RecurringItem::rowVersion) ?: 0};" +
                        "ua=${items.maxOfOrNull(RecurringItem::updatedAt).orEmpty()}")
                }
            }

    /** Fired with a cheap stable stamp after each unfiltered full-ledger items
     *  refresh. Wired in AppContainer to the budget-advice freshness sink. */
    var onFullItemsSnapshot: (stamp: String) -> Unit = {}

    override suspend fun candidates(
        expectedBinding: LogicalSessionBinding,
    ): Result<List<RecurringCandidate>> =
        errorHandler.safeCall {
            queryReader.freshQuery(expectedBinding, { recurringCandidates(timezone = recurringTimezoneId()) }, {}).getOrThrow()
                .items.map { it.toDomain() }
        }

    override suspend fun pause(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            queryReader.directMutation(expectedBinding) {
                ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                    api.pauseRecurringItem(
                        publicId.trim(),
                        com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                    ).toDomain()
                }
            }
        }

    override suspend fun resume(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            queryReader.directMutation(expectedBinding) {
                ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                    api.resumeRecurringItem(
                        publicId.trim(),
                        com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                    ).toDomain()
                }
            }
        }

    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            queryReader.directMutation(expectedBinding) {
                ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                    api.archiveRecurringItem(publicId.trim()).toDomain()
                }
            }
        }

    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> =
        errorHandler.safeCall {
            require(publicId.isNotBlank()) { "固定支出不存在。" }
            queryReader.directMutation(expectedBinding) {
                ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                    api.restoreRecurringItem(
                        publicId.trim(),
                        com.ticketbox.data.remote.dto.RecurringItemTokenRequest(expectedRowVersion),
                    ).toDomain()
                }
            }
        }
}

internal fun recurringTimezoneId(): String = TimeZone.getDefault().id

private fun recurringErrorHandler(apiProvider: ApiServiceProvider): NetworkErrorHandler =
    NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Recurring",
        statusMessages = mapOf(404 to "固定支出不存在。"),
    )
