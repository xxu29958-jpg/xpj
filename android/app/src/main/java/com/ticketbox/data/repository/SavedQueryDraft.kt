package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.SavedQueryInputDao
import com.ticketbox.data.local.SavedQueryInputEntity
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeletionReceiptDto
import com.ticketbox.data.remote.dto.SavedViewDto

enum class SavedQueryCommand { Create, Edit, Delete }

@JsonClass(generateAdapter = true)
data class SavedQueryDraft(
    val binding: LogicalSessionBinding,
    val key: String,
    val command: SavedQueryCommand,
    val definition: SavedViewDefinitionRequestDto,
    val baseline: SavedViewDto? = null,
    val phase: String = "editing",
    val receipt: SavedViewDto? = null,
    val deletionReceipt: SavedViewDeletionReceiptDto? = null,
    val error: String? = null,
) {
    val slot: String get() = if (command == SavedQueryCommand.Create) "create" else "${command.name}:${requireNotNull(baseline).publicId}"
}

fun SavedViewDto.queryDefinition() = SavedViewDefinitionRequestDto(
    name, monthMode, month, filter, tagPublicId, homeCurrencyCode, queryText, category,
)

class SavedQueryDraftStore(private val dao: SavedQueryInputDao) {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(SavedQueryDraft::class.java)

    suspend fun read(binding: LogicalSessionBinding): List<SavedQueryDraft> =
        dao.get(binding.serverUrl, binding.ownerKey, binding.ledgerId).map { requireNotNull(adapter.fromJson(it.inputJson)) }

    suspend fun write(draft: SavedQueryDraft) {
        dao.put(SavedQueryInputEntity(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            draft.slot, adapter.toJson(draft)))
    }

    suspend fun consume(draft: SavedQueryDraft) {
        check(dao.consume(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            draft.slot, adapter.toJson(draft)) == 1)
    }
}
