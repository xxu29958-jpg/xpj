package com.ticketbox.data.repository

import androidx.room.withTransaction
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.FundsInputEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.FinancialAccountDto
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

data class FundsInputState(val input: FundsInput?, val frozen: Boolean = false, val original: OutboxRow? = null)

class FundsRepository internal constructor(private val provider: ApiServiceProvider, private val database: AppDatabase,
    private val outbox: OutboxRepository, private val queries: DebtQueryReader) {
    private val inputs = database.fundsInputDao()
    private val guard = LedgerRequestGuard(provider)
    private val errors = NetworkErrorHandler({ provider.currentSession()?.serverUrl }, "Funds")
    fun access() = provider.observeActiveLedgerAccess()
    suspend fun accountChoices(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_account_choices", "all")),
        DebtReadSpec(FundsWire.choices, { fundsAccountChoices() }, validate = { rows ->
            require(rows.map { it.key }.distinct().size == rows.size)
        }, isNewer = { _, _ -> false }, project = { value, _ -> value }))
    suspend fun overview(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_overview", "all")),
        DebtReadSpec(FundsWire.overview, { fundsOverview() }, validate = { require(it.includedAccounts >= 0) },
            isNewer = { _, _ -> false }, project = { value, _ -> value }))

    suspend fun accounts(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_accounts", "all")),
        DebtReadSpec(FundsWire.listing, { fundsAccounts() }, validate = { rows ->
            require(rows.all { it.rowVersion > 0 } && rows.map { it.publicId }.distinct().size == rows.size)
        }, isNewer = { old, incoming -> old.associateBy { it.publicId }.let { previous ->
            incoming.any { row -> previous[row.publicId]?.rowVersion?.let { it < row.rowVersion } == true }
        } }, project = { rows, _ -> rows }))

    suspend fun detail(binding: LogicalSessionBinding, id: String) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_account", id)),
        DebtReadSpec(FundsWire.account, { fundsAccount(id) }, validate = { require(it.publicId == id) },
            isNewer = { old, incoming -> incoming.rowVersion > old.rowVersion }, project = { value, _ -> value }))

    suspend fun funding(binding: LogicalSessionBinding, id: Long) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "expense_funding", id.toString())),
        DebtReadSpec(FundsWire.funding, { expenseFunding(id) }, validate = { require(it.expenseId == id) },
            isNewer = { old, incoming -> incoming.expenseRowVersion > old.expenseRowVersion }, project = { value, _ -> value }))

    suspend fun installments(binding: LogicalSessionBinding, id: String) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "installments", id)),
        DebtReadSpec(FundsWire.installments, { installments(id) }, validate = { require(it.accountPublicId == id) },
            isNewer = { old, incoming -> incoming.accountRowVersion > old.accountRowVersion }, project = { value, _ -> value }))

    @OptIn(ExperimentalCoroutinesApi::class)
    fun input(binding: LogicalSessionBinding) = inputs.observe(binding.serverUrl, binding.ownerKey, binding.ledgerId).flatMapLatest { row ->
        val value = row?.let { FundsWire.input.fromJson(it.inputJson) }
        if (row?.commandJson == null) flowOf(FundsInputState(value))
        else outbox.observeOriginalCommand(PendingMutationType.FinancialAccountCommand, row.originalKey)
            .map { FundsInputState(value, true, it.singleOrNull()) }
    }

    suspend fun save(value: FundsInput) = errors.safeCall {
        val binding = value.binding
        outbox.withActiveBinding(guard.bindExact(binding)) {
            require(com.ticketbox.domain.model.ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色只读，原输入已保留。" }
            val old = inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId)
            require(old == null || old.originalKey == value.key && old.commandJson == null) { "请先核对原资金任务。" }
            inputs.put(FundsInputEntity(binding.serverUrl, binding.ownerKey, binding.ledgerId, value.key, FundsWire.input.toJson(value)))
        }
    }

    suspend fun submit(binding: LogicalSessionBinding) = errors.safeCall {
        val bound = guard.bindExact(binding)
        val row = outbox.withActiveBinding(bound) {
            val old = requireNotNull(inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId))
            val value = requireNotNull(FundsWire.input.fromJson(old.inputJson))
            require(value.binding == binding) { "身份已变化，请返回原身份继续。" }
            if (old.commandJson != null) old else old.copy(commandJson = FundsWire.command.toJson(value.command())).also { inputs.put(it) }
        }
        val command = requireNotNull(FundsWire.command.fromJson(requireNotNull(row.commandJson)))
        outbox.enqueueOriginalCreation(bound, PendingMutationIntent(PendingMutationType.FinancialAccountCommand,
            command.target(row.originalKey), row.commandJson, command.version, row.originalKey))
    }

    suspend fun retry(binding: LogicalSessionBinding) = errors.safeCall {
        val row = requireNotNull(input(binding).first().original)
        require(outbox.resolveFailed(row.id, FailedResolution.Retry(), guard.bindExact(binding))) { "原提交状态已变化，请刷新核对。" }
    }

    suspend fun finish(binding: LogicalSessionBinding) = errors.safeCall {
        val bound = guard.bindExact(binding)
        val state = input(binding).first()
        require(!state.frozen || state.original?.status == PendingMutationStatus.Done) { "原提交尚未确认，请先核实结果。" }
        outbox.withActiveBinding(bound) {
            state.input?.let { inputs.remove(binding.serverUrl, binding.ownerKey, binding.ledgerId, it.key) }
        }
        Unit
    }

    /** Retire a proven refusal and return its money to the existing raw-input owner in one Room commit. */
    internal suspend fun reopenExpenseConfirmation(binding: LogicalSessionBinding, row: OutboxRow,
        input: ExpenseFactOriginalInput, originals: ExpenseFactInputActions) = errors.safeCall {
        require(row.canReviewFunding() && input.binding == binding && input.formKey == "pending_funding" &&
            row.targetId == "expense:${input.expenseId}") { "原提交结果尚未核实，不能另行提交。" }
        outbox.withActiveBinding(guard.bindExact(binding)) { active -> database.withTransaction {
            require(com.ticketbox.domain.model.ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色只读，原提交已保留。" }
            val stored = database.pendingMutationDao().findByIdempotencyKeys(active.ownerStorageKey, active.ledgerId,
                row.type.wireValue, listOf(requireNotNull(row.idempotencyKey))).singleOrNull()
            require(stored != null && stored.id == row.id && stored.serverUrl == active.serverUrl &&
                stored.payload == row.payloadJson && stored.status == row.status.wireValue && stored.blocksFollowing == row.blocksFollowing) {
                "原提交状态已变化，请重新核对。"
            }
            originals.saveFactInput(null, input).getOrThrow()
            require(database.pendingMutationDao().abandonOriginalCommand(row.id, active.ownerStorageKey,
                active.ledgerId, row.status.wireValue, java.time.Instant.now().toString()) == 1) { "原提交已变化，原输入保留。" }
        } }
    }

    suspend fun review(binding: LogicalSessionBinding, accounts: List<FinancialAccountDto>) = errors.safeCall {
        val state = input(binding).first()
        val old = requireNotNull(state.input)
        val row = requireNotNull(state.original)
        require(old.binding == binding && (row.status == PendingMutationStatus.Conflict ||
            row.status == PendingMutationStatus.Failed && row.lastError?.startsWith(FUNDS_REFUSED) == true)) {
            "尚不能确定原提交是否生效，请保留原任务并核实。"
        }
        val target = accounts.firstOrNull { it.publicId == old.accountId }
        val payer = accounts.firstOrNull { it.publicId == old.payerId }
        require(old.mode in setOf("create", "funding") || target != null) { "账户当前不可用，原输入保留。" }
        require(target == null || target.currencyCode == old.currency) { "账户币种已变化，请核对原输入。" }
        require(payer == null || payer.currencyCode == old.payerCurrency) { "付款币种已变化，请核对原输入。" }
        val funding = if (old.mode == "funding") funding(binding, requireNotNull(old.expenseId)).getOrThrow().also {
            require(!it.fromCache && it.value.currencyCode == old.currency && it.value.canEdit) { "请联网核对消费及付款权限；原输入保留。" }
        }.value else null
        val reviewedParts = if (funding != null) requireNotNull(fundingInputAdapter.fromJson(old.fundingJson)).map { part ->
            val account = requireNotNull(accounts.firstOrNull { it.publicId == part.accountId }) { "原付款账户当前不可用。" }
            require(account.currencyCode == part.accountCurrency) { "原付款币种已变化，请保留原输入核对。" }
            part.copy(accountVersion = account.rowVersion)
        } else null
        val bound = guard.bindExact(binding)
        outbox.withActiveBinding(bound) { active -> database.withTransaction {
            require(com.ticketbox.domain.model.ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色只读，原输入已保留。" }
            require(database.pendingMutationDao().abandonOriginalCommand(row.id, active.ownerStorageKey,
                active.ledgerId, row.status.wireValue, java.time.Instant.now().toString()) == 1) {
                "原提交状态已变化，请重新核对。"
            }
            val next = old.copy(key = java.util.UUID.randomUUID().toString(), version = funding?.expenseRowVersion ?: target?.rowVersion ?: 0,
                calendarRevision = target?.calendarRevision ?: 0, payerVersion = payer?.rowVersion ?: 0,
                fundingJson = reviewedParts?.let(fundingInputAdapter::toJson) ?: old.fundingJson)
            inputs.put(FundsInputEntity(binding.serverUrl, binding.ownerKey, binding.ledgerId, next.key, FundsWire.input.toJson(next)))
        } }
    }
}
