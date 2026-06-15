package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
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
    suspend fun createDebt(draft: DebtDraft): Result<Debt>
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
            404 to "没有找到这笔欠款。",
            409 to "欠款状态已变化，请刷新后再试。",
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

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
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
}

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
