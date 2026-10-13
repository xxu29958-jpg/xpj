package com.ticketbox.data.repository

import com.ticketbox.data.local.SavedQueryInputDao
import com.ticketbox.data.local.SavedQueryInputEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeleteRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeletionReceiptDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewListDto
import com.ticketbox.data.remote.dto.SavedViewUpdateRequestDto
import com.ticketbox.viewmodel.SavedQueryDraftController
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class SavedQueryContinuityTest {
    @Test fun originalCreateEditAndDeleteSurviveRecreationWithoutOverwritingLaterFacts() = runTest {
        for (command in SavedQueryCommand.entries) {
            val fixture = QueryCommandFixture()
            val firstScope = CoroutineScope(coroutineContext + SupervisorJob())
            val first = SavedQueryDraftController(fixture.repository, firstScope) {}
            first.state.first { it.ready && it.canModify }
            val slot = requireNotNull(first.begin(fixture.original.queryDefinition().copy(name = "  原保存输入  "),
                fixture.original.takeUnless { command == SavedQueryCommand.Create }, command == SavedQueryCommand.Delete))
            first.submit(slot)
            first.state.first { !it.busy && it.drafts.single().phase == "unconfirmed" }
            val original = first.state.value.drafts.single()
            assertFalse(first.state.value.canEdit(original))
            first.change(slot, original.definition.copy(name = "不能替换原命令"))
            assertEquals(original, first.state.value.drafts.single())
            firstScope.cancel()
            fixture.current = if (command == SavedQueryCommand.Delete) null else fixture.original.copy(name = "后来人工条件", rowVersion = 19)
            val later = fixture.current
            val resumedScope = CoroutineScope(coroutineContext + SupervisorJob())
            val resumed = SavedQueryDraftController(fixture.repository, resumedScope) {}
            resumed.state.first { it.ready && it.canModify }
            assertEquals(original, resumed.state.value.drafts.single())
            resumed.submit(slot)
            resumed.state.first { !it.busy && it.drafts.single().phase == "accepted" }
            assertEquals(later, fixture.current)
            assertEquals(1, fixture.receipts.size)
            assertEquals(listOf(original.key, original.key), fixture.keys)
            assertEquals(fixture.requests.first(), fixture.requests.last())
            assertEquals("  原保存输入  ", resumed.state.value.drafts.single().definition.name)
            resumed.submit(slot); advanceUntilIdle()
            assertEquals(2, fixture.keys.size)
            resumed.acknowledge(slot)
            resumed.state.first { !it.busy && it.drafts.isEmpty() }
            assertTrue(fixture.repository.readDrafts(original.binding).getOrThrow().isEmpty())
            resumedScope.cancel()
        }
    }

    @Test fun occReviewReadsOnlyAndRetainsRawInputUntilExplicitSecondSubmission() = runTest {
        val fixture = QueryCommandFixture().apply { rejectFirst = true }
        val scope = CoroutineScope(coroutineContext + SupervisorJob())
        val controller = SavedQueryDraftController(fixture.repository, scope) {}
        controller.state.first { it.ready && it.canModify }
        val slot = requireNotNull(controller.begin(fixture.original.queryDefinition().copy(name = "  我的新名字  ", queryText = "  原关键词  "), fixture.original))
        controller.submit(slot)
        controller.state.first { !it.busy && it.drafts.single().phase == "rejected" }
        val rejected = controller.state.value.drafts.single()
        fixture.current = fixture.original.copy(name = "另一端修改", rowVersion = 12)
        controller.review(slot)
        controller.state.first { !it.busy && it.drafts.single().phase == "editing" }
        val reviewed = controller.state.value.drafts.single()
        assertEquals(rejected.definition, reviewed.definition)
        assertEquals(12L, reviewed.baseline?.rowVersion)
        assertNotEquals(rejected.key, reviewed.key)
        assertEquals(1, fixture.keys.size)
        controller.submit(slot)
        controller.state.first { !it.busy && it.drafts.single().phase == "accepted" }
        assertEquals("我的新名字", fixture.current?.name)
        assertEquals(13L, fixture.current?.rowVersion)
        scope.cancel()
    }

    @Test fun persistenceFailureAndRoleLossCannotPublishOrDiscardOriginalInput() = runTest {
        val fixture = QueryCommandFixture()
        val scope = CoroutineScope(coroutineContext + SupervisorJob())
        val controller = SavedQueryDraftController(fixture.repository, scope) {}
        controller.state.first { it.ready && it.canModify }
        fixture.inputs.failWrite = true
        val slot = requireNotNull(controller.begin(fixture.original.queryDefinition()))
        controller.state.first { it.error != null }
        controller.submit(slot); advanceUntilIdle()
        assertTrue(fixture.keys.isEmpty())
        assertTrue(controller.state.value.error != null)
        fixture.inputs.failWrite = false
        controller.retrySave(slot)
        controller.state.first { it.error == null }
        val original = controller.state.value.drafts.single()
        val session = requireNotNull(fixture.session.sessionStore.currentSession())
        fixture.session.sessionStore.replaceForFixture(session.copy(identity = session.identity.copy(role = "viewer")))
        controller.state.first { !it.canModify }
        controller.submit(slot); controller.change(slot, original.definition.copy(name = "只读不能改")); advanceUntilIdle()
        assertTrue(fixture.keys.isEmpty())
        assertEquals(original, fixture.repository.readDrafts(original.binding).getOrThrow().single())
        fixture.session.sessionStore.replaceForFixture(session.copy(bindingRevision = "new-login"))
        controller.state.first { it.binding?.bindingRevision == "new-login" && it.canModify }
        assertFalse(controller.state.value.canSubmit(original))
        controller.review(slot); advanceUntilIdle()
        assertEquals(original.key, controller.state.value.drafts.single().key)
        assertEquals(original.definition, controller.state.value.drafts.single().definition)
        scope.cancel()
    }
}

