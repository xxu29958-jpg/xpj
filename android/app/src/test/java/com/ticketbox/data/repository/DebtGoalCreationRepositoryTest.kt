package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtGoalCreationRepositoryTest {
    @Test fun originalDebtSelectionIsDurableNonmonetaryAndIsolatedFromSpendingCreation() = runTest {
        val f = DebtGoalCreationFixture()
        f.create().getOrThrow()
        val original = f.pending()
        assertEquals("还清欠款", original.request?.name)
        assertEquals(listOf("debt-b", "debt-a"), original.request?.debtPublicIds)
        assertEquals("debt_repayment", original.request?.goalType)
        for (field in listOf("month", "category", "target_amount_cents", "home_currency_code")) {
            assertFalse(original.row.payloadJson.contains("\"$field\""))
        }
        assertTrue(f.repository.observeCreations(f.binding).first().isEmpty())
        assertEquals(original, f.repository.describeCreation(original.row))
        assertTrue(f.calls.isEmpty())
    }

    @Test fun lostRemoteAcknowledgementReplaysTheOriginalIdsKeyAndFirstReceipt() = runTest {
        val f = DebtGoalCreationFixture()
        f.create().getOrThrow()
        val original = f.pending().row
        f.loseAck = true
        assertEquals(1, f.engine().drainOnce().failures)
        val failed = f.pending()
        assertTrue(failed.canRetry)
        val firstReceipt = f.accepted.values.single()
        f.laterRemaining = 800
        f.loseAck = false
        f.repository.recoverCreation(f.binding, failed, drop = false).getOrThrow()
        assertEquals(1, f.engine().drainOnce().done)
        val done = f.pending()
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.calls.map { it.second })
        assertEquals(f.calls.first().first, f.calls.last().first)
        assertEquals(listOf("debt-b", "debt-a"), f.calls.last().first.debtPublicIds)
        assertEquals(firstReceipt.toDomain(), done.confirmed)
        assertEquals(original.payloadJson, done.row.payloadJson)
        assertEquals(1, f.accepted.size)
    }

    @Test fun aMonetaryForeignOrChangedLinkReceiptCannotSettleTheDebtOriginal() = runTest {
        val mutations: List<(GoalDto) -> GoalDto> = listOf(
            { it.copy(homeCurrencyCode = "JPY") }, { it.copy(targetAmountCents = 1200) },
            { it.copy(category = "餐饮") }, { it.copy(spentAmountCents = 0) },
            { it.copy(remainingAmountCents = 1200) }, { it.copy(progressPercent = 0) },
            { it.copy(month = "2026-09") }, { it.copy(ledgerId = "another-ledger") },
            { it.copy(rowVersion = 2) }, { it.copy(debtRepayment = null) },
            { receipt -> receipt.copy(debtRepayment = receipt.debtRepayment!!.copy(goalVersion = 2)) },
            { receipt -> receipt.copy(debtRepayment = receipt.debtRepayment!!.copy(
                linkedDebts = listOf(receipt.debtRepayment!!.linkedDebts.first()))) },
            { receipt -> receipt.copy(debtRepayment = receipt.debtRepayment!!.copy(
                linkedDebts = receipt.debtRepayment!!.linkedDebts.map { it.copy(debtPublicId = "another-debt") })) },
        )
        for (mutation in mutations) {
            val f = DebtGoalCreationFixture()
            f.receiptMutation = mutation
            f.create().getOrThrow()
            val original = f.pending().row
            assertEquals(1, f.engine().drainOnce().failures)
            val refused = f.pending()
            assertEquals(PendingMutationStatus.Failed, refused.row.status)
            assertNull(refused.confirmed)
            assertEquals(original.payloadJson, refused.row.payloadJson)
            assertEquals(original.idempotencyKey, refused.row.idempotencyKey)
            assertTrue(f.acceptedRows.isEmpty())
        }
    }

    @Test fun changedNameOrDebtSelectionIsRefusedWhileAnIndependentTaskRemainsIndependent() = runTest {
        val f = DebtGoalCreationFixture()
        val id = f.create().getOrThrow()
        val original = f.pending()
        assertTrue(f.repository.createDebtGoal(f.binding, "另一个名称", listOf("debt-b", "debt-a"), f.key).isFailure)
        assertTrue(f.repository.createDebtGoal(f.binding, "还清欠款", listOf("debt-c"), f.key).isFailure)
        assertEquals(original, f.pending())
        val otherKey = UUID.randomUUID().toString()
        val second = f.repository.createDebtGoal(f.binding, "还清欠款", listOf("debt-b", "debt-a"), otherKey).getOrThrow()
        assertTrue(id != second)
        assertEquals(2, f.dao.rows.size)
        assertEquals(original.row.payloadJson, f.repository.originalCreation(f.binding, otherKey).getOrThrow()?.row?.payloadJson)
    }

    @Test fun theCommandOwnerRejectsMixedShapesBlankInputReadonlyAndReplacementBindings() = runTest {
        val f = DebtGoalCreationFixture()
        val request = GoalCreateRequestDto("还清欠款", goalType = "debt_repayment", debtPublicIds = listOf("debt-a"))
        for (invalid in listOf(request.copy(month = "2026-09"), request.copy(category = "其他"),
            request.copy(targetAmountCents = 1), request.copy(homeCurrencyCode = "JPY"),
            request.copy(name = " "), request.copy(debtPublicIds = emptyList()), request.copy(period = "annual"))) {
            assertTrue(f.repository.create(f.binding, invalid, f.key).isFailure)
        }
        for (stale in listOf(f.binding.copy(sessionGeneration = "next-session"),
            f.binding.copy(bindingRevision = "next-binding"), f.binding.copy(ledgerId = "another-ledger"))) {
            assertTrue(f.repository.create(stale, request, f.key).isFailure)
        }
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        assertTrue(f.repository.create(requireNotNull(f.repository.currentAccess()).binding, request, f.key).isFailure)
        assertTrue(f.dao.rows.isEmpty())
        assertTrue(f.calls.isEmpty())
    }

    @Test fun completedOriginalIsReadableWithoutASecondCommandOrCurrentCandidateLookup() = runTest {
        val f = DebtGoalCreationFixture()
        val id = f.create().getOrThrow()
        assertEquals(1, f.engine().drainOnce().done)
        val original = f.pending()
        assertEquals(id, f.create().getOrThrow())
        assertEquals(original, f.repository.originalCreation(f.binding, f.key).getOrThrow())
        assertEquals(1, f.dao.rows.size)
        assertEquals(1, f.calls.size)
    }

    @Test fun readonlyAndReplacementBindingsCannotReplayTheFailedOriginal() = runTest {
        val f = DebtGoalCreationFixture()
        f.create().getOrThrow()
        f.loseAck = true
        f.engine().drainOnce()
        val failed = f.pending()
        for (stale in listOf(f.binding.copy(sessionGeneration = "next-session"),
            f.binding.copy(bindingRevision = "next-binding"), f.binding.copy(ledgerId = "another-ledger"))) {
            assertTrue(f.repository.recoverCreation(stale, failed, drop = false).isFailure)
            assertTrue(f.repository.recoverCreation(stale, failed, drop = true).isFailure)
        }
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        val viewer = requireNotNull(f.repository.currentAccess()).binding
        assertTrue(f.repository.recoverCreation(viewer, failed, drop = false).isFailure)
        assertEquals(failed.row.payloadJson, f.dao.rows.values.single().payload)
        assertEquals(failed.row.idempotencyKey, f.dao.rows.values.single().idempotencyKey)
        assertEquals("failed", f.dao.rows.values.single().status)
        assertEquals(1, f.calls.size)
    }

    @Test fun stoppingDebtOriginalRetainsItsKeyBodyAndEvidenceWithoutClaimingRemoteRollback() = runTest {
        val f = DebtGoalCreationFixture()
        f.create().getOrThrow()
        val original = f.pending()
        f.loseAck = true
        assertEquals(1, f.engine().drainOnce().failures)
        val failed = f.pending()
        f.repository.recoverCreation(f.binding, failed, drop = true).getOrThrow()
        val stopped = requireNotNull(f.repository.originalCreation(f.binding, f.key).getOrThrow())
        assertEquals(PendingMutationStatus.Abandoned, stopped.row.status)
        assertEquals(original.row.payloadJson, stopped.row.payloadJson)
        assertEquals(original.row.idempotencyKey, stopped.row.idempotencyKey)
        assertEquals(original.row.id, stopped.row.id)
        assertFalse(stopped.canRetry)
        assertFalse(stopped.canDrop)
        assertTrue(f.repository.recoverCreation(f.binding, stopped, drop = false).isFailure)
        assertEquals(original.row.id, f.create().getOrThrow())
        assertEquals(0, f.engine().drainOnce().done)
        assertEquals(1, f.calls.size)
        assertEquals(1, f.accepted.size)
        assertEquals(1, f.dao.rows.size)
    }

    @Test fun acceptedDebtCreationRetiresOldQueryMembershipWithoutPromotingItsReceiptToARead() = runTest {
        lateinit var sendingApi: ApiService
        val request = GoalCreateRequestDto("新还债目标", goalType = "debt_repayment", debtPublicIds = listOf("debt-a"))
        val receipt = debtCreationTestReceipt(request)
        val f = GoalReadFixture { delegate -> object : ApiService by delegate {
            override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?) = receipt
        }.also { sendingApi = it } }
        f.api.goals = listOf(receipt.copy(publicId = "old-debt-goal"))
        val reports = f.repository
        reports.debtGoals().getOrThrow()
        val adapters = OutboxAdapterGraph()
        val queue = testOutboxRepository(FakePendingMutationDao(), bindingProvider = { f.provider.currentSession().toOutboxBinding() })
        val owner = GoalEditRepository(f.provider, queue, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter, adapters.goalCreateAdapter)
        owner.create(f.binding, request, UUID.randomUUID().toString()).getOrThrow()
        val dispatcher = CreateGoalDispatcher({ sendingApi }, adapters.goalCreateAdapter, adapters.goalReceiptAdapter,
            reports::invalidateGoalReadsAfterDelivery)
        assertEquals(1, OutboxDrainEngine(queue, listOf(dispatcher)).drainOnce().done)
        f.api.offline = true
        assertTrue(reports.debtGoals().isFailure)
        assertTrue(reports.goal("old-debt-goal").isFailure)
    }
}

