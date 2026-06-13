package com.ticketbox.ui.navigation

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavHostController
import com.ticketbox.R
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.components.AppBottomNavItem

internal const val MAIN_ROUTE = "main"
internal const val EXPENSE_ID_ARG = "expenseId"
internal const val EXPENSE_ROUTE = "expense/{$EXPENSE_ID_ARG}"

internal fun expenseRoute(expenseId: Long): String = "expense/$expenseId"

internal enum class BottomTab(
    val key: String,
    @param:StringRes val labelRes: Int,
    val icon: ImageVector,
) {
    // v0.10 IA 重排: 账本作主入口, Reports 独立 tab (从 Stats 二级拆出, 内容 V0.11 再拆分)
    Ledger("ledger", R.string.nav_tab_ledger, Icons.AutoMirrored.Filled.ReceiptLong),
    Reports("reports", R.string.nav_tab_reports, Icons.Default.Insights),
    Pending("pending", R.string.nav_tab_pending, Icons.Default.CheckCircle),
    Search("search", R.string.nav_tab_search, Icons.Default.Search),
    Settings("settings", R.string.nav_tab_settings, Icons.Default.Settings),
}

internal enum class StatsSecondaryPage {
    Budget,
    Recurring,
    IncomePlans,
}

internal class MainShellState {
    var selectedTab by mutableStateOf(BottomTab.Ledger)
        private set

    var statsSecondaryPage by mutableStateOf<StatsSecondaryPage?>(null)
        private set

    var dashboardCardsRevision by mutableStateOf(0)
        private set

    var expenseEditCompletionRevision by mutableStateOf(0)
        private set

    // 系统分享 / 启动器 shortcut 的一次性入口动作（W1），单独成类（见 LaunchActionState）：
    // MainShellState 已贴着 detekt 每文件函数上限，把那两个 post/consume 方法外置避免触顶。
    val launchAction = LaunchActionState()

    // §三报表钻取：统计分类行 → 账本带筛选打开的一次性请求（同上外置成类）。
    val ledgerDrill = LedgerDrillState()

    fun selectBottomTab(key: String) {
        BottomTab.entries.firstOrNull { it.key == key }?.let { selectedTab = it }
    }

    fun openBudget() {
        statsSecondaryPage = StatsSecondaryPage.Budget
    }

    fun openRecurring() {
        statsSecondaryPage = StatsSecondaryPage.Recurring
    }

    fun openIncomePlans() {
        statsSecondaryPage = StatsSecondaryPage.IncomePlans
    }

    fun closeStatsSecondaryPage() {
        statsSecondaryPage = null
    }

    fun markDashboardCardsChanged() {
        dashboardCardsRevision += 1
    }

    fun markExpenseEditCompleted() {
        expenseEditCompletionRevision += 1
    }

    fun surfaceRole(currentRoute: String?): SurfaceRole = when {
        currentRoute == EXPENSE_ROUTE -> SurfaceRole.Edit
        statsSecondaryPage != null -> SurfaceRole.Stats
        else -> selectedTab.surfaceRole
    }
}

@Composable
internal fun rememberMainShellState(): MainShellState = remember { MainShellState() }

internal val BottomTab.surfaceRole: SurfaceRole
    get() = when (this) {
        BottomTab.Pending -> SurfaceRole.Pending
        BottomTab.Ledger -> SurfaceRole.Ledger
        BottomTab.Reports -> SurfaceRole.Stats
        BottomTab.Search -> SurfaceRole.Ledger
        BottomTab.Settings -> SurfaceRole.Settings
    }

@Composable
internal fun BottomTab.toBottomNavItem(): AppBottomNavItem = AppBottomNavItem(
    key = key,
    label = stringResource(labelRes),
    icon = icon,
)

internal fun NavHostController.openExpense(expenseId: Long) {
    navigate(expenseRoute(expenseId)) {
        launchSingleTop = true
    }
}
