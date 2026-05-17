package com.ticketbox.domain.model

enum class ReportGranularity(val apiValue: String) {
    Day("day"),
    Week("week"),
    Month("month");

    companion object {
        fun fromApiValue(value: String): ReportGranularity =
            entries.firstOrNull { it.apiValue == value } ?: Day
    }
}

enum class ReportRankingMetric(val apiValue: String) {
    Amount("amount"),
    Count("count");

    companion object {
        fun fromApiValue(value: String): ReportRankingMetric =
            entries.firstOrNull { it.apiValue == value } ?: Amount
    }
}

data class ReportsOverviewQuery(
    val month: String? = null,
    val granularity: ReportGranularity = ReportGranularity.Day,
    val topN: Int = 8,
    val merchantCategory: String? = null,
    val rankingMetric: ReportRankingMetric = ReportRankingMetric.Amount,
)

data class ReportTrendPoint(
    val bucket: String,
    val label: String,
    val amountCents: Long,
    val count: Int,
)

data class ReportMerchantRanking(
    val merchant: String,
    val amountCents: Long,
    val count: Int,
)

data class ReportCategoryComparison(
    val category: String,
    val amountCents: Long,
    val count: Int,
    val previousAmountCents: Long,
    val previousCount: Int,
    val deltaAmountCents: Long,
    val deltaCount: Int,
)

data class ReportsOverview(
    val month: String,
    val timezone: String,
    val granularity: ReportGranularity,
    val totalAmountCents: Long,
    val count: Int,
    val previousMonth: String,
    val previousTotalAmountCents: Long,
    val previousCount: Int,
    val merchantCategory: String?,
    val rankingMetric: ReportRankingMetric,
    val trend: List<ReportTrendPoint>,
    val merchantRanking: List<ReportMerchantRanking>,
    val categoryComparison: List<ReportCategoryComparison>,
)

enum class GoalProgressState(val apiValue: String) {
    Idle("not_started"),
    OnTrack("on_track"),
    NearLimit("near_limit"),
    OverLimit("over_limit"),
    Archived("archived");

    companion object {
        fun fromApiValue(value: String): GoalProgressState =
            entries.firstOrNull { it.apiValue == value } ?: Idle
    }
}

data class Goal(
    val publicId: String,
    val ledgerId: String,
    val name: String,
    val goalType: String,
    val period: String,
    val month: String,
    val category: String?,
    val targetAmountCents: Long,
    val spentAmountCents: Long,
    val remainingAmountCents: Long,
    val progressPercent: Int,
    val progressState: GoalProgressState,
    val status: String,
    val createdAt: String,
    val updatedAt: String,
    val archivedAt: String?,
) {
    val progress: Float = (progressPercent / 100f).coerceIn(0f, 1f)
    val isArchived: Boolean = status == "archived" || archivedAt != null
    val isOverLimit: Boolean = progressState == GoalProgressState.OverLimit
}

data class GoalDraft(
    val name: String,
    val month: String,
    val targetAmountCents: Long,
    val category: String? = null,
)

data class GoalUpdate(
    val name: String? = null,
    val month: String? = null,
    val targetAmountCents: Long? = null,
    val category: String? = null,
)

enum class DashboardSurface(val apiValue: String) {
    Android("android"),
    Web("web");
}

const val DASHBOARD_CARD_PENDING = "pending"
const val DASHBOARD_CARD_MONTHLY_SPEND = "monthly_spend"
const val DASHBOARD_CARD_REPORTS = "reports"
const val DASHBOARD_CARD_BUDGET = "budget"
const val DASHBOARD_CARD_GOALS = "goals"
const val DASHBOARD_CARD_RECURRING = "recurring"
const val DASHBOARD_CARD_RECENT_UPLOADS = "recent_uploads"

enum class StatsTab {
    Overview,
    Trend,
    Category,
    Budget,
    Goals,
}

val DefaultAndroidDashboardCardKeys: List<String> = listOf(
    DASHBOARD_CARD_PENDING,
    DASHBOARD_CARD_MONTHLY_SPEND,
    DASHBOARD_CARD_REPORTS,
    DASHBOARD_CARD_BUDGET,
    DASHBOARD_CARD_GOALS,
    DASHBOARD_CARD_RECURRING,
    DASHBOARD_CARD_RECENT_UPLOADS,
)

data class DashboardCard(
    val key: String,
    val title: String,
    val visible: Boolean,
    val position: Int,
)

data class DashboardCards(
    val surface: DashboardSurface,
    val items: List<DashboardCard>,
)

data class DashboardCardUpdate(
    val key: String,
    val visible: Boolean,
    val position: Int,
)

fun visibleDashboardCardKeys(cards: List<DashboardCard>): List<String> {
    if (cards.isEmpty()) {
        return DefaultAndroidDashboardCardKeys
    }
    val defaultOrder = DefaultAndroidDashboardCardKeys.withIndex().associate { it.value to it.index }
    return cards
        .filter { it.visible }
        .sortedWith(
            compareBy<DashboardCard> { it.position }
                .thenBy { defaultOrder[it.key] ?: Int.MAX_VALUE }
                .thenBy { it.key },
        )
        .map { it.key }
}

fun statsDashboardKeysForTab(
    tab: StatsTab,
    keys: List<String>,
): List<String> {
    val allowedKeys = when (tab) {
        StatsTab.Overview -> setOf(
            DASHBOARD_CARD_MONTHLY_SPEND,
            DASHBOARD_CARD_PENDING,
            DASHBOARD_CARD_RECENT_UPLOADS,
        )
        StatsTab.Trend -> setOf(DASHBOARD_CARD_REPORTS)
        StatsTab.Category -> setOf(DASHBOARD_CARD_REPORTS)
        StatsTab.Budget -> setOf(
            DASHBOARD_CARD_BUDGET,
            DASHBOARD_CARD_RECURRING,
        )
        StatsTab.Goals -> setOf(DASHBOARD_CARD_GOALS)
    }
    return keys.filter { it in allowedKeys }
}
