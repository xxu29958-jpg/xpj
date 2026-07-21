package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.filled.AutoFixHigh
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing

data class TransactionsLibraryActions(
    val onBack: () -> Unit,
    val onOpenCategories: () -> Unit,
    val onOpenMerchants: () -> Unit,
    val onOpenTags: () -> Unit,
    val onOpenRules: () -> Unit,
    val onOpenRecycleBin: () -> Unit,
)

@Composable
fun TransactionsLibraryScreen(
    actions: TransactionsLibraryActions,
) {
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.transactions_library_title),
            subtitle = stringResource(R.string.transactions_library_subtitle),
            backText = stringResource(R.string.transactions_library_back_to_transactions),
            onBack = actions.onBack,
        ),
    ) {
        TransactionsLibraryGroup(
            title = stringResource(R.string.transactions_library_group_vocabulary),
            entries = listOf(
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_categories_title),
                    subtitle = stringResource(R.string.transactions_library_categories_subtitle),
                    icon = Icons.Filled.Category,
                    onClick = actions.onOpenCategories,
                ),
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_merchants_title),
                    subtitle = stringResource(R.string.transactions_library_merchants_subtitle),
                    icon = Icons.Filled.Storefront,
                    onClick = actions.onOpenMerchants,
                ),
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_tags_title),
                    subtitle = stringResource(R.string.transactions_library_tags_subtitle),
                    icon = Icons.AutoMirrored.Filled.Label,
                    onClick = actions.onOpenTags,
                ),
            ),
        )
        TransactionsLibraryGroup(
            title = stringResource(R.string.transactions_library_group_automation),
            entries = listOf(
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_rules_title),
                    subtitle = stringResource(R.string.transactions_library_rules_subtitle),
                    icon = Icons.Filled.AutoFixHigh,
                    onClick = actions.onOpenRules,
                ),
            ),
        )
        TransactionsLibraryGroup(
            title = stringResource(R.string.transactions_library_group_lifecycle),
            entries = listOf(
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_recycle_bin_title),
                    subtitle = stringResource(R.string.transactions_library_recycle_bin_subtitle),
                    icon = Icons.Filled.DeleteOutline,
                    onClick = actions.onOpenRecycleBin,
                ),
            ),
        )
    }
}

private data class TransactionsLibraryEntry(
    val title: String,
    val subtitle: String,
    val icon: ImageVector,
    val onClick: () -> Unit,
)

@Composable
private fun TransactionsLibraryGroup(
    title: String,
    entries: List<TransactionsLibraryEntry>,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
        AppContentCard(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.none),
        ) {
            entries.forEachIndexed { index, entry ->
                AppListRow(
                    onClick = entry.onClick,
                    showDivider = index < entries.lastIndex,
                ) {
                    TransactionsLibraryEntryContent(entry)
                }
            }
        }
    }
}

@Composable
private fun TransactionsLibraryEntryContent(
    entry: TransactionsLibraryEntry,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .defaultMinSize(minHeight = AppSpacing.controlMinHeight),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(AppSpacing.controlMinHeight)
                .clip(RoundedCornerShape(AppRadius.small))
                .background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = entry.icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(AppSpacing.cardPadding),
            )
        }
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = entry.title,
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = entry.subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
    }
}
