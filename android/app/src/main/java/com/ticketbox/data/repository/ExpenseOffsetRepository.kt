package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetIntentKind
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.PendingExpenseOffsetIntent
import kotlinx.coroutines.CancellationException
import java.io.IOException
import java.time.LocalDate
import java.time.format.DateTimeParseException
import java.util.UUID

internal class ExpenseOffsetRepository(private val core: ExpenseRepositoryCore) {
    suspend fun fetch(expenseId: Long): Result<ExpenseFactBundle> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val dto = bound.call { it.expenseFactBundle(expenseId.toString()) }
        publish(dto, bound)
        dto.toDomain()
    }

    suspend fun createAllowingOffline(
        expense: Expense,
        draft: ExpenseOffsetDraft,
    ): Result<ExpenseOffsetMutationOutcome> = core.errorHandler.safeCall {
        requireMutableRoot(expense)
        val reason = requiredReason(draft.reason)
        val accountingDate = validDate(draft.accountingDate)
        val amount = when (draft.kind) {
            com.ticketbox.domain.model.StreamOffsetKind.Reversal -> {
                if (draft.originalAmountMinor != null) throw RepositoryException("冲销金额由账单事实决定。")
                null
            }
            else -> draft.originalAmountMinor?.takeIf { it > 0 }
                ?: throw RepositoryException("请输入有效的退款金额。")
        }
        val request = ExpenseOffsetCreateRequestDto(
            kind = draft.kind.toDto(),
            originalAmountMinor = amount,
            accountingDate = accountingDate,
            reason = reason,
            expectedRowVersion = expense.rowVersion,
        )
        val bound = core.ledgerRequestGuard.bind()
        val key = UUID.randomUUID().toString()
        val targetId = expenseOutboxTargetId(expense)
        val outbox = core.outbox
        val adapter = core.offsetCreateAdapter
        if (outbox != null && adapter != null && core.hasUnresolvedQueuedMutationsFor(bound, targetId)) {
            enqueueCreate(bound, targetId, request, key)
            return@safeCall queuedCreate(draft, reason)
        }
        val response = try {
            bound.call { it.createExpenseOffset(expense.id.toString(), request, key) }
        } catch (networkError: IOException) {
            if (outbox == null || adapter == null) throw networkError
            enqueueCreate(bound, targetId, request, key)
            return@safeCall queuedCreate(draft, reason)
        }
        synced(response, bound)
    }

    suspend fun voidAllowingOffline(
        expense: Expense,
        offset: ExpenseOffsetFact,
        reason: String,
    ): Result<ExpenseOffsetMutationOutcome> = core.errorHandler.safeCall {
        requireMutableRoot(expense)
        if (offset.rowVersion <= 0) throw RepositoryException("这条退款事实还不能撤销。")
        val cleanReason = requiredReason(reason)
        val request = ExpenseOffsetVoidRequestDto(cleanReason, offset.rowVersion)
        val bound = core.ledgerRequestGuard.bind()
        val key = UUID.randomUUID().toString()
        val targetId = expenseOffsetTargetId(expense.id, offset.publicId)
        val outbox = core.outbox
        val adapter = core.offsetVoidAdapter
        if (outbox != null && adapter != null && core.hasUnresolvedQueuedMutationsFor(bound, targetId)) {
            enqueueVoid(bound, targetId, request, key)
            return@safeCall queuedVoid(offset, cleanReason)
        }
        val response = try {
            bound.call {
                it.voidExpenseOffset(expense.id.toString(), offset.publicId, request, key)
            }
        } catch (networkError: IOException) {
            if (outbox == null || adapter == null) throw networkError
            enqueueVoid(bound, targetId, request, key)
            return@safeCall queuedVoid(offset, cleanReason)
        }
        synced(response, bound)
    }

    private fun requireMutableRoot(expense: Expense) {
        if (!core.canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账单事实。")
        if (expense.status != "confirmed" || expense.pendingSync || expense.id <= 0 || expense.rowVersion <= 0) {
            throw RepositoryException("这笔账单还不能记录退款或冲销。")
        }
    }

    private suspend fun synced(
        response: ExpenseFactBundleDto,
        bound: BoundLedgerRequest,
    ): ExpenseOffsetMutationOutcome.Synced {
        val refreshPending = !publish(response, bound)
        return ExpenseOffsetMutationOutcome.Synced(response.toDomain(), refreshPending)
    }

    private suspend fun publish(response: ExpenseFactBundleDto, bound: BoundLedgerRequest): Boolean {
        return try {
            val projection = response.toCacheProjection(bound.ledgerId)
            core.withActiveBindingCommit(bound) {
                core.expenseDao.applyExpenseFactBundle(
                    ledgerId = bound.ledgerId,
                    root = projection.root,
                    activeOffsets = projection.activeOffsets,
                )
                core.onConfirmedCommitted(bound.ledgerId)
            }
            true
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (bindingError: RepositoryException) {
            throw bindingError
        } catch (_: Exception) {
            false
        }
    }

    private suspend fun enqueueCreate(
        bound: BoundLedgerRequest,
        targetId: String,
        request: ExpenseOffsetCreateRequestDto,
        key: String,
    ) {
        requireNotNull(core.outbox).enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.CreateExpenseOffset,
                targetId = targetId,
                payloadJson = requireNotNull(core.offsetCreateAdapter)
                    .toJson(request.copy(expectedRowVersion = 0)),
                expectedRowVersion = request.expectedRowVersion,
                idempotencyKey = key,
            ),
        )
    }

    private suspend fun enqueueVoid(
        bound: BoundLedgerRequest,
        targetId: String,
        request: ExpenseOffsetVoidRequestDto,
        key: String,
    ) {
        requireNotNull(core.outbox).enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.VoidExpenseOffset,
                targetId = targetId,
                payloadJson = requireNotNull(core.offsetVoidAdapter)
                    .toJson(request.copy(expectedRowVersion = 0)),
                expectedRowVersion = request.expectedRowVersion,
                idempotencyKey = key,
            ),
        )
    }
}

private fun requiredReason(value: String): String = value.trim().takeIf { it.isNotEmpty() }
    ?: throw RepositoryException("请填写原因。")

private fun validDate(value: String): String {
    val clean = value.trim()
    try {
        LocalDate.parse(clean)
    } catch (_: DateTimeParseException) {
        throw RepositoryException("请选择有效日期。")
    }
    return clean
}

private fun queuedCreate(draft: ExpenseOffsetDraft, reason: String) = ExpenseOffsetMutationOutcome.Queued(
    PendingExpenseOffsetIntent(ExpenseOffsetIntentKind.Create, draft.kind, null, reason),
)

private fun queuedVoid(offset: ExpenseOffsetFact, reason: String) = ExpenseOffsetMutationOutcome.Queued(
    PendingExpenseOffsetIntent(ExpenseOffsetIntentKind.Void, offset.kind, offset.publicId, reason),
)
