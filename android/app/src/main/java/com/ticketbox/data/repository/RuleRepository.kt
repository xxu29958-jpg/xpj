package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollback
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import com.ticketbox.domain.model.normalizeExpenseCategory

/**
 * Category-rule CRUD and bulk rule application over confirmed expenses.
 *
 * Extracted from ExpenseRepository to keep that god-object focused on
 * account / expense / sync concerns. ``onConfirmedChanged`` is fired after a
 * successful bulk apply or rollback so the AppContainer can refresh the
 * confirmed-cache via ExpenseRepository.syncConfirmed().
 */
class RuleRepository(
    private val binding: ServerSessionBinding,
    private val onConfirmedChanged: suspend () -> Unit = { },
    private val offlineMutations: CategoryRuleOfflineMutationWiring = CategoryRuleOfflineMutationWiring(),
) {
    private val outbox get() = offlineMutations.outbox
    private val categoryRuleUpdateAdapter get() = offlineMutations.updateAdapter
    private val ledgerRequestGuard = LedgerRequestGuard(binding.apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { binding.apiProvider.currentSession()?.serverUrl },
        context = "Rule",
        statusMessages = mapOf(404 to "分类规则不存在。"),
    )

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(binding.apiProvider.currentLedgerRole())

    suspend fun categoryRules(): Result<List<CategoryRule>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.categoryRules().map { it.toDomain() }
            }
        }

    fun currentAccess(): LedgerAccessContext? = ledgerRequestGuard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, canModifyLedger())
    }

    fun observeAccess(): Flow<LedgerAccessContext?> = binding.apiProvider.observeActiveLedgerAccess()

    fun describeSubmission(row: OutboxRow): PendingCategoryRuleSubmission? {
        val current = currentAccess()?.binding ?: return null
        if (row.type !in RULE_MUTATIONS || row.ownerKey != current.ownerKey || row.ledgerId != current.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(current.serverUrl)) return null
        return describeCategoryRuleSubmission(row, requireNotNull(offlineMutations.submissionAdapter),
            requireNotNull(categoryRuleUpdateAdapter), requireNotNull(offlineMutations.receiptAdapter))
    }

    fun observeSubmissions(expected: LogicalSessionBinding): Flow<List<PendingCategoryRuleSubmission>> =
        requireNotNull(outbox).observeActiveByTypes(RULE_MUTATIONS, includeCompleted = true).map { rows ->
            if (currentAccess()?.binding != expected) emptyList() else rows.mapNotNull(::describeSubmission)
        }

    suspend fun createCategoryRule(expected: LogicalSessionBinding, request: CategoryRuleRequest): Result<Long> =
        errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expected)
            require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
            val clean = request.cleanRule()
            val key = UUID.randomUUID().toString()
            enqueue(bound, PendingMutationType.CreateCategoryRule, "category_rule_create:$key", CategoryRuleSubmissionPayload(expectedRowVersion = 0, request = clean), key)
        }

    suspend fun updateCategoryRule(expected: LogicalSessionBinding, baseline: CategoryRule,
        request: CategoryRuleRequest): Result<Long> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expected)
        require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
        val clean = request.cleanRule()
        require(baseline.id > 0 && baseline.rowVersion > 0) { "请重新打开原规则。" }
        require(baseline.homeCurrencyCode == null || clean.homeCurrencyCode == baseline.homeCurrencyCode) { "原规则币种不能改贴，请核对。" }
        require((baseline.amountMinCents == null && baseline.amountMaxCents == null) || baseline.homeCurrencyCode != null) {
            "原规则金额币种尚未确认，已保留原数值，请先核对。"
        }
        enqueue(bound, PendingMutationType.UpdateCategoryRule, "category_rule:${baseline.id}",
            CategoryRuleSubmissionPayload(expectedRowVersion = baseline.rowVersion, request = clean), UUID.randomUUID().toString())
    }

    suspend fun deleteCategoryRule(expected: LogicalSessionBinding, rule: CategoryRule): Result<Long> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expected)
        require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
        require(rule.id > 0 && rule.rowVersion > 0) { "请重新打开原规则。" }
        enqueue(bound, PendingMutationType.DeleteCategoryRule, "category_rule:${rule.id}",
            CategoryRuleSubmissionPayload(expectedRowVersion = rule.rowVersion, request = rule.asRequest()), UUID.randomUUID().toString())
    }

    private suspend fun enqueue(bound: BoundLedgerRequest, type: PendingMutationType, target: String,
        payload: CategoryRuleSubmissionPayload, key: String): Long = requireNotNull(outbox).enqueue(
        boundRequest = bound,
        intent = PendingMutationIntent(type, target,
            requireNotNull(offlineMutations.submissionAdapter).toJson(payload),
            payload.expectedRowVersion, key),
        validateTargetRows = { rows -> require(rows.none { it.status != PendingMutationStatus.Done }) {
            "原规则还有待处理的提交，请先核对。"
        } },
    )

    suspend fun recoverSubmission(expected: LogicalSessionBinding, pending: PendingCategoryRuleSubmission,
        drop: Boolean): Result<Unit> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expected)
        val queue = requireNotNull(outbox)
        val current = queue.activeForTarget(bound, pending.row.targetId).firstOrNull { it.id == pending.row.id }
        require(current == pending.row) { "原提交状态已变化，请重新核对。" }
        val original = requireNotNull(describeSubmission(requireNotNull(current)))
        require(if (drop) original.canDrop else original.canRetry && canModifyLedger()) { "请核对原规则后继续。" }
        val changed = if (current.status == PendingMutationStatus.Conflict) {
            queue.resolveConflict(current.id, ConflictResolution.DropMine, bound)
        } else queue.resolveFailed(current.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
        check(changed) { "原提交状态已变化，请重新核对。" }
    }

    /**
     * ADR-0038 undo: restore a soft-deleted rule within the short undo window.
     * Mirrors [MerchantRepository.undoMerchantAlias] — a plain guarded POST; a
     * 404 (already purged / never soft-deleted) surfaces via the standard
     * NetworkErrorHandler mapping ("分类规则不存在。").
     */
    suspend fun undoDeleteRule(id: Long): Result<CategoryRule> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.undoCategoryRule(id).toDomain()
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

private val RULE_MUTATIONS = setOf(PendingMutationType.CreateCategoryRule,
    PendingMutationType.UpdateCategoryRule, PendingMutationType.DeleteCategoryRule)

private fun CategoryRuleRequest.cleanRule(): CategoryRuleRequest = copy(
    keyword = keyword?.trim(), category = category?.trim()?.let(::normalizeExpenseCategory),
    sourceContains = sourceContains?.trim()?.takeIf { it.isNotBlank() },
    tagContains = tagContains?.trim()?.takeIf { it.isNotBlank() },
).also { require(it.isCompleteRule()) { "请填写关键词、分类及有效金额范围，并明确金额币种。" } }

/**
 * Delivery result retained for [MerchantRepository.deleteMerchantAliasAllowingOffline].
 */
sealed interface DeleteOutcome {
    /** Server confirmed the DELETE; the row is gone server-side. */
    data object Synced : DeleteOutcome

    /**
     * Network failed; the DELETE is queued in the outbox. The UI
     * locally removes the row either way (the row is gone from the
     * user's perspective). PR-2g.5 banner UI will surface
     * "未同步" hints via OutboxRepository.observeStatus.
     */
    data object Queued : DeleteOutcome
}
