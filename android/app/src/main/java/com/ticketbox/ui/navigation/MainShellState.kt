package com.ticketbox.ui.navigation

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.EventNote
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.People
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
import com.ticketbox.ui.components.AppPrimaryNavItem
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

internal const val MAIN_ROUTE = "main"
internal const val EXPENSE_ID_ARG = "expenseId"
internal const val EXPENSE_ROUTE = "expense/{$EXPENSE_ID_ARG}"
internal const val REPAYMENT_DRAFT_BASE_ROUTE = "product/obligations/repayment-review"
internal const val REPAYMENT_DRAFT_FOCUS_ARG = "focusedDraftPublicId"
internal const val REPAYMENT_DRAFT_ROUTE =
    "$REPAYMENT_DRAFT_BASE_ROUTE?$REPAYMENT_DRAFT_FOCUS_ARG={$REPAYMENT_DRAFT_FOCUS_ARG}"

internal fun expenseRoute(expenseId: Long): String = "expense/$expenseId"

internal fun repaymentDraftRoute(focusedDraftPublicId: String?): String {
    val focused = focusedDraftPublicId?.trim().orEmpty()
    if (focused.isEmpty()) return REPAYMENT_DRAFT_BASE_ROUTE
    val encoded = URLEncoder.encode(focused, StandardCharsets.UTF_8.name()).replace("+", "%20")
    return "$REPAYMENT_DRAFT_BASE_ROUTE?$REPAYMENT_DRAFT_FOCUS_ARG=$encoded"
}

internal enum class PrimaryDomain(
    val key: String,
    val route: String,
    @param:StringRes val labelRes: Int,
    val icon: ImageVector,
) {
    Inbox("inbox", "product/inbox", R.string.nav_domain_inbox, Icons.Default.Inbox),
    Transactions(
        "transactions",
        "product/transactions",
        R.string.nav_domain_transactions,
        Icons.AutoMirrored.Filled.ReceiptLong,
    ),
    Obligations("obligations", "product/obligations", R.string.nav_domain_obligations, Icons.Default.People),
    Plans("plans", "product/plans", R.string.nav_domain_plans, Icons.AutoMirrored.Filled.EventNote),
    Insights("insights", "product/insights", R.string.nav_domain_insights, Icons.Default.Insights),
}

internal enum class ProductSecondaryPage(val route: String) {
    // 收件域：服务端持久化长任务台账。
    InboxProcessing("product/inbox/processing"),
    SpendingGoal("product/plans/spending-goal"),
    Budget("product/plans/budget"),
    BudgetAdvice("product/plans/budget-advice"),
    Recurring("product/plans/recurring"),
    IncomePlans("product/plans/income"),
    // 往来域：拆账中心。
    BillSplits("product/obligations/splits"),
    // 流水域：全局搜索。
    GlobalSearch("product/transactions/search"),
    // 流水域：分类、商家、标签与规则的资料库。
    TransactionsLibrary(TRANSACTIONS_LIBRARY_ROUTE),
    // 洞察域：当前账本的数据质量体检（218-B1 暂不挂路由，入口重定向到带筛选的 Inbox）。
    InsightsDataQuality("product/insights/data-quality"),
    // 往来域：还债计划。
    DebtGoals("product/obligations/repayment-plans"),
    // 往来域：还款复核。
    RepaymentDrafts(REPAYMENT_DRAFT_BASE_ROUTE),
}

internal const val WORKSPACE_ROUTE = "product/workspace"

internal sealed interface MainProductDestination {
    data class Domain(val domain: PrimaryDomain) : MainProductDestination
    data class Secondary(val page: ProductSecondaryPage) : MainProductDestination
    data object Workspace : MainProductDestination
}

internal sealed interface MainNavigationRequest {
    data class OpenDomain(
        val domain: PrimaryDomain,
        val selectionBehavior: PrimaryDomainSelectionBehavior =
            PrimaryDomainSelectionBehavior.SwitchBackStack,
    ) : MainNavigationRequest
    data class OpenSecondary(
        val page: ProductSecondaryPage,
        val route: String = page.route,
    ) : MainNavigationRequest
    data object OpenWorkspace : MainNavigationRequest
    data object Back : MainNavigationRequest
}

