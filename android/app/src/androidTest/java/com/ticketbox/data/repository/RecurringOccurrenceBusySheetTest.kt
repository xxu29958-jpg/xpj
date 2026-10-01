package com.ticketbox.data.repository

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasScrollAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.CompletableDeferred
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** An actual selection must stay reachable until its original Room admission has finished. */
class RecurringOccurrenceBusySheetTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = RecurringOccurrenceConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val host = RecurringOccurrenceHostDriver(compose, fixture)
    private val entered = CompletableDeferred<Unit>()
    private val release = CompletableDeferred<Unit>()

    @After fun close() = host.close()

    @Test fun swipeDuringAdmissionKeepsTheOriginalPaymentTaskVisibleAndAdmitsItOnce() {
        val graph = fixture.reopen()
        val original = graph.recurringRepository.occurrences
        val delayed = object : RecurringOccurrenceActions by original {
            override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> {
                entered.complete(Unit)
                release.await()
                return original.enqueue(binding, draft)
            }
        }
        host.graph = graph
        compose.runOnIdle {
            host.model.value = RecurringOccurrenceViewModel(delayed, fixture.ledger, fixture.debts)
                .also { it.open(occurrenceConnectedItem()) }
        }
        host.showOccurrenceHost()
        compose.waitUntil(10_000) { host.model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        val choice = requireNotNull(host.model.value?.uiState?.value?.choice)
        compose.onNodeWithTag("occurrence-submit").performClick()
        compose.waitUntil(5_000) { entered.isCompleted }
        assertTrue(host.model.value?.uiState?.value?.saving == true)
        assertTrue(fixture.stored().isEmpty())

        val title = compose.onAllNodesWithText(occurrenceConnectedItem().merchant).onFirst()
        title.performScrollTo().assertIsDisplayed()
        val content = compose.onNode(hasScrollAction() and hasAnyDescendant(hasText(occurrenceConnectedItem().merchant)))
        repeat(3) {
            content.performTouchInput { swipeDown() }
            compose.waitForIdle()
            title.assertIsDisplayed()
        }
        assertEquals(choice, host.model.value?.uiState?.value?.choice)
        release.complete(Unit)
        compose.waitUntil(10_000) { fixture.stored().size == 1 && host.model.value?.uiState?.value?.saving == false }
        val intent = requireNotNull(OutboxAdapterGraph().recurringOccurrenceAdapter.fromJson(
            requireNotNull(fixture.stored().single()["payload"])))
        assertEquals(choice.request, intent.request)
        assertEquals(choice.occurrence.period, intent.period)
        assertTrue(fixture.network.calls.isEmpty())
        title.performScrollTo().assertIsDisplayed()
        repeat(3) {
            if (host.model.value?.uiState?.value?.item != null) {
                content.performTouchInput { swipeDown() }
                compose.waitForIdle()
            }
        }
        assertNull(host.model.value?.uiState?.value?.item)
    }
}
