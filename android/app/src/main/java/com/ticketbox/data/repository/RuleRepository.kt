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
    private val onConfirmedChanged: suspend () -> Result<Unit> = { Result.success(Unit) },
    private val offlineMutations: CategoryRuleOfflineMutationWiring = CategoryRuleOfflineMutationWiring(),
    val definitionInputs: RuleDefinitionDraftStore? = null,
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

    suspend fun createCategoryRule(expected: LogicalSessionBinding, request: CategoryRuleRequest,
        input: RuleDefinitionDraft? = null): Result<Long> =
        errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expected)
            require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
            val clean = request.cleanRule()
            require(input == null || input.binding == expected && input.baseline == null)
            val key = input?.key ?: UUID.randomUUID().toString()
            val payload = CategoryRuleSubmissionPayload(version = if (input == null) 1 else 2,
                expectedRowVersion = 0, request = clean, originalInput = input?.originalFields())
            enqueue(bound, PendingMutationIntent(PendingMutationType.CreateCategoryRule, "category_rule_create:$key",
                requireNotNull(offlineMutations.submissionAdapter).toJson(payload), 0, key), input)
        }

    suspend fun updateCategoryRule(expected: LogicalSessionBinding, baseline: CategoryRule,
        request: CategoryRuleRequest, input: RuleDefinitionDraft? = null): Result<Long> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expected)
        require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
        val clean = request.cleanRule()
        require(input == null || input.binding == expected && input.baseline == baseline)
        require(baseline.id > 0 && baseline.rowVersion > 0) { "请重新打开原规则。" }
        require(baseline.homeCurrencyCode == null || clean.homeCurrencyCode == baseline.homeCurrencyCode) { "原规则币种不能改贴，请核对。" }
        require((baseline.amountMinCents == null && baseline.amountMaxCents == null) || baseline.homeCurrencyCode != null) {
            "原规则金额币种尚未确认，已保留原数值，请先核对。"
        }
        val payload = CategoryRuleSubmissionPayload(version = if (input == null) 1 else 2,
            expectedRowVersion = baseline.rowVersion, request = clean, originalInput = input?.originalFields())
        enqueue(bound, PendingMutationIntent(PendingMutationType.UpdateCategoryRule, "category_rule:${baseline.id}",
            requireNotNull(offlineMutations.submissionAdapter).toJson(payload), baseline.rowVersion,
            input?.key ?: UUID.randomUUID().toString()), input)
    }

    suspend fun deleteCategoryRule(expected: LogicalSessionBinding, rule: CategoryRule): Result<Long> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expected)
        require(canModifyLedger()) { "当前角色为只读，无法修改规则。" }
        require(rule.id > 0 && rule.rowVersion > 0) { "请重新打开原规则。" }
        val payload = CategoryRuleSubmissionPayload(expectedRowVersion = rule.rowVersion, request = rule.asRequest())
        enqueue(bound, PendingMutationIntent(PendingMutationType.DeleteCategoryRule, "category_rule:${rule.id}",
            requireNotNull(offlineMutations.submissionAdapter).toJson(payload), rule.rowVersion, UUID.randomUUID().toString()))
    }

    private suspend fun enqueue(bound: BoundLedgerRequest, intent: PendingMutationIntent,
        input: RuleDefinitionDraft? = null): Long = requireNotNull(outbox).enqueue(
        boundRequest = bound,
        intent = intent,
        validateTargetRows = { rows -> require(rows.none { it.status != PendingMutationStatus.Done }) {
            "原规则还有待处理的提交，请先核对。"
        } },
        afterPersisted = { input?.let { requireNotNull(definitionInputs).consume(it) } },
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

    suspend fun confirmApplyConfirmedRules(expected: LogicalSessionBinding, preview: RuleApplyConfirmedResult): Result<Long> =
        errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expected)
            require(canModifyLedger()) { "当前角色为只读，无法应用规则。" }
            require(preview.dryRun && !preview.previewToken.isNullOrBlank() && preview.changedCount > 0) { "请先预览影响范围。" }
            val payload = RuleApplicationPayload(previewToken = requireNotNull(preview.previewToken), maxScan = preview.scanLimit,
                scanned = preview.confirmedScanned, expectedChanges = preview.changedCount)
            enqueue(bound, PendingMutationIntent(PendingMutationType.ApplyConfirmedRules, RULE_APPLICATION_TARGET,
                requireNotNull(offlineMutations.applicationAdapter).toJson(payload), 0, UUID.randomUUID().toString()))
        }

    fun describeApplication(row: OutboxRow): PendingRuleApplication? {
        val current = currentAccess()?.binding ?: return null
        if (row.type != PendingMutationType.ApplyConfirmedRules || row.ownerKey != current.ownerKey || row.ledgerId != current.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(current.serverUrl)) return null
        val original = runCatching { requireNotNull(offlineMutations.applicationAdapter).fromJson(row.payloadJson) }.getOrNull()
        val receipt = row.receiptJson?.let { runCatching { requireNotNull(offlineMutations.applicationReceiptAdapter).fromJson(it) }.getOrNull() }
            ?.takeIf { original?.accepts(row, it) == true }
        return PendingRuleApplication(row, original, receipt)
    }

    fun observeApplications(expected: LogicalSessionBinding): Flow<List<PendingRuleApplication>> =
        requireNotNull(outbox).observeActiveByTypes(setOf(PendingMutationType.ApplyConfirmedRules), includeCompleted = true).map { rows ->
            if (currentAccess()?.binding != expected) emptyList() else rows.mapNotNull(::describeApplication)
        }

    suspend fun refreshAcceptedApplication(row: OutboxRow): Result<Unit> = errorHandler.safeCall {
        require(describeApplication(row) != null) { "请恢复原身份与账本后刷新流水。" }
        val bound = ledgerRequestGuard.bindExact(requireNotNull(currentAccess()).binding)
        onConfirmedChanged().getOrThrow()
        bound.requireStillActive()
    }

    suspend fun recoverApplication(expected: LogicalSessionBinding, pending: PendingRuleApplication, drop: Boolean): Result<Unit> =
        errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expected)
            val queue = requireNotNull(outbox)
            if (!drop && pending.needsRefresh && pending.receipt != null) {
                refreshAcceptedApplication(pending.row).getOrThrow()
                queue.acknowledgeRuleApplicationRefresh(bound, pending.row)
            } else {
                val current = queue.activeForTarget(bound, pending.row.targetId).firstOrNull { it.id == pending.row.id }
                require(current == pending.row) { "原应用状态已变化，请重新核对。" }
                val original = requireNotNull(describeApplication(requireNotNull(current)))
                require(if (drop) original.canDrop else original.canRetry && canModifyLedger()) { "请先核对原应用。" }
                check(if (current.status == PendingMutationStatus.Conflict) queue.resolveConflict(current.id, ConflictResolution.DropMine, bound)
                    else queue.resolveFailed(current.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound))
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