internal class MainShellState {
    var selectedDomain by mutableStateOf(PrimaryDomain.Inbox)
        private set

    var activeDestination by mutableStateOf<MainProductDestination>(
        MainProductDestination.Domain(PrimaryDomain.Inbox),
    )
        private set

    var navigationRequest by mutableStateOf<MainNavigationRequest?>(null)
        private set

    private var handledDomainRequest: PrimaryDomain? = null

    val secondaryPage: ProductSecondaryPage?
        get() = (activeDestination as? MainProductDestination.Secondary)?.page

    val accountOpen: Boolean
        get() = activeDestination == MainProductDestination.Workspace

    var insightsDataRevision by mutableStateOf(0)

    var planDataRevision by mutableStateOf(0)

    var expenseEditCompletionRevision by mutableStateOf(0)

    var transactionVocabularyRevision by mutableStateOf(0)

    // 系统分享 / 启动器 shortcut 的一次性入口动作（W1），单独成类（见 LaunchActionState）：
    // MainShellState 已贴着 detekt 每文件函数上限，把那两个 post/consume 方法外置避免触顶。
    val launchAction = LaunchActionState()

    // §三报表钻取：统计分类行 → 账本带筛选打开的一次性请求（同上外置成类）。
    val ledgerDrill = LedgerDrillState()

    // Data Quality：带具体 review filter 进入 Inbox，一次性消费。
    val pendingFilterRequest = PendingFilterRequestState()

    fun selectPrimaryDomain(key: String) {
        PrimaryDomain.entries.firstOrNull { it.key == key }?.let { domain ->
            val effectiveDomain = handledDomainRequest ?: activeDestination.primaryDomain
            val selectionBehavior =
                if (effectiveDomain == domain) {
                    PrimaryDomainSelectionBehavior.ReturnToRoot
                } else {
                    PrimaryDomainSelectionBehavior.SwitchBackStack
                }
            selectedDomain = domain
            navigationRequest = when {
                activeDestination == MainProductDestination.Domain(domain) &&
                    handledDomainRequest == null -> null
                handledDomainRequest == domain -> null
                else -> MainNavigationRequest.OpenDomain(
                    domain = domain,
                    selectionBehavior = selectionBehavior,
                )
            }
        }
    }

    fun openPrimaryDomainRoot(domain: PrimaryDomain) {
        selectedDomain = domain
        navigationRequest =
            if (
                activeDestination == MainProductDestination.Domain(domain) &&
                handledDomainRequest == null
            ) {
                null
            } else {
                MainNavigationRequest.OpenDomain(
                    domain = domain,
                    selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
                )
            }
    }

    fun openSecondaryPage(page: ProductSecondaryPage) {
        navigationRequest = MainNavigationRequest.OpenSecondary(page)
    }

    fun openRepaymentDrafts(focusedDraftPublicId: String? = null) {
        navigationRequest = MainNavigationRequest.OpenSecondary(
            page = ProductSecondaryPage.RepaymentDrafts,
            route = repaymentDraftRoute(focusedDraftPublicId),
        )
    }

    fun closeSecondaryPage() {
        navigationRequest = MainNavigationRequest.Back
    }

    fun openAccount() {
        navigationRequest = MainNavigationRequest.OpenWorkspace
    }

    fun closeAccount() {
        navigationRequest = MainNavigationRequest.Back
    }

    fun syncDestination(destination: MainProductDestination) {
        activeDestination = destination
        val destinationDomain = destination.primaryDomain
        if (handledDomainRequest == destinationDomain) {
            handledDomainRequest = null
        }
        if (
            destinationDomain != null &&
            handledDomainRequest == null &&
            navigationRequest !is MainNavigationRequest.OpenDomain
        ) {
            selectedDomain = destinationDomain
        }
    }

