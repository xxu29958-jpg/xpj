package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollback
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.io.IOException

/**
 * Category-rule CRUD and bulk rule application over confirmed expenses.
 *
 * Extracted from ExpenseRepository to keep that god-object focused on
 * account / expense / sync concerns. ``onConfirmedChanged`` is fired after a
 * successful bulk apply or rollback so the AppContainer can refresh the
 * confirmed-cache via ExpenseRepository.syncConfirmed().
 */
class RuleRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
    private val onConfirmedChanged: suspend () -> Unit = { },
    /**
     * ADR-0038 PR-2g.4: outbox surface for the offline-aware
     * [updateCategoryRuleAllowingOffline] entrypoint. ``null``
     * keeps every pre-PR-2g.4 test that didn't wire the outbox at
     * the old behaviour — the new method falls back to the direct
     * failure path when outbox/adapter aren't both supplied.
     */
    private val outbox: OutboxRepository? = null,
    private val categoryRuleUpdateAdapter: JsonAdapter<CategoryRuleUpdateRequest>? = null,
    /**
     * ADR-0038 PR-2g.5: adapter for [CategoryRuleDeleteRequest].
     * Same null-default contract as ``categoryRuleUpdateAdapter``
     * — if either ``outbox`` or this adapter is missing,
     * [deleteCategoryRuleAllowingOffline] falls back to the direct
     * failure path.
     */
    private val categoryRuleDeleteAdapter: JsonAdapter<CategoryRuleDeleteRequest>? = null,
) {
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Rule",
        statusMessages = mapOf(404 to "分类规则不存在。"),
    )

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    suspend fun categoryRules(): Result<List<CategoryRule>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.categoryRules().map { it.toDomain() }
            }
        }

    suspend fun createCategoryRule(
        keyword: String,
        category: String,
        priority: Int,
    ): Result<CategoryRule> =
        errorHandler.safeCall {
            val cleanKeyword = keyword.trim()
            val cleanCategory = category.trim()
            require(cleanKeyword.isNotBlank()) { "请输入关键词。" }
            require(cleanCategory.isNotBlank()) { "请输入分类。" }
            ledgerRequestGuard.guardedCall { api ->
                api.createCategoryRule(
                    CategoryRuleRequest(
                        keyword = cleanKeyword,
                        category = cleanCategory,
                        enabled = true,
                        priority = priority,
                    ),
                ).toDomain()
            }
        }

    // ADR-0038 PR-1: PATCH/DELETE require an optimistic-concurrency token.
    // Server returns 409 ``state_conflict`` on stale snapshots →
    // NetworkErrorHandler surfaces it through the standard mapping.
    suspend fun updateCategoryRule(
        id: Long,
        expectedUpdatedAt: String,
        keyword: String? = null,
        category: String? = null,
        enabled: Boolean? = null,
        priority: Int? = null,
    ): Result<CategoryRule> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateCategoryRule(
                    id,
                    CategoryRuleUpdateRequest(
                        expectedUpdatedAt = expectedUpdatedAt,
                        keyword = keyword,
                        category = category,
                        enabled = enabled,
                        priority = priority,
                    ),
                ).toDomain()
            }
        }

    /**
     * ADR-0038 PR-2g.4: offline-aware version of [updateCategoryRule].
     *
     * Direct PATCH first; if it fails with IOException AND outbox
     * wiring is present, enqueue the row and return
     * [CategoryRuleSaveOutcome.Queued] with an optimistic projection
     * (the rule with the user's edits applied over baseline). Any
     * other failure mode (4xx / 409 / 5xx HttpException) propagates
     * to safeCall and surfaces as Result.failure.
     *
     * Mirrors [ExpensePendingRepository.saveExpenseAllowingOffline]
     * — see that KDoc + PR-2g.3 CHANGELOG for the rationale (sealed
     * outcome so chained callers can't accidentally treat a queued
     * row as a server-confirmed success).
     *
     * The three CategoryRulesViewModel call sites (full edit /
     * toggle / [no chain]) don't hand the returned ``updatedAt`` to
     * a follow-up POST, so they can all use this method.
     * [deleteCategoryRule] is NOT routed through outbox in this PR
     * — that's PR-2g.4 follow-up (DELETE has different shape and
     * ``DeleteCategoryRuleDispatcher`` hasn't landed yet).
     */
    suspend fun updateCategoryRuleAllowingOffline(
        baseline: CategoryRule,
        keyword: String? = null,
        category: String? = null,
        enabled: Boolean? = null,
        priority: Int? = null,
    ): Result<CategoryRuleSaveOutcome> = errorHandler.safeCall {
        val request = CategoryRuleUpdateRequest(
            expectedUpdatedAt = baseline.updatedAt,
            keyword = keyword,
            category = category,
            enabled = enabled,
            priority = priority,
        )
        // [codex round-13 P1] Bind explicitly so we can re-check
        // session activity in the IOException catch. ``guardedCall``
        // performs ``requireStillActive()`` only when the block
        // returns normally; an IOException jumps straight to the
        // catch and skips it, which would otherwise let a delete
        // queued under ledger A land in the outbox after the user
        // switched to ledger B (clearAll wipes the OLD rows; the
        // NEW enqueue happens AFTER that wipe). Re-checking before
        // enqueue closes the race.
        val bound = ledgerRequestGuard.bind()
        try {
            val updated = bound.call { api ->
                api.updateCategoryRule(baseline.id, request).toDomain()
            }
            CategoryRuleSaveOutcome.Synced(updated) as CategoryRuleSaveOutcome
        } catch (networkError: IOException) {
            val outboxRef = outbox
            val adapter = categoryRuleUpdateAdapter
            if (outboxRef == null || adapter == null) {
                // Wiring missing — fall back to the original
                // failure path so we don't pretend to have saved.
                throw networkError
            }
            // [codex round-13 P1] Session-change race guard.
            // Throws RepositoryException with "账本已切换…" if the
            // active ledger differs from the one we bound to.
            // Crucially, this runs BEFORE outbox.enqueue, so a
            // mid-flight switch can't slip an old-session row into
            // the now-current ledger's queue.
            bound.requireStillActive()
            // [round-8 P3#5] strip token from payload — row's
            // expectedUpdatedAt is the single source of truth.
            // Dispatcher overwrites the request token from the row
            // on replay (see UpdateCategoryRuleDispatcher).
            outboxRef.enqueue(
                type = PendingMutationType.UpdateCategoryRule,
                targetId = "category_rule:${baseline.id}",
                payloadJson = adapter.toJson(request.copy(expectedUpdatedAt = "")),
                expectedUpdatedAt = baseline.updatedAt,
            )
            CategoryRuleSaveOutcome.Queued(
                projectOptimisticRule(baseline, keyword, category, enabled, priority),
            ) as CategoryRuleSaveOutcome
        }
    }

    /**
     * Build the optimistic projection that the UI shows while the
     * queued PATCH waits for connectivity. The user's submitted
     * fields overwrite the baseline; ``updatedAt`` stays at the
     * pre-mutation value (it's NOT a server-confirmed token, and
     * no chained POST reads it from this return path).
     */
    private fun projectOptimisticRule(
        baseline: CategoryRule,
        keyword: String?,
        category: String?,
        enabled: Boolean?,
        priority: Int?,
    ): CategoryRule = baseline.copy(
        keyword = keyword ?: baseline.keyword,
        category = category ?: baseline.category,
        enabled = enabled ?: baseline.enabled,
        priority = priority ?: baseline.priority,
    )

    suspend fun deleteCategoryRule(id: Long, expectedUpdatedAt: String): Result<Unit> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.deleteCategoryRule(
                    id,
                    CategoryRuleDeleteRequest(expectedUpdatedAt = expectedUpdatedAt),
                )
            }
            Unit
        }

    /**
     * ADR-0038 PR-2g.5: offline-aware version of [deleteCategoryRule].
     *
     * IOException → enqueue + return [DeleteOutcome.Queued] (UI
     * removes the row locally; worker drains later). Any other
     * failure surfaces as ``Result.failure`` (4xx / 409 / 5xx —
     * the user should see the actual server problem).
     *
     * Direct [deleteCategoryRule] (above) preserved for any caller
     * that doesn't want offline routing. The ViewModel
     * [com.ticketbox.viewmodel.CategoryRulesViewModel.deleteCategoryRule]
     * switches to this method.
     */
    suspend fun deleteCategoryRuleAllowingOffline(
        rule: CategoryRule,
    ): Result<DeleteOutcome> = errorHandler.safeCall {
        val request = CategoryRuleDeleteRequest(expectedUpdatedAt = rule.updatedAt)
        // [codex round-13 P1] Explicit bind so the IOException catch
        // can re-verify session activity before enqueueing.
        // ``guardedCall`` only checks ``isStillActive`` when the
        // block returns normally; an IOException skips the
        // post-check and would let an old-ledger DELETE slip into
        // the now-current ledger's outbox after a switch.
        val bound = ledgerRequestGuard.bind()
        try {
            bound.call { api ->
                api.deleteCategoryRule(rule.id, request)
            }
            DeleteOutcome.Synced as DeleteOutcome
        } catch (networkError: IOException) {
            val outboxRef = outbox
            val adapter = categoryRuleDeleteAdapter
            if (outboxRef == null || adapter == null) {
                throw networkError
            }
            // [codex round-13 P1] Session race guard: throws
            // RepositoryException if the user switched ledger mid-
            // flight, surfacing "账本已切换…" instead of stuffing an
            // old-session row into the new session's queue.
            bound.requireStillActive()
            // [round-8 P3#5] strip token from payload — row's
            // expectedUpdatedAt is the single source of truth.
            // CategoryRuleDeleteRequest.expectedUpdatedAt is
            // non-nullable String so we substitute an empty
            // placeholder; dispatcher overwrites from
            // row.expectedUpdatedAt on replay.
            outboxRef.enqueue(
                type = PendingMutationType.DeleteCategoryRule,
                targetId = "category_rule:${rule.id}",
                payloadJson = adapter.toJson(request.copy(expectedUpdatedAt = "")),
                expectedUpdatedAt = rule.updatedAt,
            )
            DeleteOutcome.Queued as DeleteOutcome
        }
    }

    suspend fun ruleApplications(limit: Int = 8): Result<List<RuleApplicationBatch>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.ruleApplications(limit = limit.coerceIn(1, 20)).items.map { it.toDomain() }
            }
        }

    suspend fun previewApplyConfirmedRules(): Result<RuleApplyConfirmedResult> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.applyConfirmedRules(
                    request = RuleApplyConfirmedRequestDto(confirm = false),
                ).toDomain()
            }
        }

    suspend fun confirmApplyConfirmedRules(previewToken: String): Result<RuleApplyConfirmedResult> =
        errorHandler.safeCall {
            val cleanPreviewToken = previewToken.trim()
            require(cleanPreviewToken.isNotBlank()) { "请先预览影响范围。" }
            ledgerRequestGuard.guardedCall { api ->
                val result = api.applyConfirmedRules(
                    request = RuleApplyConfirmedRequestDto(confirm = true, previewToken = cleanPreviewToken),
                ).toDomain()
                requireStillActive()
                if (result.changedCount > 0) {
                    onConfirmedChanged()
                }
                result
            }
        }

    suspend fun rollbackRuleApplication(publicId: String): Result<RuleApplicationRollback> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一条应用记录。" }
            ledgerRequestGuard.guardedCall { api ->
                val result = api.rollbackRuleApplication(cleanPublicId).toDomain()
                requireStillActive()
                if (result.changed > 0) {
                    onConfirmedChanged()
                }
                result
            }
        }
}

