package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OccurrencePaymentDraft
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.data.repository.RecurringOccurrenceActions
import com.ticketbox.data.repository.confirmedExpenseDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.screens.recurringItem
import java.lang.reflect.Proxy
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringOccurrenceViewModelTest {
    @Test
    fun refreshUpdatesFactsButSubmissionKeepsOriginalPaymentChoiceAndVersions() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        val payment = confirmedExpenseDtoFixture().toDomain().copy(rowVersion = 11L)
        val ledger = OccurrenceChoiceLedger(payment)
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L })
            advanceUntilIdle()
            assertTrue(model.uiState.value.canWrite)
            model.choose(model.uiState.value.payments.single() as ConfirmedStreamItem.ExpenseRow)
            val original = assertNotNull(model.uiState.value.choice)
            assertEquals(3L, original.request.expectedRowVersion)
            assertEquals(7L, original.request.expectedSeriesRowVersion)
            assertEquals(11L, original.request.expectedExpenseRowVersion)

            actions.occurrence = actions.occurrence.copy(rowVersion = 4L, seriesRowVersion = 8L)
            ledger.payment = payment.copy(rowVersion = 12L, merchant = "Updated payment")
            model.refresh()
            advanceUntilIdle()

            assertEquals(actions.occurrence, model.uiState.value.occurrence)
            assertEquals(12L, model.uiState.value.payments.single().root.rowVersion)
            assertEquals(original, model.uiState.value.choice)
            model.submit()
            advanceUntilIdle()

            assertEquals(listOf(actions.access.binding to original), actions.submissions)
            assertEquals(payment.publicId, actions.submissions.single().second.request.expensePublicId)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unpaidPeriodRecordPaymentCapturesOriginWithoutQueuingFulfillment() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        actions.occurrence = actions.occurrence.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        val model = occurrenceModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain()))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(actions.access.binding, origin.binding)
            assertEquals("rec-1", origin.seriesPublicId)
            assertEquals("2026-08", origin.period)
            assertEquals("日元订阅", origin.merchant)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals(1200L, origin.plannedAmountCents)
            assertTrue(origin.clientRef.isNotBlank())
            assertTrue(actions.submissions.isEmpty())
            assertEquals("unfulfilled", model.uiState.value.occurrence?.state)
            assertEquals(1200L, model.uiState.value.occurrence?.reservedAmountCents)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun savedStateRecreatedViewModelRestoresPeriodPaymentOrigin() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val savedState = SavedStateHandle()
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val debts = OccurrenceChoiceDebts("CNY")
        val first = occurrenceModel(actions, ledger, debts, savedState)
        val firstClientRef: String
        try {
            first.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            first.periodPayment.recordPeriodPayment()
            assertNotNull(first.uiState.value.periodPaymentOrigin)
            val recorded = assertNotNull(first.uiState.value.periodPaymentOrigin)
            first.periodPayment.capturePeriodPaymentDraft(recorded.clientRef, "订阅", "八月义务", "JPY", 1300L)
            firstClientRef = recorded.clientRef
        } finally {
            first.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
        debts.fail = true
        val restored = occurrenceModel(actions, ledger, debts, savedState)
        try {
            restored.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            val origin = assertNotNull(restored.uiState.value.periodPaymentOrigin)
            assertEquals(firstClientRef, origin.clientRef)
            assertEquals("rec-1", origin.seriesPublicId)
            assertEquals("2026-08", origin.period)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals("订阅", origin.category)
            assertEquals("八月义务", origin.note)
            assertEquals(1300L, origin.capturedAmountCents)
            assertEquals("CNY", origin.ledgerHomeCurrencyCode)
        } finally {
            restored.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unpaidPeriodWithoutConfirmedStreamUsesDebtListLedgerHome() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val debts = OccurrenceChoiceDebts("CNY")
        val model = occurrenceModel(actions, ledger, debts)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            assertEquals(emptyList<ConfirmedStreamItem>(), model.uiState.value.payments)
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals("CNY", origin.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
            assertEquals("unfulfilled", model.uiState.value.occurrence?.state)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unpaidPeriodWithoutConfirmedStreamDoesNotGuessLedgerHomeWhenCapabilityMissing() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val model = occurrenceModel(actions, ledger, OccurrenceChoiceDebts(ledgerHomeCurrencyCode = null))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertNull(origin.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun conflictingDebtRecordAndCapabilityFailClosedWithoutGuessingLedgerHome() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val debts = OccurrenceChoiceDebts(ledgerHomeCurrencyCode = "JPY", debts = listOf(periodDebt("CNY")))
        val model = occurrenceModel(actions, ledger, debts)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "USD", merchant = "海外订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertNull(origin.ledgerHomeCurrencyCode)
            assertNull(model.uiState.value.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun failedPeriodPaymentCreateKeepsOriginAndReportsSaveError() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(
            confirmedExpenseDtoFixture().toDomain(),
            emitConfirmedStream = false,
            failCreate = true,
        )
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            model.createPeriodPayment(periodPaymentDraft(origin).copy(category = "订阅", note = "八月义务"))
            advanceUntilIdle()
            assertFalse(model.uiState.value.periodPaymentSaving)
            assertEquals(UiText.raw("账本不可写"), model.uiState.value.periodPaymentError)
            val kept = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(origin.clientRef, kept.clientRef)
            assertEquals("订阅", kept.category)
            assertEquals("八月义务", kept.note)
            assertTrue(ledger.createdClientRefs.isEmpty())
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun latePeriodPaymentCreateDoesNotApplyResultToALaterVisibleOrigin() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(
            confirmedExpenseDtoFixture().toDomain(),
            emitConfirmedStream = false,
        )
        ledger.createGate = CompletableDeferred()
        val model = occurrenceModel(actions, ledger)
        val admitted = mutableListOf<String>()
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val originA = assertNotNull(model.uiState.value.periodPaymentOrigin)
            model.createPeriodPayment(periodPaymentDraft(originA), onAdmitted = { admitted += it })
            advanceUntilIdle()
            assertTrue(model.uiState.value.periodPaymentSaving)
            assertEquals(originA.clientRef, model.uiState.value.periodPaymentInFlightClientRef)

            actions.occurrence = actions.occurrence.copy(
                period = "2026-09",
                homeCurrencyCode = "JPY",
                plannedAmountCents = 1400,
                reservedAmountCents = 1400,
            )
            model.changePeriod("2026-09")
            advanceUntilIdle()
            assertNull(model.uiState.value.periodPaymentOrigin)
            assertFalse(model.uiState.value.periodPaymentSaving)
            model.periodPayment.recordPeriodPayment()
            val originB = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertTrue(originB.clientRef != originA.clientRef)

            ledger.createGate!!.complete(Result.success(ledger.payment))
            advanceUntilIdle()

            val visible = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(originB.clientRef, visible.clientRef)
            assertFalse(visible.admitted)
            assertNull(model.uiState.value.periodPaymentError)
            assertFalse(model.uiState.value.periodPaymentSaving)
            assertEquals(listOf(originA.clientRef), ledger.createdClientRefs)
            assertTrue(admitted.isEmpty())
            assertTrue(actions.submissions.isEmpty())
            assertNull(model.uiState.value.preferredPaymentClientRef)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun periodPaymentCreateOpensSubmissionWhenOriginStillVisible() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(
            confirmedExpenseDtoFixture().toDomain(),
            emitConfirmedStream = false,
        )
        val model = occurrenceModel(actions, ledger)
        val admitted = mutableListOf<String>()
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            model.createPeriodPayment(periodPaymentDraft(origin), onAdmitted = { admitted += it })
            advanceUntilIdle()
            assertEquals(listOf(origin.clientRef), admitted)
            assertEquals(listOf(origin.binding), ledger.createdBindings)
            assertEquals(listOf(origin.clientRef), ledger.createdClientRefs)
            assertNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(origin.clientRef, model.uiState.value.preferredPaymentClientRef)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun offlineAfterLoadAdmitsPaymentFromCapturedOriginWithoutRereadingSeriesOrDebts() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain().copy(homeCurrencyCode = "JPY"))
        val debts = OccurrenceChoiceDebts("CNY")
        val model = occurrenceModel(actions, ledger, debts)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            val fetchesAfterLoad = actions.fetchCount
            val syncsAfterLoad = ledger.syncCount
            val debtReadsAfterLoad = debts.listCount
            actions.failReads = true
            ledger.failSync = true
            debts.fail = true
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(fetchesAfterLoad, actions.fetchCount)
            assertEquals(syncsAfterLoad, ledger.syncCount)
            assertEquals(debtReadsAfterLoad, debts.listCount)
            assertEquals(actions.access.binding, origin.binding)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals("2026-08", origin.period)
            assertTrue(origin.clientRef.isNotBlank())
            assertEquals("CNY", origin.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
            val admitted = ledger.createManualExpense(
                ExpenseDraft(
                    amountCents = null,
                    originalCurrencyCode = com.ticketbox.domain.model.CurrencyCode.JPY,
                    originalAmountMinor = 1200,
                    merchant = origin.merchant,
                    category = "订阅",
                    note = "八月义务",
                    expenseTime = "2026-09-03T10:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                    ledgerHomeCurrency = com.ticketbox.domain.model.CurrencyCode.CNY,
                    clientRef = origin.clientRef,
                ),
            )
            assertTrue(admitted.isSuccess)
            assertEquals(listOf(origin.clientRef), ledger.createdClientRefs)
            assertEquals(fetchesAfterLoad, actions.fetchCount)
            assertEquals(syncsAfterLoad, ledger.syncCount)
            assertEquals(debtReadsAfterLoad, debts.listCount)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unknownObligationCurrencyDoesNotGuessLedgerHomeForTheBaselineAmount() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        actions.occurrence = actions.occurrence.copy(homeCurrencyCode = null)
        val model = occurrenceModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain()))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = null, merchant = "旧订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertNull(origin.obligationCurrencyCode)
            assertEquals(1200L, origin.plannedAmountCents)
            assertNull(com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(origin.obligationCurrencyCode))
            model.periodPayment.choosePeriodPaymentCurrency("JPY")
            val chosen = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals("JPY", chosen.obligationCurrencyCode)
            assertNull(chosen.plannedAmountCents)
            assertNull(chosen.capturedAmountCents)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun roomAcceptedCreateReentryReusesOriginalClientRef() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain())
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val original = assertNotNull(model.uiState.value.periodPaymentOrigin).clientRef
            ledger.createManualExpense(
                ExpenseDraft(
                    amountCents = 1200,
                    merchant = "日元订阅",
                    category = "订阅",
                    note = "八月义务",
                    expenseTime = "2026-09-03T10:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                    clientRef = original,
                ),
            ).getOrThrow()
            model.periodPayment.dismissPeriodPayment()
            model.periodPayment.recordPeriodPayment()
            val reentered = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(original, reentered.clientRef)
            assertEquals(listOf(original), ledger.createdClientRefs)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun confirmCompletionRestoresOriginalPeriodWithoutFulfillingUntilExplicitLink() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val payment = confirmedExpenseDtoFixture().toDomain().copy(
            publicId = "september-pay",
            homeCurrencyCode = "CNY",
            originalCurrencyCode = com.ticketbox.domain.model.CurrencyCode.USD,
        )
        val ledger = OccurrenceChoiceLedger(payment)
        val item = recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "USD", merchant = "海外订阅")
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(item)
            advanceUntilIdle()
            model.changePeriod("2026-08")
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            ledger.createManualExpense(
                ExpenseDraft(
                    amountCents = null,
                    originalCurrencyCode = com.ticketbox.domain.model.CurrencyCode.USD,
                    originalAmountMinor = 2000,
                    merchant = origin.merchant,
                    category = "订阅",
                    note = "八月义务",
                    expenseTime = "2026-09-03T10:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                    ledgerHomeCurrency = com.ticketbox.domain.model.CurrencyCode.CNY,
                    clientRef = origin.clientRef,
                ),
            ).getOrThrow()
            model.periodPayment.acceptPeriodPaymentAdmission(origin.clientRef)
            model.periodPayment.dismissPeriodPayment()
            assertTrue(actions.submissions.isEmpty())
            model.periodPayment.restoreAdmittedPeriodOccurrence(listOf(item))
            advanceUntilIdle()
            assertEquals("2026-08", model.uiState.value.occurrence?.period)
            assertEquals("unfulfilled", model.uiState.value.occurrence?.state)
            assertEquals(1200L, model.uiState.value.occurrence?.reservedAmountCents)
            assertNull(model.uiState.value.periodPaymentOrigin)
            assertTrue(actions.submissions.isEmpty())
            model.choose(model.uiState.value.payments.single() as ConfirmedStreamItem.ExpenseRow)
            model.submit()
            advanceUntilIdle()
            assertEquals(1, actions.submissions.size)
            assertEquals("link", actions.submissions.single().second.request.action)
            assertEquals("september-pay", actions.submissions.single().second.request.expensePublicId)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun admittedPeriodPaymentReentryPinsPreferredAndDoesNotReopenCreate() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val payment = confirmedExpenseDtoFixture().toDomain().copy(id = 71, clientRef = null)
        val ledger = OccurrenceChoiceLedger(payment)
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            model.createPeriodPayment(periodPaymentDraft(origin).copy(expenseTime = "2026-08-03T10:00:00Z"))
            advanceUntilIdle()
            assertNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(origin.clientRef, model.uiState.value.preferredPaymentClientRef)
            model.periodPayment.recordPeriodPayment()
            assertNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(origin.clientRef, model.uiState.value.preferredPaymentClientRef)
            assertEquals(listOf(origin.clientRef), ledger.createdClientRefs)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun completedLinkRetiresSessionAndRestoreUsesTheReturnedClientRef() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val payment = confirmedExpenseDtoFixture().toDomain().copy(id = 71)
        val ledger = OccurrenceChoiceLedger(payment)
        val item = recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅")
        val savedState = SavedStateHandle()
        val model = occurrenceModel(actions, ledger, savedState = savedState)
        val augustRef: String
        try {
            model.open(item)
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            model.createPeriodPayment(periodPaymentDraft(assertNotNull(model.uiState.value.periodPaymentOrigin)))
            advanceUntilIdle()
            augustRef = ledger.createdClientRefs.single()
            model.changePeriod("2026-09")
            advanceUntilIdle()
            model.periodPayment.recordPeriodPayment()
            model.createPeriodPayment(periodPaymentDraft(assertNotNull(model.uiState.value.periodPaymentOrigin)))
            advanceUntilIdle()
            assertEquals(2, ledger.createdClientRefs.size)
            model.periodPayment.rememberReturnClientRef(augustRef)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
        val restored = occurrenceModel(actions, ledger, savedState = savedState)
        try {
            restored.restoreAdmittedPeriodOccurrence(listOf(item))
            advanceUntilIdle()
            assertEquals("2026-08", restored.uiState.value.requestedPeriod)
            assertEquals(augustRef, restored.uiState.value.preferredPaymentClientRef)

            restored.choose(restored.uiState.value.payments.single() as ConfirmedStreamItem.ExpenseRow)
            restored.submit()
            advanceUntilIdle()
            restored.dismiss()
            restored.open(item)
            advanceUntilIdle()
            assertEquals("current", restored.uiState.value.requestedPeriod)
            assertNull(restored.uiState.value.preferredPaymentClientRef)
        } finally {
            restored.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun snapshotKeepsClearedMerchantAndRawAmountText() {
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        var state = RecurringOccurrenceUiState(
            access = actions.access,
            item = recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"),
            occurrence = actions.occurrence,
            requestedPeriod = "2026-08",
        )
        val session = RecurringPeriodPaymentSession(
            current = { state },
            mutate = { reducer -> state = reducer(state) },
            load = {},
            savedState = SavedStateHandle(),
        )
        session.recordPeriodPayment()
        val origin = assertNotNull(state.periodPaymentOrigin)
        session.snapshotPeriodPaymentInputs(origin.clientRef, "", "12.00", "2026-08-03T10:00:00Z")
        assertEquals("", state.periodPaymentOrigin?.merchant)
        assertEquals("12.00", state.periodPaymentOrigin?.capturedAmountText)
    }

    @Test
    fun restoreAdmittedPeriodUsesTheRequestedClientRefNotTheLastSession() {
        val actions = OccurrenceChoiceActions()
        val item = recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅")
        val august = actions.occurrence.copy(period = "2026-08")
        val september = actions.occurrence.copy(period = "2026-09")
        var state = RecurringOccurrenceUiState(
            access = actions.access,
            item = item,
            occurrence = august,
            requestedPeriod = "2026-08",
        )
        val loaded = mutableListOf<String>()
        val session = RecurringPeriodPaymentSession(
            current = { state },
            mutate = { reducer -> state = reducer(state) },
            load = { loaded += it },
            savedState = SavedStateHandle(),
        )
        session.recordPeriodPayment()
        val first = assertNotNull(state.periodPaymentOrigin)
        session.acceptPeriodPaymentAdmission(first.clientRef, 71)
        session.dismissPeriodPayment()
        state = state.copy(occurrence = september, requestedPeriod = "2026-09", periodPaymentOrigin = null)
        session.recordPeriodPayment()
        val second = assertNotNull(state.periodPaymentOrigin)
        assertTrue(second.clientRef != first.clientRef)
        session.acceptPeriodPaymentAdmission(second.clientRef, 80)
        session.dismissPeriodPayment()
        session.restoreAdmittedPeriodOccurrence(listOf(item), first.clientRef)
        assertEquals(listOf("2026-08"), loaded)
        assertEquals("2026-08", state.requestedPeriod)
        assertEquals(first.clientRef, state.preferredPaymentClientRef)
        assertEquals(71L, state.preferredPaymentAcceptedExpenseId)
    }
}

private fun occurrenceModel(
    actions: OccurrenceChoiceActions,
    ledger: OccurrenceChoiceLedger,
    debts: OccurrenceChoiceDebts = OccurrenceChoiceDebts(),
    savedState: SavedStateHandle = SavedStateHandle(),
) = RecurringOccurrenceViewModel(actions, ledger, debts, savedStateHandle = savedState)

private fun seedUnpaidAugust(actions: OccurrenceChoiceActions) {
    actions.occurrence = actions.occurrence.copy(
        period = "2026-08",
        homeCurrencyCode = "JPY",
        plannedAmountCents = 1200,
        reservedAmountCents = 1200,
    )
}

private fun periodDebt(homeCurrencyCode: String): Debt = Debt(
    publicId = "debt-$homeCurrencyCode",
    ledgerId = "owner",
    direction = "i_owe",
    counterpartyType = "external",
    counterpartyAccountId = null,
    counterpartyLabel = "对手方",
    principalAmountCents = 100_000,
    remainingAmountCents = 40_000,
    paidAmountCents = 60_000,
    status = "open",
    sourceType = "manual",
    sourceId = null,
    homeCurrencyCode = homeCurrencyCode,
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-13T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1L,
)

private class OccurrenceChoiceDebts(
    var ledgerHomeCurrencyCode: String? = "CNY",
    var fail: Boolean = false,
    var debts: List<Debt> = emptyList(),
) : DebtActions by unsupportedOccurrenceDebtActions() {
    var listCount = 0
    override suspend fun listDebts(lens: DebtListLens): Result<DebtListPage> {
        listCount++
        if (fail) return Result.failure(IllegalStateException("debts are offline"))
        return Result.success(DebtListPage(debts = debts, ledgerHomeCurrencyCode = ledgerHomeCurrencyCode))
    }
}

private fun unsupportedOccurrenceDebtActions(): DebtActions = requireNotNull(
    DebtActions::class.java.cast(
        Proxy.newProxyInstance(
            DebtActions::class.java.classLoader,
            arrayOf(DebtActions::class.java),
        ) { _, method, _ ->
            when (method.name) {
                "toString" -> "UnsupportedOccurrenceDebtActions"
                else -> throw UnsupportedOperationException(method.name)
            }
        },
    ),
)

private class OccurrenceChoiceActions : RecurringOccurrenceActions {
    val access = LedgerAccessContext(
        LogicalSessionBinding("https://occurrence.example", "ledger-1", "owner", "session", "binding"), true,
    )
    var occurrence = RecurringOccurrenceDto(
        seriesPublicId = "rec-1", period = "2026-09", seriesRowVersion = 7L, rowVersion = 3L,
        state = "unfulfilled", plannedAmountCents = 12_000L, reservedAmountCents = 12_000L,
        expensePublicId = null, paidAmountCents = null, nextDueDate = "2026-09-15", homeCurrencyCode = "CNY",
    )
    val submissions = mutableListOf<Pair<LogicalSessionBinding, OccurrencePaymentDraft>>()
    var fetchCount = 0
    var failReads = false

    override fun currentAccess(): LedgerAccessContext = access
    override fun observeAccess(): Flow<LedgerAccessContext?> = flowOf(access)
    override fun describe(row: OutboxRow): PendingOccurrencePayment? = null
    override fun observeQueue(binding: LogicalSessionBinding): Flow<List<PendingOccurrencePayment>> = flowOf(emptyList())
    override suspend fun fetch(binding: LogicalSessionBinding, seriesId: String, period: String): Result<RecurringOccurrenceDto> {
        fetchCount++
        if (failReads) return Result.failure(IllegalStateException("series read is offline"))
        val resolvedPeriod = if (period == "current") occurrence.period else period
        return Result.success(occurrence.copy(period = resolvedPeriod))
    }

    override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> {
        submissions += binding to draft
        return Result.success(1L)
    }

    override suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
        error("Recovery is not part of an unsubmitted payment choice")
}

private fun periodPaymentDraft(origin: RecurringPeriodPaymentOrigin) = ExpenseDraft(
    amountCents = null,
    originalCurrencyCode = CurrencyCode.JPY,
    originalAmountMinor = origin.capturedAmountCents ?: origin.plannedAmountCents,
    merchant = origin.merchant,
    category = origin.category ?: "订阅",
    note = origin.note ?: "八月义务",
    expenseTime = "2026-09-03T10:00:00Z",
    tags = null,
    valueScore = null,
    regretScore = null,
    ledgerHomeCurrency = CurrencyCode.CNY,
)

private class OccurrenceChoiceLedger(
    var payment: Expense,
    private val emitConfirmedStream: Boolean = true,
    var failCreate: Boolean = false,
) : LedgerActions {
    private val rows = MutableStateFlow(
        if (emitConfirmedStream) listOf(payment.asPaymentRow()) else emptyList(),
    )
    val createdClientRefs = mutableListOf<String>()
    val createdBindings = mutableListOf<LogicalSessionBinding>()
    var createGate: CompletableDeferred<Result<Expense>>? = null
    var syncCount = 0
    var failSync = false
    override fun canModifyLedger(): Boolean = true
    override fun lastConfirmedSyncAt(): String? = null
    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(if (emitConfirmedStream) listOf(payment) else emptyList())
    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = rows
    override suspend fun categories(): Result<List<String>> = error("Unexpected category read")
    override suspend fun tags(): Result<List<String>> = error("Unexpected tag read")
    override suspend fun months(): Result<List<String>> = error("Unexpected month read")

    override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> {
        syncCount++
        if (failSync) return Result.failure(IllegalStateException("confirmed stream is offline"))
        rows.value = if (emitConfirmedStream) listOf(payment.asPaymentRow()) else emptyList()
        return Result.success(if (emitConfirmedStream) listOf(payment) else emptyList())
    }

    override suspend fun exportConfirmedCsv(month: String?, category: String?, tag: String?): Result<CsvExport> =
        error("Unexpected export")
    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> {
        val ref = draft.clientRef?.takeIf { it.isNotBlank() } ?: return Result.failure(IllegalStateException("period payment must reuse the captured clientRef"))
        val gate = createGate
        if (gate != null) {
            val gated = gate.await()
            createGate = null
            if (gated.isFailure) return gated
        }
        if (failCreate) return Result.failure(IllegalStateException("账本不可写"))
        createdClientRefs += ref
        return Result.success(payment.copy(clientRef = ref, pendingSync = true))
    }

    override suspend fun createManualExpense(
        draft: ExpenseDraft,
        expectedBinding: LogicalSessionBinding,
    ): Result<Expense> {
        createdBindings += expectedBinding
        return createManualExpense(draft)
    }
    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>, category: String?, tags: String?, reason: String,
    ): Result<BatchApplyResult> = error("Unexpected expense correction")

}

private fun Expense.asPaymentRow() = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-09-01", streamAmountCents = requireNotNull(amountCents), root = this,
    lineageStatus = ExpenseLineageStatus.Confirmed, lineageHomeNetCents = requireNotNull(amountCents),
)
