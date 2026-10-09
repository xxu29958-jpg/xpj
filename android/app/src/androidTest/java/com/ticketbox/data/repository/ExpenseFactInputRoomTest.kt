package com.ticketbox.data.repository

import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.viewmodel.PendingReviewValues
import com.ticketbox.viewmodel.ExpenseFactInputCodec
import com.ticketbox.viewmodel.ExpenseFactInputDraft
import com.ticketbox.viewmodel.initialCorrectionFormState
import com.ticketbox.viewmodel.originalValues
import java.time.ZoneId
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Actual disk Room, binding guard and Outbox transaction; HTTP execution belongs to the integrated journey. */
class ExpenseFactInputRoomTest {
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    @After fun close() = fixture.close()

    @Test fun rawInputSurvivesCacheCleanupAndColdReopenButCannotMoveToAnotherAccount() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val original = input(repository)
        repository.saveFactInput(null, original).getOrThrow()
        fixture.expenseDao.clearAllExpenseCaches()
        val cold = fixture.reopen().expenseRepository
        assertEquals(listOf(original), cold.loadFactInputs(original.binding, original.expenseId).getOrThrow())
        val restored = ExpenseFactInputCodec.decode(original.json, original.expenseId)
        assertEquals(" 0012.00 ", restored.correction?.amountText)
        assertEquals("  尚未完成的原稿  ", restored.correction?.reason)
        assertEquals(original.expenseId, restored.baseline.id)
        fixture.switchAccount()
        val current = requireNotNull(cold.observeCorrections().first().access).binding
        assertTrue(cold.loadFactInputs(current, original.expenseId).getOrThrow().isEmpty())
        assertTrue(cold.loadFactInputs(original.binding, original.expenseId).isFailure)
        assertTrue(cold.discardFactInput(current, original).isFailure)
        assertEquals(1, fixture.expenseDao.factInputs(original.binding.ownerKey, original.binding.ledgerId, original.expenseId).size)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun renewedBindingRequiresExplicitAdoptionAndStaleWriterCannotOverwriteIt() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val original = input(repository)
        repository.saveFactInput(null, original).getOrThrow()
        fixture.renewBinding()
        val current = requireNotNull(repository.observeCorrections().first().access).binding
        assertEquals(original, repository.loadFactInputs(current, original.expenseId).getOrThrow().single())
        assertTrue(repository.submitCorrection(current, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("重新核对", note = "我的备注"), original).isFailure)
        assertTrue(fixture.stored().isEmpty())
        val adopted = original.copy(binding = current, originalKey = "reviewed-original-key")
        repository.saveFactInput(original, adopted).getOrThrow()
        assertTrue(repository.saveFactInput(original, original.copy(json = original.json + " ")).isFailure)
        repository.submitCorrection(current, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("重新核对", note = "我的备注"), adopted).getOrThrow()
        assertEquals("reviewed-original-key", fixture.stored().single()["idempotencyKey"])
        assertTrue(repository.loadFactInputs(current, original.expenseId).getOrThrow().isEmpty())
        assertEquals(1, fixture.schedules)
        assertTrue(fixture.network.calls.isEmpty())
    }

    @Test fun changedOriginalRollsBackTheOutboxInsertAndSuccessfulConsumptionCommitsTogether() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val original = input(repository)
        repository.saveFactInput(null, original).getOrThrow()
        val changed = original.copy(json = original.json + " ")
        repository.saveFactInput(original, changed).getOrThrow()
        assertTrue(repository.submitCorrection(original.binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("核对", note = "正式修改"), original).isFailure)
        assertTrue(fixture.stored().isEmpty())
        assertEquals(0, fixture.schedules)
        assertEquals(changed, repository.loadFactInputs(original.binding, original.expenseId).getOrThrow().single())
        repository.submitCorrection(original.binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("核对", note = "正式修改"), changed).getOrThrow()
        val cold = fixture.reopen().expenseRepository
        assertEquals(original.originalKey, fixture.stored().single()["idempotencyKey"])
        assertEquals(fixture.network.current.rowVersion.toString(), fixture.stored().single()["expectedRowVersion"])
        assertFalse(fixture.stored().single()["payload"].isNullOrBlank())
        assertTrue(cold.loadFactInputs(original.binding, original.expenseId).getOrThrow().isEmpty())
        assertTrue(fixture.network.calls.isEmpty())
    }

    private suspend fun input(repository: ExpenseRepository): ExpenseFactOriginalInput {
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val expense = fixture.network.current.toDomain()
        val form = initialCorrectionFormState(expense, ZoneId.of("Asia/Shanghai")).copy(
            reason = "  尚未完成的原稿  ", amountText = " 0012.00 ", note = "原始说明", timeFormJson = "{\"raw\":true}")
        return ExpenseFactOriginalInput(binding, expense.id, "correction", "original-input-key",
            ExpenseFactInputCodec.encode(ExpenseFactInputDraft(expense, correction = form.originalValues())))
    }

    @Test fun pendingAmountRequiresAdoptionAndCommitsBothCommandsTogetherWithOriginalConsumption() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        val repository = fixture.reopen().expenseRepository
        val expense = fixture.network.current.toDomain()
        val original = input(repository).copy(formKey = "pending_amount", json = ExpenseFactInputCodec.encode(
            ExpenseFactInputDraft(expense, pendingReview = PendingReviewValues(value = " 0043.21 "))))
        repository.saveFactInput(null, original).getOrThrow()
        fixture.renewBinding()
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        assertEquals(original, repository.loadPendingReviewInputs(binding).getOrThrow().single())
        val draft = ExpenseDraft(amountCents = null, merchant = null, category = null, note = null,
            expenseTime = null, tags = null, valueScore = null, regretScore = null,
            originalCurrencyCode = CurrencyCode.CNY, originalAmountMinor = 4321)
        assertTrue(repository.saveAndConfirmExpense(binding, expense, draft, original).isFailure)
        assertTrue(fixture.stored().isEmpty())
        val adopted = original.copy(binding = binding, originalKey = "explicitly-reviewed-pending-input")
        repository.saveFactInput(original, adopted).getOrThrow()
        assertTrue(repository.saveFactInput(original, original.copy(json = original.json + " ")).isFailure)
        val changed = adopted.copy(json = adopted.json + " ")
        repository.saveFactInput(adopted, changed).getOrThrow()
        assertTrue(repository.saveAndConfirmExpense(binding, expense, draft, adopted).isFailure)
        assertTrue("A stale input must roll back the whole two-command insert", fixture.stored().isEmpty())
        assertEquals(0, fixture.schedules)
        assertEquals(changed, repository.loadPendingReviewInputs(binding).getOrThrow().single())
        repository.saveAndConfirmExpense(binding, expense, draft, changed).getOrThrow()
        val cold = fixture.reopen().expenseRepository
        val rows = fixture.stored()
        assertEquals(listOf("patch_expense", "confirm_expense"), rows.map { it["type"] })
        assertEquals(listOf("7", "7"), rows.map { it["expectedRowVersion"] })
        assertEquals(rows.map { java.util.UUID.nameUUIDFromBytes("${changed.originalKey}:${it["type"]}".toByteArray()).toString() },
            rows.map { it["idempotencyKey"] })
        assertTrue(cold.loadPendingReviewInputs(binding).getOrThrow().isEmpty())
        assertEquals(1, fixture.schedules)
        assertTrue(fixture.network.calls.isEmpty())
    }
}
