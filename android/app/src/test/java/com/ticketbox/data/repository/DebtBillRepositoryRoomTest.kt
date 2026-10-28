package com.ticketbox.data.repository

import android.app.Application
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.DebtBillSourceReferenceDto
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class DebtBillRepositoryRoomTest {
    @Test fun coldReopenKeepsOriginalAfterDeliveryGc() = runBlocking {
        DebtBillRoomFixture().use { f ->
            val input = f.capture()
            val pending = f.db.pendingMutationDao().allRows().single()
            val scheduled = f.schedules
            f.repository.recover(input, discard = false).getOrThrow()
            assertEquals(scheduled + 1, f.schedules)
            assertEquals(pending, f.db.pendingMutationDao().allRows().single(), "Retry of admitted Pending only reschedules the original")
            f.api.loseReply = true
            f.engine().drainOnce()
            assertEquals(PendingMutationStatus.Failed.wireValue, f.db.pendingMutationDao().allRows().single().status)
            val raw = requireNotNull(f.db.debtBillInputDao().input(input.captureKey))
            f.reopen()
            // Completed-delivery GC cannot erase the independent original task owner.
            assertEquals(1, f.outbox.clearAll())
            val restored = f.repository.observe(f.binding).first().single()
            assertEquals(raw, restored.original)
            assertContentEquals(byteArrayOf(1, 2, 3), f.repository.original(restored).getOrThrow())
            val recovered = f.repository.refresh(restored).getOrThrow()
            assertEquals("source-id", recovered.source?.publicId)
            assertEquals("original-create", recovered.payload.creationKey)
            assertEquals(1, f.api.captures.size)
            assertEquals(0, f.collectOriginals())
            val failed = f.repository.suggest(recovered, retry = false).getOrThrow()
            assertEquals("failed", failed.status)
            f.reopen()
            val reopened = f.repository.observe(f.binding).first().single()
            f.repository.suggest(reopened, retry = false).getOrThrow()
            assertEquals(f.api.parses.first(), f.api.parses.last(), "Lost parse replies retain the first key and CAS body")
        }
    }

    @Test fun unsupportedCaptureKeepsOriginal() = runBlocking {
        DebtBillRoomFixture().use { f ->
            val input = f.capture()
            f.api.rejection = HttpException(Response.error<Any>(404, "{}".toResponseBody()))
            f.engine().drainOnce()
            val row = f.db.pendingMutationDao().allRows().single()
            assertEquals(PendingMutationStatus.Failed.wireValue, row.status)
            assertEquals(input.captureKey, row.idempotencyKey)
            assertEquals(input.original.payloadJson, row.payload)
            assertEquals(null, row.receiptJson)
            assertContentEquals(byteArrayOf(1, 2, 3), f.repository.original(input).getOrThrow())
            assertEquals(1, f.repository.observe(f.binding).first().size)
            assertTrue(f.api.captures.isEmpty())
        }
    }

    @Test fun ownershipAndCancellationProtectOriginal() = runBlocking {
        DebtBillRoomFixture().use { f ->
            val input = f.capture()
            f.api.rejection = CancellationException("cancelled delivery")
            try { DebtBillCaptureDispatcher({ f.api }, f.files::read).dispatch(f.db.pendingMutationDao().allRows().single().toDomain())
                error("cancellation was swallowed")
            } catch (expected: CancellationException) { assertEquals("cancelled delivery", expected.message) }
            f.session.switchLedgerForFixture("other", "Other")
            assertTrue(f.repository.original(input).isFailure)
            assertTrue(f.repository.refresh(input).isFailure)
            assertEquals(1, f.db.debtBillInputDao().allInputs().size)
            f.session.switchLedgerForFixture("owner", "Original", "viewer")
            val viewerBinding = requireNotNull(LedgerRequestGuard(f.provider).captureLogicalBinding())
            assertTrue(f.repository.capture(viewerBinding, "other-task", java.util.UUID.randomUUID().toString(), "raw",
                com.ticketbox.upload.PreparedUploadImage("x.png", "image/png", byteArrayOf(9), 1)).isFailure)
            val viewerInput = f.repository.observe(viewerBinding).first().single()
            assertTrue(f.repository.recover(viewerInput, discard = false).isFailure)
            assertTrue(f.repository.suggest(viewerInput, retry = true).isFailure)
            assertTrue(f.api.parses.isEmpty())
            assertEquals(1, f.db.pendingMutationDao().allRows().size)
        }
    }

    @Test fun sourceAdoptionKeepsOriginalCreation() = runBlocking {
        DebtBillRoomFixture().use { f ->
            val input = f.capture()
            f.engine().drainOnce()
            val recovered = f.repository.refresh(input).getOrThrow()
            val creation = DebtCreationRepository(f.provider, f.outbox, f.adapters.debt.debtCreateAdapter)
            creation.createDebt(f.binding, DebtDraft("i_owe", "Bank", 1200,
                billSource = DebtBillSourceReferenceDto(requireNotNull(recovered.source).publicId, 1)), CurrencyCode.CNY,
                input.payload.creationKey).getOrThrow()
            val row = f.db.pendingMutationDao().allRows().single { it.type == "create_debt" }
            val payload = requireNotNull(f.adapters.debt.debtCreateAdapter.fromJson(row.payload))
            assertEquals(2, payload.revision)
            assertEquals(input.payload.creationKey, row.idempotencyKey)
            assertEquals(1200L, payload.request.principalAmountCents)
            assertEquals("manual", payload.request.sourceType)
            assertEquals(DebtBillSourceReferenceDto("source-id", 1), payload.billSource)
            assertFalse(requireNotNull(f.db.debtBillInputDao().input(input.captureKey)).closed)
            f.session.switchLedgerForFixture("other", "Other")
            f.session.switchLedgerForFixture("owner", "Returned")
            val current = requireNotNull(creation.currentAccess()).binding
            val replay = creation.createDebt(current, DebtDraft("i_owe", "Bank", 1200,
                billSource = DebtBillSourceReferenceDto("source-id", 1)), CurrencyCode.CNY, input.payload.creationKey).getOrThrow()
            assertEquals(row.id, replay.intentId)
            assertEquals(row, f.db.pendingMutationDao().allRows().single { it.type == "create_debt" })
        }
    }

    @Test fun returnToLedgerFindsOriginalWithNewExactBinding() = runBlocking {
        DebtBillRoomFixture().use { f ->
            val input = f.capture()
            f.engine().drainOnce()
            val original = requireNotNull(f.db.debtBillInputDao().input(input.captureKey))
            val command = f.db.pendingMutationDao().allRows().single()
            f.session.switchLedgerForFixture("other", "Other")
            val other = requireNotNull(LedgerRequestGuard(f.provider).captureLogicalBinding())
            assertTrue(f.repository.observe(other).first().isEmpty())
            f.session.switchLedgerForFixture("owner", "Original")
            val returned = requireNotNull(LedgerRequestGuard(f.provider).captureLogicalBinding())
            assertNotEquals(f.binding.bindingRevision, returned.bindingRevision)
            assertTrue(f.repository.original(input).isFailure, "The old epoch still cannot perform a current operation")
            val visible = f.repository.observe(returned).first()
            assertEquals(1, visible.size, "The same principal's original source must remain discoverable after returning")
            val resumed = visible.single()
            assertEquals(original.payloadJson, resumed.original.payloadJson)
            assertEquals(original.creationKey, resumed.payload.creationKey)
            assertEquals(f.binding, resumed.payload.binding)
            assertContentEquals(byteArrayOf(1, 2, 3), f.repository.original(resumed).getOrThrow())
            assertEquals("source-id", f.repository.refresh(resumed).getOrThrow().source?.publicId)
            assertEquals(command.payload, f.db.pendingMutationDao().allRows().single().payload)
            f.repository.recover(resumed, discard = true).getOrThrow()
            assertTrue(requireNotNull(f.db.debtBillInputDao().input(input.captureKey)).closed)
            assertEquals(original.payloadJson, requireNotNull(f.db.debtBillInputDao().input(input.captureKey)).payloadJson)
        }
    }
}
