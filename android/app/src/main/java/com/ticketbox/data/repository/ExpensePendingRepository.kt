package com.ticketbox.data.repository

import android.util.Log
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.mergeExpenseCategories
import kotlinx.coroutines.flow.Flow
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.time.Instant
import java.util.UUID
import kotlin.system.measureTimeMillis

internal class ExpensePendingRepository(
    private val core: ExpenseRepositoryCore,
) : PendingReviewActions {
    override fun canModifyLedger(): Boolean = core.canModifyLedger()

    override fun observeActiveLedgerId(): Flow<String?> = core.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = core.currentActiveLedgerId()

    override suspend fun fetchPending(): Result<List<Expense>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.pendingExpenses().map { it.toDomain() }
        }
    }

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> = core.errorHandler.safeCall {
        require(bytes.isNotEmpty()) { "请选择一张账单截图。" }
        val bound = core.ledgerRequestGuard.bind(
            expectedLedgerId = expectedLedgerId,
            ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
        )
        val cleanName = fileName
            .trim()
            .ifBlank { "ticketbox-screenshot.jpg" }
            .replace(Regex("[\\\\/:*?\"<>|]"), "_")
        val mediaType = (contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()
        val body = bytes.toRequestBody(mediaType)
        val filePart = MultipartBody.Part.createFormData("file", cleanName, body)
        var uploadResponse: UploadResponseDto? = null
        val networkDurationMs = measureTimeMillis {
            uploadResponse = bound.call(
                ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
            ) { it.uploadScreenshot(filePart, timezone = core.currentTimezoneId()) }
        }
        val response = requireNotNull(uploadResponse)
        if (BuildConfig.DEBUG) {
            Log.d(
                ExpenseRepositoryCore.NETWORK_LOG_TAG,
                buildString {
                    append("Screenshot upload timing: ")
                    append("prepare_ms=").append(preparationDurationMs ?: -1)
                    append(" network_ms=").append(networkDurationMs)
                    append(" server_ms=").append(response.durationMs ?: -1)
                    append(" source_bytes=").append(sourceSizeBytes ?: -1)
                    append(" upload_bytes=").append(response.uploadSizeBytes ?: bytes.size)
                    append(" server_breakdown=").append(response.timingMs.orEmpty())
                },
            )
        }
        if (bound.isStillActive()) {
            core.settingsStore.saveLastUploadAt(Instant.now().toString())
        }
        response.id
    }

    override suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense> = core.errorHandler.safeCall {
        // ADR-0038 PR-2g.3 round-8: this method is the DIRECT path
        // only. Any error — IOException, HttpException, anything —
        // surfaces as Result.failure. Chained callers (confirm /
        // saveAndConfirm) rely on this: a silent offline-queue
        // would let them dispatch a follow-up with a stale token.
        //
        // For offline-aware save use [saveExpenseAllowingOffline]
        // which returns a sealed [SaveOutcome] the caller must
        // branch on.
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0042: this DIRECT path never enqueues, so the key is single-use —
        // it only satisfies the server's now-mandatory Idempotency-Key. (A
        // committed-but-unseen edit on this path still surfaces as a failure for
        // the chained caller to handle; the offline-aware variant below is the
        // one whose replay actually reuses the key.)
        val updated = core.cacheIfConfirmed(
            bound.call {
                it.updateExpense(id, draft.toRequest(baseline = baseline), UUID.randomUUID().toString())
            },
            bound.ledgerId,
        )
        updated.toDomain()
    }

    override suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<SaveOutcome> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val request = draft.toRequest(baseline = baseline)
        // ADR-0042: ONE intent-time key shared by the direct attempt and the
        // outbox replay. If the direct PATCH commits server-side but its
        // response is lost (IOException below), the enqueued row replays with
        // this SAME key — the server HITs the recorded success and returns the
        // canonical row instead of false-409ing on the now-stale row_version.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            // Direct PATCH first — fast path when online. Returns
            // Synced with the server's canonical Expense.
            val updated = core.cacheIfConfirmed(
                bound.call { it.updateExpense(id, request, idempotencyKey) },
                bound.ledgerId,
            )
            SaveOutcome.Synced(updated.toDomain()) as SaveOutcome
        } catch (networkError: IOException) {
            // Network failed. Enqueue for the worker to replay AND
            // return an optimistic Expense so the UI reflects the
            // user's edit (not the pre-edit baseline). Only
            // IOException is the offline-fallback trigger —
            // HttpException (409 / 4xx / 5xx) propagates out to
            // safeCall and surfaces as Result.failure.
            val outbox = core.outbox
            val adapter = core.patchExpenseAdapter
            val token = request.expectedRowVersion
            if (outbox == null || adapter == null || token == null || token == 0L) {
                // Outbox wiring missing OR baseline lacked a token.
                // Fall back to the failure path so we don't pretend
                // we saved.
                throw networkError
            }
            // [codex round-13 P1] Session race guard. ``bound.call``
            // only re-checks ``isStillActive`` when the API block
            // returns normally; an IOException jumps straight here
            // and would otherwise let a row queued under ledger A
            // land in ledger B's outbox after a mid-flight switch
            // (the OutboxRepository.clearAll that fires on switch
            // already wiped the OLD queue; what this guard prevents
            // is a NEW row being added AFTER the wipe with stale
            // session context). Throws RepositoryException with
            // "账本已切换…" if so; safeCall maps it to
            // Result.failure.
            bound.requireStillActive()
            // codex round-8 P3#5: strip the token from the payload
            // — outbox row's expectedRowVersion is the single source
            // of truth; replay (PatchExpenseDispatcher) already
            // overwrites the request token from the row before
            // dispatching. Saving it in the payload too duplicates
            // state and risks drift if KeepMine refreshes the row
            // token without rewriting the serialised payload.
            outbox.enqueue(
                type = PendingMutationType.PatchExpense,
                targetId = "expense:$id",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = null)),
                expectedRowVersion = token,
                // Same key as the direct attempt above — see the rationale where
                // it's minted. The dispatcher replays it from row.idempotencyKey.
                idempotencyKey = idempotencyKey,
            )
            SaveOutcome.Queued(projectOptimisticExpense(baseline, draft)) as SaveOutcome
        }
    }

    /**
     * Build the optimistic projection of what the server WOULD
     * return once the queued PATCH replays. Used as the [Expense]
     * carried in [SaveOutcome.Queued] so the UI shows the user's
     * edit (their new merchant / amount / note) rather than the
     * pre-edit baseline. The ``updatedAt`` is intentionally
     * unchanged — it's the pre-mutation token, NOT a server-
     * confirmed one; chained callers shouldn't reach this branch
     * (they use [updateExpense] which fails on IOException).
     */
    private fun projectOptimisticExpense(baseline: Expense, draft: ExpenseDraft): Expense {
        // Only fields the draft can change get overwritten; the rest
        // (timestamps, server-side derived state) stay at baseline.
        return baseline.copy(
            amountCents = draft.amountCents ?: baseline.amountCents,
            originalCurrencyCode = draft.originalCurrencyCode ?: baseline.originalCurrencyCode,
            originalAmountMinor = draft.originalAmountMinor ?: baseline.originalAmountMinor,
            merchant = draft.merchant ?: baseline.merchant,
            category = draft.category ?: baseline.category,
            note = draft.note ?: baseline.note,
            expenseTime = draft.expenseTime ?: baseline.expenseTime,
            tags = draft.tags ?: baseline.tags,
            valueScore = draft.valueScore ?: baseline.valueScore,
            regretScore = draft.regretScore ?: baseline.regretScore,
        )
    }

    override suspend fun confirmExpense(
        id: Long,
        expectedRowVersion: Long,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val confirmed = core.cacheIfConfirmed(
            bound.call {
                // ADR-0042: this DIRECT path never enqueues, so the key is
                // single-use — it only satisfies the server's mandatory header.
                it.confirmExpense(id, ExpenseStateTokenRequest(expectedRowVersion), UUID.randomUUID().toString())
            },
            bound.ledgerId,
        )
        confirmed.toDomain()
    }

    override suspend fun rejectExpense(
        id: Long,
        expectedRowVersion: Long,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val rejected = bound.call {
            // ADR-0042: single-use key — direct-only path, no replay.
            it.rejectExpense(id, ExpenseStateTokenRequest(expectedRowVersion), UUID.randomUUID().toString())
        }
        rejected.toDomain()
    }

    override suspend fun undoRejectExpense(
        id: Long,
        expectedRowVersion: Long,
    ): Result<Expense> =
        core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bind()
            val restored = bound.call {
                it.undoExpense(id, ExpenseStateTokenRequest(expectedRowVersion))
            }
            restored.toDomain()
        }

    override suspend fun markNotDuplicate(
        id: Long,
        expectedRowVersion: Long,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val updated = core.cacheIfConfirmed(
            bound.call {
                // ADR-0042: single-use key — direct-only path, no replay.
                it.markNotDuplicate(id, ExpenseStateTokenRequest(expectedRowVersion), UUID.randomUUID().toString())
            },
            bound.ledgerId,
        )
        updated.toDomain()
    }

    override suspend fun confirmExpenseAllowingOffline(
        expense: Expense,
    ): Result<ExpenseStateOutcome> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0042: ONE intent-time key shared by the direct attempt and the
        // outbox replay. A committed-but-unseen confirm (the POST commits
        // server-side but its response is lost) replays with this SAME key — the
        // server HITs the recorded success instead of false-409ing on the stale
        // token. The dispatcher replays it from row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val confirmed = core.cacheIfConfirmed(
                bound.call {
                    it.confirmExpense(expense.id, ExpenseStateTokenRequest(expense.rowVersion), idempotencyKey)
                },
                bound.ledgerId,
            )
            ExpenseStateOutcome.Synced(confirmed.toDomain()) as ExpenseStateOutcome
        } catch (networkError: IOException) {
            core.enqueueStateTransition(
                bound = bound,
                type = PendingMutationType.ConfirmExpense,
                expense = expense,
                networkError = networkError,
                idempotencyKey = idempotencyKey,
            )
            ExpenseStateOutcome.Queued(expense.copy(status = "confirmed")) as ExpenseStateOutcome
        }
    }

    override suspend fun rejectExpenseAllowingOffline(
        expense: Expense,
    ): Result<ExpenseStateOutcome> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0042: one intent-time key for both the direct attempt and the
        // replay — see confirmExpenseAllowingOffline for the rationale.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val rejected = bound.call {
                it.rejectExpense(expense.id, ExpenseStateTokenRequest(expense.rowVersion), idempotencyKey)
            }
            ExpenseStateOutcome.Synced(rejected.toDomain()) as ExpenseStateOutcome
        } catch (networkError: IOException) {
            core.enqueueStateTransition(
                bound = bound,
                type = PendingMutationType.RejectExpense,
                expense = expense,
                networkError = networkError,
                idempotencyKey = idempotencyKey,
            )
            ExpenseStateOutcome.Queued(expense.copy(status = "rejected")) as ExpenseStateOutcome
        }
    }

    override suspend fun markNotDuplicateAllowingOffline(
        expense: Expense,
    ): Result<ExpenseStateOutcome> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0042: one intent-time key for both the direct attempt and the
        // replay — see confirmExpenseAllowingOffline for the rationale.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val updated = core.cacheIfConfirmed(
                bound.call {
                    it.markNotDuplicate(expense.id, ExpenseStateTokenRequest(expense.rowVersion), idempotencyKey)
                },
                bound.ledgerId,
            )
            ExpenseStateOutcome.Synced(updated.toDomain()) as ExpenseStateOutcome
        } catch (networkError: IOException) {
            core.enqueueStateTransition(
                bound = bound,
                type = PendingMutationType.MarkNotDuplicate,
                expense = expense,
                networkError = networkError,
                idempotencyKey = idempotencyKey,
            )
            // Optimistic projection: the suspected-duplicate badge clears
            // the moment the user taps "保留" — duplicateStatus flips to
            // "none" so the pending row stops showing the dedup
            // affordance while the POST waits for connectivity.
            ExpenseStateOutcome.Queued(expense.copy(duplicateStatus = "none")) as ExpenseStateOutcome
        }
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { core.readProtectedImage(it.expenseThumbnail(id)) }
    }

    override suspend fun categories(): Result<List<String>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            mergeExpenseCategories(api.categories().items)
        }
    }
}
