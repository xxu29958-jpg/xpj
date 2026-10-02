package com.ticketbox.data.repository

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.ui.screens.plan.SpendingGoalDetailScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalEditField
import java.net.ConnectException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Existing Retrofit/Room/query owner and real detail UI; the history producer is raw wire JSON. */
class SpendingGoalHistoryRoomConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val current = mutableStateOf<SpendingGoalDetailViewModel?>(null)
    private val models = mutableListOf<SpendingGoalDetailViewModel>()
    private val requests = CopyOnWriteArrayList<HttpUrl>()
    @Volatile private var legacy = true
    @Volatile private var archived = false
    @Volatile private var offline = false
    @Volatile private var denied = false
    @Volatile private var failHistoryOnce = false
    private val wire = buildApiService("https://goal-history.example.test/", OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request()
        requests += request.url
        if (offline) throw ConnectException("Synthetic offline history transport")
        val history = request.url.encodedPath.endsWith("/history")
        val status = when {
            denied -> 403
            history && failHistoryOnce -> 503.also { failHistoryOnce = false }
            else -> 200
        }
        val body = when {
            status != 200 -> """{"error":"history_unavailable","message":"无法读取计划记录"}"""
            history -> historyJson(request.url.queryParameter("before_version"))
            request.url.encodedPath == "/api/goals/history-goal" -> goalJson()
            else -> error("Unexpected goal history request: ${request.url.encodedPath}")
        }
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(status).message("Synthetic history transport")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }.build())
    private val fixture = ExpenseCorrectionConnectedFixture(context) { wire }

    @After fun close() { models.forEach { it.viewModelScope.cancel() }; fixture.close() }

    @Test fun archivedGoalHistorySurvivesRoomReopenButOfflineCannotInventAnUnreadOlderPage() {
        archived = true
        mount()
        openHistory()
        waitForText("修改后的计划")
        compose.onNodeWithText("修改后的计划").assertExists()
        assertEquals(1, historyRequests().size)
        current.value?.viewModelScope?.cancel()
        offline = true
        installModel()
        compose.waitUntil(10_000) { current.value?.state?.value?.fromCache == true }
        openHistory()
        waitForText("修改后的计划")
        compose.onNodeWithText("修改后的计划").assertExists()
        compose.onNodeWithText("已读取的历史", substring = true).assertExists()
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        compose.waitUntil(10_000) { historyRequests().any { it.queryParameter("before_version") == "9" } }
        compose.onNodeWithText("修改后的计划").assertExists()
        compose.onNodeWithText("旧版已有计划").assertDoesNotExist()
        waitForText(context.getString(R.string.common_retry))
        compose.onNodeWithText(context.getString(R.string.common_retry)).assertExists()
        assertTrue(requireNotNull(current.value).state.value.goal?.isArchived == true)
    }

    @Test fun realCreateEditArchiveRestoreDefinitionsUseOriginalCurrencyAndNeverClaimPastProgress() {
        legacy = false
        mount()
        openHistory()
        waitForText("归档时的计划")
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        waitForText("创建时的计划")
        compose.onNodeWithText("修改后的计划").assertExists()
        compose.onNodeWithText("创建时的计划").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("计划定义", substring = true).assertExists()
        compose.onNodeWithText("旧版已有计划").assertDoesNotExist()
        compose.onAllNodes(hasText("JPY") and hasAnyAncestor(isDialog())).assertCountEquals(4)
        compose.onAllNodes(hasText("¥1,200") and hasAnyAncestor(isDialog())).assertCountEquals(4)
        com.ticketbox.ui.saveConsumerArtPreview("goal-history-original-yen", requireNotNull(
            androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertEquals(listOf(null, "3"), historyRequests().map { it.queryParameter("before_version") })
        assertEquals(4L, current.value?.state?.value?.goal?.rowVersion)
    }

    @Test fun legacyDefinitionHistoryStartsAtRealBaselineSevenWithoutInventingEarlierSaves() {
        mount()
        openHistory()
        waitForText("归档时的计划")
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        waitForText("旧版已有计划")
        compose.onNodeWithText("旧版已有计划").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("更早的修改没有记录", substring = true).assertExists()
        compose.onNodeWithText("创建时的计划").assertDoesNotExist()
        assertEquals(listOf(null, "10"), historyRequests().map { it.queryParameter("before_version") })
        assertFalse(historyRequests().any { it.queryParameter("before_version") in (1..6).map(Int::toString) })
    }

    @Test fun historyReadAndTransportRetryKeepDirtyOriginalTextAndPublishedBodyKeyOcc() {
        mount()
        val model = requireNotNull(current.value)
        compose.runOnIdle {
            model.beginEdit()
            model.updateField(SpendingGoalEditField.Name, "尚未确认的原名称")
            model.updateField(SpendingGoalEditField.Amount, "1250")
            model.updateField(SpendingGoalEditField.Category, "原分类")
        }
        val access = requireNotNull(fixture.graph.goalEditRepository.currentAccess())
        runBlocking { fixture.graph.goalEditRepository.save(access.binding, requireNotNull(model.state.value.goal),
            GoalUpdate(11, name = "另一笔原计划提交", targetAmountCents = 1300, homeCurrencyCode = "JPY")).getOrThrow() }
        val original = fixture.stored().single()
        failHistoryOnce = true
        openHistory()
        waitForText(context.getString(R.string.common_retry))
        compose.onNodeWithText(context.getString(R.string.common_retry)).performClick()
        compose.waitUntil(10_000) { historyRequests().size == 2 }
        waitForText("归档时的计划")
        compose.onNodeWithText("归档时的计划").assertExists()
        assertTrue(model.state.value.isEditing)
        assertTrue(model.state.value.formDirty)
        assertEquals("尚未确认的原名称", model.state.value.name)
        assertEquals("1250", model.state.value.targetAmountInput)
        assertEquals("原分类", model.state.value.category)
        assertEquals(11L, model.state.value.goal?.rowVersion)
        assertEquals(original, fixture.stored().single())
        assertTrue(requests.all { it.encodedPath in setOf("/api/goals/history-goal", "/api/goals/history-goal/history") })
    }

    @Test fun historyAccessRefusalClearsReadPagesAndRoomCacheButNeverRemovesOriginalIntent() {
        mount()
        val access = requireNotNull(fixture.graph.goalEditRepository.currentAccess())
        runBlocking { fixture.graph.goalEditRepository.save(access.binding, requireNotNull(current.value?.state?.value?.goal),
            GoalUpdate(11, name = "权限收回前的原提交", homeCurrencyCode = "JPY")).getOrThrow() }
        val original = fixture.stored().single()
        openHistory()
        waitForText("归档时的计划")
        compose.onNodeWithText("归档时的计划").assertExists()
        denied = true
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        compose.waitUntil(10_000) { current.value?.state?.value?.goal == null }
        compose.onNodeWithText("归档时的计划").assertDoesNotExist()
        assertEquals(original, fixture.stored().single())
        offline = true
        current.value?.viewModelScope?.cancel()
        installModel()
        compose.waitUntil(10_000) { current.value?.state?.value?.loadError != null }
        assertNull(current.value?.state?.value?.goal)
        assertEquals(original, fixture.stored().single())
    }

    private fun mount() {
        installModel()
        compose.setContent { current.value?.let { model ->
            TicketboxTheme(skin = AppSkin.Paper) { SpendingGoalDetailScreen(model, {}) }
        } }
        compose.waitUntil(10_000) { current.value?.state?.value?.goal != null }
    }

    private fun installModel() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            current.value = SpendingGoalDetailViewModel(graph.reportsRepository, graph.goalEditRepository)
                .also { models += it; it.load("history-goal") }
        }
    }

    private fun openHistory() {
        compose.onNodeWithText("定义历史").performScrollTo().performClick()
        compose.waitUntil(10_000) { historyRequests().isNotEmpty() }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun historyRequests() = requests.filter { it.encodedPath == "/api/goals/history-goal/history" }

    private fun goalJson(): String = """{
        "public_id":"history-goal","ledger_id":"correction-ledger","name":"${if (archived) "归档时的计划" else "恢复后的计划"}",
        "goal_type":"spending_limit","period":"monthly","month":"2026-09","category":null,"target_amount_cents":2400,
        "home_currency_code":"JPY","spent_amount_cents":999999,"remaining_amount_cents":null,"progress_percent":null,
        "progress_state":"unavailable","status":"${if (archived) "archived" else "active"}",
        "created_at":"2026-09-01T00:00:00Z","updated_at":"2026-09-20T00:00:00Z",
        "row_version":${if (!legacy) 4 else if (archived) 10 else 11},"archived_at":null
    }"""

    private fun historyJson(before: String?): String {
        val versions = if (!legacy) { if (before == null) listOf(4, 3) else listOf(2, 1) }
            else if (before == null) { if (archived) listOf(10, 9) else listOf(11, 10) }
            else { if (before == "9") listOf(8, 7) else listOf(9, 8, 7) }
        val cursor = if (before != null) "null" else if (!legacy) "3" else if (archived) "9" else "10"
        return """{"ledger_id":"correction-ledger","public_id":"history-goal",
            "items":[${versions.joinToString(",", transform = ::revisionJson)}],"next_before_version":$cursor}"""
    }

    private fun revisionJson(version: Int): String {
        val (kind, name) = when (version) {
            4, 11 -> "restore" to "恢复后的计划"
            3, 10 -> "archive" to "归档时的计划"
            2, 9 -> "edit" to "修改后的计划"
            8 -> "edit" to "更早的修改"
            1 -> "create" to "创建时的计划"
            else -> "baseline" to "旧版已有计划"
        }
        return """{"row_version":$version,"change_kind":"$kind","recorded_at":"2026-09-${version.toString().padStart(2, '0')}T12:00:00Z",
            "snapshot":{"name":"$name","goal_type":"spending_limit","period":"monthly","month":"2026-09",
                "category":null,"target_amount_cents":1200,"home_currency_code":"JPY","status":"${if (version in setOf(3, 10)) "archived" else "active"}"}}"""
    }
}
