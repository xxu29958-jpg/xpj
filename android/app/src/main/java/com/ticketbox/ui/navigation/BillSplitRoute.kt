package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.BillSplitScreen
import com.ticketbox.viewmodel.BillSplitViewModel
import com.ticketbox.viewmodel.billSplitViewModelFactory

/**
 * 拆账中心二级页路由（A3 IA）。与 [BudgetRoute] / [RecurringRoute] 同形——构建 VM + 渲染屏，
 * 返回交回 [MainShellState.closeStatsSecondaryPage]。
 *
 * 单独成文件而不并入 [StatsRoutes]：拆账是账本域功能（从账本动作区进入、背景走 Ledger surface），
 * 与统计/规划面不同源；放进 stats 命名的文件会误导读者。仍由 [MainNavGraph] 的二级页 overlay
 * 统一承载（设置树里的 BillSplits 入口保持不变，二者是各自独立的渲染路径）。
 */
@Composable
internal fun BillSplitRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val billSplitViewModel: BillSplitViewModel = viewModel(
        factory = billSplitViewModelFactory(
            screenFactory.repository,
            screenFactory.ledgerRepository,
        ),
    )
    BillSplitScreen(
        viewModel = billSplitViewModel,
        onBack = onBack,
    )
}
