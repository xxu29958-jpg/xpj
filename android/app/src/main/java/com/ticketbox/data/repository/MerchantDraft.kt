package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.MerchantCreationInputDao
import com.ticketbox.data.local.MerchantCreationInputEntity
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy

enum class MerchantDraftKind {
    Catalog, Alias, Rename, Visibility, Delete, Merge;
    val isCreation get() = this == Catalog || this == Alias
}

@JsonClass(generateAdapter = true)
data class MerchantDraft(
    val binding: LogicalSessionBinding,
    val kind: MerchantDraftKind,
    val key: String,
    val displayName: String = "",
    val canonicalMerchant: String = "",
    val alias: String = "",
    val phase: String = "editing",
    val catalogReceipt: MerchantCatalogDto? = null,
    val aliasReceipt: MerchantAliasDto? = null,
    val error: String? = null,
    val source: MerchantCatalog? = null,
    val target: MerchantCatalog? = null,
    val aliasPolicy: MerchantCatalogAliasPolicy? = null,
    val nextStatus: String = "",
    val sourceUnavailable: Boolean = false,
    val targetUnavailable: Boolean = false,
    val parentRenameKey: String? = null,
    val mergeReceipt: MerchantCatalogMergeDto? = null,
    val reviewed: Boolean = false,
) {
    val acceptedId: String? get() = catalogReceipt?.publicId ?: aliasReceipt?.publicId ?: mergeReceipt?.source?.publicId
    // The existing Catalog/Alias slots and serialized fields remain readable without rewriting retained inputs.
    val slot: String get() = if (kind.isCreation) kind.name else "${kind.name}:${requireNotNull(source).publicId}"
}

/** Only this capability's Room input table stores its raw fields, original binding/key and receipt. */
class MerchantDraftStore(private val dao: MerchantCreationInputDao) {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(MerchantDraft::class.java)

    suspend fun read(binding: LogicalSessionBinding): List<MerchantDraft> =
        dao.get(binding.serverUrl, binding.ownerKey, binding.ledgerId).map { requireNotNull(adapter.fromJson(it.draftJson)) }

    suspend fun write(draft: MerchantDraft) {
        writeAll(listOf(draft))
    }

    suspend fun writeAll(drafts: List<MerchantDraft>) {
        dao.putAll(drafts.map { draft -> MerchantCreationInputEntity(draft.binding.serverUrl,
            draft.binding.ownerKey, draft.binding.ledgerId, draft.slot, draft.key, adapter.toJson(draft)) })
    }

    suspend fun remove(draft: MerchantDraft) {
        dao.remove(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId, draft.slot, draft.key)
    }

    suspend fun acknowledge(draft: MerchantDraft) {
        dao.removeKeys(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            listOfNotNull(draft.key, draft.parentRenameKey))
    }
}
