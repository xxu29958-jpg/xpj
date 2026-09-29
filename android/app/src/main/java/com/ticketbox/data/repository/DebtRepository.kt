package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalRejectRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalWithdrawRequestDto
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.domain.model.ledgerRoleCanModify
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

/**
 * Canonical Debt queries and existing online fact/proposal operations.
 * External creation and adjustment belong to [DebtCreationActions] and [DebtWriteActions].
 */
interface DebtActions {
    fun observeReadAccessDenials(): Flow<SnapshotAccessDenial> = emptyFlow()
    fun observeResourceDenials(): Flow<DebtReadResourceDenial> = emptyFlow()
    fun canModifyLedger(): Boolean
    suspend fun listDebts(lens: DebtListLens = DebtListLens.Ledger, expectedBinding: LogicalSessionBinding? = null): Result<ReadSnapshot<DebtListPage>>
    suspend fun getDebt(publicId: String): Result<ReadSnapshot<Debt>>
    suspend fun parseDebtBillImage(expectedBinding: LogicalSessionBinding, fileName: String,
        contentType: String?, bytes: ByteArray): Result<DebtBillSuggestion>
}

/**
 * 账本欠款列表页（PR#255 R6）：[debts] + 服务端随列表信封下发的**安装级 currency capability**
 * （ADR-0061 C02/C03；与每条 record 的 `homeCurrencyCode` 同一 binding）。空账本没有 record 级
 * 币种可得时，消费方（DebtListViewModel）用 [ledgerHomeCurrencyCode] 解析账本币种放行首笔创建；
 * null = 旧服务端未下发（调用方 fail closed，不得回落默认 CNY 猜测）。
 */
data class DebtListPage(
    val debts: List<Debt>,
    val ledgerHomeCurrencyCode: String?,
)

/**
 * Personal receivables: this account's local ledger obligations plus cross-ledger member
 * receivables. The server selects participants and redacts cross-ledger identity. Read-only.
 */
interface ReceivablesActions {
    fun observeReadAccessDenials(): Flow<SnapshotAccessDenial> = emptyFlow()
    fun observeResourceDenials(): Flow<DebtReadResourceDenial> = emptyFlow()
    suspend fun listReceivables(): Result<ReadSnapshot<List<Debt>>>
}

/** Participant commands reuse the canonical server owners and the original displayed task. */
interface DebtProposalActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    suspend fun listRepaymentProposals(task: DebtTask): Result<List<MemberRepaymentProposal>>
    suspend fun submit(
        task: DebtTask,
        command: MemberSettlementCommand,
        idempotencyKey: String,
    ): Result<MemberSettlementResult>
}

