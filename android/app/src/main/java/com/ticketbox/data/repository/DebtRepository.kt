package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalRejectRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalWithdrawRequestDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.util.UUID

/**
 * ADR-0049 §2 (slice 8) Debt entity repository: list the active ledger's debts and create
 * external/manual ones. Direct-only online (no outbox) — a debt create is not part of the
 * offline outbox surface. Failure semantics follow the rest of the repository layer: every
 * suspend method returns `Result<T>`; viewer role short-circuits the write before the network.
 */
interface DebtActions {
    fun canModifyLedger(): Boolean
    suspend fun listDebts(): Result<List<Debt>>
    suspend fun getDebt(publicId: String): Result<Debt>
    suspend fun createDebt(draft: DebtDraft): Result<Debt>
    // ADR-0049 §3 (slice 8c) direct fact writes on an external/manual Debt. [expectedRowVersion]
    // is the §2.1 OCC carrier (the local Debt's row_version); the response is the fold-after Debt
    // (status / remaining / paid / a fresh row_version) the detail screen swaps in.
    suspend fun recordRepayment(publicId: String, expectedRowVersion: Long, amountCents: Long): Result<Debt>
    suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt>
    suspend fun voidDebt(publicId: String, expectedRowVersion: Long, reason: String): Result<Debt>
}

/**
 * ADR-0049 §3.2 (slice 8d) member repayment-proposal operations, split from [DebtActions] so the
 * proposal ViewModel depends only on this narrow surface (and its test fakes stay small). The two
 * parties of a member Debt can live in different ledgers (§5.2), so these are participant-scoped on
 * the server, not ledger-scoped. The debtor proposes "I paid" / withdraws; the creditor confirms
 * (full or partial) / rejects. Confirm is the only fold-changing op (carries the §2.1 OCC carrier
 * [Debt.rowVersion]) and replies with the fold-after [Debt]; the others reply with the proposal.
 * Direct-only online (no offline outbox); viewer role short-circuits writes before the network.
 */
interface DebtProposalActions {
    fun canModifyLedger(): Boolean
    suspend fun listRepaymentProposals(debtPublicId: String): Result<List<MemberRepaymentProposal>>
    suspend fun proposeRepayment(
        debtPublicId: String,
        proposedAmountCents: Long,
        note: String?,
        supersedesProposalPublicId: String?,
    ): Result<MemberRepaymentProposal>
    suspend fun withdrawRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal>
    suspend fun confirmRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
        expectedRowVersion: Long,
        confirmedAmountCents: Long?,
    ): Result<Debt>
    suspend fun rejectRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal>
}