/**
 * ADR-0038 PR-2g.4 sealed result for
 * [RuleRepository.updateCategoryRuleAllowingOffline]. Mirrors
 * [SaveOutcome] for the expense path — parallel-defined here so
 * neither type's surface accidentally widens to the other's
 * payload. A future PR may generic-ify both into ``SaveOutcome<T>``.
 */
sealed interface CategoryRuleSaveOutcome {
    val rule: CategoryRule

    /** Server confirmed the PATCH; [rule] carries the canonical post-mutation token. */
    data class Synced(override val rule: CategoryRule) : CategoryRuleSaveOutcome

    /**
     * Network failed; the mutation was persisted to the outbox and
     * [rule] is the optimistic projection (baseline merged with the
     * user's submitted fields). ``updatedAt`` is the pre-mutation
     * token; chained POSTs must not consume it.
     */
    data class Queued(override val rule: CategoryRule) : CategoryRuleSaveOutcome
}

/**
 * ADR-0038 PR-2g.5 sealed result for offline-aware DELETE
 * entrypoints. Shared between
 * [RuleRepository.deleteCategoryRuleAllowingOffline] and
 * [MerchantRepository.deleteMerchantAliasAllowingOffline] — both
 * DELETE shapes return ``Unit`` (no payload), only the
 * "synced vs queued" distinction matters for the UI message.
 */
sealed interface DeleteOutcome {
    /** Server confirmed the DELETE; the row is gone server-side. */
    data object Synced : DeleteOutcome

    /**
     * Network failed; the DELETE is queued in the outbox. The UI
     * locally removes the row either way (the row is gone from the
     * user's perspective). PR-2g.5 banner UI will surface
     * "未同步" hints via OutboxRepository.observeConflicts /
     * observeFailed.
     */
    data object Queued : DeleteOutcome
}
