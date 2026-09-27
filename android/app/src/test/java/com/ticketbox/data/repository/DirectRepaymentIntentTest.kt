package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.security.StoredSessionToken
import java.time.Clock
import java.time.Duration
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class DirectRepaymentIntentTest {
    @Test fun changedBindingPendingRepaymentCanBeStoppedOfflineBeforeAnyDelivery() = runTest {
        for (axis in listOf("session", "revision")) {
            val fixture = DirectRepaymentTestFixture()
            fixture.save().getOrThrow()
            val original = fixture.dao.rows.values.single()
            assertEquals(PendingMutationStatus.Pending.wireValue, original.status)
            assertTrue(fixture.repository.recover(fixture.binding, fixture.pending(), drop = true).isFailure)
            assertEquals(original, fixture.dao.rows.values.single())
            val session = requireNotNull(fixture.session.sessionStore.currentSession())
            fixture.session.sessionStore.replaceForFixture(if (axis == "session") session.copy(sessionGeneration = "new-session")
                else session.copy(bindingRevision = "new-revision"))
            val outbox = fixture.newOutbox(fixture.clock)
            val writes = fixture.newRepository(outbox, fixture.clock)
            val binding = requireNotNull(writes.currentAccess()).binding
            val pending = writes.observeWrites(binding, fixture.debt.publicId).first().single()
            assertTrue(pending.originalBindingChanged, axis)
            assertFalse(pending.canRetry)
            assertTrue(writes.recover(binding, pending, drop = true).isSuccess, axis)
            val stopped = fixture.dao.rows.values.single()
            assertEquals(original.copy(status = PendingMutationStatus.Abandoned.wireValue,
                completedAt = stopped.completedAt), stopped)
            assertNotNull(stopped.completedAt)
            assertTrue(fixture.api.calls.isEmpty())
            assertTrue(fixture.api.facts.isEmpty())
            assertEquals(0, fixture.engine(outbox).drainOnce().attempted)
            writes.saveRepayment(binding, fixture.debt, 10_000L).getOrThrow()
            assertEquals(2, fixture.dao.rows.size)
            assertEquals(stopped, fixture.dao.rows.getValue(stopped.id))
        }
    }

    @Test fun newCurrentSessionOrRevisionCannotRecoverOriginalRepaymentButCanExplicitlyStopIt() = runTest {
        for (axis in listOf("session", "revision")) {
            val fixture = DirectRepaymentTestFixture()
            fixture.save().getOrThrow()
            assertEquals(1, fixture.engine().drainOnce().failures)
            val original = fixture.dao.rows.values.single()
            val originalIntent = fixture.pending().intent
            val session = requireNotNull(fixture.session.sessionStore.currentSession())
            fixture.session.sessionStore.replaceForFixture(if (axis == "session") session.copy(sessionGeneration = "new-session")
                else session.copy(bindingRevision = "new-revision"))
            val outbox = fixture.newOutbox(fixture.clock)
            val writes = fixture.newRepository(outbox, fixture.clock)
            val binding = requireNotNull(writes.currentAccess()).binding
            assertEquals(fixture.binding.ownerKey, binding.ownerKey)
            val pending = writes.observeWrites(binding, fixture.debt.publicId).first().single()
            assertEquals(originalIntent, assertNotNull(pending.intent))
            val refused = writes.recover(binding, pending, drop = false)
            assertTrue(refused.isFailure, axis)
            assertFalse(refused.exceptionOrNull()?.message.isNullOrBlank())
            assertFalse(pending.canRetry)
            assertEquals(original, fixture.dao.rows.values.single())
            assertEquals(0, fixture.engine(outbox).drainOnce().attempted)
            assertEquals(1, fixture.api.calls.size)
            writes.recover(binding, pending, drop = true).getOrThrow()
            val stopped = fixture.dao.rows.values.single()
            assertEquals(original.payload, stopped.payload)
            assertEquals(original.idempotencyKey, stopped.idempotencyKey)
            assertEquals(original.expectedRowVersion, stopped.expectedRowVersion)
            assertEquals(original.targetId, stopped.targetId)
            assertEquals(PendingMutationStatus.Abandoned.wireValue, stopped.status)
            assertEquals(1, fixture.api.facts.size)
        }
    }

    @Test fun automaticDrainCannotAdoptOriginalRepaymentUnderNewCurrentSessionOrRevision() = runTest {
        for (axis in listOf("session", "revision")) {
            val fixture = DirectRepaymentTestFixture()
            fixture.save().getOrThrow()
            val original = fixture.dao.rows.values.single()
            val originalIntent = fixture.pending().intent
            val session = requireNotNull(fixture.session.sessionStore.currentSession())
            fixture.session.sessionStore.replaceForFixture(if (axis == "session") session.copy(sessionGeneration = "new-session")
                else session.copy(bindingRevision = "new-revision"))
            val outbox = fixture.newOutbox(fixture.clock)
            val writes = fixture.newRepository(outbox, fixture.clock)
            fixture.engine(outbox).drainOnce()
            assertTrue(fixture.api.calls.isEmpty(), axis)
            assertTrue(fixture.api.facts.isEmpty(), axis)
            val binding = requireNotNull(writes.currentAccess()).binding
            val pending = writes.observeWrites(binding, fixture.debt.publicId).first().single()
            assertEquals(originalIntent, assertNotNull(pending.intent))
            assertFalse(pending.canRetry)
            assertTrue(pending.isUnresolved)
            val retained = fixture.dao.rows.values.single()
            assertEquals(original.payload, retained.payload)
            assertEquals(original.idempotencyKey, retained.idempotencyKey)
            assertEquals(original.expectedRowVersion, retained.expectedRowVersion)
            assertEquals(original.targetId, retained.targetId)
            assertEquals(null, retained.receiptJson)
        }
    }

    @Test fun credentialRefreshKeepsOriginalRepaymentRecoverableWithoutChangingBodyKeyOccOrFact() = runTest {
        val fixture = DirectRepaymentTestFixture()
        fixture.save().getOrThrow()
        assertEquals(1, fixture.engine().drainOnce().failures)
        val original = fixture.dao.rows.values.single()
        val session = requireNotNull(fixture.session.sessionStore.currentSession())
        val refresh = requireNotNull(fixture.session.sessionStore.sessionRefresh.beginOrReuse(
            expectedSessionGeneration = session.sessionGeneration, expectedToken = session.credential.token))
        assertTrue(fixture.session.sessionStore.sessionRefresh.completeIfCurrent(
            expectedSessionGeneration = session.sessionGeneration, expectedToken = session.credential.token,
            refreshAttemptId = refresh.attemptId, replacement = StoredSessionToken("refreshed-token")))
        assertEquals(fixture.binding, requireNotNull(fixture.repository.currentAccess()).binding)
        assertTrue(fixture.pending().canRetry)
        fixture.repository.recover(fixture.binding, fixture.pending(), drop = false).getOrThrow()
        fixture.api.loseResponse = false
        assertEquals(1, fixture.engine().drainOnce().done)
        val confirmed = fixture.dao.rows.values.single()
        assertEquals(original.payload, confirmed.payload)
        assertEquals(original.idempotencyKey, confirmed.idempotencyKey)
        assertEquals(original.expectedRowVersion, confirmed.expectedRowVersion)
        assertEquals(original.targetId, confirmed.targetId)
        assertEquals(1, fixture.api.facts.size)
        assertTrue(fixture.api.calls.all { it == fixture.api.calls.first() })
        assertEquals(PendingMutationStatus.Done.wireValue, confirmed.status)
    }

    @Test fun retryAfterLostResponseKeepsOriginalBindingBodyTimeOccAndKeyAcrossReopen() = runTest {
        val fixture = DirectRepaymentTestFixture()
        val id = fixture.save().getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        assertEquals(listOf(1), fixture.publishedDepths)
        assertTrue(fixture.api.calls.isEmpty())
        assertEquals("2026-09-30T15:59:00Z", fixture.pending().repayment?.request?.paidAt)
        assertEquals(1, fixture.engine().drainOnce().failures)
        assertEquals(1, fixture.api.facts.size)

        val nextDay = Clock.offset(fixture.clock, Duration.ofDays(1))
        val reopenedOutbox = fixture.newOutbox(nextDay)
        val reopenedOwner = fixture.newRepository(reopenedOutbox, nextDay)
        reopenedOwner.recover(fixture.binding, fixture.pending(reopenedOwner), drop = false).getOrThrow()
        assertEquals(1, fixture.engine(reopenedOutbox, nextDay).drainOnce().done)

        val delivered = fixture.dao.rows.getValue(id)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls.first(), fixture.api.calls.last())
        assertEquals(1, fixture.api.facts.size)
        assertEquals(original.copy(status = delivered.status, retryCount = delivered.retryCount,
            lastError = delivered.lastError, attemptedAt = delivered.attemptedAt,
            completedAt = delivered.completedAt, receiptJson = delivered.receiptJson), delivered)
        assertEquals(PendingMutationStatus.Done.wireValue, delivered.status)
        val receipt = assertNotNull(fixture.adapters.debtRepaymentReceiptAdapter.fromJson(assertNotNull(delivered.receiptJson)))
        assertEquals("repayment-original", receipt.repaymentPublicId)
        assertEquals(40_000L, DebtRepository(fixture.provider, debtReaderFixture(fixture.provider, fixture.session))
            .getDebt("d1").getOrThrow().value.remainingAmountCents)
    }

    @Test fun publicationRejectsInvalidAmountViewerAndNonDirectDebtBeforePersistOrSend() = runTest {
        val fixture = DirectRepaymentTestFixture()
        for (amount in listOf(0L, -1L, 50_001L)) assertTrue(fixture.save(amount).isFailure)
        val viewer = DirectRepaymentTestFixture(role = "viewer")
        assertTrue(viewer.save().isFailure)
        assertTrue(fixture.repository.saveRepayment(fixture.binding, fixture.debt.copy(ledgerId = "other"), 100).isFailure)
        assertTrue(fixture.repository.saveRepayment(fixture.binding,
            fixture.debt.copy(counterpartyType = "member"), 100).isFailure)
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(viewer.dao.rows.isEmpty())
        assertTrue(fixture.api.calls.isEmpty())
        assertTrue(viewer.api.calls.isEmpty())
    }

    @Test fun repaymentAndAdjustmentShareOneTargetPublicationBoundary() = runTest {
        val fixture = DirectRepaymentTestFixture()
        val outcomes = listOf(
            async { fixture.save() },
            async { fixture.repository.save(fixture.binding, fixture.debt, 100, "原调整") },
        ).awaitAll()
        assertEquals(1, outcomes.count { it.isSuccess })
        assertEquals(1, fixture.dao.rows.size)
        assertEquals(listOf(1), fixture.publishedDepths)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test fun protocolRefusalAndUnverifiedReceiptNeverSettleDone() = runTest {
        for (case in listOf("upgrade", "missing_identity", "wrong_debt", "wrong_currency", "old_occ")) {
            val fixture = DirectRepaymentTestFixture()
            fixture.api.loseResponse = false
            if (case == "upgrade") fixture.api.refusal = 426 to "client_upgrade_required"
            fixture.api.receiptTransform = { when (case) {
                "missing_identity" -> it.copy(repaymentPublicId = "")
                "wrong_debt" -> it.copy(debtPublicId = "other")
                "wrong_currency" -> it.copy(homeCurrencyCode = "JPY")
                "old_occ" -> it.copy(rowVersion = 1)
                else -> it
            } }
            val id = fixture.save().getOrThrow()
            val original = fixture.dao.rows.getValue(id)
            assertEquals(0, fixture.engine().drainOnce().done, case)
            val failed = fixture.dao.rows.getValue(id)
            assertEquals(PendingMutationStatus.Failed.wireValue, failed.status, case)
            assertEquals(original.payload, failed.payload, case)
            assertEquals(original.idempotencyKey, failed.idempotencyKey, case)
            assertEquals(null, failed.receiptJson, case)
        }
    }

    @Test fun acceptedRepaymentDoesNotLendItsFreshOccToAFollowingOriginal() = runTest {
        val fixture = DirectRepaymentTestFixture()
        fixture.api.loseResponse = false
        fixture.save().getOrThrow()
        val original = fixture.pending()
        val next = fixture.outbox.enqueue(PendingMutationType.RecordDebtRepayment, original.row.targetId,
            original.row.payloadJson, 1, "separate-original-key")
        val result = fixture.engine().drainOnce()
        assertEquals(1, result.done)
        assertEquals(1, result.conflicts)
        assertEquals(1L, fixture.dao.rows.getValue(next).expectedRowVersion)
        assertEquals(original.row.payloadJson, fixture.dao.rows.getValue(next).payload)
        assertEquals(1, fixture.api.facts.size)
    }

    @Test fun bindingChangeCannotRetargetOriginalRetryOrStop() = runTest {
        val fixture = DirectRepaymentTestFixture()
        val id = fixture.save().getOrThrow()
        fixture.engine().drainOnce()
        val pending = fixture.pending()
        val stored = fixture.dao.rows.getValue(id)
        fixture.session.switchLedgerForFixture("other", "另一本账", "owner")
        assertTrue(fixture.repository.recover(fixture.binding, pending, drop = false).isFailure)
        assertTrue(fixture.repository.recover(fixture.binding, pending, drop = true).isFailure)
        assertEquals(stored, fixture.dao.rows.getValue(id))
        assertEquals(1, fixture.api.calls.size)
        assertTrue(fixture.repository.observeWrites(fixture.binding, "d1").first().isEmpty())
    }
}
