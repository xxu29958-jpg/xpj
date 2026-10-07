package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.click
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryPreferenceListResponseDto
import com.ticketbox.data.remote.dto.CategoryPreferenceDto
import com.ticketbox.data.remote.dto.ReferenceCreateRequestDto
import com.ticketbox.data.remote.dto.ReferenceCreatedDto
import com.ticketbox.data.remote.dto.TagListItemDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import org.junit.Assert.assertEquals
import org.junit.After
import org.junit.Rule
import org.junit.Test
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/** Shipped library routes and repositories, with controlled remote replies. */
class ReferenceCreationNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val accepted = ConcurrentHashMap<String, ReferenceCreatedDto>()
    private val requests = CopyOnWriteArrayList<Triple<String, String, String>>()
    private var vocabularyChanges = 0
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun categoryPreferences() = CategoryPreferenceListResponseDto(accepted.values
                .filter { it.kind == "category" }.map { CategoryPreferenceDto(it.publicId, it.name, "custom", 0,
                    it.rowVersion, "2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", null) })
            override suspend fun listManagedTags() = TagManagementListDto(accepted.values.filter { it.kind == "tag" }
                .map { TagListItemDto(it.publicId, it.name, 0, it.rowVersion) })
            override suspend fun createTag(key: String, request: ReferenceCreateRequestDto) = accept("tag", key, request)
            override suspend fun createCategoryPreference(key: String, request: ReferenceCreateRequestDto) = accept("category", key, request)
        }
    }
    private lateinit var navigation: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun unusedCategoryCreationSurvivesLibraryExitAndReplaysItsOriginalCommand() = createAndRecover("分类", TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE)
    @Test fun unusedTagCreationSurvivesLibraryExitAndReplaysItsOriginalCommand() = createAndRecover("标签", TRANSACTIONS_LIBRARY_TAGS_ROUTE)

    private fun createAndRecover(label: String, route: String) {
        compose.setContent {
            ReferenceLibraryTestTheme {
                if (mounted.value) {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            navigation = rememberNavController()
                            NavHost(navigation, startDestination = "test/root") {
                                composable("test/root") { }
                                transactionsLibraryGraph(navigation, harness.screenFactory,
                                    TransactionsLibraryWrites({ vocabularyChanges++ }, {}, {}),
                                    creationOwner = { outer.getBackStackEntry(MAIN_ROUTE) })
                            }
                        }
                    }
                }
            }
        }
        openDirectory(route)
        click("添加$label", scroll = true)
        compose.onNode(hasSetTextAction()).performTextInput("  暑期旅行  ")
        click("添加$label")
        waitFor("回执暂时不可达")
        captureReferenceLibraryStep(compose, context, "$label-unconfirmed")
        compose.onNodeWithText("  暑期旅行  ").assertIsNotEnabled()
        click("稍后继续")
        compose.runOnIdle { navigation.popBackStack("test/root", false) }
        openDirectory(route)
        click("继续添加$label", scroll = true)
        compose.onNodeWithText("  暑期旅行  ").assertIsDisplayed()
        click("核实原添加")
        waitFor("已确认添加「暑期旅行」。")
        compose.onNodeWithText("暑期旅行").performScrollTo().assertIsDisplayed()
        assertEquals(2, requests.size)
        assertEquals(requests.first(), requests.last())
        assertEquals(1, accepted.size)
        assertEquals(1, vocabularyChanges)
        captureReferenceLibraryStep(compose, context, "$label-accepted")
    }

    private fun openDirectory(route: String) {
        compose.runOnIdle { navigation.navigate(TRANSACTIONS_LIBRARY_ROUTE); navigation.navigate(route) }
        compose.waitForIdle()
    }

    private fun click(text: String, scroll: Boolean = false) {
        val node = compose.onNode(hasText(text) and hasClickAction())
        if (scroll) node.performScrollTo()
        node.assertIsDisplayed().performTouchInput { click() }
    }

    private fun waitFor(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }

    private fun accept(kind: String, key: String, request: ReferenceCreateRequestDto): ReferenceCreatedDto {
        requests += Triple(kind, key, request.name)
        accepted[key]?.let { return it }
        accepted[key] = ReferenceCreatedDto(kind, UUID.randomUUID().toString(), request.name.trim(), 1)
        throw HttpException(Response.error<ReferenceCreatedDto>(503,
            """{"error":"service_unavailable","message":"回执暂时不可达"}""".toResponseBody("application/json".toMediaType())))
    }
}
