package com.ticketbox.data.repository

import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.flow.Flow
import java.io.IOException
import java.util.UUID

internal class ExpenseLedgerRepositoryActions(
    private val core: ExpenseRepositoryCore,
) : LedgerActions {
    override fun canModifyLedger(): Boolean = core.canModifyLedger()

    override fun lastConfirmedSyncAt(): String? = core.settingsStore.lastConfirmedSyncAt()

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
            service = bound.service,
            ledgerIdAtRequest = bound.ledgerId,
            month = month,
            category = category,
            tag = tag,
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
                bound.ledgerId,
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
                bound.ledgerId,
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
    ): Result<BatchApplyResult> = core.errorHandler.safeCall {
        // Fan out into one offline-aware PatchExpense per expense. Each call owns
        // its own direct-PATCH-then-outbox attempt + idempotency key, so the
        // batch is non-atomic by design: synced / queued / failed are tallied
        // independently (mirrors the per-row keep-mine model, unlike the atomic
        // /web batch endpoint). Sequential — same-scale as the confirmed list and
        // keeps the ledger-session guard + outbox ordering simple.
        // KNOWN LIMITATION (review P2, deferred): a SYNCED fan-out row updates the
        // Room cache (patchExpenseOffline → cacheIfConfirmed) so the confirmed list
        // reflects it immediately; a QUEUED (offline) row does NOT, so during the
        // offline window the list keeps the old category/tags even though the
        // "已加入同步" snackbar fired. It self-heals on the next confirmed-list
        // sync (syncConfirmed re-fetches from the server) — NOT on drain, since
        // PatchExpenseDispatcher's success doesn't re-cache locally. Optimistic
        // local-cache write for the queued case needs a domain→entity mapper that
        // doesn't exist yet; tracked as a follow-up rather than risking an
        // optimistic/server normalisation skew.
        val pending = ExpensePendingRepository(core)
        var synced = 0
        var queued = 0
        var failed = 0
        for (expense in expenses) {
            pending.applyConfirmedFieldsOffline(expense, category = category, tags = tags).fold(
                onSuccess = { outcome ->
                    when (outcome) {
                        is SaveOutcome.Synced -> synced++
                        is SaveOutcome.Queued -> queued++
                    }
                },
                onFailure = { failed++ },
            )
        }
        BatchApplyResult(synced = synced, queued = queued, failed = failed)
    }
}
