package com.ticketbox.ui.screens

import androidx.compose.material3.adaptive.currentWindowAdaptiveInfo
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.WindowSize
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.GOAL_TYPE_SPENDING_LIMIT
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneMode
import com.ticketbox.ui.design.AppAdaptivePostureConstraint
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptiveLayoutPolicy
import com.ticketbox.ui.navigation.ObligationsNavigationActions
import com.ticketbox.ui.navigation.ObligationsTaskNavigation
import com.ticketbox.ui.navigation.RelationsAdaptivePaneConsumer
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanDestinationTestTags
import com.ticketbox.ui.screens.plan.PlanScreen
import com.ticketbox.ui.screens.plan.PlanScreenActions
import com.ticketbox.ui.screens.plan.PlanScreenData
import com.ticketbox.ui.screens.plan.PlanStatusTestTags
import com.ticketbox.ui.screens.plan.PlanStatusCard
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanMonthSummary
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.viewmodel.SpendingGoalsUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * 218-B1 适配（替代原 StatsPlanningMenuTest）：Stats 头部的「规划」下拉菜单随五域导航骨架被
 * 删除，规划入口迁往新域——Budget / BudgetAdvice / SpendingGoal / Recurring / IncomePlans 落在
 * Plan 域根
 * [PlanScreen]（[PlanDestinationTestTags] 钉住各入口行）。W2-C：DebtGoals 从 Plan hub「目标」段
 * 与往来(Obligations)域任务行双向可达（共享同一 DebtGoalRoute，不复制 surface）。
 * 本测试钉住新现实下的等价行为：
 * 入口可见（testTag + 文案）且点击分发到对应回调。旧菜单的展开/收起态播报与菜单钮 48dp 触控
 * 断言随菜单本身一并删除（B1 后无任何等价 UI 可断言）。
 */
class PlanningDestinationsNavigationTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun retainedGoalProgressShowsTheRefreshFailure() {
        val goal = Goal(
            publicId = "goal-retained", ledgerId = "owner", name = "本月餐饮", goalType = GOAL_TYPE_SPENDING_LIMIT,
            period = "monthly", month = "2026-10", category = null, targetAmountCents = 900_00, spentAmountCents = 600_00,
            remainingAmountCents = 300_00, progressPercent = 66, progressState = GoalProgressState.OnTrack,
            status = "active", createdAt = "2026-10-01T00:00:00Z", updatedAt = "2026-10-01T00:00:00Z",
            rowVersion = 1L, archivedAt = null, homeCurrencyCode = "CNY",
        )
        val state = mutableStateOf(SpendingGoalsUiState(
            canModify = true, month = "2026-10", goals = listOf(goal), isLoading = false,
        ))
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                PlanStatusCard(RecurringUiState(), state.value, {}, {})
            }
        }
        composeRule.onNodeWithText("本月餐饮").assertIsDisplayed()
        composeRule.runOnIdle { state.value = state.value.copy(loadError = UiText.raw("刷新失败，请重试")) }
        composeRule.onNodeWithText("本月餐饮").assertIsDisplayed()
        composeRule.onNodeWithText("刷新失败，请重试").assertIsDisplayed()
    }

    @Test fun retainedIncomeForecastKeepsItsMonthAndSourceEvenWhenNoCurrentManagementHeadRemains() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                com.ticketbox.ui.screens.plan.PlanFixedArrangementsSection(RecurringUiState(),
                    IncomePlanUiState(loadState = com.ticketbox.viewmodel.IncomePlanLoadState.Loaded,
                        activePlans = emptyList(), forecastMonth = "2026-09", forecastCurrencyCode = "CNY",
                        currentMonthSummary = com.ticketbox.viewmodel.IncomePlanMonthSummary(1, 10_000),
                        fetchedAt = "2026-09-28T10:00:00Z", fromCache = true), {}, {})
            }
        }
        composeRule.onNodeWithText("2026-09 · 1 项有效 · 预计", substring = true).assertIsDisplayed()
        composeRule.onNodeWithText("包含离线保留的读取", substring = true).assertIsDisplayed()
    }

    @Test
    fun planDomainShowsPlanningDestinationsAndDispatchesActions() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val hits = PlanningDestinationHits()

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PlanScreen(
                    data = PlanScreenData(
                        budget = BudgetUiState(),
                        recurring = RecurringUiState(),
                        income = IncomePlanUiState(),
                        goals = SpendingGoalsUiState(canModify = true, month = "2026-10", isLoading = false),
                    ),
                    actions = PlanScreenActions(
                        budgetNavigation = PlanBudgetNavigationActions(
                            onOpenBudget = { hits.budget++ },
                            onOpenAdvice = { hits.budgetAdvice++ },
                        ),
                        onOpenSpendingGoal = { hits.spendingGoal++ },
                        onOpenDebtGoal = { hits.debtGoal++ },
                        onOpenRecurring = { hits.recurring++ },
                        onOpenIncomePlans = { hits.incomePlans++ },
                        onRefresh = {},
                    ),
                )
            }
        }

        assertPlanDestination(
            tag = PlanDestinationTestTags.Budget,
            label = context.getString(R.string.plan_budget_title),
            assertHit = { assertEquals(1, hits.budget) },
        )
        assertPlanDestination(
            tag = PlanDestinationTestTags.BudgetAdvice,
            label = context.getString(R.string.plan_budget_advice_title),
            assertHit = { assertEquals(1, hits.budgetAdvice) },
        )
        assertPlanDestination(
            tag = PlanDestinationTestTags.SpendingGoal,
            label = context.getString(R.string.plan_spending_goal_title),
            assertHit = { assertEquals(1, hits.spendingGoal) },
        )
        assertPlanDestination(
            tag = PlanDestinationTestTags.DebtGoal,
            label = context.getString(R.string.plan_debt_goal_title),
            assertHit = { assertEquals(1, hits.debtGoal) },
        )
        assertPlanDestination(
            tag = PlanDestinationTestTags.Recurring,
            label = context.getString(R.string.plan_recurring_title),
            assertHit = { assertEquals(1, hits.recurring) },
        )
        assertPlanDestination(
            tag = PlanDestinationTestTags.IncomePlans,
            label = context.getString(R.string.plan_income_title),
            assertHit = { assertEquals(1, hits.incomePlans) },
        )
    }

    /** DW1：真实窗口策略判定 supporting pane 时，预算、状态卡与目标留主栏，固定安排与月度安排进辅助区，各只出现一次。 */
    @Test
    fun expandedWindowKeepsBudgetAndGoalsPrimaryAndArrangementsSupporting() {
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.WindowSize(DpSize(1000.dp, 640.dp))) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    CompositionLocalProvider(
                        LocalAppAdaptiveLayoutPolicy provides
                            currentWindowAdaptiveInfo(supportLargeAndXLargeWidth = true).toAppAdaptiveLayoutPolicy(),
                    ) {
                        PlanScreen(data = populatedPlan(), actions = noPlanActions())
                    }
                }
            }
        }
        val primary = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Plans.primaryTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val supporting = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Plans.supportingTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        fun assertIn(tag: String, pane: androidx.compose.ui.geometry.Rect, name: String) {
            val bounds = composeRule.onNodeWithTag(tag).performScrollTo().assertIsDisplayed().fetchSemanticsNode().boundsInRoot
            assertTrue("$tag must sit in the $name pane: $bounds vs $pane", bounds.left >= pane.left && bounds.right <= pane.right)
        }
        listOf(PlanDestinationTestTags.Budget, PlanStatusTestTags.NextPayment, PlanStatusTestTags.Goals,
            PlanDestinationTestTags.SpendingGoal, PlanDestinationTestTags.DebtGoal)
            .forEach { assertIn(it, primary, "primary") }
        listOf(PlanDestinationTestTags.Recurring, PlanDestinationTestTags.IncomePlans, PlanDestinationTestTags.BudgetAdvice)
            .forEach { assertIn(it, supporting, "supporting") }
        saveConsumerArtPreview("plans-wide-window", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }

    @Test
    fun obligationsDomainDispatchesDebtGoalsEntry() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val debtGoalsLabel = context.getString(R.string.relations_debt_goals)
        var debtGoals = 0

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                // 强制 Expanded 双栏：任务导航行（含还债计划入口）渲染在支持面板。
                CompositionLocalProvider(
                    LocalAppAdaptiveLayoutPolicy provides expandedSupportingPolicy,
                ) {
                    RelationsAdaptivePaneConsumer(
                        navigation = {
                            ObligationsTaskNavigation(
                                actions = ObligationsNavigationActions(
                                    onOpenAllDebts = {},
                                    onOpenBillSplits = {},
                                    onOpenRepaymentReview = {},
                                    onOpenDebtGoals = { debtGoals++ },
                                ),
                                ledgerName = null,
                            )
                        },
                        primaryPane = {},
                    )
                }
            }
        }

        composeRule.onNode(hasText(debtGoalsLabel) and hasClickAction())
            .assertIsDisplayed()
            .performClick()
        composeRule.runOnIdle { assertEquals(1, debtGoals) }
    }

    private fun assertPlanDestination(
        tag: String,
        label: String,
        assertHit: () -> Unit,
    ) {
        // testTag 钉住入口行的接线；click 落在 AppListRow 内 clickable 合并出的语义节点上
        // （tag 在外层 Column，OnClick 与文案在内层 Row 的合并节点，故按 label+clickAction 定位点击）。
        composeRule.onNodeWithTag(tag).performScrollTo().assertIsDisplayed()
        composeRule.onNode(hasText(label) and hasClickAction())
            .assertIsDisplayed()
            .performClick()
        composeRule.waitForIdle()
        assertHit()
    }

    private data class PlanningDestinationHits(
        var budget: Int = 0,
        var budgetAdvice: Int = 0,
        var spendingGoal: Int = 0,
        var debtGoal: Int = 0,
        var recurring: Int = 0,
        var incomePlans: Int = 0,
    )

    private fun noPlanActions() = PlanScreenActions(
        budgetNavigation = PlanBudgetNavigationActions(onOpenBudget = {}, onOpenAdvice = {}),
        onOpenSpendingGoal = {},
        onOpenDebtGoal = {},
        onOpenRecurring = {},
        onOpenIncomePlans = {},
        onRefresh = {},
    )

    private fun populatedPlan() = PlanScreenData(
        budget = BudgetUiState(
            month = "2026-10",
            budget = BudgetMonthly(
                ledgerId = "owner", month = "2026-10", configured = true, homeCurrencyCode = "CNY", rowVersion = 1,
                totalAmountCents = 4000_00, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
                flexBudgetCents = 4000_00, spentAmountCents = 2460_00, excludedAmountCents = 0,
                remainingAmountCents = 1540_00, overspentAmountCents = 0, excludedCategories = emptyList(),
                excludedBreakdown = emptyList(), categoryBudgets = emptyList(), updatedAt = null,
            ),
            fetchedAt = "2026-10-03T04:00:00Z",
        ),
        recurring = RecurringUiState(
            items = listOf(recurring("rec-rent", "房租", 3000_00), recurring("rec-net", "宽带", 99_00)),
            itemsFetchedAt = "2026-10-03T04:00:00Z",
            itemsLoadState = RecurringListLoadState.Loaded,
            candidatesLoadState = RecurringListLoadState.Loaded,
        ),
        income = IncomePlanUiState(
            loadState = IncomePlanLoadState.Loaded,
            forecastMonth = "2026-10",
            forecastCurrencyCode = "CNY",
            currentMonthSummary = IncomePlanMonthSummary(1, 7000_00),
            fetchedAt = "2026-10-03T04:00:00Z",
        ),
        goals = SpendingGoalsUiState(canModify = true, month = "2026-10", isLoading = false, fetchedAt = "2026-10-03T04:00:00Z"),
    )

    private fun recurring(id: String, merchant: String, cents: Long) = RecurringItem(
        publicId = id, ledgerId = "owner", merchant = merchant, merchantKey = merchant, frequency = "monthly",
        baselineAmountCents = cents, lastAmountCents = cents, occurrenceCount = 3, lastSeenAt = "2026-09-01T00:00:00Z",
        nextExpectedDate = "2026-11-01", status = "active", confidence = "high", source = "manual", anomalyStatus = "normal",
        currentMonthAmountCents = cents, historicalAverageAmountCents = cents, amountDeltaPercent = 0,
        createdAt = "2026-06-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1L,
        pausedAt = null, archivedAt = null, homeCurrencyCode = "CNY",
    )

    private companion object {
        val expandedSupportingPolicy = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Expanded,
            paneMode = AppAdaptivePaneMode.ExpandedSupporting,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
    }
}
