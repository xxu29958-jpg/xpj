package com.ticketbox.ui.navigation

import androidx.annotation.StringRes
import androidx.annotation.DrawableRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.navigation.NavHostController
import com.ticketbox.R
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.components.AppPrimaryNavItem
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

internal const val MAIN_ROUTE = "main"
internal const val EXPENSE_ID_ARG = "expenseId"
internal const val EXPENSE_ROUTE = "expense/{$EXPENSE_ID_ARG}?$NOTIFICATION_QUERY"
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
    @param:DrawableRes val iconRes: Int,
) {
    Inbox("inbox", "product/inbox", R.string.nav_domain_inbox, R.drawable.ic_lucide_inbox),
    Transactions(
        "transactions",
        "product/transactions",
        R.string.nav_domain_transactions,
        R.drawable.ic_lucide_receipt_text,
    ),
    Obligations("obligations", "product/obligations", R.string.nav_domain_obligations, R.drawable.ic_lucide_users),
    Plans("plans", "product/plans", R.string.nav_domain_plans, R.drawable.ic_lucide_calendar_check),
    Insights("insights", "product/insights", R.string.nav_domain_insights, R.drawable.ic_lucide_chart_no_axes_combined),
}

internal enum class ProductSecondaryPage(val route: String) {
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
    // 往来域：全账本往来（个人透镜之上的账本完整视图，W2-C）。
    AllDebts("product/obligations/debts"),
    ObligationSync("product/obligations/sync-status"),
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
        val singleTop: Boolean = true,
    ) : MainNavigationRequest
    data class OpenWorkspace(val route: String = WORKSPACE_ROUTE) : MainNavigationRequest
    data object Back : MainNavigationRequest
}

internal class MainShellState(val launchAction: LaunchActionState = LaunchActionState()) {
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

    var financialDataRevision by mutableStateOf(0)

    var expenseEditCompletionRevision by mutableStateOf(0)

    var transactionVocabularyRevision by mutableStateOf(0)

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

    fun openSecondaryPage(page: ProductSecondaryPage, route: String = page.route, singleTop: Boolean = true) {
        navigationRequest = MainNavigationRequest.OpenSecondary(page, route, singleTop)
    }

    fun openBudget(month: String) {
        navigationRequest = MainNavigationRequest.OpenSecondary(
            page = ProductSecondaryPage.Budget, route = budgetRoute(month),
        )
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

    fun openAccount(route: String = WORKSPACE_ROUTE) {
        navigationRequest = MainNavigationRequest.OpenWorkspace(route)
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
            currentRoute in setOf(EXPENSE_ROUTE, MANUAL_EXPENSE_SUBMISSION_ROUTE, CORRECTION_RATE_ROUTE) -> SurfaceRole.Edit
            activeDestination == MainProductDestination.Workspace -> SurfaceRole.Settings
            activeDestination is MainProductDestination.Secondary ->
                (activeDestination as MainProductDestination.Secondary).page.surfaceRole
            activeDestination is MainProductDestination.Domain ->
                (activeDestination as MainProductDestination.Domain).domain.surfaceRole
            else -> selectedDomain.surfaceRole
        }
    }
}

internal fun MainShellState.markFinancialDataChanged() {
    financialDataRevision += 1
}

internal fun MainShellState.markExpenseEditCompleted() {
    expenseEditCompletionRevision += 1
    markFinancialDataChanged()
}

internal fun MainShellState.markTransactionVocabularyChanged() {
    transactionVocabularyRevision += 1
    markFinancialDataChanged()
}

/**
 * Recycle-bin restores can revive rows from BOTH the transactions vocabulary
 * domain (category preferences) and the plan domain (budget / income plans /
 * recurring / goals). Refresh the vocabulary and the shared financial reads.
 */
internal fun MainShellState.markRecycleBinRestoreCompleted() {
    transactionVocabularyRevision += 1
    markFinancialDataChanged()
}

@Composable
internal fun rememberMainShellState(): MainShellState {
    val launchAction = rememberSaveable(saver = LaunchActionState.Saver) { LaunchActionState() }
    return remember(launchAction) { MainShellState(launchAction) }
}

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
        ProductSecondaryPage.BillSplits,
        ProductSecondaryPage.GlobalSearch,
        ProductSecondaryPage.TransactionsLibrary,
        ProductSecondaryPage.DebtGoals,
        ProductSecondaryPage.AllDebts,
        ProductSecondaryPage.RepaymentDrafts,
        -> SurfaceRole.Ledger

        ProductSecondaryPage.ObligationSync -> SurfaceRole.Settings

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
        ?: if (route == WORKSPACE_ROUTE || route?.startsWith("$WORKSPACE_ROUTE?") == true) MainProductDestination.Workspace else null

@Composable
internal fun PrimaryDomain.toPrimaryNavItem(): AppPrimaryNavItem = AppPrimaryNavItem(
    key = key,
    label = stringResource(labelRes),
    icon = ImageVector.vectorResource(iconRes),
)

internal fun NavHostController.openExpense(expenseId: Long) {
    navigate(expenseRoute(expenseId)) {
        launchSingleTop = true
    }
}
