package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map

interface DebtCreationActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observePendingCreations(): Flow<DebtCreationQueueSnapshot>
    suspend fun createDebt(
        expectedBinding: LogicalSessionBinding,
        draft: DebtDraft,
        homeCurrency: CurrencyCode,
    ): Result<DebtCreationReceipt>
}

/** Local acceptance only. A Debt fact is published exclusively by the backend command. */
data class DebtCreationReceipt(val intentId: Long, val binding: LogicalSessionBinding)

/** Owns intent publication; the registered dispatcher is the only network create caller. */
class DebtCreationRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val payloadAdapter: JsonAdapter<DebtCreateOutboxPayload>,
) : DebtCreationActions {
    private val guard = LedgerRequestGuard(apiProvider)

    override fun currentAccess(): LedgerAccessContext? = guard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, ledgerRoleCanModify(apiProvider.currentLedgerRole()))
    }

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override suspend fun createDebt(
        expectedBinding: LogicalSessionBinding,
        draft: DebtDraft,
        homeCurrency: CurrencyCode,
    ): Result<DebtCreationReceipt> {
        return try {
            val bound = guard.bindExact(expectedBinding)
            if (currentAccess()?.canModify != true) {
                return Result.failure(RepositoryException("当前角色为只读，无法修改账本。", "permission_denied"))
            }
            val cleanDraft = draft.validatedForCreation().getOrElse { return Result.failure(it) }
            val payload = DebtCreateOutboxPayload(
                revision = DEBT_CREATE_PAYLOAD_REVISION,
                homeCurrencyCode = homeCurrency.storageKey,
                originSessionGeneration = expectedBinding.sessionGeneration,
                originBindingRevision = expectedBinding.bindingRevision,
                request = cleanDraft.toCreateRequest(),
            )
            val key = UUID.randomUUID().toString()
            val id = outbox.enqueue(
                boundRequest = bound,
                intent = PendingMutationIntent(
                    type = PendingMutationType.CreateDebt,
                    targetId = "$DEBT_CREATE_TARGET_PREFIX$key",
                    payloadJson = payloadAdapter.toJson(payload),
                    expectedRowVersion = 0,
                    idempotencyKey = key,
                ),
            )
            Result.success(DebtCreationReceipt(id, expectedBinding))
        } catch (error: CancellationException) {
            throw error
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (_: Exception) {
            // Storage/encoding did not acknowledge publication. Keep the form and never report a Debt.
            Result.failure(RepositoryException("未能确认本机保存，请保留表单并检查待同步记录。", "debt_create_local_save_failed"))
        }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observePendingCreations(): Flow<DebtCreationQueueSnapshot> =
        observeActiveLedgerAccess().flatMapLatest { access ->
            flow {
                // Retire the previous ledger's visible projection before waiting for Room's new query.
                emit(DebtCreationQueueSnapshot(binding = access?.binding))
                if (access == null) return@flow
                outbox.observeActiveByTypes(setOf(PendingMutationType.CreateDebt), includeCompleted = true)
                    .map { rows ->
                        rows.filter {
                            it.ownerKey == access.binding.ownerKey && it.ledgerId == access.binding.ledgerId
                        }
                    }.collect { rows ->
                        emit(
                            DebtCreationQueueSnapshot(
                                binding = access.binding,
                                intents = rows.filter { it.status != PendingMutationStatus.Done }
                                    .map { it.toPendingDebtCreation(payloadAdapter) },
                                completedIntentIds = rows.filter { it.status == PendingMutationStatus.Done }
                                    .mapTo(mutableSetOf()) { it.id },
                            ),
                        )
                    }
            }
        }
}

private fun DebtDraft.validatedForCreation(): Result<DebtDraft> = try {
    val cleanLabel = counterpartyLabel.trim()
    require(cleanLabel.isNotBlank()) { "请填写欠款对象。" }
    require(cleanLabel.length <= 255) { "欠款对象名称太长。" }
    require(direction == DebtDirections.I_OWE || direction == DebtDirections.OWED_TO_ME) { "请选择欠款方向。" }
    require(principalAmountCents > 0L) { "金额必须大于 0。" }
    Result.success(copy(counterpartyLabel = cleanLabel))
} catch (error: IllegalArgumentException) {
    Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
}
