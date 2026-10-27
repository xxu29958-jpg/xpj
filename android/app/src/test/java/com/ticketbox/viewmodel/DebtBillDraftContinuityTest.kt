package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CancellationException
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
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog

/** Real editor/draft owner; the source boundary controls Room admission and write failures. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class DebtBillDraftContinuityTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher); ShadowLog.clear() }
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
        sources.inputs.value = listOf(original.copy(original = original.original.copy(draftJson =
            original.original.draftJson.replace("\"input\":{", "\"input\":{\"calendarRevision\":\"private-draft-secret\","))))
        reopened.billTask(original.captureKey, DebtBillTaskAction.Resume)
        advanceUntilIdle()
        assertEquals(UiText.raw("原稿暂时未能读取，请保留当前输入后重试。"), reopened.state.value.error)
        assertEquals(original.payload, sources.inputs.value.single().payload)
        assertTrue(repo.creation.createDrafts.isEmpty())
        assertSanitizedDiagnostic("private-draft-secret", "Debt bill task unverified")
        sources.inputs.value = listOf(original)
        reopened.billTask(original.captureKey, DebtBillTaskAction.Resume)
        advanceUntilIdle()
        assertEquals(stored.input, reopened.state.value.addDraft)
        assertEquals(original.captureKey, reopened.state.value.activeBillCaptureKey)
        assertTrue(reopened.state.value.canSubmitCreation)
        ShadowLog.clear()
        val handled = RepositoryException("已处理的原建议拒绝", "permission_denied")
        repo.parseBillResult = Result.failure(handled)
        assertSame(handled, runDebtBillTask(sources, original, DebtBillTaskAction.Parse).exceptionOrNull())
        val cancelled = CancellationException("original cancelled")
        repo.parseBillResult = Result.failure(cancelled)
        assertSame(cancelled, assertFailsWith<CancellationException> { runDebtBillTask(sources, original, DebtBillTaskAction.Parse) })
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").isEmpty())
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
        reopened.updateDraftCounterparty("另一张原稿")
        reopened.billTask(input.captureKey, DebtBillTaskAction.Resume)
        advanceUntilIdle()
        assertEquals(UiText.raw("请先保存或放弃当前原稿，再继续另一张账单。"), reopened.state.value.error)
        assertEquals("另一张原稿", reopened.state.value.addDraft.counterpartyLabel)
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").isEmpty())
        reopened.discardDraft()
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
        val privateFailure = "SELECT private_bank_statement FROM C:/private-bank/secret.db password=private-draft-secret"
        sources.draftWriteFailure = IOException(privateFailure)
        model.submitDraft()
        advanceUntilIdle()
        assertTrue(repo.creation.createDrafts.isEmpty())
        assertFalse(model.state.value.isSubmitting)
        assertTrue(model.state.value.publicationUnverified)
        assertNotNull(model.state.value.addDraft.validationError)
        assertEquals(UiText.res(R.string.expense_fact_input_save_failed), model.state.value.addDraft.validationError)
        assertSanitizedDiagnostic(privateFailure, "Debt bill original draft persistence")
        sources.draftWriteFailure = null
        model.submitDraft()
        advanceUntilIdle()
        assertEquals(input.payload.creationKey, repo.creation.creationKeys.single())
        assertEquals(1200L, repo.creation.createDrafts.single().principalAmountCents)
        assertEquals(input.source?.publicId, repo.creation.createDrafts.single().billSource?.publicId)
    }

    private fun image() = PreparedUploadImage("bank.png", "image/png", byteArrayOf(1), 1)

    private fun assertSanitizedDiagnostic(privateDetail: String, operation: String) {
        val logs = ShadowLog.getLogsForTag("TicketboxNetwork")
        assertTrue(logs.isNotEmpty())
        val output = logs.joinToString("\n") { it.msg }
        assertTrue(output.contains("operation=$operation"))
        assertTrue(output.contains("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT}"))
        assertFalse(output.contains(privateDetail) || output.contains("private-bank") || output.contains("private-draft-secret"))
        assertTrue(logs.all { it.throwable == null })
    }

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
