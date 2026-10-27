package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Real editor/draft owner; the source boundary controls Room admission and write failures. */
class DebtBillDraftContinuityTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test fun editsBeforeCaptureAdmissionSurviveAColdEditorAndResumeTheOriginalTask() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = CurrencyCode.CNY.name }
        val sources = repo.creation.billSources as FakeDebtBillActions
        sources.captureGate = CompletableDeferred()
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("first")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        runCurrent()
        model.updateDraftCounterparty("edited while capture inserts")
        model.updateDraftAmount("12.34")
        runCurrent()
        assertTrue(sources.inputs.value.isEmpty())
        sources.captureGate?.complete(Unit)
        advanceUntilIdle()
        val original = sources.inputs.value.single()
        val stored = DebtCreationDraftStore(SavedStateHandle()).restore(original.original.draftJson, original.payload.binding)
        assertEquals("edited while capture inserts", stored.input.counterpartyLabel)
        assertEquals("12.34", stored.input.amountYuanInput)
        assertEquals(original.payload.creationKey, stored.creationKey)
        assertTrue(repo.parseBillCalls.isEmpty(), "Editing retires the in-flight automatic prefill, not its retained source")
        val reopened = DebtListViewModel(repo, repo.creation, repo.writes, savedStateHandle = SavedStateHandle())
        advanceUntilIdle()
        reopened.billTask(original.captureKey, DebtBillTaskAction.Resume)
        advanceUntilIdle()
        assertEquals(stored.input, reopened.state.value.addDraft)
        assertEquals(original.captureKey, reopened.state.value.activeBillCaptureKey)
        assertTrue(reopened.state.value.canSubmitCreation)
    }

    @Test fun sourceCreateFreezesTheOriginalDraftBeforeLocalAdmissionAndAdoptedResumeEndsIt() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = "CNY" }
        val sources = repo.creation.billSources as FakeDebtBillActions
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("bank")
        model.updateDraftAmount("12.00")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        repo.creation.createGate = CompletableDeferred()
        model.submitDraft()
        runCurrent()
        val input = sources.inputs.value.single()
        val frozen = DebtCreationDraftStore(SavedStateHandle()).restore(input.original.draftJson, input.payload.binding)
        assertTrue(frozen.publicationAttempted)
        assertNotNull(frozen.frozenBillSource)
        assertEquals(input.payload.creationKey, repo.creation.creationKeys.single())
        assertEquals(frozen.frozenBillSource, repo.creation.createDrafts.single().billSource)
        repo.creation.createGate?.complete(Unit)
        advanceUntilIdle()
        sources.inputs.value = listOf(input.copy(source = requireNotNull(input.source).copy(
            status = "confirmed", adoptedDebtPublicId = "created-debt")))
        val reopened = DebtListViewModel(repo, repo.creation, repo.writes, savedStateHandle = SavedStateHandle())
        advanceUntilIdle()
        reopened.billTask(input.captureKey, DebtBillTaskAction.Resume)
        advanceUntilIdle()
        assertFalse(reopened.state.value.publicationUnverified)
        assertEquals(null, reopened.state.value.activeBillCaptureKey)
        assertEquals("", reopened.state.value.addDraft.counterpartyLabel)
    }

    @Test fun failedOriginalDraftWriteBlocksCreateAndRetryKeepsTheSameSourceBodyAndKey() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = "CNY" }
        val sources = repo.creation.billSources as FakeDebtBillActions
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("bank")
        model.updateDraftAmount("12.00")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        val input = sources.inputs.value.single()
        sources.draftWriteFailure = IOException("Room write failed")
        model.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.creation.createDrafts.isEmpty())
        assertFalse(model.state.value.isSubmitting)
        assertTrue(model.state.value.publicationUnverified)
        assertNotNull(model.state.value.addDraft.validationError)
        sources.draftWriteFailure = null
        model.submitDraft()
        advanceUntilIdle()
        assertEquals(input.payload.creationKey, repo.creation.creationKeys.single())
        assertEquals(1200L, repo.creation.createDrafts.single().principalAmountCents)
        assertEquals(input.source?.publicId, repo.creation.createDrafts.single().billSource?.publicId)
    }

    private fun image() = PreparedUploadImage("bank.png", "image/png", byteArrayOf(1), 1)

    @Test fun failedLocalCaptureRetriesItsOriginalKeyAndDraft() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = "CNY" }
        val sources = (repo.creation.billSources as FakeDebtBillActions).apply { captureFailure = IOException("Room unavailable") }
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("preserved lender")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        val originalKey = sources.captureKeys.single()
        assertEquals(originalKey, model.state.value.activeBillCaptureKey)
        assertFalse(model.state.value.canSubmitCreation)
        sources.captureFailure = null
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        assertEquals(listOf(originalKey, originalKey), sources.captureKeys)
        assertEquals("preserved lender", model.state.value.addDraft.counterpartyLabel)
        assertTrue(model.state.value.canSubmitCreation)
    }

    @Test fun failedLocalCaptureCanBeExplicitlyAbandonedAfterLocalAbsenceIsVerified() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = "CNY" }
        val sources = (repo.creation.billSources as FakeDebtBillActions).apply { captureFailure = IOException("Room unavailable") }
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("preserved until discard")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        assertTrue(sources.inputs.value.isEmpty())
        model.discardDraft()
        advanceUntilIdle()
        assertEquals(null, model.state.value.activeBillCaptureKey)
        assertEquals("", model.state.value.addDraft.counterpartyLabel)
        assertTrue(repo.creation.createDrafts.isEmpty())
    }

    @Test fun unverifiedCaptureCannotDiscardAnUnknownOrAdmittedInputAsAbsent() = runTest(dispatcher) {
        val repo = FakeDebtActions().apply { listCapability = "CNY" }
        val sources = (repo.creation.billSources as FakeDebtBillActions).apply { captureFailure = IOException("Room unavailable") }
        val model = DebtListViewModel(repo, repo.creation, repo.writes)
        advanceUntilIdle()
        model.updateDraftCounterparty("retain the original")
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        val key = sources.captureKeys.single()
        sources.findFailure = IOException("Room lookup unavailable")
        model.discardDraft()
        advanceUntilIdle()
        assertEquals(key, model.state.value.activeBillCaptureKey)
        assertEquals("retain the original", model.state.value.addDraft.counterpartyLabel)
        assertNotNull(model.state.value.error)
        sources.findFailure = null
        sources.captureFailure = null
        sources.loseCaptureReply = true
        model.parseDebtBillImage(requireNotNull(model.markBillParsePreparing()), image())
        advanceUntilIdle()
        assertEquals(key, sources.inputs.value.single().captureKey)
        assertEquals(key, model.state.value.activeBillCaptureKey)
        model.discardDraft()
        advanceUntilIdle()
        assertEquals(listOf(key), sources.discardedKeys, "An admitted original must go through its actual discard owner")
        assertEquals(null, model.state.value.activeBillCaptureKey)
        assertTrue(repo.creation.createDrafts.isEmpty())
    }
}
