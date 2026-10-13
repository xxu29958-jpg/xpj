package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.TagDeleteRequest
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.data.remote.dto.TagUndoRequest
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.TagMutationResult
import com.ticketbox.domain.model.TagUndoResult
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow

/**
 * Tag-management surface the [com.ticketbox.viewmodel.TagManagementViewModel]
 * depends on (so it can be faked in unit tests). Mirrors the [IncomePlanActions]
 * pattern. Implemented by [TagRepository].
 */
interface TagActions {
    fun canModifyLedger(): Boolean
    fun captureBinding(): LogicalSessionBinding?
    fun observeLedgerAccess(): Flow<LedgerAccessContext?>
    suspend fun tags(binding: LogicalSessionBinding): Result<List<ManagedTag>>
    suspend fun renameTag(binding: LogicalSessionBinding, tag: ManagedTag, name: String, requireOrphan: Boolean = false): Result<Unit>
    suspend fun deleteTag(binding: LogicalSessionBinding, tag: ManagedTag, requireOrphan: Boolean = false): Result<TagMutationResult>
    suspend fun mergeTags(
        binding: LogicalSessionBinding,
        source: ManagedTag,
        target: ManagedTag,
        requireOrphan: Boolean = false,
    ): Result<TagMutationResult>
    suspend fun undoTagMutation(binding: LogicalSessionBinding, mutationPublicId: String, expectedRowVersion: Long): Result<TagUndoResult>
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
    private val apiProvider: ApiServiceProvider,
) : TagActions {
    val creation: ReferenceCreationActions = ReferenceCreationRepository(apiProvider, ReferenceKind.Tag)
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Tag",
        statusMessages = mapOf(404 to "标签不存在或已删除。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun captureBinding(): LogicalSessionBinding? = ledgerRequestGuard.captureLogicalBinding()

    override fun observeLedgerAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override suspend fun tags(binding: LogicalSessionBinding): Result<List<ManagedTag>> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.listManagedTags().items.map { it.toDomain() }
            }
        }

    override suspend fun renameTag(
        binding: LogicalSessionBinding,
        tag: ManagedTag,
        name: String,
        requireOrphan: Boolean,
    ): Result<Unit> =
        errorHandler.safeCall {
            val cleanPublicId = tag.publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个标签。" }
            val cleanName = name.trim()
            require(cleanName.isNotBlank()) { "请输入标签名。" }
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.renameTag(
                    cleanPublicId,
                    TagRenameRequest(expectedRowVersion = tag.rowVersion, name = cleanName, requireOrphan = requireOrphan),
                )
            }
            Unit
        }

    override suspend fun deleteTag(
        binding: LogicalSessionBinding,
        tag: ManagedTag,
        requireOrphan: Boolean,
    ): Result<TagMutationResult> =
        errorHandler.safeCall {
            val cleanPublicId = tag.publicId.trim()
            require(cleanPublicId.isNotBlank()) { "请选择一个标签。" }
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.deleteTag(
                    cleanPublicId,
                    TagDeleteRequest(expectedRowVersion = tag.rowVersion, requireOrphan = requireOrphan),
                ).toDomain()
            }
        }

    override suspend fun mergeTags(
        binding: LogicalSessionBinding,
        source: ManagedTag,
        target: ManagedTag,
        requireOrphan: Boolean,
    ): Result<TagMutationResult> =
        errorHandler.safeCall {
            val cleanSource = source.publicId.trim()
            val cleanTarget = target.publicId.trim()
            require(cleanSource.isNotBlank() && cleanTarget.isNotBlank()) { "请选择要合并的标签。" }
            require(cleanSource != cleanTarget) { "不能把标签合并到自身。" }
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.mergeTag(
                    cleanSource,
                    TagMergeRequest(
                        expectedRowVersion = source.rowVersion,
                        targetPublicId = cleanTarget,
                        targetRowVersion = target.rowVersion,
                        requireOrphan = requireOrphan,
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
        binding: LogicalSessionBinding,
        mutationPublicId: String,
        expectedRowVersion: Long,
    ): Result<TagUndoResult> =
        errorHandler.safeCall {
            val cleanId = mutationPublicId.trim()
            require(cleanId.isNotBlank()) { "撤销信息已失效。" }
            ledgerRequestGuard.bindExact(binding).call { api ->
                api.undoTagMutation(
                    cleanId,
                    TagUndoRequest(expectedRowVersion = expectedRowVersion),
                ).toDomain()
            }
        }
}
