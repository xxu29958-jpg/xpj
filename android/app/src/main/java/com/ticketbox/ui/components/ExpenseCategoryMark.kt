package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DefaultExpenseCategories
import com.ticketbox.ui.design.AppDensity
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun expenseCategorySurface(category: String) = with(LocalThemeVisuals.current) {
    when (category) {
        DefaultExpenseCategories.DINING, DefaultExpenseCategories.HOUSING -> surfaceApricot
        DefaultExpenseCategories.TRANSIT, DefaultExpenseCategories.OTHER -> surfaceLilac
        else -> brandPrimaryBg
    }
}

/**
 * W2-B: 默认分类从单调首字块升级为语义图标（展示助读，分类文本仍是事实）；
 * 自定义/未知分类回退首字，不为无事实的分类硬造图形。
 */
private val expenseCategoryIcons: Map<String, Int> = mapOf(
    DefaultExpenseCategories.DINING to R.drawable.ic_lucide_utensils,
    DefaultExpenseCategories.TRANSIT to R.drawable.ic_lucide_bus,
    DefaultExpenseCategories.SHOPPING to R.drawable.ic_lucide_shopping_bag,
    DefaultExpenseCategories.ENTERTAINMENT to R.drawable.ic_lucide_clapperboard,
    DefaultExpenseCategories.MEDICAL to R.drawable.ic_lucide_briefcase_medical,
    DefaultExpenseCategories.EDUCATION to R.drawable.ic_lucide_graduation_cap,
    DefaultExpenseCategories.HOUSING to R.drawable.ic_lucide_house,
    DefaultExpenseCategories.TELECOM to R.drawable.ic_lucide_phone,
    DefaultExpenseCategories.AI_SUBSCRIPTION to R.drawable.ic_lucide_bot,
    DefaultExpenseCategories.DIGITAL to R.drawable.ic_lucide_monitor_smartphone,
    DefaultExpenseCategories.GAMES to R.drawable.ic_lucide_gamepad_2,
    DefaultExpenseCategories.LIFE to R.drawable.ic_lucide_sofa,
    DefaultExpenseCategories.OTHER to R.drawable.ic_lucide_ellipsis,
)

@Composable
internal fun ExpenseCategoryMark(category: String, density: AppListDensity) {
    val visuals = LocalThemeVisuals.current
    val rowMetrics = AppDensity.rowMetrics(density)
    val background = expenseCategorySurface(category)
    Box(
        modifier = Modifier
            .size(rowMetrics.markSize)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(background),
        contentAlignment = Alignment.Center,
    ) {
        val icon = expenseCategoryIcons[category]
        if (icon != null) {
            Icon(
                imageVector = ImageVector.vectorResource(icon),
                contentDescription = null,
                tint = visuals.primary,
                modifier = Modifier.size(
                    if (density == AppListDensity.Compact) 18.dp else 20.dp,
                ),
            )
        } else {
            val markFallback = stringResource(R.string.ledger_item_category_mark_fallback)
            Text(
                text = category.take(1).ifBlank { markFallback },
                color = visuals.primary,
                style = if (density == AppListDensity.Compact) {
                    MaterialTheme.typography.labelLarge
                } else {
                    MaterialTheme.typography.titleMedium
                },
                fontWeight = AppTypography.cardTitle.weight,
                textAlign = TextAlign.Center,
            )
        }
    }
}
