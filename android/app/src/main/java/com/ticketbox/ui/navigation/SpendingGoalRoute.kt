package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.CreateSpendingGoalScreen
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory

private const val CreateSpendingGoalViewModelKey = "create-spending-goal"

/**
 * 消费目标二级页（product/plans/spending-goal）。
 *
 * 218-B1 骨架保留 main 的单页创建表单（[CreateSpendingGoalScreen]）：#218 的
 * 列表 → 创建 → 详情三段流（SpendingGoalsScreen / SpendingGoalDetailScreen）属后续
 * slice。创建成功后交回 [onBack]（弹回计划域）。
 */
@Composable
internal fun SpendingGoalsRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val viewModel: CreateSpendingGoalViewModel = viewModel(
        key = CreateSpendingGoalViewModelKey,
        factory = createSpendingGoalViewModelFactory(screenFactory.reportsRepository),
    )
    CreateSpendingGoalScreen(
        viewModel = viewModel,
        onBack = onBack,
        onCreated = onBack,
    )
}