private class DebtGoalCreationFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val dao = FakePendingMutationDao()
    val adapters = OutboxAdapterGraph()
    val outbox = testOutboxRepository(dao)
    val calls = mutableListOf<Pair<GoalCreateRequestDto, String>>()
    val accepted = mutableMapOf<String, GoalDto>()
    val acceptedRows = mutableListOf<Long>()
    val key = UUID.randomUUID().toString()
    var loseAck = false
    var laterRemaining = 1200L
    var receiptMutation: (GoalDto) -> GoalDto = { it }
    private val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?): GoalDto {
            val originalKey = requireNotNull(idempotencyKey)
            calls += request to originalKey
            val receipt = accepted.getOrPut(originalKey) { debtCreationTestReceipt(request, laterRemaining) }
            if (loseAck) throw IOException("Synthetic response lost after remote creation")
            return receiptMutation(receipt)
        }
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, session)
    val repository = GoalEditRepository(provider, outbox, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter, adapters.goalCreateAdapter)
    val binding = requireNotNull(repository.currentAccess()).binding
    suspend fun create() = repository.createDebtGoal(binding, "  还清欠款  ", listOf(" debt-b ", "debt-a", "debt-b", ""), key)
    suspend fun pending() = repository.observeCreations(binding, goalType = "debt_repayment").first().single()
    fun engine() = OutboxDrainEngine(outbox, listOf(CreateGoalDispatcher({ api }, adapters.goalCreateAdapter,
        adapters.goalReceiptAdapter) { acceptedRows += it.id }), maxAttempts = 1)
}

private fun debtCreationTestReceipt(request: GoalCreateRequestDto, remaining: Long = 1200) = GoalDto(
    "created-debt-goal", "owner", request.name, "debt_repayment", "monthly", null, null, null, null, null, null,
    "in_progress", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null,
    debtRepayment = DebtRepaymentEvaluationDto(1, "in_progress", false, linkedDebts = request.debtPublicIds.orEmpty().map {
        DebtGoalLinkViewDto(it, "open", "i_owe", "external", "原欠款对象", 1200, remaining, "JPY")
    }, voidedDebtPublicIds = emptyList()),
)
