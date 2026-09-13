package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalUpdate
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class GoalEditRepositoryTest {
    @Test fun publishIsDurableBeforeSchedulingAndRejectsDuplicateUnresolvedIntent() = runTest {
        val f = GoalEditFixture()
        val id = f.save().getOrThrow()
        assertEquals(listOf(1), f.scheduledDepth)
        assertTrue(f.keys.isEmpty())
        val original = f.dao.rows.getValue(id)
        assertEquals("goal:goal-1", original.targetId)
        assertEquals(1, original.expectedRowVersion)
        assertEquals("", f.adapters.goalUpdateAdapter.fromJson(original.payload)?.category)
        assertEquals(1, f.adapters.goalUpdateAdapter.fromJson(original.payload)?.expectedRowVersion)
        assertEquals("JPY", f.adapters.goalUpdateAdapter.fromJson(original.payload)?.homeCurrencyCode)
        assertTrue(f.save().isFailure)
        assertEquals(listOf(original), f.dao.rows.values.toList())
    }

    @Test fun lostAckRetriesTheOriginalKeyAndStoresCanonicalReceipt() = runTest {
        val f = GoalEditFixture()
        val id = f.save().getOrThrow()
        val original = f.dao.rows.getValue(id)
        f.loseAck = true
        assertEquals(1, f.engine().drainOnce().failures)
        val failed = f.pending()
        assertTrue(failed.canRetry)
        f.repository.recover(f.binding, failed, drop = false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine().drainOnce().done)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(listOf(id), f.acceptedRows)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(2, f.pending().confirmed?.rowVersion)
        assertEquals(35000, f.pending().confirmed?.targetAmountCents)
        assertEquals(27000, f.pending().confirmed?.remainingAmountCents)
        assertTrue(f.save(goal = f.current.toDomain()).isSuccess)
    }

    @Test fun exactBindingAndViewerProtectTheOriginalIntent() = runTest {
        val f = GoalEditFixture()
        val id = f.save().getOrThrow()
        f.outbox.markFailed(id, "max_attempts_exceeded(1/1): offline")
        val pending = f.pending()
        val original = f.dao.rows.getValue(id)
        f.session.switchLedgerForFixture("other", "另一账本")
        assertTrue(f.repository.recover(f.binding, pending, false).isFailure)
        assertTrue(f.save().isFailure)
        assertTrue(f.repository.observeEdits(f.binding, "goal-1").first().isEmpty())
        assertEquals(original, f.dao.rows.getValue(id))
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        val currentBinding = f.repository.currentAccess()!!.binding
        assertTrue(f.repository.recover(currentBinding, pending, false).isFailure)
        assertEquals(original, f.dao.rows.getValue(id))
    }

    @Test fun terminalRefusalCannotOfferAnEndlessRetry() = runTest {
        val f = GoalEditFixture()
        val id = f.save().getOrThrow()
        f.outbox.markFailed(id, "目标参数已失效")
        val failed = f.pending()
        assertFalse(failed.canRetry)
        assertTrue(f.repository.recover(f.binding, failed, false).isFailure)
        assertTrue(f.repository.recover(f.binding, failed, true).isSuccess)
        assertTrue(f.dao.rows.isEmpty())
    }

    @Test fun currencyUsesExistingRuntimeCapabilityWithoutDebtReads() = runTest {
        val f = GoalEditFixture()
        assertEquals(CurrencyCode.JPY, f.repository.currency(f.binding).getOrThrow())
    }

    @Test fun editCannotRelabelAnExistingGoalAndLegacyIntentStaysReadableWithoutRetry() = runTest {
        val f = GoalEditFixture()
        val goal = f.current.toDomain()
        assertTrue(f.repository.save(f.binding, goal,
            GoalUpdate(goal.rowVersion, targetAmountCents = 1200, homeCurrencyCode = "CNY")).isFailure)
        assertTrue(f.dao.rows.isEmpty())
        val id = f.save().getOrThrow()
        f.outbox.markFailed(id, "client_upgrade_required")
        val pending = f.pending()
        assertTrue(pending.canRetry)
        val raw = pending.row.payloadJson.replace("\"home_currency_code\":\"JPY\",", "")
            .replace(",\"home_currency_code\":\"JPY\"", "")
        val legacy = f.repository.describeEdit(pending.row.copy(payloadJson = raw))!!
        assertEquals(35000, legacy.request?.targetAmountCents)
        assertEquals(null, legacy.request?.homeCurrencyCode)
        assertFalse(legacy.canRetry)
        assertEquals(raw, legacy.row.payloadJson)
        assertEquals(null, f.repository.describeEdit(pending.row.copy(serverUrl = "https://other.example")))
    }
}

private class GoalEditFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val dao = FakePendingMutationDao()
    val adapters = OutboxAdapterGraph()
    val scheduledDepth = mutableListOf<Int>()
    val outbox = testOutboxRepository(dao, onEnqueued = { scheduledDepth += dao.rows.size })
    val keys = mutableListOf<String?>()
    val acceptedRows = mutableListOf<Long>()
    var loseAck = false
    var current = GoalDto("goal-1", "owner", "餐饮", "spending_limit", "monthly", "2026-09", "餐饮",
        20000, 8000, 12000, 40, "on_track", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null,
        homeCurrencyCode = "JPY")
    private val results = mutableMapOf<String, GoalDto>()
    private val api = object : com.ticketbox.data.remote.ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun runtimeCompatibility() = com.ticketbox.data.remote.dto.RuntimeCompatibilityDto(
            com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION, "compatible",
            com.ticketbox.data.remote.dto.RuntimeProductCapabilitiesDto(
                com.ticketbox.data.remote.dto.RuntimeCurrencyCapabilityDto("1:1:JPY", "JPY", 0, "compatible")))
        override suspend fun updateGoal(publicId: String, request: GoalUpdateRequestDto,
            idempotencyKey: String?, timezone: String?): GoalDto {
            keys += idempotencyKey
            val result = results.getOrPut(requireNotNull(idempotencyKey)) {
                check(request.expectedRowVersion == current.rowVersion)
                current.copy(targetAmountCents = 35000, remainingAmountCents = 27000, category = null,
                    rowVersion = current.rowVersion + 1).also { current = it }
            }
            if (loseAck) throw IOException("lost synthetic acknowledgement")
            return result
        }
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, session)
    val repository = GoalEditRepository(provider, outbox, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter,
        adapters.goalCreateAdapter)
    val binding = repository.currentAccess()!!.binding
    suspend fun save(goal: com.ticketbox.domain.model.Goal = current.toDomain()) =
        repository.save(binding, goal, GoalUpdate(goal.rowVersion, targetAmountCents = 35000, category = "", homeCurrencyCode = "JPY"))
    suspend fun pending() = repository.observeEdits(binding, "goal-1").first().last()
    fun engine() = OutboxDrainEngine(outbox, listOf(UpdateGoalDispatcher({ api },
        adapters.goalUpdateAdapter, adapters.goalReceiptAdapter) { acceptedRows += it.id }), maxAttempts = 1)
}
