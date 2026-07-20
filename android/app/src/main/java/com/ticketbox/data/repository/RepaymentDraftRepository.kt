package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.RepaymentNotificationDraft
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID

/**
 * ADR-0049 §杠杆③ (slice 3a) repayment-capture inbox repository.
 *
 * - [createDraft] is the NLS path: it posts a PENDING capture (never auto-records, §8) and is bound to
 *   the complete session authority captured at notification-post time, so a server, principal, device,
 *   ledger, or session transition before IO is rejected. The capture is content+identity deduped
 *   server-side, so it carries no idempotency key.
 * - [listPendingDrafts] / [confirmDraft] / [dismissDraft] drive the in-app review inbox.
 *
 * Direct-only online (no offline outbox). Writes short-circuit on the viewer role before the network
 * (the server also 403s). Confirm is the only fold-changing op (carries the chosen Debt's OCC token +
 * an ADR-0042 intent-time idempotency key); dismiss is a status-guarded terminal flip (no token).
 */
interface RepaymentDraftActions {
    fun canModifyLedger(): Boolean
    suspend fun listPendingDrafts(): Result<List<RepaymentDraft>>
    suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
    ): Result<RepaymentDraft>
    suspend fun dismissDraft(draftPublicId: String): Result<RepaymentDraft>
}

class RepaymentDraftRepository(
    private val apiProvider: ApiServiceProvider,
) : RepaymentDraftActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "RepaymentDraft",
        statusMessages = mapOf(
            403 to "当前账号无法处理还款草稿。",
            404 to "没有找到这条还款草稿或欠款。",
            409 to "这条还款草稿已被处理，或欠款状态已变化，请刷新后再试。",
            422 to "还款金额超过这笔欠款的剩余，请换一笔欠款。",
        ),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    internal fun captureDeferredLedgerBinding(): LogicalSessionBinding? =
        ledgerRequestGuard.captureLogicalBinding()

    internal suspend fun createDraft(
        draft: RepaymentNotificationDraft,
        expectedBinding: LogicalSessionBinding,
        notificationKey: String?,
    ): Result<RepaymentDraft> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expectedBinding)
        bound.call { api ->
            // No idempotency key: the route is content+identity deduped server-side (notificationKey is
            // the primary axis), and the capture is not part of the offline outbox.
            api.createRepaymentDraft(draft.toCreateRequest(notificationKey)).toDomain()
        }
    }

    override suspend fun listPendingDrafts(): Result<List<RepaymentDraft>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.repaymentDrafts(status = RepaymentDraftStatuses.PENDING).items.map { it.toDomain() }
            }
        }

    override suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
    ): Result<RepaymentDraft> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(REPAYMENT_DRAFT_VIEWER_READONLY))
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.confirmRepaymentDraft(
                    publicId = draftPublicId,
                    request = confirmRepaymentDraftRequest(
                        targetDebtPublicId = targetDebtPublicId,
                        expectedRowVersion = expectedRowVersion,
                    ),
                    // ADR-0042: single-use key — direct-only path, no offline replay.
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    override suspend fun dismissDraft(draftPublicId: String): Result<RepaymentDraft> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(REPAYMENT_DRAFT_VIEWER_READONLY))
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.dismissRepaymentDraft(
                    publicId = draftPublicId,
                    request = RepaymentDraftDismissRequestDto(),
                ).toDomain()
            }
        }
    }
}

/** Shared viewer short-circuit copy (kept in sync with [RepaymentDraftInboxViewModel] expectations). */
private const val REPAYMENT_DRAFT_VIEWER_READONLY = "当前角色为只读，无法修改账本。"