private class QueryCommandFixture {
    val original = SavedViewDto("query-1", "原名称", 7, "fixed", "2026-10", "", null, null, "JPY", null, "便利店", "购物")
    var current: SavedViewDto? = original
    var rejectFirst = false
    val receipts = mutableMapOf<String, Any>()
    val keys = mutableListOf<String>()
    val requests = mutableListOf<Any>()
    val inputs = QueryInputDao()
    val session = ledgerSessionFixture("owner", "Ledger")
    private val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun savedViews() = SavedViewListDto(listOfNotNull(current))
        override suspend fun savedView(publicId: String) = requireNotNull(current)
        override suspend fun createSavedView(request: SavedViewDefinitionRequestDto, idempotencyKey: String): SavedViewDto = accept(idempotencyKey, request) {
            original.copy(name = request.name.trim(), rowVersion = 1).also { current = it }
        } as SavedViewDto
        override suspend fun updateSavedView(publicId: String, request: SavedViewUpdateRequestDto, idempotencyKey: String): SavedViewDto = accept(idempotencyKey, request) {
            requireNotNull(current).copy(name = request.name.trim(), rowVersion = request.expectedRowVersion + 1).also { current = it }
        } as SavedViewDto
        override suspend fun deleteSavedView(publicId: String, request: SavedViewDeleteRequestDto, idempotencyKey: String): SavedViewDeletionReceiptDto = accept(idempotencyKey, request) {
            SavedViewDeletionReceiptDto(original.publicId, original.rowVersion, original.name).also { current = null }
        } as SavedViewDeletionReceiptDto
    }
    val repository = SavedQueryRepository(testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, session), SavedQueryDraftStore(inputs))

    private fun accept(key: String, request: Any, create: () -> Any): Any {
        keys += key; requests += request
        if (keys.size == 1 && rejectFirst) throw RepositoryException("stale", errorCode = "state_conflict")
        val result = receipts.getOrPut(key, create)
        if (keys.size == 1) throw IOException("reply lost")
        return result
    }
}

private class QueryInputDao : SavedQueryInputDao {
    val rows = mutableListOf<SavedQueryInputEntity>()
    var failWrite = false
    override suspend fun get(server: String, owner: String, ledger: String) = rows.filter { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger }
    override suspend fun put(input: SavedQueryInputEntity) {
        if (failWrite) throw IOException("disk write failed")
        rows.removeAll { it.serverUrl == input.serverUrl && it.ownerKey == input.ownerKey && it.ledgerId == input.ledgerId && it.slot == input.slot }
        rows += input
    }
    override suspend fun consume(server: String, owner: String, ledger: String, slot: String, original: String): Int {
        return if (rows.removeAll { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger && it.slot == slot && it.inputJson == original }) 1 else 0
    }
}
