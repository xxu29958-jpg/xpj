package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
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
    val visuals = LocalThemeVisuals.current
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
                    icon = ImageVector.vectorResource(R.drawable.ic_lucide_shapes),
                    background = visuals.surfaceApricot,
                    onClick = actions.onOpenCategories,
                ),
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_merchants_title),
                    subtitle = stringResource(R.string.transactions_library_merchants_subtitle),
                    icon = ImageVector.vectorResource(R.drawable.ic_lucide_store),
                    background = MaterialTheme.colorScheme.primaryContainer,
                    onClick = actions.onOpenMerchants,
                ),
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_tags_title),
                    subtitle = stringResource(R.string.transactions_library_tags_subtitle),
                    icon = ImageVector.vectorResource(R.drawable.ic_lucide_tag),
                    background = visuals.surfaceLilac,
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
                    icon = ImageVector.vectorResource(R.drawable.ic_lucide_wand_sparkles),
                    background = MaterialTheme.colorScheme.primaryContainer,
                    onClick = actions.onOpenRules,
                ),
                TransactionsLibraryEntry(
                    title = stringResource(R.string.transactions_library_recycle_bin_title),
                    subtitle = stringResource(R.string.transactions_library_recycle_bin_subtitle),
                    icon = ImageVector.vectorResource(R.drawable.ic_lucide_trash_2),
                    background = visuals.surfaceApricot,
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
    val background: Color,
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
        AppSectionHeader(title)
        entries.forEachIndexed { index, entry ->
            AppListRow(onClick = entry.onClick, showDivider = index < entries.lastIndex) {
                TransactionsLibraryEntryContent(entry)
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
        SettingsEntryIcon(entry.icon, background = entry.background)
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
                style = MaterialTheme.typography.bodyMedium,
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
