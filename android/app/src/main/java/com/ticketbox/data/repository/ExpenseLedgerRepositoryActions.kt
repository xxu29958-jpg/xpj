package com.ticketbox.data.repository

import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateRequestDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import java.util.UUID

internal class ExpenseLedgerRepositoryActions(
    private val core: ExpenseRepositoryCore,
) : LedgerActions {
    private val confirmedBatchIntentLock = Any()
    private var unresolvedConfirmedBatchIntent: ConfirmedBatchIntent? = null
    val manualCreation = ExpenseManualCreation(core)

    override fun canModifyLedger(): Boolean = core.canModifyLedger()

    override fun lastConfirmedSyncAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastConfirmedSyncAtForLedger)

    override fun observeConfirmed(): Flow<List<Expense>> = core.observeConfirmed()
    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = core.observeConfirmedStream()

    override suspend fun categories(): Result<List<String>> = ExpensePendingRepository(core).categories()

    override suspend fun tags(): Result<List<String>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.tags().items
        }
    }

    override suspend fun months(): Result<List<String>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.months(timezone = core.currentTimezoneId()).items
        }
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        core.syncConfirmedFromService(
            bound = bound,
            request = ConfirmedSyncRequest(
                month = month,
                category = category,
                tag = tag,
            ),
        )
    }

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> = core.errorHandler.safeCall {
        val cleanMonth = month?.trim()?.ifBlank { null }
        val cleanCategory = category?.trim()?.ifBlank { null }
        val cleanTag = tag?.trim()?.ifBlank { null }
        core.ledgerRequestGuard.guardedCall { api ->
            val response = api.exportCsv(
                month = cleanMonth,
                category = cleanCategory,
                tag = cleanTag,
                timezone = core.currentTimezoneId(),
            )
            if (!response.isSuccessful) {
                val parsed = core.errorHandler.parseErrorMessage(response.code(), response.errorBody()?.string())
                throw RepositoryException(parsed.message, parsed.errorCode)
            }
            val body = response.body() ?: throw RepositoryException("导出内容为空。")
            val fileName = buildString {
                append("ticketbox-expenses")
                if (cleanMonth != null) append("-").append(cleanMonth)
                if (cleanTag != null) append("-tag-").append(cleanTag.toFileNameSegment())
                append(".csv")
            }
            CsvExport(fileName = fileName, bytes = body.use { it.bytes() })
        }
    }

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = manualCreation.create(draft)

    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>,
        category: String?,
        tags: String?,
        reason: String,
    ): Result<BatchApplyResult> = core.errorHandler.safeCall {
        require(expenses.isNotEmpty()) { "请先选择要更正的账单。" }
        require(category != null || tags != null) { "请选择要批量更正的字段。" }
        require(expenses.map(Expense::id).distinct().size == expenses.size) {
            "批量更正中存在重复账单。"
        }
        val cleanReason = reason.trim()
        require(cleanReason.isNotEmpty()) { "请填写更正理由。" }
        val cleanCategory = category?.trim()
        val cleanTags = tags?.trim()
        val orderedExpenses = expenses.sortedBy(Expense::id)
        val request = ConfirmedExpenseBatchUpdateRequestDto(
            expenseIds = orderedExpenses.map(Expense::id),
            expectedRowVersionById = orderedExpenses.associate { it.id to it.rowVersion },
            category = cleanCategory,
            tags = cleanTags,
            reason = cleanReason,
        )
        val bound = core.ledgerRequestGuard.bind()
        // A failed call has an unknown publication outcome. Keep its random UUID
        // for an identical same-ledger retry; another binding or changed request
        // is a distinct user intent.
        val intent = synchronized(confirmedBatchIntentLock) {
            unresolvedConfirmedBatchIntent
                ?.takeIf { it.binding == bound.outboxBinding && it.request == request }
                ?: ConfirmedBatchIntent(bound.outboxBinding, request, UUID.randomUUID().toString()).also {
                    unresolvedConfirmedBatchIntent = it
                }
        }

        val response = bound.call { api ->
            api.updateConfirmedBatch(
                idempotencyKey = intent.idempotencyKey,
                request = intent.request,
            )
        }
        synchronized(confirmedBatchIntentLock) {
            if (unresolvedConfirmedBatchIntent?.idempotencyKey == intent.idempotencyKey) {
                unresolvedConfirmedBatchIntent = null
            }
        }

        // The command response owns counts, not row projections. Refresh through
        // the same bound ledger before reporting success so Room and every real
        // confirmed-list consumer observe the published facts.
        val refreshPending = try {
            core.syncConfirmedFromService(bound)
            false
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            true
        }
        BatchApplyResult(
            requested = response.requestedCount,
            updated = response.updatedCount,
            skippedNotFound = response.skippedNotFound,
            skippedNotConfirmed = response.skippedNotConfirmed,
            refreshPending = refreshPending,
        )
    }
}

private data class ConfirmedBatchIntent(
    val binding: OutboxBinding,
    val request: ConfirmedExpenseBatchUpdateRequestDto,
    val idempotencyKey: String,
)
