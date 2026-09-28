package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.click
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryPreferenceDto
import com.ticketbox.data.remote.dto.CategoryPreferenceListResponseDto
import com.ticketbox.data.remote.dto.CategoryPreferenceTokenRequestDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
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

/** The shipped directory, HTTP error decoding and real library navigation remain in the path. */
class CategoryReferenceNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val category = CategoryPreferenceDto("bakery-category", "烘焙", "custom", 1, 3,
        "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", null)
    @Volatile private var blocked = true
    @Volatile private var removed = false
    @Volatile private var reads = 0
    private var referenceKind = "rule"
    private var referenceId = "42"
    private var referenceLabel = "规则「bakery」"
    private val budgetReads = CopyOnWriteArrayList<String>()
    private val goalReads = CopyOnWriteArrayList<String>()
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun categoryPreferences(): CategoryPreferenceListResponseDto {
                reads += 1
                return CategoryPreferenceListResponseDto(if (removed) emptyList() else listOf(category))
            }
            override suspend fun deleteCategoryPreference(publicId: String,
                request: CategoryPreferenceTokenRequestDto): CategoryPreferenceDto {
                assertEquals(category.publicId, publicId)
                assertEquals(category.rowVersion, request.expectedRowVersion)
                if (blocked) throw HttpException(Response.error<CategoryPreferenceDto>(409,
                    """{"error":"state_conflict","message":"这个分类仍被规则使用，请先处理相关配置。",
                        "category_references":[{"kind":"$referenceKind","id":"$referenceId","label":"$referenceLabel"}]}"""
                        .toResponseBody("application/json".toMediaType())))
                removed = true
                return category.copy(deletedAt = "2026-09-28T00:00:00Z", rowVersion = 4)
            }
            override suspend fun categoryRules(): List<CategoryRuleDto> = listOf(rule(7, "other"), rule(42, "bakery"))
            override suspend fun monthlyBudget(month: String, timezone: String?) = referenceBudget(month).also {
                budgetReads += month
            }
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?) =
                GoalListResponseDto(listOf(referenceGoal("other-goal"), referenceGoal("bakery-goal")))
            override suspend fun goal(publicId: String, timezone: String?) = referenceGoal(publicId).also {
                goalReads += publicId
            }
        }
    }
    private lateinit var navigation: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun blockedRemovalOpensItsRuleAndReturnsToRefreshedDirectory() {
        showDirectory()
        waitForText("烘焙")
        removeCategory()
        waitForText("这个分类仍被规则使用，请先处理相关配置。")
        compose.onNodeWithText("烘焙").assertIsDisplayed()
        compose.onNodeWithText("规则「bakery」").performScrollTo().performTouchInput { click() }
        waitForText(context.getString(R.string.category_rule_editor_submit_update))
        compose.onNode(hasSetTextAction() and hasText("bakery")).assertIsDisplayed()
        compose.runOnIdle { assertEquals("42", navigation.currentBackStackEntry?.arguments?.getString("rule")) }

        val previousReads = reads
        blocked = false // The referenced configuration is resolved while this directory is away.
        compose.onNodeWithText("返回分类").performScrollTo().performTouchInput { click() }
        compose.waitUntil(5_000) { reads > previousReads }
        waitForText("烘焙")
        removeCategory()
        waitForText(context.getString(R.string.category_directory_deleted, "烘焙"))
        compose.onNodeWithText("烘焙").assertDoesNotExist()
        assertEquals(true, removed)
    }

    @Test fun blockedRemovalOpensTheReferencedBudgetMonthAndReturnsToRefreshedDirectory() {
        referenceKind = "budget"
        referenceId = "2026-02"
        referenceLabel = "预算 2026-02（分类额度与排除分类）"
        showDirectory()
        openReference()
        compose.waitUntil(5_000) { budgetReads.isNotEmpty() }
        compose.runOnIdle {
            assertEquals(referenceId, navigation.currentBackStackEntry?.arguments?.getString("month"))
        }
        assertEquals(listOf(referenceId), budgetReads.distinct())
        compose.onNodeWithText(context.getString(R.string.budget_header_subtitle, referenceId)).assertIsDisplayed()
        val previousReads = reads
        blocked = false
        compose.onNodeWithText("返回分类")
            .performScrollTo().performTouchInput { click() }
        assertDirectoryRefreshed(previousReads)
    }

    @Test fun blockedRemovalOpensTheReferencedSpendingGoalAndReturnsToRefreshedDirectory() {
        referenceKind = "goal"
        referenceId = "bakery-goal"
        referenceLabel = "消费目标「烘焙限额」"
        showDirectory()
        openReference()
        waitForText("烘焙限额")
        compose.runOnIdle {
            assertEquals(referenceId, navigation.currentBackStackEntry?.arguments?.getString("goal"))
        }
        assertEquals(listOf(referenceId), goalReads.distinct())
        compose.onNodeWithText("烘焙限额").assertIsDisplayed()
        val previousReads = reads
        blocked = false
        compose.onNodeWithText("返回分类")
            .performScrollTo().performTouchInput { click() }
        assertDirectoryRefreshed(previousReads)
    }

    private fun showDirectory() {
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    ReferenceNavigation()
                }
            }
        }
        compose.runOnIdle { navigation.navigate(TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE) }
    }

    @Composable private fun ReferenceNavigation() {
        val outer = rememberNavController()
        NavHost(outer, startDestination = MAIN_ROUTE) {
            composable(MAIN_ROUTE) {
                navigation = rememberNavController()
                val dependencies = MainProductRouteDependencies(
                    MainNavigationRuntime(outer, harness.shell, harness.screenFactory), navigation,
                    MainWorkspaceControls(SettingsPreferenceControls(AppSkin.Default, AppThemeMode.System,
                        CurrencyCode.CNY, onThemeModeChange = {}, onCurrencyChange = {}),
                        onBindingCleared = { error("Navigation preserves the identity") }),
                )
                NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                    transactionsLibraryGraph(navigation, harness.screenFactory, {}, {}, {})
                    addPlanRoutes(dependencies)
                }
            }
        }
    }

    private fun openReference() {
        waitForText("烘焙")
        removeCategory()
        waitForText(referenceLabel)
        compose.onNodeWithText("烘焙").assertIsDisplayed()
        assertEquals(false, removed)
        compose.onNodeWithText(referenceLabel).performScrollTo().performTouchInput { click() }
    }

    private fun assertDirectoryRefreshed(previousReads: Int) {
        compose.waitUntil(5_000) { reads > previousReads }
        compose.runOnIdle {
            assertEquals(TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE, navigation.currentDestination?.route)
        }
        waitForText("烘焙")
        removeCategory()
        waitForText(context.getString(R.string.category_directory_deleted, "烘焙"))
        compose.onNodeWithText("烘焙").assertDoesNotExist()
        assertEquals(true, removed)
    }

    private fun removeCategory() {
        compose.onNodeWithContentDescription(context.getString(R.string.category_directory_delete_description, "烘焙"))
            .performScrollTo().performTouchInput { click() }
        compose.onNodeWithText(context.getString(R.string.category_directory_delete_confirm)).performTouchInput { click() }
    }

    private fun rule(id: Long, keyword: String) = CategoryRuleDto(id, keyword, "烘焙", true, 10,
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1, homeCurrencyCode = "CNY")

    private fun waitForText(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }
}