class DebtRepository internal constructor(
    private val apiProvider: ApiServiceProvider,
    private val queryReader: DebtQueryReader,
    val splitAgreement: SplitAgreementActions? = null,
) : DebtActions, ReceivablesActions {
    val activity: DebtActivityQueries = DebtActivityRepository(queryReader)
    override fun observeReadAccessDenials(): Flow<SnapshotAccessDenial> = queryReader.readAccessDenials
    override fun observeResourceDenials(): Flow<DebtReadResourceDenial> = queryReader.readResourceDenials
    suspend fun prepareReadsBeforeDispatch(row: OutboxRow) = queryReader.prepareDebtDispatch(row)
    suspend fun finishReadDispatch(row: OutboxRow, result: DispatchResult?) = queryReader.finishDebtDispatch(row, result)
    suspend fun invalidateReadsAfterAccepted(row: OutboxRow) = queryReader.invalidateDebtAccepted(row)
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
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

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override suspend fun listDebts(lens: DebtListLens, expectedBinding: LogicalSessionBinding?): Result<ReadSnapshot<DebtListPage>> {
        val binding = expectedBinding ?: ledgerRequestGuard.captureLogicalBinding() ?: return Result.failure(RepositoryException("请重新绑定账本。"))
        return queryReader.list(binding, lens)
    }

    override suspend fun getDebt(publicId: String): Result<ReadSnapshot<Debt>> {
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return Result.failure(RepositoryException("请重新绑定账本。"))
        return queryReader.detail(binding, publicId)
    }

    override suspend fun listReceivables(): Result<ReadSnapshot<List<Debt>>> {
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return Result.failure(RepositoryException("请重新绑定账本。"))
        return queryReader.receivables(binding)
    }
    override suspend fun parseDebtBillImage(
        expectedBinding: LogicalSessionBinding,
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> {
        if (!canModifyLedger()) return Result.failure(RepositoryException(DEBT_VIEWER_READONLY))
        if (bytes.isEmpty()) return Result.failure(RepositoryException("请选择一张账单截图。"))
        return errorHandler.safeCall {
            val cleanName = fileName
                .trim()
                .ifBlank { "ticketbox-debt-bill.jpg" }
                .replace(Regex("[\\\\/:*?\"<>|]"), "_")
            val mediaType = (contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()
            val body = bytes.toRequestBody(mediaType)
            val filePart = MultipartBody.Part.createFormData("file", cleanName, body)
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.parseDebtBill(filePart).toDomain()
            }
        }
    }

    val proposals: DebtProposalActions = ProposalActions()

    private inner class ProposalActions : DebtProposalActions {
        override fun currentAccess(): LedgerAccessContext? {
            val session = apiProvider.currentSession() ?: return null
            val binding = session.toBoundSessionSnapshotOrNull()?.logicalBinding ?: return null
            return LedgerAccessContext(binding, ledgerRoleCanModify(session.identity.role))
        }

        override fun observeAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

        override suspend fun listRepaymentProposals(task: DebtTask): Result<List<MemberRepaymentProposal>> =
            queryReader.freshQuery(task) { repaymentProposals(task.debtPublicId).items.map { it.toDomain() } }

        override suspend fun submit(
            task: DebtTask,
            command: MemberSettlementCommand,
            idempotencyKey: String,
        ): Result<MemberSettlementResult> = errorHandler.safeCall {
            if (currentAccess()?.canModify != true) throw RepositoryException(DEBT_VIEWER_READONLY)
            if (idempotencyKey.isBlank()) throw RepositoryException("缺少原提交标识，请重新核对。")
            if (command is MemberSettlementCommand.Propose && command.amountCents <= 0L) {
                throw RepositoryException("还款金额必须大于 0。")
            }
            if (command is MemberSettlementCommand.Confirm && command.amountCents != null && command.amountCents <= 0L) {
                throw RepositoryException("确认金额必须大于 0。")
            }
            ledgerRequestGuard.bindExact(task.binding).call { api ->
                queryReader.direct(task.binding, task.debtPublicId) { when (command) {
                    is MemberSettlementCommand.Propose -> MemberSettlementResult.Proposal(
                        api.createRepaymentProposal(task.debtPublicId, MemberRepaymentProposalCreateRequestDto(
                            proposedAmountCents = command.amountCents, note = command.note,
                            supersedesProposalPublicId = command.supersedesProposalPublicId), idempotencyKey).toDomain())
                    is MemberSettlementCommand.Confirm -> MemberSettlementResult.DebtChanged(
                        api.confirmRepaymentProposal(task.debtPublicId, command.proposalPublicId,
                            MemberRepaymentProposalConfirmRequestDto(confirmedAmountCents = command.amountCents, expectedRowVersion = command.expectedRowVersion),
                            idempotencyKey).toDomain())
                    is MemberSettlementCommand.Withdraw -> MemberSettlementResult.Proposal(
                        api.withdrawRepaymentProposal(task.debtPublicId, command.proposalPublicId,
                            MemberRepaymentProposalWithdrawRequestDto(), idempotencyKey).toDomain())
                    is MemberSettlementCommand.Reject -> MemberSettlementResult.Proposal(
                        api.rejectRepaymentProposal(task.debtPublicId, command.proposalPublicId,
                            MemberRepaymentProposalRejectRequestDto(), idempotencyKey).toDomain())
                    is MemberSettlementCommand.Forgive -> MemberSettlementResult.DebtChanged(
                        api.forgiveDebt(task.debtPublicId, DebtForgiveCreateRequestDto(command.expectedRowVersion),
                            idempotencyKey).toDomain())
                } }
            }
        }
    }
}

/** Shared viewer short-circuit copy (kept in sync with [DebtListViewModel] expectations). */
private const val DEBT_VIEWER_READONLY = "当前角色为只读，无法修改账本。"
