package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.test.espresso.Espresso.pressBack
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.RepositoryGraph
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.RecurringExpenseNavigation
import com.ticketbox.ui.navigation.RecurringOccurrenceHost
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentRestore
import com.ticketbox.ui.navigation.RecurringPaymentTask
import com.ticketbox.ui.navigation.recurringPaymentTaskJson
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecurringOccurrenceRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = RecurringOccurrenceConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<RecurringOccurrenceViewModel?>(null)
    private val openedExpenses = mutableListOf<Long>()
    private var graph: RepositoryGraph? = null
    private val paymentTask = mutableStateOf<RecurringPaymentTask?>(null)

    @After
    fun close() {
        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun userSelectionSurvivesRoomRestartAndUnknownResponseThenExplicitUndo() {
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    current::choose, current::submit, current::recover,
                    onOpenExpense = { openedExpenses += it },
                ))
            }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.canWrite == true }
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
        assertEquals("unfulfilled", model.value?.uiState?.value?.occurrence?.state)

        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
        fixture.reopen()
        assertEquals(original, fixture.stored().single())
        assertEquals(1, runBlocking { fixture.drain() }.retryable)
        fixture.advanceForRetry()
        fixture.network.loseResponse = false
        installModel()
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { model.value?.uiState?.value?.occurrence?.state == "fulfilled" }
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(0L, model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        compose.onNodeWithText("关联付款当前金额 JPY ¥12,345").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("查看关联账单").performScrollTo().performClick()
        assertEquals(listOf(1L), openedExpenses)
        completeUndo()
    }

    private fun completeUndo() {
        compose.waitUntil(10_000) { model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithText("撤销本期关联").performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 2 }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { model.value?.uiState?.value?.occurrence?.state == "unfulfilled" }
        assertEquals(10_000L, model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        assertEquals("2026-09-05", model.value?.uiState?.value?.occurrence?.nextDueDate)
        assertEquals("clear", fixture.network.calls.last().first.action)
    }

    private fun installModel(open: Boolean = true) {
        val graph = fixture.reopen()
        this.graph = graph
        compose.runOnIdle {
            model.value = RecurringOccurrenceViewModel(
                graph.recurringRepository.occurrences,
                fixture.ledger,
                fixture.debts,
            ).also { if (open) it.open(occurrenceConnectedItem()) }
        }
    }

    @Test
    fun restoredTaskSurvivesUnloadAndLateItemsThenReopensTheOriginalPeriod() {
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        installModel(open = false)
        val binding = requireNotNull(model.value?.uiState?.value?.access).binding
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
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}),
                    RecurringPaymentRestore(
                        items = listed.value,
                        initialTaskJson = recurringPaymentTaskJson(restored),
                    ),
                )
            }
        }
        compose.waitForIdle()
        assertEquals(null, model.value?.uiState?.value?.item)
        compose.runOnIdle { listed.value = listOf(occurrenceConnectedItem()) }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                model.value?.uiState?.value?.occurrence?.period == "2026-08"
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
        installModel(open = false)
        val binding = requireNotNull(model.value?.uiState?.value?.access).binding
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
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem(), occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费")),
                        initialTaskJson = recurringPaymentTaskJson(restored),
                    ),
                )
            }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.occurrence?.period == "2026-08" }
        fixture.network.current = fixture.network.current.copy(
            seriesPublicId = "recurring-2",
            period = "2026-08",
            state = "fulfilled",
            reservedAmountCents = 0,
        )
        compose.runOnIdle {
            model.value?.open(occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费"), "2026-08")
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.item?.publicId == "recurring-2" &&
                model.value?.uiState?.value?.occurrence?.state == "fulfilled"
        }
        fixture.network.current = fixture.network.current.copy(
            seriesPublicId = "recurring-1",
            period = "2026-08",
            state = "unfulfilled",
            reservedAmountCents = 1200,
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
        )
        compose.runOnIdle { model.value?.open(occurrenceConnectedItem(), "2026-08") }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.clientRef == "restore-august" }
        assertEquals("restore-august", paymentTask.value?.clientRef)
        assertEquals("2026-08", paymentTask.value?.period)
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
        installModel(open = false)
        val binding = requireNotNull(model.value?.uiState?.value?.access).binding
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
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
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
            model.value?.uiState?.value?.item?.publicId == "recurring-1" &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
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
            model.value?.open(occurrenceConnectedItem().copy(publicId = "recurring-2", merchant = "电费"), "2026-08")
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.item?.publicId == "recurring-2" &&
                model.value?.uiState?.value?.occurrence?.period == "2026-08"
        }
        pressBack()
        compose.waitUntil(10_000) { model.value?.uiState?.value?.item == null }
        compose.waitForIdle()
        assertNull(model.value?.uiState?.value?.item)
        assertEquals("september-ref", drafts.remembered(binding, "recurring-1", "2026-09")?.clientRef)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test
    fun closingThenReopeningAndLinkingRetiresOnlyTheFulfilledTask() {
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        installModel()
        val binding = requireNotNull(model.value?.uiState?.value?.access).binding
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
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.period == "2026-09" }
        val septemberRef = requireNotNull(paymentTask.value?.clientRef)
        runBlocking {
            requireNotNull(graph).expenseRepository.manualCreation.create(
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
        compose.waitUntil(10_000) { model.value?.uiState?.value?.item == null }
        compose.runOnIdle { model.value?.open(occurrenceConnectedItem()) }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
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
            model.value?.uiState?.value?.occurrence?.state == "fulfilled" &&
                drafts.remembered(binding, "recurring-1", "2026-09") == null
        }
        assertEquals("august-ref", drafts.remembered(binding, "recurring-1", "2026-08")?.clientRef)
        assertEquals("2026-09", model.value?.uiState?.value?.occurrence?.period)
        assertEquals("recurring-1", model.value?.uiState?.value?.item?.publicId)
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
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
                    RecurringPaymentRestore(
                        items = listOf(occurrenceConnectedItem()),
                        drafts = drafts,
                    ),
                )
            }
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.ledgerHomeCurrencyCode != null &&
                model.value?.uiState?.value?.occurrence?.period == "2026-08"
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.period == "2026-08" }
        val augustRef = requireNotNull(paymentTask.value?.clientRef)
        fixture.network.current = fixture.network.current.copy(
            period = "2026-09",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            state = "unfulfilled",
        )
        compose.runOnIdle { model.value?.changePeriod("2026-09") }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                model.value?.uiState?.value?.canWrite == true
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.period == "2026-09" }
        assertNotEquals(augustRef, paymentTask.value?.clientRef)
        fixture.network.current = fixture.network.current.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            state = "unfulfilled",
        )
        compose.runOnIdle { model.value?.changePeriod("2026-08") }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.occurrence?.period == "2026-08" &&
                model.value?.uiState?.value?.canWrite == true
        }
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.clientRef == augustRef }
        assertEquals(augustRef, paymentTask.value?.clientRef)
        assertEquals("2026-08", paymentTask.value?.period)
        assertEquals(augustRef, drafts.remembered(
            paymentTask.value?.binding,
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
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
                    RecurringPaymentRestore(items = listOf(occurrenceConnectedItem())),
                )
            }
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        fixture.network.failReads = true
        compose.onNodeWithTag("occurrence-state").assertTextEquals("本期尚未履约")
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value != null }
        val task = requireNotNull(paymentTask.value)
        assertEquals("JPY", task.recordedCurrencyCode)
        assertEquals(1200L, task.suggestedAmountMinor)
        assertEquals("房租", task.merchant)
        assertEquals("CNY", task.ledgerHomeCurrencyCode)
        assertEquals("2026-08", task.period)
        assertEquals(emptyList<Any>(), fixture.stored())
        assertEquals("unfulfilled", model.value?.uiState?.value?.occurrence?.state)
        assertEquals(1200L, model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        assertEquals("JPY", model.value?.uiState?.value?.occurrence?.homeCurrencyCode)
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
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    current::choose, current::submit, current::recover,
                ))
            }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.seriesPending?.size == 1 && model.value?.uiState?.value?.loading == false }
        compose.onNodeWithText("八月房租 · 2026-08").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("八月完整付款", substring = true).performScrollTo().assertIsDisplayed()
        assertEquals(null, model.value?.uiState?.value?.occurrence)
        assertEquals(1, fixture.network.calls.size)
        val pending = model.value!!.uiState.value.seriesPending.single()
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
        installModel()
        val drafts = mutableStateOf(RecurringPaymentDraftStore(SavedStateHandle()))
        val hostMounted = mutableStateOf(true)
        compose.setContent {
            val current = model.value ?: return@setContent
            if (!hostMounted.value) return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                key(drafts.value) {
                    RecurringOccurrenceHost(
                        current,
                        requireNotNull(graph).expenseRepository.manualCreation,
                        RecurringExpenseNavigation({}, { paymentTask.value = it }),
                        RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts.value),
                    )
                }
            }
        }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09" &&
                model.value?.uiState?.value?.ledgerHomeCurrencyCode != null
        }
        compose.waitForIdle()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.period == "2026-09" }
        val originalRef = requireNotNull(paymentTask.value?.clientRef)
        val binding = requireNotNull(paymentTask.value?.binding)
        runBlocking {
            requireNotNull(graph).expenseRepository.manualCreation.create(
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
                RecurringPaymentOrigin("recurring-1", "2026-09"),
            ).getOrThrow()
        }
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        paymentTask.value = null
        val rebuilt = RecurringPaymentDraftStore(SavedStateHandle())
        compose.runOnIdle {
            drafts.value = rebuilt
            hostMounted.value = false
        }
        compose.waitForIdle()
        compose.runOnIdle { hostMounted.value = true }
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        compose.waitForIdle()
        compose.waitUntil(10_000) {
            runCatching { compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick() }
            paymentTask.value?.clientRef == originalRef
        }
        assertEquals(originalRef, paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
        assertTrue(rebuilt.remembered(binding, "recurring-1", "2026-09")?.clientRef == originalRef)
    }

    @Test
    fun leftoverN1SessionRestoresUnwrappedOutboxClientRefWithoutAnotherCreate() {
        fixture.confirmedStream.value = emptyList()
        installModel()
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        val binding = requireNotNull(graph).expenseRepository.captureDeferredLedgerBinding()
            ?: error("binding")
        runBlocking {
            requireNotNull(graph).expenseRepository.manualCreation.create(
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
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"recurring-1","period":"2026-09","clientRef":"legacy-ref","merchant":"房租","obligationCurrencyCode":"CNY","plannedAmountCents":10000,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val drafts = RecurringPaymentDraftStore(SavedStateHandle())
        drafts.adoptLegacyPeriodPaymentSessions(leftover)
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        compose.setContent {
            val current = model.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation({}, { paymentTask.value = it }),
                    RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts),
                )
            }
        }
        compose.waitForIdle()
        compose.onNodeWithTag("occurrence-record-payment").performScrollTo().performClick()
        compose.waitUntil(10_000) { paymentTask.value?.clientRef == "legacy-ref" }
        runBlocking {
            val creation = requireNotNull(graph).expenseRepository.manualCreation
            val payment = ExpenseDraft(
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
            )
            creation.create(payment, binding, "legacy-ref", RecurringPaymentOrigin("recurring-1", "2026-09")).getOrThrow()
            creation.create(payment, binding, "upgraded-ref", RecurringPaymentOrigin("recurring-1", "2026-09")).getOrThrow()
        }
        assertEquals("legacy-ref", paymentTask.value?.clientRef)
        assertEquals(1, fixture.stored().count { it["type"] == "create_expense" })
    }
}
