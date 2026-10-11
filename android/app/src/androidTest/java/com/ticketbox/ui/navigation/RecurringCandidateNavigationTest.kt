package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.performScrollToNode
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringCandidateItemDto
import com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.IOException
import java.util.concurrent.atomic.AtomicInteger
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The actual route captures an adoption, then reconstructs its pending consumer over disk Room. */
class RecurringCandidateNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private var candidatesAvailable = false
    private val candidateReads = AtomicInteger()
    private val harness = FactEntryNavigationHarness(context) { delegate -> object : ApiService by delegate {
        override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?) =
            RecurringItemListResponseDto(emptyList())
        override suspend fun recurringCandidates(timezone: String?): RecurringCandidatesResponseDto {
            candidateReads.incrementAndGet()
            if (!candidatesAvailable) throw IOException("Synthetic unavailable observation query")
            return RecurringCandidatesResponseDto(listOf(
                RecurringCandidateItemDto("每月云端订阅", 2400, 3, "2026-09-09T12:00:00Z", "high", "每月观察", "JPY")) +
                (2..9).map { RecurringCandidateItemDto("观察建议 $it", 1200, it, "2026-09-09T12:00:00Z", "medium", "观察 $it", "CNY") })
        }
    } }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun adoptionStaysAnOriginalPendingTaskAfterRouteRecreation() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                    AppSkin.Midnight else AppSkin.Paper) {
                    NavHost(rememberNavController(), startDestination = ProductSecondaryPage.Recurring.route) {
                        composable(ProductSecondaryPage.Recurring.route) { RecurringRoute(harness.screenFactory, {}) }
                    }
                }
            }
        }
        val adopt = context.getString(R.string.recurring_candidate_confirm)
        waitFor(context.getString(R.string.recurring_section_formal))
        compose.onNodeWithText(adopt).assertDoesNotExist()
        capture("recurring-formal")
        selectSection(R.string.recurring_section_suggestions)
        val retry = context.getString(R.string.common_retry)
        waitFor(retry)
        scrollTo(retry)
        capture("recurring-suggestions-unavailable")
        compose.runOnIdle { candidatesAvailable = true }
        compose.onNodeWithText(retry).performClick()
        waitFor(adopt)
        scrollTo("观察建议 9")
        compose.onNodeWithText("观察建议 9").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.recurring_candidate_meta_summary, 9,
            context.getString(R.string.recurring_candidate_review))).assertExists()
        adoptFirst("recurring-suggestions")
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        assertEquals("confirm_recurring_candidate", original["type"])
        assertEquals("pending", original["status"])
        assertTrue(requireNotNull(original["payload"]).contains("JPY"))
        val pending = context.getString(R.string.recurring_pending_kind_state,
            context.getString(R.string.recurring_pending_kind_candidate), context.getString(R.string.recurring_pending_state_waiting))
        scrollTo(pending)
        compose.onNodeWithText(pending).assertIsDisplayed()
        capture("recurring-candidate-pending")
        selectSection(R.string.recurring_section_formal)
        val paused = context.getString(R.string.recurring_tab_label_count, context.getString(R.string.recurring_tab_paused), 0)
        scrollTo(paused)
        compose.onNodeWithText(paused).performClick()
        selectSection(R.string.recurring_section_suggestions)
        selectSection(R.string.recurring_section_formal)
        scrollTo(paused)
        compose.onNodeWithText(paused).assertIsSelected()
        assertEquals(1, harness.fixture.stored().size)

        val previousReads = candidateReads.get()
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.reopen()
        compose.runOnIdle { mounted.value = true }
        compose.waitUntil(10_000) { candidateReads.get() > previousReads }
        compose.waitForIdle()
        scrollTo(pending)
        compose.onNodeWithText(pending).assertIsDisplayed()
        compose.onAllNodesWithText("JPY ¥2,400")[0].assertIsDisplayed()
        assertEquals(original["payload"], harness.fixture.stored().single()["payload"])
        assertEquals(original["idempotency_key"], harness.fixture.stored().single()["idempotency_key"])
        selectSection(R.string.recurring_section_suggestions)
        adoptFirst("recurring-candidate-original")
        waitFor(context.getString(R.string.recurring_candidate_pending))
        assertEquals(1, harness.fixture.stored().size)
        scrollTo(context.getString(R.string.recurring_candidate_pending))
        capture("recurring-candidate-reopened")
    }

    private fun selectSection(label: Int) {
        val text = context.getString(label)
        scrollTo(text)
        compose.onNodeWithText(text).performClick()
    }

    private fun adoptFirst(scene: String) {
        val observation = context.getString(R.string.recurring_candidate_meta_summary, 3,
            context.getString(R.string.recurring_candidate_stable))
        scrollTo(observation)
        compose.onNodeWithText(observation).assertIsDisplayed()
        compose.onNode(hasScrollToIndexAction()).performScrollToIndex(0)
        capture(scene)
        scrollTo(observation)
        compose.onAllNodesWithText(context.getString(R.string.recurring_candidate_confirm))[0].performScrollTo().performClick()
    }

    private fun capture(name: String) {
        saveConsumerArtPreview(name, requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    private fun waitFor(text: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun scrollTo(text: String) {
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(text))
        compose.onNodeWithText(text).performScrollTo()
    }
}
