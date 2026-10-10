package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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
    private val harness = FactEntryNavigationHarness(context) { delegate -> object : ApiService by delegate {
        override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?) =
            RecurringItemListResponseDto(emptyList())
        override suspend fun recurringCandidates(timezone: String?) = RecurringCandidatesResponseDto(listOf(
            RecurringCandidateItemDto("每月云端订阅", 2400, 3, "2026-09-09T12:00:00Z", "high", "每月观察", "JPY")))
    } }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun adoptionStaysAnOriginalPendingTaskAfterRouteRecreation() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    NavHost(rememberNavController(), startDestination = ProductSecondaryPage.Recurring.route) {
                        composable(ProductSecondaryPage.Recurring.route) { RecurringRoute(harness.screenFactory, {}) }
                    }
                }
            }
        }
        val adopt = context.getString(R.string.recurring_candidate_confirm)
        waitFor(adopt)
        scrollTo(adopt)
        compose.onNodeWithText(adopt).performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        assertEquals("confirm_recurring_candidate", original["type"])
        assertEquals("pending", original["status"])
        assertTrue(requireNotNull(original["payload"]).contains("JPY"))
        val pending = context.getString(R.string.recurring_pending_kind_state,
            context.getString(R.string.recurring_pending_kind_candidate), context.getString(R.string.recurring_pending_state_waiting))
        scrollTo(pending)
        compose.onNodeWithText(pending).assertIsDisplayed()
        saveConsumerArtPreview("recurring-candidate-pending", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))

        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.reopen()
        compose.runOnIdle { mounted.value = true }
        waitFor(context.getString(R.string.recurring_pending_title))
        scrollTo(pending)
        compose.onNodeWithText(pending).assertIsDisplayed()
        compose.onAllNodesWithText("JPY ¥2,400")[0].assertIsDisplayed()
        assertEquals(original["payload"], harness.fixture.stored().single()["payload"])
        assertEquals(original["idempotency_key"], harness.fixture.stored().single()["idempotency_key"])
        scrollTo(adopt)
        compose.onNodeWithText(adopt).performClick()
        waitFor(context.getString(R.string.recurring_candidate_pending))
        assertEquals(1, harness.fixture.stored().size)
        scrollTo(context.getString(R.string.recurring_candidate_pending))
        saveConsumerArtPreview("recurring-candidate-reopened", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    private fun waitFor(text: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun scrollTo(text: String) {
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(text))
        compose.onNodeWithText(text).performScrollTo()
    }
}
