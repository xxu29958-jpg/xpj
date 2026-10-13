package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalUpdate
import java.io.IOException
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class GoalEditRepositoryTest {
    @Test fun dateSetAndClearRetainTheirOwnOriginalKeyOccAndFirstReceipt() = runTest {
        val f = GoalEditFixture().apply { useDebtGoal() }
        val id = f.saveDate("2028-03-01").getOrThrow()
        val original = f.dao.rows.getValue(id)
        assertTrue(f.keys.isEmpty())
        assertTrue(f.saveLinks().isFailure)
        f.loseAck = true
        assertEquals(1, f.engine().drainOnce().failures)
        val failed = f.pending()
        assertEquals("2028-03-01", failed.debtEdit?.dateRequest?.targetDate)
        assertTrue(failed.canRetry)
        f.current = f.current.copy(rowVersion = 3, name = "另一端后来修改",
            debtRepayment = f.current.debtRepayment?.copy(targetDate = "2029-12-31"))
        f.repository.recover(f.binding, failed, drop = false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine().drainOnce().done)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(original.expectedRowVersion, f.dao.rows.getValue(id).expectedRowVersion)
        assertEquals(2, f.pending().confirmed?.rowVersion)
        assertEquals(1, f.pending().confirmed?.debtRepayment?.goalVersion)
        assertEquals("2028-03-01", f.pending().confirmed?.debtRepayment?.targetDate)
        val clearId = f.saveDate(null).getOrThrow()
        assertEquals(1, f.engine().drainOnce().done)
        assertEquals(null, f.pending().confirmed?.debtRepayment?.targetDate)
        assertEquals(4, f.pending().confirmed?.rowVersion)
        assertEquals(1, f.pending().confirmed?.debtRepayment?.goalVersion)
        assertTrue(f.dao.rows.getValue(clearId).idempotencyKey != original.idempotencyKey)
    }

    @Test fun dateTaskRejectsNonApplicableGoalsAndUnmatchedReceiptsWithoutDroppingTheOriginal() = runTest {
        val f = GoalEditFixture().apply { useDebtGoal() }
        assertTrue(f.saveDate("2028-02-31").isFailure)
        val current = f.current
        f.current = current.copy(debtRepayment = current.debtRepayment?.copy(linkedDebts =
            current.debtRepayment.linkedDebts.map { it.copy(counterpartyType = "member") }))
        assertTrue(f.saveDate("2028-03-01").isFailure)
        f.current = current
        val id = f.saveDate("2028-03-01").getOrThrow()
        val original = f.dao.rows.getValue(id)
        f.receiptOverride = current.copy(rowVersion = 2, debtRepayment = current.debtRepayment?.copy(
            targetDate = "2028-03-01", goalVersion = 2))
        assertEquals(1, f.engine().drainOnce().failures)
        assertEquals(null, f.pending().confirmed)
        assertFalse(f.pending().isDone)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(original.idempotencyKey, f.dao.rows.getValue(id).idempotencyKey)
        assertTrue(f.acceptedRows.isEmpty())
    }

    @Test fun debtEditReplayRetainsTheOriginalSelectionAndReceiptAfterALaterGoalChange() = runTest {
        val f = GoalEditFixture()
        f.useDebtGoal()
        val id = f.saveLinks().getOrThrow()
        val original = f.dao.rows.getValue(id)
        assertEquals(listOf(1), f.scheduledDepth)
        assertTrue(f.keys.isEmpty())
        assertTrue(f.saveLinks().isFailure)
        f.loseAck = true
        assertEquals(1, f.engine().drainOnce().failures)
        val failed = f.pending()
        assertEquals(listOf("debt-a", "debt-b"), failed.debtEdit?.request?.debtPublicIds)
        assertTrue(failed.canRetry)
        f.current = f.current.copy(rowVersion = 3, name = "另一端后来修改")
        f.repository.recover(f.binding, failed, drop = false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine().drainOnce().done)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(original.expectedRowVersion, f.dao.rows.getValue(id).expectedRowVersion)
        assertEquals(2, f.pending().confirmed?.rowVersion)
        assertEquals("原还债目标", f.pending().confirmed?.name)
        assertEquals(listOf(id), f.acceptedRows)
    }

    @Test fun debtEditRefuseForeignAndNewerReceiptsAndCannotSubmitAsViewer() = runTest {
        val f = GoalEditFixture()
        f.useDebtGoal()
        val id = f.saveLinks().getOrThrow()
        val original = f.pending()
        f.receiptOverride = f.current.copy(rowVersion = 8)
        assertEquals(1, f.engine().drainOnce().failures)
        assertEquals(null, f.pending().confirmed)
        assertFalse(f.pending().canRetry)
        assertTrue(f.acceptedRows.isEmpty())
        val stored = f.dao.rows.getValue(id)
        f.session.switchLedgerForFixture("other", "另一账本")
        assertEquals(null, f.repository.describeEdit(original.row))
        assertTrue(f.saveLinks().isFailure)
        assertEquals(stored, f.dao.rows.getValue(id))
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        assertTrue(f.repository.save(requireNotNull(f.repository.currentAccess()).binding,
            f.current.toDomain(), com.ticketbox.domain.model.DebtGoalLinksUpdate(f.current.rowVersion, mapOf("debt-a" to "甲"))).isFailure)
        val missing = GoalEditFixture().apply {
            useDebtGoal()
            replyFailure = retrofit2.HttpException(retrofit2.Response.error<Any>(404,
                """{"error":"goal_not_found","message":"目标不存在"}""".toResponseBody()))
        }
        val missingId = missing.saveLinks().getOrThrow()
        val missingOriginal = missing.dao.rows.getValue(missingId)
        assertEquals(1, missing.engine().drainOnce().failures)
        assertFalse(missing.pending().isDone)
        assertTrue(missing.pending().canDrop)
        assertEquals(null, missing.pending().confirmed)
        assertEquals(missingOriginal.payload, missing.dao.rows.getValue(missingId).payload)
        assertEquals(missingOriginal.idempotencyKey, missing.dao.rows.getValue(missingId).idempotencyKey)
    }

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
    var receiptOverride: GoalDto? = null
    var replyFailure: Exception? = null
    var current = GoalDto("goal-1", "owner", "餐饮", "spending_limit", "monthly", "2026-09", "餐饮",
        20000, 8000, 12000, 40, "on_track", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null,
        homeCurrencyCode = "JPY")
    private val results = mutableMapOf<String, GoalDto>()
    private val api = object : com.ticketbox.data.remote.ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun setGoalTargetDate(publicId: String,
            request: com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto, idempotencyKey: String?, timezone: String?): GoalDto {
            keys += idempotencyKey
            replyFailure?.let { throw it }
            val result = results.getOrPut(requireNotNull(idempotencyKey)) {
                check(request.expectedRowVersion == current.rowVersion)
                current.copy(rowVersion = current.rowVersion + 1, debtRepayment = current.debtRepayment?.copy(
                    targetDate = request.targetDate)).also { current = it }
            }
            if (loseAck) throw IOException("lost synthetic date reply")
            return receiptOverride ?: result
        }
        override suspend fun replaceGoalDebtLinks(publicId: String,
            request: com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto,
            idempotencyKey: String?, timezone: String?): GoalDto {
            keys += idempotencyKey
            replyFailure?.let { throw it }
            val result = results.getOrPut(requireNotNull(idempotencyKey)) {
                check(request.expectedRowVersion == current.rowVersion)
                current.copy(rowVersion = current.rowVersion + 1, debtRepayment = current.debtRepayment?.copy(
                    linkedDebts = request.debtPublicIds.map { debtId ->
                        com.ticketbox.data.remote.dto.DebtGoalLinkViewDto(debtId, "open", "i_owe", "external", debtId, 100, 100, "CNY")
                    })).also { current = it }
            }
            if (loseAck) throw IOException("lost synthetic acknowledgement")
            return receiptOverride ?: result
        }
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
        adapters.goalCreateAdapter, adapters.goalDebtEditAdapter)
    val binding = repository.currentAccess()!!.binding
    fun useDebtGoal() {
        current = current.copy(name = "原还债目标", goalType = "debt_repayment", period = "unbounded", month = null,
            targetAmountCents = null, homeCurrencyCode = null,
            debtRepayment = com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto(1, "in_progress", false,
                linkedDebts = listOf(com.ticketbox.data.remote.dto.DebtGoalLinkViewDto(
                    "debt-a", "open", "i_owe", "external", "原欠款", 100, 100, "CNY")), voidedDebtPublicIds = emptyList()))
    }
    suspend fun saveDate(value: String?) = repository.save(binding, current.toDomain(),
        com.ticketbox.domain.model.DebtGoalTargetDateUpdate(current.rowVersion, value))
    suspend fun saveLinks() = repository.save(binding, current.toDomain(),
        com.ticketbox.domain.model.DebtGoalLinksUpdate(current.rowVersion, linkedMapOf("debt-a" to "甲", "debt-b" to "乙")))
    suspend fun save(goal: com.ticketbox.domain.model.Goal = current.toDomain()) =
        repository.save(binding, goal, GoalUpdate(goal.rowVersion, targetAmountCents = 35000, category = "", homeCurrencyCode = "JPY"))
    suspend fun pending() = repository.observeEdits(binding, "goal-1").first().last()
    fun engine() = OutboxDrainEngine(outbox, listOf(UpdateGoalDispatcher({ api },
        adapters.goalUpdateAdapter, adapters.goalReceiptAdapter) { acceptedRows += it.id },
        DebtGoalEditDispatcher({ api }, adapters.goalDebtEditAdapter, adapters.goalReceiptAdapter) { acceptedRows += it.id },
        DebtGoalEditDispatcher({ api }, adapters.goalDebtEditAdapter, adapters.goalReceiptAdapter,
            com.ticketbox.data.local.PendingMutationType.SetGoalTargetDate) { acceptedRows += it.id }), maxAttempts = 1)
}
