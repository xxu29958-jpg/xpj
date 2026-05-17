package com.ticketbox.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavHostController
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.components.AppBottomNavItem

internal const val MAIN_ROUTE = "main"
internal const val EXPENSE_ID_ARG = "expenseId"
internal const val EXPENSE_ROUTE = "expense/{$EXPENSE_ID_ARG}"

internal fun expenseRoute(expenseId: Long): String = "expense/$expenseId"

internal enum class BottomTab(
    val key: String,
    val label: String,
    val icon: ImageVector,
) {
    Pending("pending", "待确认", Icons.Default.CheckCircle),
    Ledger("ledger", "账本", Icons.AutoMirrored.Filled.ReceiptLong),
    Stats("stats", "统计", Icons.Default.BarChart),
    Settings("settings", "设置", Icons.Default.Settings),
}

internal enum class StatsSecondaryPage {
    Budget,
    Recurring,
}

internal class MainShellState {
    var selectedTab by mutableStateOf(BottomTab.Pending)
        private set

    var statsSecondaryPage by mutableStateOf<StatsSecondaryPage?>(null)
        private set

    var dashboardCardsRevision by mutableStateOf(0)
        private set

    var expenseEditCompletionRevision by mutableStateOf(0)
        private set

    fun selectBottomTab(key: String) {
        BottomTab.entries.firstOrNull { it.key == key }?.let { selectedTab = it }
    }

    fun openBudget() {
        statsSecondaryPage = StatsSecondaryPage.Budget
    }

    fun openRecurring() {
        statsSecondaryPage = StatsSecondaryPage.Recurring
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
        BottomTab.Stats -> SurfaceRole.Stats
        BottomTab.Settings -> SurfaceRole.Settings
    }

internal fun BottomTab.toBottomNavItem(): AppBottomNavItem = AppBottomNavItem(
    key = key,
    label = label,
    icon = icon,
)

internal fun NavHostController.openExpense(expenseId: Long) {
    navigate(expenseRoute(expenseId)) {
        launchSingleTop = true
    }
}
