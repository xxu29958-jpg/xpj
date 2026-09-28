package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanCreateDraftContinuityTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun rawDraftSurvivesReentryAndSavedStateWithoutUsingLaterForecastDefaults() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "JPY") }
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("  十月临时稿  ")
        owner.updateDraftIncomeMonth("2026-08")
        owner.updateDraftSource(IncomeSourceType.FREELANCE)
        owner.updateDraftFrequency(IncomeFrequency.ONE_TIME)
        owner.updateDraftPayDay("09")
        owner.updateDraftAmount("12.50")
        val frozen = assertNotNull(owner.state.value.session)
        repo.active = repo.active.copy(month = "2026-10", homeCurrencyCode = "CNY")
        owner.openOriginal(repo) // sheet close, actual route pop and reentry use the retained owner
        advanceUntilIdle()
        assertEquals(frozen, owner.state.value.session)
        val reconstructed = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertEquals(frozen, reconstructed.state.value.session)
        assertFalse(requireNotNull(reconstructed.state.value.session).draft.isValid)
        reconstructed.submit()
        advanceUntilIdle()
        assertTrue(repo.creationCalls.isEmpty())
        assertEquals("12.50", reconstructed.state.value.session?.draft?.amountYuanInput)
        reconstructed.updateDraftAmount("1200")
        reconstructed.submit()
        advanceUntilIdle()
        val sent = repo.creationCalls.single()
        assertEquals(frozen.binding, sent.binding)
        assertEquals(frozen.creationKey, sent.creationKey)
        assertEquals("2026-09", sent.draft.intentMonth)
        assertEquals("2026-08", sent.draft.incomeMonth)
        assertEquals("十月临时稿", sent.draft.label)
        assertEquals("JPY", sent.draft.homeCurrencyCode)
        assertEquals(1200L, sent.draft.amountCents)
        assertEquals(9, sent.draft.payDay)
        assertEquals(IncomeSourceType.FREELANCE, sent.draft.sourceType)
    }

    @Test
    fun forecastRefreshPreservesExplicitlyClearedIncomeMonthAndOriginalIntentPeriod() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val listing = IncomePlanViewModel(repo)
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftIncomeMonth("")
        repo.active = repo.active.copy(month = "2026-10")
        listing.refresh()
        advanceUntilIdle()
        owner.openOriginal(repo)
        advanceUntilIdle()
        assertEquals("2026-10", listing.state.value.forecastMonth)
        assertEquals("", owner.state.value.session?.draft?.incomeMonthInput)
        assertEquals("2026-09", owner.state.value.session?.draft?.intentMonth)
    }

    @Test
    fun everyCompleteIdentityComponentHidesDraftAndExactReturnRestoresItReadOnly() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("原身份收入")
        owner.updateDraftAmount("0009.00")
        val frozen = assertNotNull(owner.state.value.session)
        val original = requireNotNull(repo.activeAccessFlow.value)
        val others = listOf(
            frozen.binding.copy(serverUrl = "https://other.example.com"),
            frozen.binding.copy(ledgerId = "other-ledger"),
            frozen.binding.copy(ownerKey = "other-owner"),
            frozen.binding.copy(sessionGeneration = "other-session"),
            frozen.binding.copy(bindingRevision = "other-revision"),
        )
        for (binding in others) {
            repo.activeAccessFlow.value = original.copy(binding = binding)
            advanceUntilIdle()
            assertNull(owner.state.value.session)
            owner.open(frozen.binding, "2026-10", CurrencyCode.JPY)
            owner.submit()
            assertNull(owner.state.value.session)
            repo.activeAccessFlow.value = original.copy(canModify = false)
            advanceUntilIdle()
            assertEquals(frozen, owner.state.value.session)
            assertFalse(owner.state.value.canModify)
            owner.updateDraftLabel("越权覆盖")
            owner.updateDraftAmount("99")
            owner.submit()
            assertEquals(frozen, owner.state.value.session)
        }
        assertTrue(repo.creationCalls.isEmpty())
    }

    @Test
    fun permissionRoundTripKeepsOriginalTaskAndViewerCannotStartAnotherDraft() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository()
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("保留原稿")
        val frozen = assertNotNull(owner.state.value.session)
        val original = requireNotNull(repo.activeAccessFlow.value)
        repo.activeAccessFlow.value = original.copy(canModify = false)
        advanceUntilIdle()
        owner.openOriginal(repo)
        advanceUntilIdle()
        assertEquals(frozen, owner.state.value.session)
        owner.updateDraftFrequency(IncomeFrequency.MONTHLY)
        assertEquals(frozen, owner.state.value.session)
        repo.activeAccessFlow.value = original
        advanceUntilIdle()
        assertTrue(owner.state.value.canModify)
        assertEquals(frozen, owner.state.value.session)
        owner.cancel()
        repo.activeAccessFlow.value = original.copy(canModify = false)
        advanceUntilIdle()
        owner.openOriginal(repo)
        assertNull(owner.state.value.session)
        assertTrue(repo.creationCalls.isEmpty())
    }

    @Test
    fun closeRetainsOriginalInputButExplicitCancelDiscardsAndNewTaskGetsNewKey() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository()
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("  未发送收入  ")
        val frozen = assertNotNull(owner.state.value.session)
        owner.openOriginal(repo)
        advanceUntilIdle()
        assertEquals(frozen, owner.state.value.session)
        owner.cancel()
        assertNull(owner.state.value.session)
        val reconstructed = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertNull(reconstructed.state.value.session)
        reconstructed.openOriginal(repo)
        val fresh = assertNotNull(reconstructed.state.value.session)
        assertNotEquals(frozen.creationKey, fresh.creationKey)
        assertEquals("", fresh.draft.label)
        assertTrue(repo.creationCalls.isEmpty())
    }

    @Test
    fun unsupportedCurrencyIsNeverReinterpretedByLaterDefault() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository().apply { active = active.copy(homeCurrencyCode = "VND") }
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("原未知币种收入")
        owner.updateDraftAmount("1200")
        val key = owner.state.value.session?.creationKey
        repo.active = repo.active.copy(homeCurrencyCode = "CNY")
        owner.openOriginal(repo)
        advanceUntilIdle()
        owner.submit()
        assertEquals(key, owner.state.value.session?.creationKey)
        assertNull(owner.state.value.session?.draft?.homeCurrency)
        assertEquals("1200", owner.state.value.session?.draft?.amountYuanInput)
        assertTrue(repo.creationCalls.isEmpty())
    }
}

internal fun createStateSnapshot(saved: SavedStateHandle) =
    SavedStateHandle(mapOf("income.create.drafts" to saved.get<String>("income.create.drafts")))
