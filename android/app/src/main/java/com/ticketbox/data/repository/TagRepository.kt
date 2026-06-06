package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.TagDeleteRequest
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.data.remote.dto.TagUndoRequest
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.TagMutationResult
import com.ticketbox.domain.model.TagUndoResult
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore

/**
 * Tag-management surface the [com.ticketbox.viewmodel.TagManagementViewModel]
 * depends on (so it can be faked in unit tests). Mirrors the [IncomePlanActions]
 * pattern. Implemented by [TagRepository].
 */
interface TagActions {
    fun canModifyLedger(): Boolean
    suspend fun tags(): Result<List<ManagedTag>>
    suspend fun renameTag(publicId: String, expectedRowVersion: Long, name: String): Result<Unit>
    suspend fun deleteTag(publicId: String, expectedRowVersion: Long): Result<TagMutationResult>
    suspend fun mergeTags(
        sourcePublicId: String,
        sourceRowVersion: Long,
        targetPublicId: String,
        targetRowVersion: Long,
    ): Result<TagMutationResult>
    suspend fun undoTagMutation(mutationPublicId: String, expectedRowVersion: Long): Result<TagUndoResult>
}

/**
 * ADR-0043 slice C — tag management (list + usage, rename / delete / merge / undo).
 *
 * Online-only mutate surface (契约 7): every mutation carries the OCC token
 * (`expected_row_version`) and NONE goes through the offline outbox / idempotency
 * key path — unlike [MerchantRepository], there is no offline routing here. A
 * stale token surfaces as 409 `state_conflict`; a rename key-collision as 409
 * `tag_conflict` → the caller offers a merge instead (契约 5).
 */
class TagRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) : TagActions {
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Tag",
        statusMessages = mapOf(404 to "标签不存在或已删除。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun tags(): Result<List<ManagedTag>> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.listManagedTags().items.map { it.toDomain() }
            }
        }

    override suspend fun renameTag(
        publicId: String,
        expectedRowVersion: Long,
        name: String,
    ): Result<Unit> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个标签。" }
            val cleanName = name.trim()
            require(cleanName.isNotBlank()) { "请输入标签名。" }
            ledgerRequestGuard.guardedCall { api ->
                api.renameTag(
                    cleanPublicId,
                    TagRenameRequest(expectedRowVersion = expectedRowVersion, name = cleanName),
                )
            }
            Unit
        }

    override suspend fun deleteTag(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<TagMutationResult> =
        errorHandler.safeCall {
            val cleanPublicId = publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个标签。" }
            ledgerRequestGuard.guardedCall { api ->
                api.deleteTag(
                    cleanPublicId,
                    TagDeleteRequest(expectedRowVersion = expectedRowVersion),
                ).toDomain()
            }
        }

    override suspend fun mergeTags(
        sourcePublicId: String,
        sourceRowVersion: Long,
        targetPublicId: String,
        targetRowVersion: Long,
    ): Result<TagMutationResult> =
        errorHandler.safeCall {
            val cleanSource = sourcePublicId.trim()
            val cleanTarget = targetPublicId.trim()
            require(cleanSource.isNotBlank() && cleanTarget.isNotBlank()) { "请选择要合并的标签。" }
            require(cleanSource != cleanTarget) { "不能把标签合并到自身。" }
            ledgerRequestGuard.guardedCall { api ->
                api.mergeTag(
                    cleanSource,
                    TagMergeRequest(
                        expectedRowVersion = sourceRowVersion,
                        targetPublicId = cleanTarget,
                        targetRowVersion = targetRowVersion,
                    ),
                ).toDomain()
            }
        }

    /**
     * Undo a delete/merge. Online-only — the undo affordance only appears after a
     * synced mutation, so there is no offline path. 404 `tag_undo_not_found` once
     * the 5-minute window has elapsed (cleanup purged the snapshot) → degrade.
     */
    override suspend fun undoTagMutation(
        mutationPublicId: String,
        expectedRowVersion: Long,
    ): Result<TagUndoResult> =
        errorHandler.safeCall {
            val cleanId = mutationPublicId.trim()
            require(cleanId.isNotBlank()) { "撤销信息已失效。" }
            ledgerRequestGuard.guardedCall { api ->
                api.undoTagMutation(
                    cleanId,
                    TagUndoRequest(expectedRowVersion = expectedRowVersion),
                ).toDomain()
            }
        }
}
