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
        AppSkin.Pine -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFE6981B), Color(0xFF8A5A12), Color(0xFFFFFCF7)),
            monthSpend = DashboardCardAccent(Color(0xFF185B4F), Color(0xFF0E433A), Color(0xFFFFFCF7)),
            recentUpload = DashboardCardAccent(Color(0xFF2D7A80), Color(0xFF143E42), Color(0xFFFFFCF7)),
            recurring = DashboardCardAccent(Color(0xFFC8995F), Color(0xFF6E4D1D), Color(0xFFFFFCF7)),
            goals = DashboardCardAccent(Color(0xFF5E8A6F), Color(0xFF2E5841), Color(0xFFFFFCF7)),
            budget = DashboardCardAccent(Color(0xFF185B4F), Color(0xFF0E433A), Color(0xFFFFFCF7)),
            backup = DashboardCardAccent(Color(0xFF4A6E84), Color(0xFF253C4E), Color(0xFFFFFCF7)),
            device = DashboardCardAccent(Color(0xFF8B7A65), Color(0xFF55483A), Color(0xFFFFFCF7)),
        )
        AppSkin.Pomelo -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFE6981B), Color(0xFF8A5A12), Color(0xFFFFFCF7)),
            monthSpend = DashboardCardAccent(Color(0xFFCB6C2F), Color(0xFF6C3712), Color(0xFFFFFCF7)),
            recentUpload = DashboardCardAccent(Color(0xFF2D7A80), Color(0xFF143E42), Color(0xFFFFFCF7)),
            recurring = DashboardCardAccent(Color(0xFF8A6A2D), Color(0xFF473513), Color(0xFFFFFCF7)),
            goals = DashboardCardAccent(Color(0xFF6A8C3F), Color(0xFF36511C), Color(0xFFFFFCF7)),
            budget = DashboardCardAccent(Color(0xFFE6981B), Color(0xFF8A5A12), Color(0xFFFFFCF7)),
            backup = DashboardCardAccent(Color(0xFF45A6A3), Color(0xFF1F5957), Color(0xFFFFFCF7)),
            device = DashboardCardAccent(Color(0xFFB05E91), Color(0xFF5F2F4D), Color(0xFFFFFCF7)),
        )
        AppSkin.Harbor -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFD5A35D), Color(0xFF7C5414), Color(0xFFFFFCF7)),
            monthSpend = DashboardCardAccent(Color(0xFF245D78), Color(0xFF12384C), Color(0xFFFFFCF7)),
            recentUpload = DashboardCardAccent(Color(0xFF3E92AE), Color(0xFF1E5A6E), Color(0xFFFFFCF7)),
            recurring = DashboardCardAccent(Color(0xFFB87A48), Color(0xFF6B431E), Color(0xFFFFFCF7)),
            goals = DashboardCardAccent(Color(0xFF185B4F), Color(0xFF0E433A), Color(0xFFFFFCF7)),
            budget = DashboardCardAccent(Color(0xFF245D78), Color(0xFF12384C), Color(0xFFFFFCF7)),
            backup = DashboardCardAccent(Color(0xFF6B7F4D), Color(0xFF394823), Color(0xFFFFFCF7)),
            device = DashboardCardAccent(Color(0xFF5A4E78), Color(0xFF2F274A), Color(0xFFFFFCF7)),
        )
        AppSkin.Berry -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFC4657F), Color(0xFF73263F), Color(0xFFFFFAFC)),
            monthSpend = DashboardCardAccent(Color(0xFFA83C5A), Color(0xFF511B2A), Color(0xFFFFFAFC)),
            recentUpload = DashboardCardAccent(Color(0xFF3E7A6A), Color(0xFF1F4138), Color(0xFFFFFAFC)),
            recurring = DashboardCardAccent(Color(0xFF8B7A65), Color(0xFF55483A), Color(0xFFFFFAFC)),
            goals = DashboardCardAccent(Color(0xFF6F4C7A), Color(0xFF3F2548), Color(0xFFFFFAFC)),
            budget = DashboardCardAccent(Color(0xFFA83C5A), Color(0xFF511B2A), Color(0xFFFFFAFC)),
            backup = DashboardCardAccent(Color(0xFF457495), Color(0xFF1F3F58), Color(0xFFFFFAFC)),
            device = DashboardCardAccent(Color(0xFFB8814D), Color(0xFF6A4520), Color(0xFFFFFAFC)),
        )
        AppSkin.Night -> DashboardCardTokens(
            pending = DashboardCardAccent(Color(0xFFD2A46E), Color(0xFFF7E1C1), Color(0xFF0D2027)),
            monthSpend = DashboardCardAccent(Color(0xFF2BB49A), Color(0xFFC7F2E8), Color(0xFF0D2027)),
            recentUpload = DashboardCardAccent(Color(0xFF84BCD4), Color(0xFFD4E8EF), Color(0xFF0D2027)),
            recurring = DashboardCardAccent(Color(0xFFE8C07A), Color(0xFFF8E1B6), Color(0xFF0D2027)),
            goals = DashboardCardAccent(Color(0xFFAFC97A), Color(0xFFDDEEB7), Color(0xFF0D2027)),
            budget = DashboardCardAccent(Color(0xFF2BB49A), Color(0xFFC7F2E8), Color(0xFF0D2027)),
            backup = DashboardCardAccent(Color(0xFF6FB1AD), Color(0xFFCFEAE7), Color(0xFF0D2027)),
            device = DashboardCardAccent(Color(0xFFB78ED3), Color(0xFFE0CCEF), Color(0xFF0D2027)),
        )
    }
}
