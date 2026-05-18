package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollback
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore

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

    suspend fun updateCategoryRule(
        id: Long,
        keyword: String? = null,
        category: String? = null,
        enabled: Boolean? = null,
        priority: Int? = null,
    ): Result<CategoryRule> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateCategoryRule(
                    id,
                    CategoryRuleRequest(
                        keyword = keyword,
                        category = category,
                        enabled = enabled,
                        priority = priority,
                    ),
                ).toDomain()
            }
        }

    suspend fun deleteCategoryRule(id: Long): Result<Unit> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.deleteCategoryRule(id)
            }
            Unit
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