    fun consumeNavigationRequest(): MainNavigationRequest? {
        val request = navigationRequest
        navigationRequest = null
        if (request is MainNavigationRequest.OpenDomain) {
            handledDomainRequest = request.domain
        }
        return request
    }

    fun surfaceRole(currentRoute: String?): SurfaceRole {
        return when {
            currentRoute == EXPENSE_ROUTE -> SurfaceRole.Edit
            activeDestination == MainProductDestination.Workspace -> SurfaceRole.Settings
            activeDestination is MainProductDestination.Secondary ->
                (activeDestination as MainProductDestination.Secondary).page.surfaceRole
            activeDestination is MainProductDestination.Domain ->
                (activeDestination as MainProductDestination.Domain).domain.surfaceRole
            else -> selectedDomain.surfaceRole
        }
    }
}

internal fun MainShellState.markInsightsDataChanged() {
    insightsDataRevision += 1
}

internal fun MainShellState.markPlanDataChanged() {
    planDataRevision += 1
    markInsightsDataChanged()
}

internal fun MainShellState.markExpenseEditCompleted() {
    expenseEditCompletionRevision += 1
    markInsightsDataChanged()
}

internal fun MainShellState.markTransactionVocabularyChanged() {
    transactionVocabularyRevision += 1
    markInsightsDataChanged()
}

/**
 * Recycle-bin restores can revive rows from BOTH the transactions vocabulary
 * domain (category preferences) and the plan domain (budget / income plans /
 * recurring / goals), so a restore invalidates the two channels together.
 * Insights gets a single bump — the two marks above would double-count it.
 */
internal fun MainShellState.markRecycleBinRestoreCompleted() {
    transactionVocabularyRevision += 1
    markPlanDataChanged()
}

@Composable
internal fun rememberMainShellState(): MainShellState = remember { MainShellState() }

internal val PrimaryDomain.surfaceRole: SurfaceRole
    get() = when (this) {
        PrimaryDomain.Inbox -> SurfaceRole.Pending
        PrimaryDomain.Transactions -> SurfaceRole.Ledger
        PrimaryDomain.Obligations -> SurfaceRole.Ledger
        PrimaryDomain.Plans -> SurfaceRole.Stats
        PrimaryDomain.Insights -> SurfaceRole.Stats
    }

internal val ProductSecondaryPage.surfaceRole: SurfaceRole
    get() = when (this) {
        ProductSecondaryPage.InboxProcessing -> SurfaceRole.Pending

        ProductSecondaryPage.BillSplits,
        ProductSecondaryPage.GlobalSearch,
        ProductSecondaryPage.TransactionsLibrary,
        ProductSecondaryPage.DebtGoals,
        ProductSecondaryPage.RepaymentDrafts,
        -> SurfaceRole.Ledger

        ProductSecondaryPage.SpendingGoal,
        ProductSecondaryPage.Budget,
        ProductSecondaryPage.BudgetAdvice,
        ProductSecondaryPage.Recurring,
        ProductSecondaryPage.IncomePlans,
        ProductSecondaryPage.InsightsDataQuality,
        -> SurfaceRole.Stats
    }

internal fun mainProductDestination(route: String?): MainProductDestination? =
    PrimaryDomain.entries.firstOrNull { it.route == route }
        ?.let { MainProductDestination.Domain(it) }
        ?: ProductSecondaryPage.entries.firstOrNull { page ->
            route == page.route ||
                route?.startsWith("${page.route}/") == true ||
                route?.startsWith("${page.route}?") == true
        }
            ?.let { MainProductDestination.Secondary(it) }
        ?: if (route == WORKSPACE_ROUTE) MainProductDestination.Workspace else null

@Composable
internal fun PrimaryDomain.toPrimaryNavItem(): AppPrimaryNavItem = AppPrimaryNavItem(
    key = key,
    label = stringResource(labelRes),
    icon = icon,
)

internal fun NavHostController.openExpense(expenseId: Long) {
    navigate(expenseRoute(expenseId)) {
        launchSingleTop = true
    }
}
