package com.ticketbox.ui.screens

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneMode
import com.ticketbox.ui.design.AppAdaptivePostureConstraint
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.navigation.ObligationsNavigationActions
import com.ticketbox.ui.navigation.ObligationsTaskNavigation
import com.ticketbox.ui.navigation.RelationsAdaptivePaneConsumer
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanDestinationTestTags
import com.ticketbox.ui.screens.plan.PlanScreen
import com.ticketbox.ui.screens.plan.PlanScreenActions
import com.ticketbox.ui.screens.plan.PlanScreenData
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.RecurringUiState
import org.junit.Assert.assertEquals
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

    private companion object {
        val expandedSupportingPolicy = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Expanded,
            paneMode = AppAdaptivePaneMode.ExpandedSupporting,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
    }
}
