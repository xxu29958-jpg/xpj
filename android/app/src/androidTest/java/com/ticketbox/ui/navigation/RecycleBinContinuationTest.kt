package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.click
import androidx.compose.ui.unit.Density
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.CopyOnWriteArrayList

/** Filtering is presentation only: retry still addresses the original object and reviewed token. */
class RecycleBinContinuationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<RecycleBinRestoreRequestDto>()
    @Volatile private var blocked = true
    @Volatile private var restored = false
    private val alias = RecycleBinItemDto("merchant_alias", "商家别名", "breakfast-alias",
        "早餐店", "恢复为 街角小馆 的别名", "2026-10-07T08:00:00Z", "30 天内可恢复", 4)
    private val budget = RecycleBinItemDto("monthly_budget", "预算", "2026-09",
        "2026-09 月度预算", "CNY ¥4,000.00", "2026-10-07T08:00:00Z", "长期保留", 2)
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun recycleBin() = RecycleBinListResponseDto(
                if (restored) listOf(budget) else listOf(budget, alias), if (restored) 0 else 1)
            override suspend fun restoreRecycleBinItem(request: RecycleBinRestoreRequestDto): RecycleBinRestoreResponseDto {
                requests += request
                if (blocked) throw HttpException(Response.error<RecycleBinRestoreResponseDto>(409,
                    """{"error":"state_conflict","message":"别名已被更新，请核对后重试。"}"""
                        .toResponseBody("application/json".toMediaType())))
                restored = true
                return RecycleBinRestoreResponseDto("商家别名已恢复。")
            }
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun filteringAndConflictKeepTheOriginalRestoreTarget() {
        compose.setContent {
            if (!mounted.value) return@setContent
            val arguments = InstrumentationRegistry.getArguments()
            val large = arguments.getString("visualMode") == "large"
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                LocalDensity provides Density(LocalDensity.current.density, if (large) 2f else 1f)) {
                TicketboxTheme(skin = if (large) AppSkin.Midnight else AppSkin.Default) { Directory() }
            }
        }
        capture("library")
        click("回收站")
        waitFor("早餐店")
        capture("recycle")
        click("资料")
        compose.onNodeWithText("2026-09 月度预算").assertDoesNotExist()
        restore()
        waitFor("别名已被更新，请核对后重试。")
        compose.onNodeWithText("早餐店").performScrollTo().assertIsDisplayed()
        click("计划")
        compose.onNodeWithText("早餐店").assertDoesNotExist()
        compose.onNodeWithText("2026-09 月度预算").performScrollTo().assertIsDisplayed()
        click("资料")
        blocked = false
        restore()
        waitFor("商家别名已恢复。")
        compose.onNodeWithText("资料").assertIsSelected()
        compose.onNodeWithText("早餐店").assertDoesNotExist()
        assertEquals(listOf("breakfast-alias", "breakfast-alias"), requests.map { it.resourceId })
        assertEquals(listOf(4, 4), requests.map { it.expectedRowVersion })
        assertEquals(listOf("merchant_alias", "merchant_alias"), requests.map { it.kind })
        click("计划")
        compose.onNodeWithText("2026-09 月度预算").performScrollTo().assertIsDisplayed()
    }

    @Composable private fun Directory() {
        val navigation = rememberNavController()
        NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
            transactionsLibraryGraph(navigation, harness.screenFactory, TransactionsLibraryWrites({}, {}, {}))
        }
    }
    private fun restore() {
        compose.onNodeWithContentDescription("恢复 早餐店").performScrollTo().assertIsDisplayed()
        capture("alias-action")
        compose.onNodeWithContentDescription("恢复 早餐店").performTouchInput { click() }
        waitFor("恢复项目？")
        compose.onAllNodesWithText("恢复").fetchSemanticsNodes().let { nodes ->
            compose.onAllNodesWithText("恢复")[nodes.lastIndex].performTouchInput { click() }
        }
    }
    private fun click(text: String) = compose.onNodeWithText(text).performScrollTo().performTouchInput { click() }
    private fun waitFor(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }
    private fun capture(name: String) {
        captureReferenceLibraryStep(compose, context, name)
    }
}
