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
    /**
     * ADR-0038 PR-2g.6: adapter for [MerchantAliasUpdateRequest].
     * Same null-default contract — if either ``outbox`` or this
     * adapter is missing, [updateMerchantAliasAllowingOffline]
     * falls back to the direct failure path.
     */
    private val merchantAliasUpdateAdapter: JsonAdapter<MerchantAliasUpdateRequest>? = null,
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
        expectedRowVersion: Long,
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
                        expectedRowVersion = expectedRowVersion,
                        canonicalMerchant = canonicalMerchant?.trim()?.takeIf { it.isNotBlank() },
                        alias = alias?.trim()?.takeIf { it.isNotBlank() },
                        enabled = enabled,
                    ),
                ).toDomain()
            }
        }

    suspend fun deleteMerchantAlias(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Unit> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.deleteMerchantAlias(
                    cleanPublicId,
                    MerchantAliasDeleteRequest(expectedRowVersion = expectedRowVersion),
                )
            }
            Unit
        }

    /**
     * ADR-0038 undo: restore a soft-deleted alias. Online-only — the undo
     * snackbar only appears after a [DeleteOutcome.Synced] delete (the server
     * has the soft-deleted row), so there is no offline/outbox path here.
     * 404 ``merchant_alias_not_found`` once cleanup has purged it.
     */
    suspend fun undoMerchantAlias(publicId: String): Result<MerchantAlias> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.undoMerchantAlias(cleanPublicId).toDomain()
            }
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
        val request = MerchantAliasDeleteRequest(expectedRowVersion = alias.rowVersion)
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
            // expectedRowVersion is the single source of truth.
            outboxRef.enqueue(
                type = PendingMutationType.DeleteMerchantAlias,
                targetId = "merchant_alias:$cleanPublicId",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = alias.rowVersion,
            )
            DeleteOutcome.Queued as DeleteOutcome
        }
    }

    /**
     * ADR-0038 PR-2g.6: offline-aware version of [updateMerchantAlias].
     *
     * Mirrors [RuleRepository.updateCategoryRuleAllowingOffline]
     * exactly (PR-2g.4): direct PATCH first; IOException after
     * session re-check → enqueue + [MerchantAliasSaveOutcome.Queued]
     * with an optimistic projection; HttpException
     * (409 / 4xx / 5xx) → ``Result.failure``.
     *
     * Used by [com.ticketbox.viewmodel.MerchantAliasViewModel.toggleMerchantAlias]
     * — no chained POST reads the returned ``updatedAt``.
     */
    suspend fun updateMerchantAliasAllowingOffline(
        baseline: MerchantAlias,
        canonicalMerchant: String? = null,
        alias: String? = null,
        enabled: Boolean? = null,
    ): Result<MerchantAliasSaveOutcome> = errorHandler.safeCall {
        val cleanPublicId = baseline.publicId.trim()
        require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
        val request = MerchantAliasUpdateRequest(
            expectedRowVersion = baseline.rowVersion,
            canonicalMerchant = canonicalMerchant?.trim()?.takeIf { it.isNotBlank() },
            alias = alias?.trim()?.takeIf { it.isNotBlank() },
            enabled = enabled,
        )
        // [codex round-13 P1] Explicit bind so IOException catch
        // can re-check session activity before enqueue.
        val bound = ledgerRequestGuard.bind()
        try {
            val updated = bound.call { api ->
                api.updateMerchantAlias(cleanPublicId, request).toDomain()
            }
            MerchantAliasSaveOutcome.Synced(updated) as MerchantAliasSaveOutcome
        } catch (networkError: IOException) {
            val outboxRef = outbox
            val adapter = merchantAliasUpdateAdapter
            if (outboxRef == null || adapter == null) {
                throw networkError
            }
            // [codex round-13 P1] session race guard — see PR-2g.4
            // / 2g.5 producers for the rationale.
            bound.requireStillActive()
            // [round-8 P3#5] payload sans token; row.expectedRowVersion
            // is single source of truth.
            outboxRef.enqueue(
                type = PendingMutationType.UpdateMerchantAlias,
                targetId = "merchant_alias:$cleanPublicId",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = baseline.rowVersion,
            )
            MerchantAliasSaveOutcome.Queued(
                projectOptimisticAlias(baseline, canonicalMerchant, alias, enabled),
            ) as MerchantAliasSaveOutcome
        }
    }

    /**
     * Optimistic projection: apply submitted fields over baseline.
     * ``updatedAt`` stays at the pre-mutation value (NOT a
     * server-confirmed token; no chained POST reads it from this
     * return path).
     */
    private fun projectOptimisticAlias(
        baseline: MerchantAlias,
        canonicalMerchant: String?,
        alias: String?,
        enabled: Boolean?,
    ): MerchantAlias = baseline.copy(
        canonicalMerchant = canonicalMerchant?.trim()?.takeIf { it.isNotBlank() }
            ?: baseline.canonicalMerchant,
        alias = alias?.trim()?.takeIf { it.isNotBlank() } ?: baseline.alias,
        enabled = enabled ?: baseline.enabled,
    )
}

/**
 * ADR-0038 PR-2g.6 sealed result for
 * [MerchantRepository.updateMerchantAliasAllowingOffline]. Mirrors
 * [SaveOutcome] (expense) and [CategoryRuleSaveOutcome] (rule).
 * Parallel-defined; future PR may generic-ify into ``SaveOutcome<T>``.
 */
sealed interface MerchantAliasSaveOutcome {
    val alias: MerchantAlias

    /** Server confirmed the PATCH; ``alias.updatedAt`` is the post-mutation token. */
    data class Synced(override val alias: MerchantAlias) : MerchantAliasSaveOutcome

    /**
     * Network failed; row queued in outbox. ``alias`` is the
     * optimistic projection (submitted fields applied over baseline).
     * ``updatedAt`` is pre-mutation; chained POSTs must not consume it.
     */
    data class Queued(override val alias: MerchantAlias) : MerchantAliasSaveOutcome
}
