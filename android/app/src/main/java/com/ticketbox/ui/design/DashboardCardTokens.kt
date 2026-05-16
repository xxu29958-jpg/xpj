package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class DashboardCardAccent(
    val accent: Color,
    val iconTint: Color,
    val surface: Color,
)

data class DashboardCardTokens(
    val pending: DashboardCardAccent,
    val monthSpend: DashboardCardAccent,
    val recentUpload: DashboardCardAccent,
    val recurring: DashboardCardAccent,
    val goals: DashboardCardAccent,
    val budget: DashboardCardAccent,
    val backup: DashboardCardAccent,
    val device: DashboardCardAccent,
)

val LocalDashboardCardTokens = compositionLocalOf { dashboardCardTokensForSkin(AppSkin.Default) }

fun dashboardCardTokensForSkin(skin: AppSkin): DashboardCardTokens {
    return when (skin) {
        AppSkin.Paper -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFF8A5A2B), Color(0xFF5A3A14), Color(0xFFFBF8F1)),
            monthSpend = DashboardCardAccent(Color(0xFF1C1A18), Color(0xFF0A0908), Color(0xFFFBF8F1)),
            recentUpload = DashboardCardAccent(Color(0xFF3E6770), Color(0xFF1C3E46), Color(0xFFFBF8F1)),
            recurring = DashboardCardAccent(Color(0xFFA4361C), Color(0xFF6E220F), Color(0xFFFBF8F1)),
            goals = DashboardCardAccent(Color(0xFF4F6B3A), Color(0xFF2E4220), Color(0xFFFBF8F1)),
            budget = DashboardCardAccent(Color(0xFF8A5A2B), Color(0xFF5A3A14), Color(0xFFFBF8F1)),
            backup = DashboardCardAccent(Color(0xFF807968), Color(0xFF4A463F), Color(0xFFFBF8F1)),
            device = DashboardCardAccent(Color(0xFF5A4A6E), Color(0xFF382D44), Color(0xFFFBF8F1)),
        )
        AppSkin.Mono -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFF6F6E6A), Color(0xFF3A3A37), Color(0xFFFAFAF8)),
            monthSpend = DashboardCardAccent(Color(0xFF0E0E0C), Color(0xFF000000), Color(0xFFFAFAF8)),
            recentUpload = DashboardCardAccent(Color(0xFF3A4A52), Color(0xFF1D2A30), Color(0xFFFAFAF8)),
            recurring = DashboardCardAccent(Color(0xFF8E1D12), Color(0xFF5A1009), Color(0xFFFAFAF8)),
            goals = DashboardCardAccent(Color(0xFF2C5036), Color(0xFF15301C), Color(0xFFFAFAF8)),
            budget = DashboardCardAccent(Color(0xFF0E0E0C), Color(0xFF000000), Color(0xFFFAFAF8)),
            backup = DashboardCardAccent(Color(0xFF6F6E6A), Color(0xFF3A3A37), Color(0xFFFAFAF8)),
            device = DashboardCardAccent(Color(0xFF5A4A6E), Color(0xFF382D44), Color(0xFFFAFAF8)),
        )
        AppSkin.Midnight -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFD6B487), Color(0xFFF0D9B3), Color(0xFF15171C)),
            monthSpend = DashboardCardAccent(Color(0xFFB89564), Color(0xFFE8D2AD), Color(0xFF15171C)),
            recentUpload = DashboardCardAccent(Color(0xFF84BCD4), Color(0xFFC4DEE9), Color(0xFF15171C)),
            recurring = DashboardCardAccent(Color(0xFFD97757), Color(0xFFF0B8A3), Color(0xFF15171C)),
            goals = DashboardCardAccent(Color(0xFFA8B88A), Color(0xFFCCD9B8), Color(0xFF15171C)),
            budget = DashboardCardAccent(Color(0xFFD6B487), Color(0xFFF0D9B3), Color(0xFF15171C)),
            backup = DashboardCardAccent(Color(0xFF7C8A6A), Color(0xFFB8C4A3), Color(0xFF15171C)),
            device = DashboardCardAccent(Color(0xFF8A7EAC), Color(0xFFC3B9D9), Color(0xFF15171C)),
        )
    }
}
