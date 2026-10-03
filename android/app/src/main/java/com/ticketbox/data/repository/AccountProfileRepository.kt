package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.AccountProfileDto
import com.ticketbox.data.remote.dto.AccountProfileRenameDto

data class AccountProfile(val accountPublicId: String, val displayName: String)

interface AccountProfileActions {
    fun currentBinding(): LogicalSessionBinding?
    suspend fun read(binding: LogicalSessionBinding): Result<AccountProfile>
    suspend fun rename(binding: LogicalSessionBinding, name: String, expectedName: String): Result<AccountProfile>
}

/** Online account metadata; ledger role and financial Outbox are not writers. */
class AccountProfileRepository(
    apiProvider: ApiServiceProvider,
    private val coordinator: LocalLedgerSessionCoordinator,
) : AccountProfileActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "AccountProfile")

    override fun currentBinding(): LogicalSessionBinding? = guard.captureLogicalBinding()

    override suspend fun read(binding: LogicalSessionBinding): Result<AccountProfile> = request(binding) { bound ->
        bound.call { it.accountProfile() }
    }

    override suspend fun rename(binding: LogicalSessionBinding, name: String, expectedName: String): Result<AccountProfile> =
        request(binding) { bound ->
            val clean = name.trim()
            require(clean.isNotEmpty() && clean.length <= 120) { "账号名称需在 1–120 个字符之间。" }
            bound.call { it.renameAccountProfile(AccountProfileRenameDto(clean, expectedName)) }
        }

    private suspend fun request(
        binding: LogicalSessionBinding,
        send: suspend (BoundLedgerRequest) -> AccountProfileDto,
    ): Result<AccountProfile> = errors.safeCall {
        val snapshot = coordinator.currentSnapshot()
        val bound = guard.bindExact(binding)
        val dto = send(bound)
        require(dto.accountPublicId == bound.outboxBinding.owner?.accountPublicId) { "账号已变化，请重新打开账号设置。" }
        val applied = coordinator.applyTransitionIfCurrent(snapshot) { current ->
            LedgerSessionTransition(LocalSessionChange.RefreshProjection, current.copy(accountName = dto.displayName))
        }
        if (!applied) {
            throw RepositoryException("登录状态已变化，请重新打开账号设置。")
        }
        AccountProfile(dto.accountPublicId, dto.displayName)
    }
}
