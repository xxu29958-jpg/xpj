package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalsViewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import java.net.ConnectException
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** The real list route opens a detail that was never requested before Room was reopened. */
class GoalOfflineReadingConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(false)
    @Volatile private var offline = false
    @Volatile private var denied = false
    private val detailCalls = AtomicInteger()
    private val original = GoalDto("offline-goal", "correction-ledger", "九月日元目标", "spending_limit",
        "monthly", "2026-09", null, 1200, null, null, null, "on_track", "active",
        "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 4, null, homeCurrencyCode = "JPY")
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                checkTransport()
                return GoalListResponseDto(listOf(original))
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                detailCalls.incrementAndGet()
                checkTransport()
                assertEquals(original.publicId, publicId)
                return original
            }
        }
    }
    private lateinit var list: SpendingGoalsViewModel

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun listReadSurvivesRoomReopenAndUnvisitedDetailThenRefusalClearsOnlyReadData() {
        val pending = prepare()
        show()
        openCachedDetail()
        val detail = detailModel()
        assertEquals("JPY", detail.state.value.goal?.homeCurrencyCode)
        assertNull(detail.state.value.goal?.progress)
        assertNotNull(detail.state.value.fetchedAt)
        assertTrue(detail.state.value.fromCache)
        compose.onNodeWithText(context.getString(R.string.spending_goal_progress_unavailable)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("goal-read-source").assertIsDisplayed()
        denied = true
        compose.runOnIdle { detail.load() }
        compose.waitUntil(5_000) { !detail.state.value.isLoading && detail.state.value.loadError != null }
        assertNull(detail.state.value.goal)
        assertNull(detail.state.value.fetchedAt)
        compose.onNodeWithTag("goal-read-source").assertDoesNotExist()
        assertEquals(pending, harness.fixture.stored())
        denied = false
        compose.runOnIdle { detail.load() }
        compose.waitUntil(5_000) { !detail.state.value.isLoading }
        assertNull(detail.state.value.goal)
    }

    @Test fun replacingBindingHidesTheOriginalSnapshotAndPreservesTheOriginalOutbox() {
        val pending = prepare()
        show()
        openCachedDetail()
        val detail = detailModel()
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) { detail.state.value.goal == null && !detail.state.value.isLoading }
        assertNull(detail.state.value.fetchedAt)
        assertTrue(list.state.value.goals.isEmpty())
        assertEquals(pending, harness.fixture.stored())
        compose.onNodeWithTag("goal-read-source").assertDoesNotExist()
    }

    private fun prepare(): List<Map<String, String?>> {
        runBlocking {
            harness.fixture.graph.reportsRepository.goals("2026-09").getOrThrow()
            harness.saveFailedCorrection()
        }
        assertEquals(0, detailCalls.get())
        val originalRows = harness.fixture.stored()
        offline = true
        harness.fixture.reopen()
        return originalRows
    }

    private fun show() {
        val graph = harness.fixture.graph
        val factory = MainScreenFactory(harness.screenFactory.repositories.copy(
            reportsRepository = graph.reportsRepository, goalEditRepository = graph.goalEditRepository,
        ), harness.screenFactory.viewModelFactories)
        compose.runOnIdle {
            list = ViewModelProvider(harness.models, viewModelFactory {
                initializer { SpendingGoalsViewModel(graph.reportsRepository, graph.goalEditRepository, "2026-09") }
            })["spending-goals", SpendingGoalsViewModel::class.java]
            mounted.value = true
        }
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                    LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                    if (mounted.value) SpendingGoalsRoute(factory, onBack = {})
                }
            }
        }
    }

    private fun openCachedDetail() {
        compose.waitUntil(5_000) { list.state.value.fromCache && !list.state.value.isLoading }
        compose.onNodeWithText(original.name).performScrollTo().performClick()
        compose.waitForIdle()
        val detail = detailModel()
        compose.waitUntil(5_000) { detail.state.value.goal != null && !detail.state.value.isLoading }
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("goal-read-source")).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun detailModel() = ViewModelProvider(harness.models)["spending-goal-detail", SpendingGoalDetailViewModel::class.java]

    private fun checkTransport() {
        if (denied) throw HttpException(Response.error<Any>(403, "{}".toResponseBody()))
        if (offline) throw ConnectException("Synthetic unavailable transport")
    }
}
