package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.RuleDefinitionInputDao
import com.ticketbox.data.local.RuleDefinitionInputEntity
import com.ticketbox.domain.model.CategoryRule
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

@JsonClass(generateAdapter = true)
data class RuleDefinitionDraft(
    val binding: LogicalSessionBinding,
    val key: String,
    val keyword: String,
    val category: String,
    val priorityText: String,
    val baseline: CategoryRule? = null,
    val minimumAmount: String = "",
    val maximumAmount: String = "",
    val homeCurrencyCode: String? = null,
    val sourceContains: String = "",
    val tagContains: String = "",
) {
    val slot: String get() = baseline?.id?.toString() ?: "new"
    fun originalFields(): Map<String, String> = mapOf("keyword" to keyword, "category" to category,
        "priority" to priorityText, "amount_min" to minimumAmount, "amount_max" to maximumAmount,
        "home_currency_code" to homeCurrencyCode.orEmpty(), "source_contains" to sourceContains, "tag_contains" to tagContains)
}

class RuleDefinitionDraftStore(private val dao: RuleDefinitionInputDao) {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(RuleDefinitionDraft::class.java)
    private val writes = Mutex()

    suspend fun read(binding: LogicalSessionBinding): List<RuleDefinitionDraft> = writes.withLock {
        dao.get(binding.serverUrl, binding.ownerKey, binding.ledgerId).map { row ->
            requireNotNull(adapter.fromJson(row.inputJson)).also { draft ->
                require(draft.binding.serverUrl == binding.serverUrl && draft.binding.ownerKey == binding.ownerKey &&
                    draft.binding.ledgerId == binding.ledgerId && draft.slot == row.slot && draft.key == row.originalKey)
            }
        }
    }

    suspend fun write(draft: RuleDefinitionDraft) = writes.withLock {
        dao.put(RuleDefinitionInputEntity(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            draft.slot, draft.key, adapter.toJson(draft)))
    }

    /** Called inside the existing Outbox insert transaction; only the exact input can be consumed. */
    suspend fun consume(draft: RuleDefinitionDraft) {
        check(dao.consume(draft.binding.serverUrl, draft.binding.ownerKey, draft.binding.ledgerId,
            draft.slot, adapter.toJson(draft)) == 1) { "原规则输入已变化，请重新核对。" }
    }
}
