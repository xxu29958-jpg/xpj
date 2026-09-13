package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.TagStats
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

/** Counts and independent amounts remain useful when a share cannot be established. */
@Composable
internal fun CategoryStructureFacts(
    categories: List<CategoryStats>,
    tags: List<TagStats>,
    homeCurrencyCode: String,
    onCategoryClick: ((String) -> Unit)?,
) {
    val currency = CurrencyDisplay.forRecord(homeCurrencyCode)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(R.string.stats_category_structure_title), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.stats_comparison_unavailable), style = MaterialTheme.typography.bodySmall)
        categories.sortedBy { it.category }.forEach { category ->
            StatsFactRow(category.category, category.count, category.amountCents, currency,
                Modifier.clickable(enabled = onCategoryClick != null) { onCategoryClick?.invoke(category.category) })
        }
        if (tags.isNotEmpty()) {
            Text(stringResource(R.string.stats_tag_distribution_title), style = MaterialTheme.typography.titleSmall)
            tags.sortedBy { it.tag }.forEach { tag -> StatsFactRow(tag.tag, tag.count, tag.amountCents, currency) }
        }
    }
}

@Composable
private fun StatsFactRow(name: String, count: Int, amount: Long?, currency: CurrencyDisplay, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Column(Modifier.weight(1f)) {
            Text(name)
            Text(stringResource(R.string.stats_overview_count_value, count), style = MaterialTheme.typography.bodySmall)
        }
        Text(amount?.let { formatDisplayAmount(it, currency) } ?: stringResource(R.string.reports_amount_unavailable))
    }
}

@Composable
internal fun CategoryStructureCard(
    categories: List<CategoryStats>,
    tags: List<TagStats>,
    totalAmountCents: Long?,
    homeCurrencyCode: String,
    onCategoryClick: ((String) -> Unit)? = null,
) {
    val comparable = totalAmountCents != null && totalAmountCents > 0L &&
        categories.all { it.amountCents != null && it.amountCents >= 0L } &&
        tags.all { it.amountCents != null && it.amountCents >= 0L }
    if (comparable) {
        ComparableCategoryStructureCard(categories, tags, requireNotNull(totalAmountCents), homeCurrencyCode, onCategoryClick)
    } else {
        CategoryStructureFacts(categories, tags, homeCurrencyCode, onCategoryClick)
    }
}

