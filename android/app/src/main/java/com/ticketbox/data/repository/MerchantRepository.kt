package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.io.IOException

/**
 * Merchant-alias CRUD. Extracted from ExpenseRepository.
 */
class MerchantRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
    /**
     * ADR-0038 PR-2g.5: optional outbox + delete-adapter for the
     * offline-aware [deleteMerchantAliasAllowingOffline] entrypoint.
     * ``null`` defaults preserve every pre-PR-2g.5 test caller
     * (they fall back to the direct failure path on IOException).
     */
    private val outbox: OutboxRepository? = null,
    private val merchantAliasDeleteAdapter: JsonAdapter<MerchantAliasDeleteRequest>? = null,
) {
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Merchant",
        statusMessages = mapOf(404 to "商家别名不存在。"),
    )

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    suspend fun merchantAliases(): Result<List<MerchantAlias>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.merchantAliases().items.map { it.toDomain() }
            }
        }

    suspend fun createMerchantAlias(
        canonicalMerchant: String,
        alias: String,
    ): Result<MerchantAlias> =
        errorHandler.safeCall {
            val cleanCanonical = canonicalMerchant.trim()
            val cleanAlias = alias.trim()
            require(cleanCanonical.isNotBlank()) { "请输入标准商家名。" }
            require(cleanAlias.isNotBlank()) { "请输入别名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.createMerchantAlias(
                    MerchantAliasRequest(
                        canonicalMerchant = cleanCanonical,
                        alias = cleanAlias,
                        enabled = true,
                    ),
                ).toDomain()
            }
        }

    // ADR-0038 PR-2e: PATCH/DELETE merchant alias require an optimistic-
    // concurrency token. Server rejects stale snapshots as 409 ``state_conflict``
    // → NetworkErrorHandler surfaces "已被其它设备修改" to the user.
    suspend fun updateMerchantAlias(
        publicId: String,
        expectedUpdatedAt: String,
        canonicalMerchant: String? = null,
        alias: String? = null,
        enabled: Boolean? = null,
    ): Result<MerchantAlias> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.updateMerchantAlias(
                    cleanPublicId,
                    MerchantAliasUpdateRequest(
                        expectedUpdatedAt = expectedUpdatedAt,
                        canonicalMerchant = canonicalMerchant?.trim()?.takeIf { it.isNotBlank() },
                        alias = alias?.trim()?.takeIf { it.isNotBlank() },
                        enabled = enabled,
                    ),
                ).toDomain()
            }
        }

    suspend fun deleteMerchantAlias(
        publicId: String,
        expectedUpdatedAt: String,
    ): Result<Unit> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.deleteMerchantAlias(
                    cleanPublicId,
                    MerchantAliasDeleteRequest(expectedUpdatedAt = expectedUpdatedAt),
                )
            }
            Unit
        }

    /**
     * ADR-0038 PR-2g.5: offline-aware version of [deleteMerchantAlias].
     *
     * Same pattern as [RuleRepository.deleteCategoryRuleAllowingOffline]:
     * IOException → enqueue + [DeleteOutcome.Queued]; anything else
     * (HttpException 4xx / 409 / 5xx) → ``Result.failure``.
     * Direct [deleteMerchantAlias] above preserved for callers that
     * don't want offline routing.
     */
    suspend fun deleteMerchantAliasAllowingOffline(
        alias: MerchantAlias,
    ): Result<DeleteOutcome> = errorHandler.safeCall {
        val cleanPublicId = alias.publicId.trim()
        require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
        val request = MerchantAliasDeleteRequest(expectedUpdatedAt = alias.updatedAt)
        // [codex round-13 P1] Explicit bind for IOException-catch
        // session re-check. See [RuleRepository.deleteCategoryRuleAllowingOffline]
        // for the rationale: ``guardedCall``'s post-check is
        // skipped on exception paths, so without this an old-
        // ledger DELETE could land in the new ledger's outbox
        // after a switch.
        val bound = ledgerRequestGuard.bind()
        try {
            bound.call { api ->
                api.deleteMerchantAlias(cleanPublicId, request)
            }
            DeleteOutcome.Synced as DeleteOutcome
        } catch (networkError: IOException) {
            val outboxRef = outbox
            val adapter = merchantAliasDeleteAdapter
            if (outboxRef == null || adapter == null) {
                throw networkError
            }
            // [codex round-13 P1] Throws if session changed since
            // the bind above — prevents wrong-session enqueue.
            bound.requireStillActive()
            // [round-8 P3#5] payload carries no token; row's
            // expectedUpdatedAt is the single source of truth.
            outboxRef.enqueue(
                type = PendingMutationType.DeleteMerchantAlias,
                targetId = "merchant_alias:$cleanPublicId",
                payloadJson = adapter.toJson(request.copy(expectedUpdatedAt = "")),
                expectedUpdatedAt = alias.updatedAt,
            )
            DeleteOutcome.Queued as DeleteOutcome
        }
    }
}
