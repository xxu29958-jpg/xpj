package com.ticketbox.data.repository

import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateRequestDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import java.io.IOException
import java.util.UUID

internal class ExpenseLedgerRepositoryActions(
    private val core: ExpenseRepositoryCore,
) : LedgerActions {
    override fun canModifyLedger(): Boolean = core.canModifyLedger()

    override fun lastConfirmedSyncAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastConfirmedSyncAtForLedger)

    override fun observeConfirmed(): Flow<List<Expense>> = core.observeConfirmed()

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

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = core.errorHandler.safeCall {
        require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
        val bound = core.ledgerRequestGuard.bind()
        val outbox = core.outbox
        val adapter = core.manualCreateAdapter
        if (outbox == null || adapter == null) {
            // No offline wiring (pre-slice-4 tests) — direct-only create with no
            // client_ref; any failure surfaces as Result.failure.
            val created = core.cacheIfConfirmed(
                bound.call { it.createManualExpense(draft.toManualCreateRequest()) },
                bound,
            )
            return@safeCall created.toDomain()
        }
        // issue #65 slice 4: offline-aware. ONE device-unique client_ref shared by
        // the direct attempt and the outbox replay — a committed-but-unseen create
        // (POST committed server-side but the response was lost) replays with the
        // SAME ref so the server HITs the existing row instead of double-creating
        // (backend Slice 1 keys dedup on {device_id}:{client_ref}).
        val clientRef = UUID.randomUUID().toString()
        try {
            val created = core.cacheIfConfirmed(
                bound.call { it.createManualExpense(draft.toManualCreateRequest(clientRef = clientRef)) },
                bound,
            )
            created.toDomain()
        } catch (networkError: IOException) {
            // Offline: write the optimistic local row (shows immediately in the
            // confirmed list, survives restart) + queue the CreateExpense replay,
            // return the optimistic Expense. enqueueLocalCreate re-checks the
            // bound ledger is still active before writing. Only IOException is the
            // offline trigger — HttpException (validation / 4xx / 5xx) propagates
            // to safeCall as Result.failure so we don't pretend we saved.
            core.enqueueLocalCreate(bound, outbox, adapter, draft, clientRef)
        }
    }

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
        val idempotencyKey = UUID.randomUUID().toString()

        val bound = core.ledgerRequestGuard.bind()
        val response = bound.call { api ->
            api.updateConfirmedBatch(
                idempotencyKey = idempotencyKey,
                request = ConfirmedExpenseBatchUpdateRequestDto(
                    expenseIds = orderedExpenses.map(Expense::id),
                    expectedRowVersionById = orderedExpenses.associate { it.id to it.rowVersion },
                    category = cleanCategory,
                    tags = cleanTags,
                    reason = cleanReason,
                ),
            )
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
