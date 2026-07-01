package com.ticketbox.ui.navigation

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Today
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
    // IA 重排: 底栏只放高频任务域；全局搜索降级到账本工具里的全屏二级页。
    Today("today", R.string.nav_tab_today, Icons.Default.Today),
    Pending("pending", R.string.nav_tab_pending, Icons.Default.CheckCircle),
    Ledger("ledger", R.string.nav_tab_ledger, Icons.AutoMirrored.Filled.ReceiptLong),
    Insights("insights", R.string.nav_tab_insights, Icons.Default.Insights),
    Settings("settings", R.string.nav_tab_settings, Icons.Default.Settings),
}

internal enum class StatsSecondaryPage {
    Budget,
    Recurring,
    IncomePlans,
    // A3 IA: 拆账中心从账本动作区提级为全屏二级页, 复用本 overlay 机制(与预算/固定支出同形)。
    // 它是账本域页面而非统计面, 故 surfaceRole 单独归 Ledger(见下方 surfaceRole)。
    BillSplits,
    // IA mobile: 搜索从底栏降级为账本工具内的全屏二级页，避免底栏长期占位。
    GlobalSearch,
    // ADR-0049 §6 (slice 7): 还债目标(规划面, 与预算/收入计划同 overlay)。
    DebtGoals,
    // ADR-0049 §2 (slice 8): 债务管理(欠款列表+新建外部欠款), 由账本里的关系账入口打开。
    Debts,
    // ADR-0049 P3b / ⑤c (slice ⑤c-2): 欠我的(应收) 只读发现面, 与「欠款」并列成中性 sibling。
    Receivables,
    // ADR-0049 §杠杆③ (slice 3a): NLS 还款捕获复核箱(列 pending 还款草稿→选债 confirm/dismiss)。
    RepaymentDrafts,
}

internal class MainShellState {
    var selectedTab by mutableStateOf(BottomTab.Today)
        private set

    var statsSecondaryPage by mutableStateOf<StatsSecondaryPage?>(null)
        private set

    var focusedRepaymentDraftPublicId by mutableStateOf<String?>(null)
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

    // 二级页（预算 / 固定支出 / 收入计划 / 拆账 / 还债目标 / 债务 / 还款复核）共用一个参数化入口：原本每页一个
    // 同形 setter，MainShellState 已贴着 detekt 每文件函数上限（见上方 launchAction/ledgerDrill 外置注），再加一
    // 个还款页就会触顶——收成单个 [openStatsSecondary] 是真简化（7→1）而非加 baseline 豁免。
    fun openStatsSecondary(page: StatsSecondaryPage) {
        statsSecondaryPage = page
    }

    fun openRepaymentDrafts(focusedDraftPublicId: String? = null) {
        focusedRepaymentDraftPublicId = focusedDraftPublicId
        openStatsSecondary(StatsSecondaryPage.RepaymentDrafts)
    }

    fun clearFocusedRepaymentDraft() {
        focusedRepaymentDraftPublicId = null
    }

    fun closeStatsSecondaryPage() {
        if (statsSecondaryPage == StatsSecondaryPage.RepaymentDrafts) {
            focusedRepaymentDraftPublicId = null
        }
        statsSecondaryPage = null
    }

    fun markDashboardCardsChanged() {
        dashboardCardsRevision += 1
    }

    fun markExpenseEditCompleted() {
        expenseEditCompletionRevision += 1
    }

    fun surfaceRole(currentRoute: String?): SurfaceRole {
        val secondaryPage = statsSecondaryPage
        return when {
            currentRoute == EXPENSE_ROUTE -> SurfaceRole.Edit
            // 账本工具打开的搜索 / 拆账 / 关系账二级页归账本域；预算、固定支出、收入计划、目标仍归洞察。
            secondaryPage == StatsSecondaryPage.BillSplits -> SurfaceRole.Ledger
            secondaryPage == StatsSecondaryPage.GlobalSearch -> SurfaceRole.Ledger
            secondaryPage == StatsSecondaryPage.Debts -> SurfaceRole.Ledger
            secondaryPage == StatsSecondaryPage.Receivables -> SurfaceRole.Ledger
            secondaryPage == StatsSecondaryPage.RepaymentDrafts -> SurfaceRole.Ledger
            secondaryPage != null -> SurfaceRole.Stats
            else -> selectedTab.surfaceRole
        }
    }
}

@Composable
internal fun rememberMainShellState(): MainShellState = remember { MainShellState() }

internal val BottomTab.surfaceRole: SurfaceRole
    get() = when (this) {
        BottomTab.Today -> SurfaceRole.Today
        BottomTab.Pending -> SurfaceRole.Pending
        BottomTab.Ledger -> SurfaceRole.Ledger
        BottomTab.Insights -> SurfaceRole.Stats
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
