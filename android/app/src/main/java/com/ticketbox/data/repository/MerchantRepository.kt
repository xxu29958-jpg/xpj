package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.io.IOException
import java.util.UUID

/**
 * Merchant governance CRUD. Alias outbox behavior stays here; catalog actions
 * are online-only for this slice, so they share the guarded API/session plumbing
 * without widening the offline mutation protocol yet.
 */
@Suppress("TooManyFunctions")
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

    suspend fun merchantCatalog(includeHidden: Boolean = true): Result<List<MerchantCatalog>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.merchantCatalog(includeHidden = includeHidden).items.map { it.toDomain() }
            }
        }

    suspend fun createMerchantCatalog(displayName: String): Result<MerchantCatalog> =
        errorHandler.safeCall {
            val cleanDisplayName = displayName.trim()
            require(cleanDisplayName.isNotBlank()) { "请输入商家名称。" }
            ledgerRequestGuard.guardedCall { api ->
                api.createMerchantCatalog(
                    MerchantCatalogCreateRequest(displayName = cleanDisplayName),
                ).toDomain()
            }
        }

    suspend fun updateMerchantCatalog(
        publicId: String,
        expectedRowVersion: Long,
        displayName: String? = null,
        status: String? = null,
    ): Result<MerchantCatalog> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家。" }
            ledgerRequestGuard.guardedCall { api ->
                api.updateMerchantCatalog(
                    cleanPublicId,
                    MerchantCatalogUpdateRequest(
                        expectedRowVersion = expectedRowVersion,
                        displayName = displayName?.trim()?.takeIf { it.isNotBlank() },
                        status = status?.trim()?.takeIf { it.isNotBlank() },
                    ),
                    UUID.randomUUID().toString(),
                ).toDomain()
            }
        }

    suspend fun deleteMerchantCatalog(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<MerchantCatalog> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个商家。" }
            ledgerRequestGuard.guardedCall { api ->
                api.deleteMerchantCatalog(
                    cleanPublicId,
                    MerchantCatalogDeleteRequest(expectedRowVersion = expectedRowVersion),
                    UUID.randomUUID().toString(),
                ).toDomain()
            }
        }

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
                    // ADR-0042: single-use key — direct-only path, no replay.
                    UUID.randomUUID().toString(),
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
                    // ADR-0042: single-use key — direct-only path, no replay.
                    UUID.randomUUID().toString(),
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
        // ADR-0042: one intent-time key for both the direct attempt and the
        // outbox replay — a committed-but-unseen DELETE replays with this SAME
        // key so the server HITs the recorded success instead of false-409ing
        // on the now-stale token. The dispatcher replays it from
        // row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        val outboxRef = outbox
        val adapter = merchantAliasDeleteAdapter
        if (outboxRef == null || adapter == null) {
            // Wiring missing — direct-only; failures surface as Result.failure.
            bound.call { api ->
                api.deleteMerchantAlias(cleanPublicId, request, idempotencyKey)
            }
            return@safeCall DeleteOutcome.Synced
        }
        if (outboxRef.activeForTarget("merchant_alias:$cleanPublicId").isNotEmpty()) {
            // Per-target FIFO guard (codex follow-up review) — a direct DELETE
            // must not jump an unresolved queued mutation for the same alias.
            enqueueDeleteMerchantAlias(bound, outboxRef, adapter, cleanPublicId, request, alias.rowVersion, idempotencyKey)
            return@safeCall DeleteOutcome.Queued
        }
        try {
            bound.call { api ->
                api.deleteMerchantAlias(cleanPublicId, request, idempotencyKey)
            }
            DeleteOutcome.Synced as DeleteOutcome
        } catch (networkError: IOException) {
            enqueueDeleteMerchantAlias(bound, outboxRef, adapter, cleanPublicId, request, alias.rowVersion, idempotencyKey)
            DeleteOutcome.Queued as DeleteOutcome
        }
    }

    /**
     * Shared DeleteMerchantAlias enqueue for the queue-jump guard and the
     * IOException fallback. [codex round-13 P1] session race guard before
     * enqueue + [round-8 P3#5] payload token strip (row.expectedRowVersion is
     * the single source of truth; dispatcher overwrites on replay).
     */
    private suspend fun enqueueDeleteMerchantAlias(
        bound: BoundLedgerRequest,
        outboxRef: OutboxRepository,
        adapter: com.squareup.moshi.JsonAdapter<MerchantAliasDeleteRequest>,
        cleanPublicId: String,
        request: MerchantAliasDeleteRequest,
        token: Long,
        idempotencyKey: String,
    ) {
        bound.requireStillActive()
        outboxRef.enqueue(
            type = PendingMutationType.DeleteMerchantAlias,
            targetId = "merchant_alias:$cleanPublicId",
            payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
            expectedRowVersion = token,
            idempotencyKey = idempotencyKey,
        )
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
        // ADR-0042: one intent-time key for both the direct attempt and the
        // replay — see deleteMerchantAliasAllowingOffline for the rationale.
        val idempotencyKey = UUID.randomUUID().toString()
        val outboxRef = outbox
        val adapter = merchantAliasUpdateAdapter
        if (outboxRef == null || adapter == null) {
            // Wiring missing — direct-only; failures surface as Result.failure.
            val updated = bound.call { api ->
                api.updateMerchantAlias(cleanPublicId, request, idempotencyKey).toDomain()
            }
            return@safeCall MerchantAliasSaveOutcome.Synced(updated)
        }
        if (outboxRef.activeForTarget("merchant_alias:$cleanPublicId").isNotEmpty()) {
            // Per-target FIFO guard — see deleteMerchantAliasAllowingOffline.
            enqueueUpdateMerchantAlias(bound, outboxRef, adapter, cleanPublicId, request, baseline.rowVersion, idempotencyKey)
            return@safeCall MerchantAliasSaveOutcome.Queued(
                projectOptimisticAlias(baseline, canonicalMerchant, alias, enabled),
            )
        }
        try {
            val updated = bound.call { api ->
                api.updateMerchantAlias(cleanPublicId, request, idempotencyKey).toDomain()
            }
            MerchantAliasSaveOutcome.Synced(updated) as MerchantAliasSaveOutcome
        } catch (networkError: IOException) {
            enqueueUpdateMerchantAlias(bound, outboxRef, adapter, cleanPublicId, request, baseline.rowVersion, idempotencyKey)
            MerchantAliasSaveOutcome.Queued(
                projectOptimisticAlias(baseline, canonicalMerchant, alias, enabled),
            ) as MerchantAliasSaveOutcome
        }
    }

    /**
     * Shared UpdateMerchantAlias enqueue for the queue-jump guard and the
     * IOException fallback — same race-guard + token-strip contract as
     * [enqueueDeleteMerchantAlias].
     */
    private suspend fun enqueueUpdateMerchantAlias(
        bound: BoundLedgerRequest,
        outboxRef: OutboxRepository,
        adapter: com.squareup.moshi.JsonAdapter<MerchantAliasUpdateRequest>,
        cleanPublicId: String,
        request: MerchantAliasUpdateRequest,
        token: Long,
        idempotencyKey: String,
    ) {
        bound.requireStillActive()
        outboxRef.enqueue(
            type = PendingMutationType.UpdateMerchantAlias,
            targetId = "merchant_alias:$cleanPublicId",
            payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
            expectedRowVersion = token,
            idempotencyKey = idempotencyKey,
        )
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
