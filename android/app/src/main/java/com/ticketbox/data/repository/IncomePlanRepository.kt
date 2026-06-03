package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

/**
 * v1.1 monthly income plan repository. CRUD over /api/income-plans plus
 * an "active total" aggregate that the budget overview card surfaces.
 *
 * Failure semantics follow the rest of the repository layer: every
 * suspend method returns ``Result<T>``; viewer role short-circuits
 * write calls without hitting the network.
 */
interface IncomePlanActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    suspend fun listActive(): Result<IncomePlanListing>
    suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>>
    suspend fun create(draft: IncomePlanDraft): Result<IncomePlan>
    suspend fun update(publicId: String, patch: IncomePlanPatch): Result<IncomePlan>
    suspend fun archive(publicId: String, expectedRowVersion: Long): Result<IncomePlan>
    suspend fun restore(publicId: String, expectedRowVersion: Long): Result<IncomePlan>
}

data class IncomePlanListing(
    val plans: List<IncomePlan>,
    val totalActiveAmountCents: Long,
)

class IncomePlanRepository(
    apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(
        apiClient, settingsStore, tokenStore,
    ),
) : IncomePlanActions {

    private val ledgerRequestGuard = LedgerRequestGuard(
        settingsStore,
        tokenStore,
        apiProvider,
    )
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "IncomePlan",
        statusMessages = mapOf(
            404 to "收入计划不存在。",
            409 to "已归档的收入计划不能直接修改，请先恢复。",
            422 to "请检查输入的金额和发薪日。",
        ),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    override suspend fun listActive(): Result<IncomePlanListing> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                val response = api.listIncomePlans(status = "active")
                IncomePlanListing(
                    plans = response.items.map { it.toDomain() },
                    totalActiveAmountCents = response.totalActiveAmountCents,
                )
            }
        }

    override suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.listIncomePlans(status = status.wireValue)
                    .items.map { it.toDomain() }
            }
        }

    override suspend fun create(draft: IncomePlanDraft): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.createIncomePlan(draft.toCreateRequest()).toDomain()
            }
        }
    }

    override suspend fun update(
        publicId: String,
        patch: IncomePlanPatch,
    ): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateIncomePlan(publicId, patch.toUpdateRequest()).toDomain()
            }
        }
    }

    override suspend fun archive(publicId: String, expectedRowVersion: Long): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.archiveIncomePlan(
                    publicId,
                    com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto(expectedRowVersion),
                ).toDomain()
            }
        }
    }

    override suspend fun restore(publicId: String, expectedRowVersion: Long): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.restoreIncomePlan(
                    publicId,
                    com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto(expectedRowVersion),
                ).toDomain()
            }
        }
    }
}
