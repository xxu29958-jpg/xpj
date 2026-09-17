package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.test.espresso.Espresso.pressBack
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.RecurringExpenseNavigation
import com.ticketbox.ui.navigation.RecurringOccurrenceHost
import com.ticketbox.ui.navigation.RecurringPaymentDraft
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentIdentity
import com.ticketbox.ui.navigation.RecurringPaymentRestore
import com.ticketbox.ui.navigation.RecurringPaymentTask
import com.ticketbox.ui.navigation.recurringPaymentTaskJson
import com.ticketbox.ui.screens.recurring.OccurrencePaymentGuard
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecurringOccurrenceRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = RecurringOccurrenceConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val host = RecurringOccurrenceHostDriver(compose, fixture)

    @After
    fun close() {
        host.close()
    }

    @Test
    fun userSelectionSurvivesRoomRestartAndUnknownResponseThenExplicitUndo() {
        host.installModel()
        compose.setContent {
            val current = host.model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    current::choose, current::submit, current::recover,
                    onOpenExpense = { host.openedExpenses += it },
                ))
            }
        }
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithTag("occurrence-state").assertTextEquals("本期尚未履约")
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        val review = InstrumentationRegistry.getInstrumentation().targetContext.getString(
            com.ticketbox.R.string.occurrence_link_review, "房租付款", "JPY ¥12,345")
        compose.onNodeWithText(review).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals("set_recurring_occurrence_payment", original["type"])
        assertEquals("recurring-ledger", original["ledgerId"])
        assertEquals("unfulfilled", host.model.value?.uiState?.value?.occurrence?.state)

        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        fixture.reopen()
        assertEquals(original, fixture.stored().single())
        assertEquals(1, runBlocking { fixture.drain() }.retryable)
        fixture.advanceForRetry()
        fixture.network.loseResponse = false
        host.installModel()
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.occurrence?.state == "fulfilled" }
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(0L, host.model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        compose.onNodeWithText("关联付款当前金额 JPY ¥12,345").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("查看关联账单").performScrollTo().performClick()
        assertEquals(listOf(1L), host.openedExpenses)
        completeUndo()
    }

    private fun completeUndo() {
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithText("撤销本期关联").performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 2 }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled" }
        assertEquals(10_000L, host.model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        assertEquals("2026-09-05", host.model.value?.uiState?.value?.occurrence?.nextDueDate)
        assertEquals("clear", fixture.network.calls.last().first.action)
    }

    @Test
    fun restoredTaskSurvivesUnloadAndLateItemsThenReopensTheOriginalPeriod() {
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        host.installModel(open = false)
        val binding = requireNotNull(host.model.value?.uiState?.value?.access).binding
        val restored = RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "recurring-1",
            period = "2026-08",
            clientRef = "restore-august",
            merchant = "房租",
            recordedCurrencyCode = "JPY",
            suggestedAmountMinor = 1200,
            ledgerHomeCurrencyCode = "CNY",
        )
        val listed = androidx.compose.runtime.mutableStateOf(emptyList<RecurringItem>())
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}),
                    RecurringPaymentRestore(
                        items = listed.value,
                        initialTaskJson = recurringPaymentTaskJson(restored),
                    ),
                )
            }
        }
        compose.waitForIdle()
        assertEquals(null, host.model.value?.uiState?.value?.item)
        compose.runOnIdle { listed.value = listOf(occurrenceConnectedItem()) }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-08"
        }
    }

    @Test
    fun otherSeriesFulfilmentDoesNotRetireTheOriginalTaskClientRef() {
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        host.installModel(open = false)
        val binding = requireNotNull(host.model.value?.uiState?.value?.access).binding
        val restored = RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "recurring-1",
            period = "2026-08",
            clientRef = "restore-august",
            merchant = "房租",
            recordedCurrencyCode = "JPY",
            suggestedAmountMinor = 1200,
            ledgerHomeCurrencyCode = "CNY",
        )
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem(), occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费")),
                        initialTaskJson = recurringPaymentTaskJson(restored),
                    ),
                )
            }
        }
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.occurrence?.period == "2026-08" }
        fixture.network.current = fixture.network.current.copy(
            seriesPublicId = "recurring-2",
            period = "2026-08",
            state = "fulfilled",
            reservedAmountCents = 0,
        )
        compose.runOnIdle {
            host.model.value?.open(occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费"), "2026-08")
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.item?.publicId == "recurring-2" &&
                host.model.value?.uiState?.value?.occurrence?.state == "fulfilled"
        }
        fixture.network.current = fixture.network.current.copy(
            seriesPublicId = "recurring-1",
            period = "2026-08",
            state = "unfulfilled",
            reservedAmountCents = 1200,
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
        )
        compose.runOnIdle { host.model.value?.open(occurrenceConnectedItem(), "2026-08") }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.clientRef == "restore-august" }
        assertEquals("restore-august", host.paymentTask.value?.clientRef)
        assertEquals("2026-08", host.paymentTask.value?.period)
    }

    @Test
    fun closingAnotherOccurrenceDoesNotRetireOrAutoOpenTheLastTask() {
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        fixture.network.current = fixture.network.current.copy(
            period = "2026-09",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            state = "unfulfilled",
        )
        host.installModel(open = false)
        val binding = requireNotNull(host.model.value?.uiState?.value?.access).binding
        val september = RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "recurring-1",
            period = "2026-09",
            clientRef = "september-ref",
            merchant = "房租",
            recordedCurrencyCode = "JPY",
            suggestedAmountMinor = 1200,
            ledgerHomeCurrencyCode = "CNY",
        )
        drafts.remember(september)
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(
                            occurrenceConnectedItem(),
                            occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费"),
                        ),
                        drafts = drafts,
                        initialTaskJson = recurringPaymentTaskJson(september),
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        fixture.network.current = fixture.network.current.copy(
            seriesPublicId = "recurring-2",
            period = "2026-08",
            state = "unfulfilled",
            reservedAmountCents = 1200,
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
        )
        compose.runOnIdle {
            host.model.value?.open(occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费"), "2026-08")
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.item?.publicId == "recurring-2" &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-08"
        }
        pressBack()
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.item == null }
        compose.waitForIdle()
        assertNull(host.model.value?.uiState?.value?.item)
        assertEquals("september-ref", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test
    fun closingThenReopeningAndLinkingRetiresOnlyTheFulfilledTask() {
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.installModel()
        val binding = requireNotNull(host.model.value?.uiState?.value?.access).binding
        drafts.remember(
            RecurringPaymentTask(
                binding = binding,
                seriesPublicId = "recurring-1",
                period = "2026-08",
                clientRef = "august-ref",
                merchant = "房租",
                recordedCurrencyCode = "JPY",
                suggestedAmountMinor = 1200,
                ledgerHomeCurrencyCode = "CNY",
            ),
        )
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.period == "2026-09" }
        val septemberRef = requireNotNull(host.paymentTask.value?.clientRef)
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                septemberRef,
            ).getOrThrow()
        }
        drafts.removeDraft(septemberRef)
        assertEquals(septemberRef, drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        pressBack()
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.item == null }
        compose.runOnIdle { host.model.value?.open(occurrenceConnectedItem()) }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.onNodeWithTag("occurrence-record-payment").assertIsDisplayed()
        fixture.network.loseResponse = false
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        val review = InstrumentationRegistry.getInstrumentation().targetContext.getString(
            com.ticketbox.R.string.occurrence_link_review, "房租付款", "JPY ¥12,345")
        compose.onNodeWithText(review).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().any { it["type"] == "set_recurring_occurrence_payment" } }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.state == "fulfilled" &&
                drafts.remembered(binding, "recurring-1", "2026-09") == null
        }
        assertEquals("august-ref", drafts.remembered(binding, "recurring-1", "2026-08")?.clientRef)
        assertEquals("2026-09", host.model.value?.uiState?.value?.occurrence?.period)
        assertEquals("recurring-1", host.model.value?.uiState?.value?.item?.publicId)
    }

    @Test
    fun recordingSeptemberThenAugustReusesTheOriginalAugustClientRef() {
        val drafts = RecurringPaymentDraftStore(androidx.lifecycle.SavedStateHandle())
        fixture.confirmedStream.value = emptyList()
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        host.installModel()
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-08"
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.period == "2026-08" }
        val augustRef = requireNotNull(host.paymentTask.value?.clientRef)
        fixture.network.current = fixture.network.current.copy(
            period = "2026-09",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            state = "unfulfilled",
        )
        compose.runOnIdle { host.model.value?.changePeriod("2026-09") }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.canWrite == true
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.period == "2026-09" }
        assertNotEquals(augustRef, host.paymentTask.value?.clientRef)
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            state = "unfulfilled",
        )
        compose.runOnIdle { host.model.value?.changePeriod("2026-08") }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.period == "2026-08" &&
                host.model.value?.uiState?.value?.canWrite == true
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.clientRef == augustRef }
        assertEquals(augustRef, host.paymentTask.value?.clientRef)
        assertEquals("2026-08", host.paymentTask.value?.period)
        assertEquals(augustRef, drafts.remembered(
            host.paymentTask.value?.binding,
            "recurring-1",
            "2026-08",
        )?.clientRef)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test
    fun unpaidPeriodWithoutConfirmedStreamOpensExistingManualSheetFromRecordPayment() {
        fixture.confirmedStream.value = emptyList()
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        host.installModel()
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(items = listOf(occurrenceConnectedItem())),
                )
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        fixture.network.failReads = true
        compose.onNodeWithTag("occurrence-state").assertTextEquals("本期尚未履约")
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value != null }
        val task = requireNotNull(host.paymentTask.value)
        assertEquals("JPY", task.recordedCurrencyCode)
        assertEquals(1200L, task.suggestedAmountMinor)
        assertEquals("房租", task.merchant)
        assertEquals("CNY", task.ledgerHomeCurrencyCode)
        assertEquals("2026-08", task.period)
        assertEquals(emptyList<Any>(), fixture.stored())
        assertEquals("unfulfilled", host.model.value?.uiState?.value?.occurrence?.state)
        assertEquals(1200L, host.model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        assertEquals("JPY", host.model.value?.uiState?.value?.occurrence?.homeCurrencyCode)
        assertTrue(fixture.network.calls.isEmpty())
    }

    @Test
    fun savedPriorPeriodCanBeIdentifiedWhenReopenedWithUnavailablePeriodRead() {
        val graph = fixture.reopen()
        val actions = graph.recurringRepository.occurrences
        val binding = requireNotNull(actions.currentAccess()).binding
        val prior = fixture.network.current.copy(period = "2026-08")
        fixture.network.current = prior
        runBlocking {
            actions.enqueue(binding, OccurrencePaymentDraft(prior, "八月房租",
                com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto("link", 0, 7, "payment-august", 2),
                "八月完整付款", 9_800, "CNY")).getOrThrow()
        }
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        val originalKey = fixture.stored().single()["idempotencyKey"]
        fixture.network.failReads = true
        host.installModel()
        compose.setContent {
            val current = host.model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    current::choose, current::submit, current::recover,
                ))
            }
        }
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.seriesPending?.size == 1 && host.model.value?.uiState?.value?.loading == false }
        compose.onNodeWithText("八月房租 · 2026-08").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("八月完整付款", substring = true).performScrollTo().assertIsDisplayed()
        assertEquals(null, host.model.value?.uiState?.value?.occurrence)
        assertEquals(1, fixture.network.calls.size)
        val pending = host.model.value!!.uiState.value.seriesPending.single()
        assertEquals("2026-08", pending.intent?.period)
        assertEquals(2L, pending.intent?.request?.expectedExpenseRowVersion)
        fixture.network.loseResponse = false
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(originalKey, fixture.network.calls.last().second)
        assertEquals(1, fixture.network.results.size)
    }

    @Test
    fun emptyDraftStoreReusesOutboxClientRefForTheSamePeriodWithoutAnotherCreate() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        val drafts = mutableStateOf(RecurringPaymentDraftStore(SavedStateHandle()))
        val hostMounted = mutableStateOf(true)
        compose.setContent {
            val current = host.model.value ?: return@setContent
            if (!hostMounted.value) return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                key(drafts.value) {
                    RecurringOccurrenceHost(
                        current,
                        requireNotNull(host.graph).expenseRepository.manualCreation,
                        RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                        RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts.value),
                    )
                }
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        compose.waitForIdle()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.period == "2026-09" }
        val originalRef = requireNotNull(host.paymentTask.value?.clientRef)
        val binding = requireNotNull(host.paymentTask.value?.binding)
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                originalRef,
                RecurringPaymentOrigin("recurring-1", "2026-09", requireNotNull(host.paymentTask.value?.occurrenceRowVersion)),
            ).getOrThrow()
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        host.paymentTask.value = null
        val rebuilt = RecurringPaymentDraftStore(SavedStateHandle())
        compose.runOnIdle {
            drafts.value = rebuilt
            hostMounted.value = false
        }
        compose.waitForIdle()
        compose.runOnIdle { hostMounted.value = true }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitForIdle()
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.clientRef == originalRef
        }
        assertEquals(originalRef, host.paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        assertTrue(rebuilt.remembered(binding, "recurring-1", "2026-09")?.clientRef == originalRef)
    }

    @Test
    fun leftoverN1SessionRestoresUnwrappedOutboxClientRefWithoutAnotherCreate() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "legacy-ref",
            ).getOrThrow()
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        host.installModel(savedState = leftover)
        assertTrue(host.model.value?.savedState === leftover)
        val drafts = mutableStateOf(RecurringPaymentDraftStore(SavedStateHandle()))
        val hostMounted = mutableStateOf(true)
        compose.setContent {
            val current = host.model.value ?: return@setContent
            if (!hostMounted.value) return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                key(drafts.value) {
                    RecurringOccurrenceHost(
                        current,
                        requireNotNull(host.graph).expenseRepository.manualCreation,
                        RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                        RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts.value),
                    )
                }
            }
        }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null &&
                drafts.value.remembered(binding, "recurring-1", "2026-09")?.clientRef == "legacy-ref"
        }
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation
                .observeOrigin(
                    binding,
                    RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
                )
                .first()
            val found = lookup as RecurringPaymentOriginLookup.Found
            assertEquals("legacy-ref", found.projection.request?.clientRef)
        }
        val payload = fixture.stored().single { it["type"] == "create_expense" }["payload"]
        assertNotNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(payload),
            ),
        )
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        host.paymentTask.value = null
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        host.installModel(savedState = SavedStateHandle())
        compose.runOnIdle {
            drafts.value = RecurringPaymentDraftStore(SavedStateHandle())
            hostMounted.value = false
        }
        compose.waitForIdle()
        compose.runOnIdle { hostMounted.value = true }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitForIdle()
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.clientRef == "legacy-ref"
        }
        assertEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        assertTrue(drafts.value.remembered(binding, "recurring-1", "2026-09")?.clientRef == "legacy-ref")
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation
                .observeOrigin(
                    binding,
                    RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
                )
                .first()
            val found = lookup as RecurringPaymentOriginLookup.Found
            assertEquals("legacy-ref", found.projection.request?.clientRef)
        }
    }

    @Test
    fun leftoverGoneRawCreateRequiresReviewInsteadOfGuessingMerchant() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        val generation = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "legacy-ref",
            ).getOrThrow()
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(fixture.stored().single { it["type"] == "create_expense" }["payload"]),
            ),
        )
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitForIdle()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "legacy-ref"
        }
        val freshRef = requireNotNull(host.paymentTask.value?.clientRef)
        val before = requireNotNull(fixture.stored().single { it["type"] == "create_expense" }["payload"])
        runBlocking {
            val admitted = requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                freshRef,
                RecurringPaymentOrigin("recurring-1", "2026-09", generation),
            ).getOrThrow()
            val review = admitted as ManualExpenseCreateAdmission.ReviewRequired
            assertEquals(listOf("legacy-ref"), review.candidateClientRefs)
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        assertEquals(before, fixture.stored().single { it["type"] == "create_expense" }["payload"])
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                before,
            ),
        )
        assertEquals(freshRef, host.paymentTask.value?.clientRef)
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverUnsubmittedSessionKeepsTheOriginalClientRefWithoutCreatingOutbox() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null &&
                drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef == "legacy-ref"
        }
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.clientRef == "legacy-ref"
        }
        assertEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAdmittedSessionWithoutOutboxDisablesOnlyThisPeriod() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        val json =
            leftoverPeriodPaymentSessionsJson(leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = true))
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = json
        host.installModel(savedState = leftover)
        host.showOccurrenceHost()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover").performScrollTo().assertIsDisplayed()
            }.isSuccess
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("2026-09"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAdmittedMissingAbandonUnlocksANewClientRefWithoutTouchingOtherMonths() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(
                leftoverRentSession(binding, "2026-08", "august-ref", admitted = true),
                leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = true),
            )
        host.installModel(savedState = leftover)
        host.showOccurrenceHost()
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover").performScrollTo().assertIsDisplayed()
            }.isSuccess
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("occurrence-payment-leftover-abandon").performScrollTo().performClick()
        compose.waitUntil(10_000) {
            leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("legacy-ref") != true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref") == true
        }
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "legacy-ref"
        }
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("august-ref"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAdmittedMissingRetiresAfterLinkThenClearAllowsANewClientRef() {
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(
                leftoverRentSession(binding, "2026-08", "august-ref", admitted = true),
                leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = true),
            )
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover").performScrollTo().assertIsDisplayed()
            }.isSuccess
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        fixture.network.loseResponse = false
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        val review = InstrumentationRegistry.getInstrumentation().targetContext.getString(
            com.ticketbox.R.string.occurrence_link_review, "房租付款", "JPY ¥12,345")
        compose.onNodeWithText(review).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().any { it["type"] == "set_recurring_occurrence_payment" } }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.state == "fulfilled" &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("legacy-ref") != true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref") == true
        }
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
        compose.onNodeWithText("撤销本期关联").performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().count { it["type"] == "set_recurring_occurrence_payment" } == 2 }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled" }
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" &&
                host.paymentTask.value?.clientRef != null &&
                host.paymentTask.value?.clientRef != "legacy-ref"
        }
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertNotEquals("august-ref", host.paymentTask.value?.clientRef)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("august-ref"))
        assertTrue(!leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAdmittedMissingRetiresAfterAbsentHostLinkAndClear() {
        val binding = host.bindWritableSeptember()
        host.stopOccurrenceModel()
        val leftover = host.leftoverHandle(
            binding,
            leftoverRentSession(binding, "2026-08", "august-ref", admitted = true),
            leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = true),
        )
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        val hostOpen = mutableStateOf(true)
        host.showOccurrenceHost(drafts, hostOpen)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        host.waitLeftoverBlocked()
        val seen = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel(); hostOpen.value = false }
        compose.waitForIdle()
        host.bumpOccurrenceGenerationFrom(seen)
        host.installModel(savedState = leftover)
        compose.runOnIdle { hostOpen.value = true }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled" &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("legacy-ref") != true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref") == true
        }
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" &&
                host.paymentTask.value?.clientRef != null &&
                host.paymentTask.value?.clientRef != "legacy-ref"
        }
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertNotEquals("august-ref", host.paymentTask.value?.clientRef)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("august-ref"))
        assertTrue(!leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
        assertNull(drafts.remembered(binding, "recurring-1", "2026-09")?.takeIf { it.clientRef == "legacy-ref" })
    }

    @Test
    fun leftoverUnsubmittedDoesNotUpgradeAfterAbsentHostLinkAndClear() {
        val binding = host.bindWritableSeptember()
        val seen = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        host.stopOccurrenceModel()
        val leftover = host.leftoverHandle(binding, leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        leftover[requireNotNull(RecurringPaymentIdentity(binding, "recurring-1", "2026-09", seen).leftoverSeenKey())] = seen
        host.bumpOccurrenceGenerationFrom(seen)
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled" &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null &&
                drafts.remembered(binding, "recurring-1", "2026-09") == null
        }
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" &&
                host.paymentTask.value?.clientRef != null &&
                host.paymentTask.value?.clientRef != "legacy-ref"
        }
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertNull(drafts.read("legacy-ref"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverUnsubmittedFirstOpenAfterGenerationMoveHoldsUntilContinue() {
        val scene = host.openHeldLeftover { binding ->
            listOf(leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        }
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        assertTrue(scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(scene.drafts.remembered(scene.binding, "recurring-1", "2026-09"))
        val mapping = scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
        compose.onNodeWithTag("occurrence-payment-leftover-continue").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.openedPayments.size == 1 }
        assertEquals(1, host.openedPayments.size)
        assertEquals("legacy-ref", host.openedPayments.single().clientRef)
        assertEquals(mapping, scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY))
        assertTrue(scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(scene.drafts.remembered(scene.binding, "recurring-1", "2026-09"))
        compose.onNodeWithTag("occurrence-payment-leftover").assertIsDisplayed()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
        assertNull(RecurringPaymentIdentity(scene.binding, "recurring-1", "2026-09", scene.seen + 2).leftoverSeen(scene.leftover))
    }

    @Test
    fun leftoverAbandonAfterContinueDeletesDraftWithoutTouchingOutbox() {
        val scene = host.openHeldLeftover { binding ->
            listOf(
                leftoverRentSession(
                    binding, "2026-09", "legacy-b", admitted = false,
                    category = "住房", note = "旧草稿", capturedAmountCents = 9800,
                ),
            )
        }
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-payment-leftover-continue").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.clientRef == "legacy-b" }
        assertEquals("住房", scene.drafts.read("legacy-b")?.category)
        compose.onNodeWithTag("occurrence-payment-leftover-abandon").performScrollTo().performClick()
        compose.waitUntil(10_000) { scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null }
        assertNull(scene.drafts.read("legacy-b"))
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
    }

    @Test
    fun leftoverRawCreateExpenseFirstOpenAfterGenerationMoveStaysUnattributed() {
        fixture.confirmedStream.value = emptyList()
        val binding = host.bindWritableSeptember()
        val seen = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "legacy-ref",
            ).getOrThrow()
        }
        val before = requireNotNull(fixture.stored().single { it["type"] == "create_expense" }["payload"])
        host.stopOccurrenceModel()
        val leftover = host.leftoverHandle(binding, leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        host.bumpOccurrenceGenerationFrom(seen)
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(drafts.remembered(binding, "recurring-1", "2026-09"))
        assertEquals(before, fixture.stored().single { it["type"] == "create_expense" }["payload"])
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                before,
            ),
        )
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation.observeOrigin(
                binding,
                RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
            ).first()
            assertTrue(lookup is RecurringPaymentOriginLookup.Absent)
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverActiveOriginHidesContinueAndKeepsUnsubmittedDraft() {
        val scene = host.openHeldLeftover(
            beforeShow = { opened ->
            runBlocking {
                requireNotNull(host.graph).expenseRepository.manualCreation.create(
                    ExpenseDraft(
                        amountCents = 10_000,
                        originalCurrencyCode = CurrencyCode.CNY,
                        originalAmountMinor = 10_000,
                        ledgerHomeCurrency = CurrencyCode.CNY,
                        merchant = "房租",
                        category = "餐饮",
                        note = null,
                        expenseTime = "2026-09-05T08:00:00Z",
                        tags = null,
                        valueScore = null,
                        regretScore = null,
                    ),
                    opened.binding,
                    "origin-a",
                    RecurringPaymentOrigin("recurring-1", "2026-09", opened.generation),
                ).getOrThrow()
            }
            opened.drafts.write(
                RecurringPaymentDraft(
                    clientRef = "legacy-b",
                    amountText = "98.00",
                    currencyCode = "CNY",
                    merchant = "房租",
                    category = "住房",
                    note = "旧草稿",
                    expenseTime = "",
                ),
            )
            },
        ) { binding ->
            listOf(
                leftoverRentSession(
                    binding, "2026-09", "legacy-b", admitted = false,
                    category = "住房", note = "旧草稿", capturedAmountCents = 9800,
                ),
            )
        }
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-payment-leftover-existing-origin").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-payment-leftover-continue").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        assertTrue(scene.leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertEquals("origin-a", scene.drafts.remembered(scene.binding, "recurring-1", "2026-09")?.clientRef)
        assertEquals("旧草稿", scene.drafts.read("legacy-b")?.note)
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation.observeOrigin(
                scene.binding,
                RecurringPaymentOrigin("recurring-1", "2026-09", scene.generation),
            ).first()
            assertTrue(lookup is RecurringPaymentOriginLookup.Found)
            assertEquals("origin-a", (lookup as RecurringPaymentOriginLookup.Found).projection.request?.clientRef)
        }
    }

    @Test
    fun leftoverContinueKeepsCapturedDraftWhenOriginAppearsAfterOpen() {
        val binding = host.bindWritableSeptember()
        val seen = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        host.stopOccurrenceModel()
        host.bumpOccurrenceGenerationFrom(seen)
        val generation = fixture.network.current.rowVersion
        val leftover = host.leftoverHandle(
            binding,
            leftoverRentSession(
                binding,
                "2026-09",
                "legacy-b",
                admitted = false,
                category = "住房",
                note = "旧草稿",
                capturedAmountCents = 9800,
            ),
        )
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-payment-leftover-continue").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.clientRef == "legacy-b" }
        assertEquals("住房", drafts.read("legacy-b")?.category)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "origin-a",
                RecurringPaymentOrigin("recurring-1", "2026-09", generation),
            ).getOrThrow()
        }
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover-existing-origin").performScrollTo().assertIsDisplayed()
            }.isSuccess &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b") &&
                drafts.read("legacy-b")?.category == "住房"
        }
        compose.onNodeWithTag("occurrence-payment-leftover-continue").assertDoesNotExist()
        assertEquals("住房", drafts.read("legacy-b")?.category)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation.observeOrigin(
                binding,
                RecurringPaymentOrigin("recurring-1", "2026-09", generation),
            ).first()
            assertTrue(lookup is RecurringPaymentOriginLookup.Found)
            assertEquals("origin-a", (lookup as RecurringPaymentOriginLookup.Found).projection.request?.clientRef)
        }
    }

    @Test
    fun leftoverRawCreateExpenseDoesNotBindAfterAbsentHostLinkAndClear() {
        fixture.confirmedStream.value = emptyList()
        val binding = host.bindWritableSeptember()
        val seen = requireNotNull(host.model.value?.uiState?.value?.occurrence?.rowVersion)
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "legacy-ref",
            ).getOrThrow()
        }
        val before = requireNotNull(fixture.stored().single { it["type"] == "create_expense" }["payload"])
        host.stopOccurrenceModel()
        val leftover = host.leftoverHandle(binding, leftoverRentSession(binding, "2026-09", "legacy-ref", admitted = false))
        leftover[requireNotNull(RecurringPaymentIdentity(binding, "recurring-1", "2026-09", seen).leftoverSeenKey())] = seen
        host.bumpOccurrenceGenerationFrom(seen)
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null &&
                drafts.remembered(binding, "recurring-1", "2026-09") == null
        }
        assertEquals(before, fixture.stored().single { it["type"] == "create_expense" }["payload"])
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                before,
            ),
        )
        runBlocking {
            val lookup = requireNotNull(host.graph).expenseRepository.manualCreation.observeOrigin(
                binding,
                RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
            ).first()
            assertTrue(lookup is RecurringPaymentOriginLookup.Absent)
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) {
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "legacy-ref"
        }
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverUnparseableBlobAbandonRemovesTheKey() {
        fixture.confirmedStream.value = emptyList()
        val binding = host.bindWritableSeptember()
        host.stopOccurrenceModel()
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = "not-json"
        host.installModel(savedState = leftover)
        host.showOccurrenceHost()
        host.waitLeftoverBlocked()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("occurrence-payment-leftover-abandon").performScrollTo().performClick()
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover-abandon-unreadable").assertIsDisplayed()
            }.isSuccess
        }
        compose.onNodeWithTag("occurrence-payment-leftover-abandon-confirm").performClick()
        compose.waitUntil(10_000) { leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null }
        compose.onNodeWithTag("occurrence-payment-leftover").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performClick()
        compose.waitUntil(10_000) { host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != null }
        assertNotEquals("legacy-ref", host.paymentTask.value?.clientRef)
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
        assertTrue(binding.ledgerId.isNotBlank())
    }

    @Test
    fun leftoverAdmittedAugustDoesNotDisableSeptemberRecord() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(leftoverRentSession(binding, "2026-08", "august-ref", admitted = true))
        host.installModel(savedState = leftover)
        host.showOccurrenceHost()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "august-ref"
        }
        assertNotEquals("august-ref", host.paymentTask.value?.clientRef)
        assertEquals("2026-09", host.paymentTask.value?.period)
        assertEquals(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref"), true)
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverIncompleteAugustDoesNotDisableSeptemberRecord() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(leftoverRentSession(binding, "2026-08", "august-ref", admitted = false, home = null))
        host.installModel(savedState = leftover)
        host.showOccurrenceHost()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "august-ref"
        }
        assertNotEquals("august-ref", host.paymentTask.value?.clientRef)
        assertEquals("2026-09", host.paymentTask.value?.period)
        assertEquals(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref"), true)
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAugustStaysUntilAugustLoadsThenRestoresTheOriginal() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            listOf("august-ref", "september-ref").forEach { clientRef ->
                requireNotNull(host.graph).expenseRepository.manualCreation.create(
                    ExpenseDraft(
                        amountCents = 10_000,
                        originalCurrencyCode = CurrencyCode.CNY,
                        originalAmountMinor = 10_000,
                        ledgerHomeCurrency = CurrencyCode.CNY,
                        merchant = "房租",
                        category = "餐饮",
                        note = null,
                        expenseTime = "2026-09-05T08:00:00Z",
                        tags = null,
                        valueScore = null,
                        regretScore = null,
                    ),
                    binding,
                    clientRef,
                ).getOrThrow()
            }
        }
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(
                leftoverRentSession(binding, "2026-08", "august-ref", admitted = false),
                leftoverRentSession(binding, "2026-09", "september-ref", admitted = false),
            )
        host.installModel(savedState = leftover)
        val drafts = mutableStateOf(RecurringPaymentDraftStore(SavedStateHandle()))
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                key(drafts.value) {
                    RecurringOccurrenceHost(
                        current,
                        requireNotNull(host.graph).expenseRepository.manualCreation,
                        RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                        RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts.value),
                    )
                }
            }
        }
        compose.waitUntil(10_000) {
            leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref") == true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("september-ref") != true &&
                drafts.value.remembered(binding, "recurring-1", "2026-09")?.clientRef == "september-ref"
        }
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(fixture.stored().single { it["targetId"] == "expense:local:august-ref" }["payload"]),
            ),
        )
        compose.runOnIdle { drafts.value = RecurringPaymentDraftStore(SavedStateHandle()) }
        compose.waitForIdle()
        fixture.network.current = fixture.network.current.copy(period = "2026-08")
        compose.runOnIdle { host.model.value?.changePeriod("2026-08") }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.period == "2026-08" &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) == null &&
                drafts.value.remembered(binding, "recurring-1", "2026-08")?.clientRef == "august-ref"
        }
        host.paymentTask.value = null
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.clientRef == "august-ref"
        }
        val freshRef = requireNotNull(host.paymentTask.value?.clientRef)
        runBlocking {
            val admitted = requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                freshRef,
                RecurringPaymentOrigin("recurring-1", "2026-08", fixture.network.current.rowVersion),
            ).getOrThrow()
            assertEquals("august-ref", (admitted as ManualExpenseCreateAdmission.Accepted).clientRef)
        }
        assertEquals(2, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun leftoverAugustUnsubmittedMigratesOnTheSameHostAfterSeptember() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        compose.runOnIdle { host.model.value?.viewModelScope?.cancel() }
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            leftoverPeriodPaymentSessionsJson(
                leftoverRentSession(binding, "2026-08", "august-ref", admitted = false),
                leftoverRentSession(binding, "2026-09", "september-ref", admitted = false),
            )
        host.installModel(savedState = leftover)
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("august-ref") == true &&
                leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)?.contains("september-ref") != true &&
                drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef == "september-ref"
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        fixture.network.current = fixture.network.current.copy(period = "2026-08")
        compose.runOnIdle { host.model.value?.changePeriod("2026-08") }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.period == "2026-08" &&
                runCatching {
                    compose.onNodeWithTag("occurrence-record-payment").assertIsEnabled()
                    true
                }.getOrDefault(false)
        }
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        assertEquals("august-ref", host.paymentTask.value?.clientRef)
        assertEquals(0, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun rememberedStoreRefYieldsToDurableOriginOnReturnAndRecord() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "origin-a",
                RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
            ).getOrThrow()
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        val stale = RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "recurring-1",
            period = "2026-09",
            clientRef = "store-b",
            merchant = "房租",
            recordedCurrencyCode = "CNY",
            suggestedAmountMinor = 10_000,
            ledgerHomeCurrencyCode = "CNY",
        )
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        drafts.remember(stale)
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { host.paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                        initialTaskJson = recurringPaymentTaskJson(stale),
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef == "origin-a"
        }
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.clientRef == "origin-a"
        }
        assertEquals("origin-a", host.paymentTask.value?.clientRef)
        assertEquals("origin-a", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun currentVersionDraftStaysReachableAfterOriginAWins() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "origin-a",
                RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
            ).getOrThrow()
        }
        val local = RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "recurring-1",
            period = "2026-09",
            clientRef = "current-b",
            merchant = "房租",
            recordedCurrencyCode = "CNY",
            suggestedAmountMinor = 10_000,
            ledgerHomeCurrencyCode = "CNY",
        )
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        drafts.remember(local)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "CNY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-09-01T00:00:00Z",
            ),
        )
        compose.setContent {
            val current = host.model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(host.graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation(
                        { host.openedExpenses += it },
                        { host.paymentTask.value = it; host.openedPayments += it },
                        { host.openedSubmissions += it },
                    ),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                        initialTaskJson = recurringPaymentTaskJson(local),
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-local-draft").performScrollTo().assertIsDisplayed()
            }.isSuccess
        }
        assertEquals("current-b", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        assertEquals("当前草稿", drafts.read("current-b")?.note)
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("occurrence-payment-local-draft-open").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.openedPayments.any { it.clientRef == "current-b" } }
        val reopened = host.openedPayments.single { it.clientRef == "current-b" }
        assertEquals("current-b", host.paymentTask.value?.clientRef)
        assertEquals(fixture.network.current.rowVersion, reopened.occurrenceRowVersion)
        assertEquals("current-b", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        host.paymentTask.value = null
        compose.onNodeWithTag("occurrence-payment-local-draft-view").performScrollTo().performClick()
        compose.waitUntil(10_000) { host.openedSubmissions.contains("origin-a") }
        assertNull(host.paymentTask.value)
        assertTrue(host.openedPayments.none { it.clientRef == "origin-a" })
        assertEquals("current-b", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        compose.onNodeWithTag("occurrence-payment-local-draft-abandon").performScrollTo().performClick()
        compose.waitUntil(10_000) {
            drafts.read("current-b") == null &&
                drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef == "origin-a"
        }
        compose.onNodeWithTag("occurrence-payment-local-draft").assertDoesNotExist()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsEnabled()
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun fulfillingThenClearingAssociationDoesNotReopenRetiredOrigin() {
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "origin-a",
                RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
            ).getOrThrow()
        }
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        fixture.network.loseResponse = false
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        val review = InstrumentationRegistry.getInstrumentation().targetContext.getString(
            com.ticketbox.R.string.occurrence_link_review, "房租付款", "JPY ¥12,345")
        compose.onNodeWithText(review).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().any { it["type"] == "set_recurring_occurrence_payment" } }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.occurrence?.state == "fulfilled" &&
                drafts.remembered(binding, "recurring-1", "2026-09") == null
        }
        compose.waitUntil(10_000) {
            val payload = fixture.stored().single { it["type"] == "create_expense" }["payload"]
            decodeRecurringPaymentPayload(OutboxAdapterGraph().recurringPaymentCreateAdapter, requireNotNull(payload))?.retired == true
        }
        fixture.network.current = fixture.network.current.copy(
            state = "unfulfilled",
            expenseId = null,
            expensePublicId = null,
            paidAmountCents = null,
            paidHomeCurrencyCode = null,
            reservedAmountCents = 10_000,
        )
        compose.runOnIdle { host.model.value?.refresh() }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled"
        }
        host.paymentTask.value = null
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "origin-a"
        }
        assertNotEquals("origin-a", host.paymentTask.value?.clientRef)
        runBlocking {
            assertTrue(
                requireNotNull(host.graph).expenseRepository.manualCreation
                    .observeOrigin(
                        binding,
                        RecurringPaymentOrigin("recurring-1", "2026-09", fixture.network.current.rowVersion),
                    )
                    .first() is RecurringPaymentOriginLookup.Absent,
            )
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun hostAbsentOccurrenceGenerationDoesNotOccupyTheCurrentOrigin() {
        fixture.confirmedStream.value = emptyList()
        host.installModel()
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                host.model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        val binding = requireNotNull(host.graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        val previous = fixture.network.current.rowVersion
        runBlocking {
            requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                "origin-a",
                RecurringPaymentOrigin("recurring-1", "2026-09", previous),
            ).getOrThrow()
        }
        fixture.network.current = fixture.network.current.copy(rowVersion = previous + 2)
        compose.runOnIdle { host.model.value?.refresh() }
        compose.waitUntil(10_000) {
            host.model.value?.uiState?.value?.canWrite == true &&
                host.model.value?.uiState?.value?.occurrence?.rowVersion == previous + 2 &&
                host.model.value?.uiState?.value?.occurrence?.state == "unfulfilled"
        }
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        host.showOccurrenceHost(drafts)
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            host.paymentTask.value?.period == "2026-09" && host.paymentTask.value?.clientRef != "origin-a"
        }
        assertNotEquals("origin-a", host.paymentTask.value?.clientRef)
        assertEquals(previous + 2, host.paymentTask.value?.occurrenceRowVersion)
        runBlocking {
            val later = RecurringPaymentOrigin("recurring-1", "2026-09", previous + 2)
            assertTrue(
                requireNotNull(host.graph).expenseRepository.manualCreation
                    .observeOrigin(binding, later)
                    .first() is RecurringPaymentOriginLookup.Absent,
            )
            val original = requireNotNull(host.graph).expenseRepository.manualCreation
                .observeOrigin(binding, RecurringPaymentOrigin("recurring-1", "2026-09", previous))
                .first() as RecurringPaymentOriginLookup.Found
            assertEquals("origin-a", original.projection.request?.clientRef)
            val admitted = requireNotNull(host.graph).expenseRepository.manualCreation.create(
                ExpenseDraft(
                    amountCents = 10_000,
                    originalCurrencyCode = CurrencyCode.CNY,
                    originalAmountMinor = 10_000,
                    ledgerHomeCurrency = CurrencyCode.CNY,
                    merchant = "房租",
                    category = "餐饮",
                    note = null,
                    expenseTime = "2026-09-05T08:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                ),
                binding,
                requireNotNull(host.paymentTask.value?.clientRef),
                later,
            ).getOrThrow()
            assertEquals(host.paymentTask.value?.clientRef, (admitted as ManualExpenseCreateAdmission.Accepted).clientRef)
        }
        assertEquals(2, fixture.stored().count { it["type"] == "create_expense" })
    }

    @Test
    fun originConflictShowsCopyAndDisablesRecordPayment() {
        host.installModel()
        compose.setContent {
            val current = host.model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(
                    state,
                    OccurrenceSheetActions(
                        current::dismiss, current::refresh, current::changePeriod,
                        current::choose, current::submit, current::recover,
                    ),
                    origin = OccurrencePaymentGuard(resolved = true, conflict = true),
                )
            }
        }
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithTag("occurrence-payment-conflict").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().assertIsNotEnabled()
    }
}