class DebtRepository(
    apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(
        apiClient, settingsStore, tokenStore,
    ),
) : DebtActions {
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Debt",
        statusMessages = mapOf(
            // 403: the proposal flow's debtor-only / creditor-only guard (§3.2). The UI gates by
            // role, so this is a defensive fallback rather than an expected path.
            403 to "当前账号无法对这笔欠款执行该操作。",
            404 to "没有找到这笔欠款。",
            409 to "欠款或提案状态已变化，请刷新后再试。",
            422 to "请检查方向、对象和金额。",
        ),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun listDebts(): Result<List<Debt>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.debts().items.map { it.toDomain() }
            }
        }

    override suspend fun getDebt(publicId: String): Result<Debt> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api -> api.debt(publicId).toDomain() }
        }

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
        }
        val cleanDraft = draft.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.createDebt(
                    request = cleanDraft.toCreateRequest(),
                    // ADR-0042: single-use key — direct-only path, no offline replay.
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
        if (amountCents <= 0L) return Result.failure(RepositoryException("还款金额必须大于 0。"))
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.recordDebtRepayment(
                    publicId = publicId,
                    request = RepaymentCreateRequestDto(
                        amountCents = amountCents,
                        expectedRowVersion = expectedRowVersion,
                    ),
                    // ADR-0042: single-use key — direct-only path, no offline replay.
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
        if (amountCents == 0L) return Result.failure(RepositoryException("调整金额不能为 0。"))
        val cleanReason = reason.trim()
        if (cleanReason.isEmpty()) return Result.failure(RepositoryException("请填写调整原因。"))
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.recordDebtAdjustment(
                    publicId = publicId,
                    request = DebtAdjustmentCreateRequestDto(
                        amountCents = amountCents,
                        reason = cleanReason,
                        expectedRowVersion = expectedRowVersion,
                    ),
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
        val cleanReason = reason.trim()
        if (cleanReason.isEmpty()) return Result.failure(RepositoryException("请填写作废原因。"))
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.voidDebt(
                    publicId = publicId,
                    request = DebtVoidCreateRequestDto(
                        reason = cleanReason,
                        expectedRowVersion = expectedRowVersion,
                    ),
                    idempotencyKey = UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    /**
     * ADR-0049 §3.2 (slice 8d) member repayment-proposal operations, exposed as a focused
     * sub-surface so the proposal ViewModel depends only on [DebtProposalActions] (and its test
     * fakes stay small) while DebtRepository keeps a single cohesive Debt concern. The inner class
     * reuses the parent's [ledgerRequestGuard] / [errorHandler] / [canModifyLedger], so no IO infra
     * is duplicated.
     */
    val proposals: DebtProposalActions = ProposalActions()

    private inner class ProposalActions : DebtProposalActions {
        override fun canModifyLedger(): Boolean = this@DebtRepository.canModifyLedger()

        override suspend fun listRepaymentProposals(
            debtPublicId: String,
        ): Result<List<MemberRepaymentProposal>> =
            errorHandler.safeCall {
                ledgerRequestGuard.guardedCall { api ->
                    api.repaymentProposals(debtPublicId).items.map { it.toDomain() }
                }
            }

        override suspend fun proposeRepayment(
            debtPublicId: String,
            proposedAmountCents: Long,
            note: String?,
            supersedesProposalPublicId: String?,
        ): Result<MemberRepaymentProposal> {
            if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
            if (proposedAmountCents <= 0L) return Result.failure(RepositoryException("还款金额必须大于 0。"))
            return errorHandler.safeCall {
                ledgerRequestGuard.guardedCall { api ->
                    api.createRepaymentProposal(
                        publicId = debtPublicId,
                        request = MemberRepaymentProposalCreateRequestDto(
                            proposedAmountCents = proposedAmountCents,
                            note = note?.trim()?.ifBlank { null },
                            supersedesProposalPublicId = supersedesProposalPublicId,
                        ),
                        // ADR-0042: single-use key — direct-only path, no offline replay.
                        idempotencyKey = UUID.randomUUID().toString(),
                    ).toDomain()
                }
            }
        }

        override suspend fun withdrawRepaymentProposal(
            debtPublicId: String,
            proposalPublicId: String,
        ): Result<MemberRepaymentProposal> {
            if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
            return errorHandler.safeCall {
                ledgerRequestGuard.guardedCall { api ->
                    api.withdrawRepaymentProposal(
                        publicId = debtPublicId,
                        proposalPublicId = proposalPublicId,
                        request = MemberRepaymentProposalWithdrawRequestDto(),
                        idempotencyKey = UUID.randomUUID().toString(),
                    ).toDomain()
                }
            }
        }

        override suspend fun confirmRepaymentProposal(
            debtPublicId: String,
            proposalPublicId: String,
            expectedRowVersion: Long,
            confirmedAmountCents: Long?,
        ): Result<Debt> {
            if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
            if (confirmedAmountCents != null && confirmedAmountCents <= 0L) {
                return Result.failure(RepositoryException("确认金额必须大于 0。"))
            }
            return errorHandler.safeCall {
                ledgerRequestGuard.guardedCall { api ->
                    api.confirmRepaymentProposal(
                        publicId = debtPublicId,
                        proposalPublicId = proposalPublicId,
                        request = MemberRepaymentProposalConfirmRequestDto(
                            confirmedAmountCents = confirmedAmountCents,
                            expectedRowVersion = expectedRowVersion,
                        ),
                        idempotencyKey = UUID.randomUUID().toString(),
                    ).toDomain()
                }
            }
        }

        override suspend fun rejectRepaymentProposal(
            debtPublicId: String,
            proposalPublicId: String,
        ): Result<MemberRepaymentProposal> {
            if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
            return errorHandler.safeCall {
                ledgerRequestGuard.guardedCall { api ->
                    api.rejectRepaymentProposal(
                        publicId = debtPublicId,
                        proposalPublicId = proposalPublicId,
                        request = MemberRepaymentProposalRejectRequestDto(),
                        idempotencyKey = UUID.randomUUID().toString(),
                    ).toDomain()
                }
            }
        }
    }
}

/** Shared viewer short-circuit copy (kept in sync with [DebtListViewModel] expectations). */
private const val DEBT_VIEWER_READONLY = "当前角色为只读，无法修改账本。"

private const val DEBT_COUNTERPARTY_LABEL_MAX = 255

private fun DebtDraft.validated(): Result<DebtDraft> = runCatching {
    val cleanLabel = counterpartyLabel.trim()
    require(cleanLabel.isNotBlank()) { "请填写欠款对象。" }
    require(cleanLabel.length <= DEBT_COUNTERPARTY_LABEL_MAX) { "欠款对象名称太长。" }
    require(direction == DebtDirections.I_OWE || direction == DebtDirections.OWED_TO_ME) {
        "请选择欠款方向。"
    }
    require(principalAmountCents > 0L) { "金额必须大于 0。" }
    copy(counterpartyLabel = cleanLabel)
}.mapDebtError()

private fun <T> Result<T>.mapDebtError(): Result<T> = fold(
    onSuccess = { Result.success(it) },
    onFailure = { Result.failure(RepositoryException(it.message ?: "请求参数不正确。")) },
)
