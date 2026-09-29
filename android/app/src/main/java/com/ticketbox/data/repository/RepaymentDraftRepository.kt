package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID

/** Reviews personal repayment captures. Durable capture is owned by NotificationCaptureRepository. */
interface RepaymentDraftActions {
    fun canModifyLedger(): Boolean
    suspend fun listPendingDrafts(expectedBinding: LogicalSessionBinding? = null): Result<List<RepaymentDraft>>
    suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
        expectedBinding: LogicalSessionBinding,
    ): Result<RepaymentDraft>
    suspend fun dismissDraft(draftPublicId: String, expectedBinding: LogicalSessionBinding? = null): Result<RepaymentDraft>
}

class RepaymentDraftRepository internal constructor(
    private val apiProvider: ApiServiceProvider,
    private val queryReader: DebtQueryReader,
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

    override suspend fun listPendingDrafts(expectedBinding: LogicalSessionBinding?): Result<List<RepaymentDraft>> =
        errorHandler.safeCall {
            (expectedBinding?.let(ledgerRequestGuard::bindExact) ?: ledgerRequestGuard.bind()).call { api ->
                api.repaymentDrafts(status = RepaymentDraftStatuses.PENDING).items.map { it.toDomain() }
            }
        }

    override suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
        expectedBinding: LogicalSessionBinding,
    ): Result<RepaymentDraft> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(REPAYMENT_DRAFT_VIEWER_READONLY))
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                queryReader.direct(expectedBinding, targetDebtPublicId) { api.confirmRepaymentDraft(
                    publicId = draftPublicId,
                    request = confirmRepaymentDraftRequest(
                        targetDebtPublicId = targetDebtPublicId,
                        expectedRowVersion = expectedRowVersion,
                    ),
                    // ADR-0042: single-use key — direct-only path, no offline replay.
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain() }
            }
        }
    }

    override suspend fun dismissDraft(draftPublicId: String, expectedBinding: LogicalSessionBinding?): Result<RepaymentDraft> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(REPAYMENT_DRAFT_VIEWER_READONLY))
        return errorHandler.safeCall {
            (expectedBinding?.let(ledgerRequestGuard::bindExact) ?: ledgerRequestGuard.bind()).call { api ->
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
