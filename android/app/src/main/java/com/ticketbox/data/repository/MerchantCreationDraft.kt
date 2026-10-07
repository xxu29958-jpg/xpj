package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.MerchantCreationInputDao
import com.ticketbox.data.local.MerchantCreationInputEntity
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantCatalogDto

enum class MerchantCreationKind { Catalog, Alias }

@JsonClass(generateAdapter = true)
data class MerchantCreationDraft(
    val binding: LogicalSessionBinding,
    val kind: MerchantCreationKind,
    val key: String,
    val displayName: String = "",
    val canonicalMerchant: String = "",
    val alias: String = "",
    val phase: String = "editing",
    val catalogReceipt: MerchantCatalogDto? = null,
    val aliasReceipt: MerchantAliasDto? = null,
    val error: String? = null,
) {
    val acceptedId: String? get() = catalogReceipt?.publicId ?: aliasReceipt?.publicId
}

/** Only this capability's Room input table stores its raw fields, original binding/key and receipt. */
class MerchantCreationDraftStore(private val dao: MerchantCreationInputDao) {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(MerchantCreationDraft::class.java)

    suspend fun read(binding: LogicalSessionBinding): List<MerchantCreationDraft> =
        dao.get(binding.serverUrl, binding.ownerKey, binding.ledgerId).map { requireNotNull(adapter.fromJson(it.draftJson)) }

    suspend fun write(draft: MerchantCreationDraft) {
        dao.put(MerchantCreationInputEntity(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            draft.kind.name, draft.key, adapter.toJson(draft)))
    }

    suspend fun remove(draft: MerchantCreationDraft) {
        dao.remove(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId, draft.kind.name, draft.key)
    }
}
