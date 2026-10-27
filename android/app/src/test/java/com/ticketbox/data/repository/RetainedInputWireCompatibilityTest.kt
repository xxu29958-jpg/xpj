package com.ticketbox.data.repository

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.MerchantCreationInputDao
import com.ticketbox.data.local.MerchantCreationInputEntity
import com.ticketbox.data.local.SavedQueryInputDao
import com.ticketbox.data.local.SavedQueryInputEntity
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Legacy shapes are frozen from c7738; expectations do not use the new domain mappers. */
class RetainedInputWireCompatibilityTest {
    private val binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "original-session", "original-binding")
    private val bindingJson = """{"serverUrl":"https://example.test","ledgerId":"ledger","ownerKey":"owner","sessionGeneration":"original-session","bindingRevision":"original-binding"}"""
    private val json = Moshi.Builder().build().adapter(Any::class.java)

    @Test fun memberProposalRetainsNestedWireTimeAndOriginalWhitespace() {
        val legacy = """{"amountCents":1234,"note":"  原说明  ","supersedesProposalPublicId":"original-proposal","timeInput":{"precision":"date_only","calendar_revision":7,"user_local_date":"2026-09-30","source_timezone":"Asia/Tokyo","source_utc_offset_seconds":32400,"accounting_date":"2026-09-30"}}"""
        val command = MemberSettlementCommandJson.read("propose", legacy) as MemberSettlementCommand.Propose
        assertEquals(7L, command.timeInput?.calendarRevision)
        assertEquals("  原说明  ", command.note)
        assertEquals("propose", MemberSettlementCommandJson.kind(command))
        assertEquals(json.fromJson(legacy), json.fromJson(MemberSettlementCommandJson.write(command)))
    }

    @Test fun acceptedReferenceSavedStateRetainsReceiptAndOriginalCommandIdentity() {
        val legacy = """[{"binding":$bindingJson,"key":"original-reference-key","name":"  原名称  ","phase":"accepted","receipt":{"kind":"tag","public_id":"original-tag","name":"原名称","row_version":7},"error":"original-warning"}]"""
        val state = SavedStateHandle(mapOf("reference.creation.drafts" to legacy))
        val store = ReferenceCreationDraftStore(state)
        val retained = assertNotNull(store.read(binding))
        assertEquals("original-tag", retained.receipt?.publicId)
        assertEquals(7L, retained.receipt?.rowVersion)
        store.write(retained)
        assertEquals(json.fromJson(legacy), json.fromJson(assertNotNull(state.get<String>("reference.creation.drafts"))))
        assertEquals(retained, ReferenceCreationDraftStore(state).read(binding))
        store.remove(retained.key)
        assertEquals("[]", state.get<String>("reference.creation.drafts"))
    }

    @Test fun everyRetainedFundsFieldAndNestedActivityPartSurvivesDomainProjection() {
        val legacy = assertNotNull(javaClass.getResource("/retained-input-funds-c7738.json")).readText()
        val wire = assertNotNull(FundsWire.input.fromJson(legacy))
        val input = wire.toDomain()
        assertEquals(binding, input.binding)
        assertEquals(listOf(1234L, -1234L), input.activityParts.map { it.amountMinor })
        assertEquals("  原账户  ", input.activityParts.first().accountName)
        assertEquals(json.fromJson(legacy), json.fromJson(FundsWire.input.toJson(input.toWire())))
    }

    @Test fun acceptedMerchantInputKeepsItsReceiptWithoutReallocatingItsKey() = runTest {
        val legacy = """{"binding":$bindingJson,"kind":"Catalog","key":"original-merchant-key","displayName":"  原商户  ","canonicalMerchant":"","alias":"","phase":"accepted","catalogReceipt":{"public_id":"merchant-one","display_name":"原商户","merchant_key":"original-key","status":"hidden","usage_count":19,"created_at":"2026-09-01","updated_at":"2026-09-30","row_version":11},"error":"original-warning","nextStatus":"","sourceUnavailable":false,"targetUnavailable":false,"reviewed":true}"""
        val dao = RetainedMerchantInputDao(MerchantCreationInputEntity(binding.serverUrl, binding.ownerKey, binding.ledgerId,
            "Catalog", "original-merchant-key", legacy))
        val store = MerchantDraftStore(dao)
        val retained = store.read(binding).single()
        assertEquals("hidden", retained.catalogReceipt?.status)
        assertEquals(19, retained.catalogReceipt?.usageCount)
        store.write(retained)
        assertEquals(json.fromJson(legacy), json.fromJson(dao.row.draftJson))
        assertEquals(retained, MerchantDraftStore(dao).read(binding).single())
    }

    @Test fun savedQueryDeletionCanConsumeTheExactPreMigrationStoredBytes() = runTest {
        val definition = """{"name":"  原条件  ","month_mode":"fixed","month":"2026-09","filter":"confirmed","tag_public_id":"tag-one","home_currency_code":"JPY","query_text":"  原关键词  ","category":"交通"}"""
        val baseline = """{"public_id":"query-one","name":"原条件","row_version":7,"month_mode":"fixed","month":"2026-09","filter":"confirmed","tag_public_id":"tag-one","tag_name":"原标签","home_currency_code":"JPY","query_text":"原关键词","category":"交通"}"""
        val legacy = """{"binding":$bindingJson,"key":"original-query-key","command":"Delete","definition":$definition,"baseline":$baseline,"phase":"accepted","deletionReceipt":{"public_id":"query-one","row_version":7,"name":"原条件"},"error":"original-warning"}"""
        val dao = RetainedQueryInputDao(SavedQueryInputEntity(binding.serverUrl, binding.ownerKey, binding.ledgerId, "Delete:query-one", legacy))
        val store = SavedQueryDraftStore(dao)
        val retained = store.read(binding).single()
        assertEquals("  原关键词  ", retained.definition.queryText)
        assertEquals("query-one", retained.deletionReceipt?.publicId)
        store.consume(retained)
        assertTrue(dao.consumed, "Acknowledgement must match the original persisted bytes, including nested wire names")
    }
}

private class RetainedMerchantInputDao(var row: MerchantCreationInputEntity) : MerchantCreationInputDao {
    override suspend fun get(server: String, owner: String, ledger: String) = listOf(row)
    override suspend fun put(input: MerchantCreationInputEntity) { row = input }
    override suspend fun putAll(inputs: List<MerchantCreationInputEntity>) { row = inputs.single() }
    override suspend fun remove(server: String, owner: String, ledger: String, kind: String, key: String) = error("Unused deletion")
    override suspend fun removeKeys(server: String, owner: String, ledger: String, keys: List<String>) = error("Unused acknowledgement")
}

private class RetainedQueryInputDao(private var row: SavedQueryInputEntity) : SavedQueryInputDao {
    var consumed = false
    override suspend fun get(server: String, owner: String, ledger: String) = listOf(row)
    override suspend fun put(input: SavedQueryInputEntity) { row = input }
    override suspend fun consume(server: String, owner: String, ledger: String, slot: String, original: String): Int {
        consumed = server == row.serverUrl && owner == row.ownerKey && ledger == row.ledgerId && slot == row.slot && original == row.inputJson
        return if (consumed) 1 else 0
    }
}
