package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.StatusDto
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CategoryRuleCommandTest {
    @Test fun createAndEditEnterRoomBeforeHttpAndKeepConfirmedFacts() = runTest {
        val f = CategoryRuleCommandFixture()
        val create = f.repository.createCategoryRule(f.binding, f.current.asRequest()).getOrThrow()
        assertEquals(0, f.calls)
        assertEquals("JPY", f.pending(create).request?.homeCurrencyCode)
        assertEquals(null, f.pending(create).confirmed)
        assertEquals(1, f.engine(PendingMutationType.CreateCategoryRule).drainOnce().done)
        assertEquals("JPY", f.pending(create).confirmed?.homeCurrencyCode)
        val update = f.repository.updateCategoryRule(f.binding, f.current.toDomain(),
            f.current.asRequest().copy(amountMinCents = 3500, amountMaxCents = null)).getOrThrow()
        assertEquals(1, f.calls)
        assertEquals(1200L, f.current.amountMinCents)
        assertTrue(f.repository.deleteCategoryRule(f.binding, f.current.toDomain()).isFailure)
        assertEquals(3500L, f.pending(update).request?.amountMinCents)
    }

    @Test fun lostAckRetryKeepsKeyBoundsAndOriginalReceiptAfterAnotherEdit() = runTest {
        val f = CategoryRuleCommandFixture()
        val id = f.repository.updateCategoryRule(f.binding, f.current.toDomain(),
            f.current.asRequest().copy(amountMinCents = 3500, amountMaxCents = null)).getOrThrow()
        val original = f.dao.rows.getValue(id)
        f.loseAck = true
        assertEquals(1, f.engine(PendingMutationType.UpdateCategoryRule).drainOnce().failures)
        val accepted = f.current
        f.current = f.current.copy(amountMinCents = 7000, rowVersion = f.current.rowVersion + 1)
        f.repository.recoverSubmission(f.binding, f.pending(id), false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine(PendingMutationType.UpdateCategoryRule).drainOnce().done)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(accepted.toDomain(), f.pending(id).confirmed)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(1, f.accepted.size)
    }

    @Test fun currencyRelabelForeignBindingAndReadonlyCannotPublishOrRetry() = runTest {
        val f = CategoryRuleCommandFixture()
        assertTrue(f.repository.updateCategoryRule(f.binding, f.current.toDomain(),
            f.current.asRequest().copy(homeCurrencyCode = "CNY")).isFailure)
        val id = f.repository.createCategoryRule(f.binding, f.current.asRequest()).getOrThrow()
        f.outbox.markFailed(id, "client_upgrade_required")
        val pending = f.pending(id)
        assertTrue(pending.canRetry)
        f.session.switchLedgerForFixture("other", "其他账本")
        assertTrue(f.repository.recoverSubmission(f.binding, pending, false).isFailure)
        assertTrue(f.repository.createCategoryRule(f.binding, f.current.asRequest()).isFailure)
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        assertTrue(f.repository.recoverSubmission(f.repository.currentAccess()!!.binding, pending, false).isFailure)
        assertEquals(0, f.calls)
    }

    @Test fun terminalRefusalAndMalformedTargetNeverGetRequeuedOrSettled() = runTest {
        val f = CategoryRuleCommandFixture()
        val id = f.repository.createCategoryRule(f.binding, f.current.asRequest()).getOrThrow()
        f.outbox.markFailed(id, "目标参数不再适用")
        val pending = f.pending(id)
        assertFalse(pending.canRetry)
        assertTrue(f.repository.recoverSubmission(f.binding, pending, false).isFailure)
        val dispatcher = f.dispatcher(PendingMutationType.CreateCategoryRule)
        assertTrue(dispatcher.dispatch(pending.row.copy(targetId = "category_rule_create:")) is DispatchResult.Failure)
        assertEquals(0, f.calls)
        f.repository.recoverSubmission(f.binding, pending, true).getOrThrow()
        assertTrue(f.dao.rows.isEmpty())
    }

    @Test fun deleteIsDurableAndCanRemoveAnUnconfirmedCurrencyWithoutRelabelingIt() = runTest {
        val f = CategoryRuleCommandFixture()
        val id = f.repository.deleteCategoryRule(f.binding, f.current.toDomain().copy(homeCurrencyCode = null)).getOrThrow()
        assertEquals(0, f.calls)
        assertEquals(1, f.engine(PendingMutationType.DeleteCategoryRule).drainOnce().done)
        assertEquals(1200L, f.pending(id).request?.amountMinCents)
        assertEquals(null, f.pending(id).request?.homeCurrencyCode)
    }
}

internal class CategoryRuleCommandFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-rule-session") }
    val adapters = OutboxAdapterGraph()
    val dao = FakePendingMutationDao()
    val outbox = testOutboxRepository(dao)
    var current = CategoryRuleDto(7, "旅行", "交通", true, 10, 1200, 5000,
        createdAt = "2026-09-09T00:00:00Z", updatedAt = "2026-09-09T00:00:00Z", rowVersion = 1, homeCurrencyCode = "JPY")
    var loseAck = false
    var calls = 0
    val keys = mutableListOf<String?>()
    val accepted = mutableMapOf<String, CategoryRuleDto>()
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun createCategoryRule(request: CategoryRuleRequest, idempotencyKey: String): CategoryRuleDto =
            accept(idempotencyKey, request, 1)
        override suspend fun updateCategoryRule(id: Long, request: CategoryRuleUpdateRequest, idempotencyKey: String?,): CategoryRuleDto =
            accept(requireNotNull(idempotencyKey), CategoryRuleRequest(request.keyword, request.category, request.enabled,
                request.priority, request.amountMinCents, request.amountMaxCents, request.sourceContains,
                request.tagContains, request.homeCurrencyCode), request.expectedRowVersion + 1)
        override suspend fun deleteCategoryRule(id: Long, request: CategoryRuleDeleteRequest, idempotencyKey: String?): StatusDto {
            calls += 1; keys += idempotencyKey
            check(request.expectedRowVersion == current.rowVersion)
            return StatusDto("ok")
        }
    }
    private fun accept(key: String, request: CategoryRuleRequest, version: Long): CategoryRuleDto {
        calls += 1; keys += key
        val result = accepted.getOrPut(key) { current.copy(keyword = requireNotNull(request.keyword),
            category = requireNotNull(request.category), enabled = requireNotNull(request.enabled), priority = requireNotNull(request.priority),
            amountMinCents = request.amountMinCents, amountMaxCents = request.amountMaxCents, sourceContains = request.sourceContains,
            tagContains = request.tagContains, homeCurrencyCode = request.homeCurrencyCode, rowVersion = version).also { current = it } }
        if (loseAck) throw IOException("Synthetic lost acknowledgement")
        return result
    }
    private val factory = object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }
    val repository = RuleRepository(testServerSessionBinding(factory, FakeTicketboxSettingsStore(), session),
        offlineMutations = CategoryRuleOfflineMutationWiring(outbox, adapters.categoryRuleUpdateAdapter,
            adapters.categoryRuleDeleteAdapter, adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter))
    val binding = repository.currentAccess()!!.binding
    suspend fun pending(id: Long) = repository.observeSubmissions(binding).first().single { it.row.id == id }
    fun dispatcher(type: PendingMutationType) = CategoryRuleDispatcher(type, { api },
        adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter)
    fun engine(type: PendingMutationType) = OutboxDrainEngine(outbox, listOf(dispatcher(type)), maxAttempts = 1)
}
