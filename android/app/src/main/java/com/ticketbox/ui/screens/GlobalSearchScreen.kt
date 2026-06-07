package com.ticketbox.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.GlobalSearchResultKind
import com.ticketbox.viewmodel.GlobalSearchResultUi
import com.ticketbox.viewmodel.GlobalSearchScope
import com.ticketbox.viewmodel.GlobalSearchUiState

@Composable
fun GlobalSearchScreen(
    state: GlobalSearchUiState,
    onQueryChange: (String) -> Unit,
    onScopeChange: (GlobalSearchScope) -> Unit,
    onRefreshPending: () -> Unit,
    onOpenExpense: (Long) -> Unit,
) {
    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.loadingPending,
        onRefresh = onRefreshPending,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            AppPageHeader(
                title = stringResource(R.string.global_search_header_title),
                subtitle = stringResource(R.string.global_search_header_subtitle),
            )
        }
        item {
            SearchControlCard(
                state = state,
                onQueryChange = onQueryChange,
                onScopeChange = onScopeChange,
            )
        }
        state.message?.let { message ->
            item { SearchMessageCard(message = message) }
        }
        when {
            state.query.isBlank() -> item {
                SearchEmptyCard(
                    title = stringResource(R.string.global_search_empty_blank_title),
                    subtitle = stringResource(R.string.global_search_empty_blank_subtitle),
                )
            }
            state.results.isEmpty() -> item {
                SearchEmptyCard(
                    title = stringResource(R.string.global_search_empty_nomatch_title),
                    subtitle = stringResource(R.string.global_search_empty_nomatch_subtitle),
                )
            }
            else -> {
                items(
                    items = state.results,
                    key = { result -> "${result.kind}-${result.expense.id}" },
                ) { result ->
                    SearchResultCard(
                        result = result,
                        onClick = { onOpenExpense(result.expense.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun SearchControlCard(
    state: GlobalSearchUiState,
    onQueryChange: (String) -> Unit,
    onScopeChange: (GlobalSearchScope) -> Unit,
) {
    AppContentCard(
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        OutlinedTextField(
            value = state.query,
            onValueChange = onQueryChange,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            leadingIcon = {
                Icon(
                    imageVector = Icons.Filled.Search,
                    contentDescription = null,
                    modifier = Modifier.size(SearchLayout.IconSize),
                )
            },
            trailingIcon = {
                if (state.query.isNotBlank()) {
                    IconButton(onClick = { onQueryChange("") }) {
                        Icon(
                            Icons.Filled.Close,
                            contentDescription = stringResource(R.string.global_search_clear_action),
                        )
                    }
                }
            },
            label = { Text(stringResource(R.string.global_search_field_label)) },
            placeholder = { Text(stringResource(R.string.global_search_field_placeholder)) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        )
        AppSegmentedControl(
            options = listOf(
                AppSegmentedItem(
                    GlobalSearchScope.All,
                    stringResource(
                        R.string.global_search_scope_all,
                        state.pendingMatchCount + state.confirmedMatchCount,
                    ),
                ),
                AppSegmentedItem(
                    GlobalSearchScope.Pending,
                    stringResource(R.string.global_search_scope_pending, state.pendingMatchCount),
                ),
                AppSegmentedItem(
                    GlobalSearchScope.Confirmed,
                    stringResource(R.string.global_search_scope_confirmed, state.confirmedMatchCount),
                ),
            ),
            selectedValue = state.scope,
            onValueChange = onScopeChange,
        )
    }
}

@Composable
private fun SearchMessageCard(message: UiText) {
    val tone = LocalStateTokens.current.warn
    AppContentCard(
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
    ) {
        Text(
            text = message.asString(),
            color = tone.fg,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun SearchEmptyCard(
    title: String,
    subtitle: String,
) {
    AppContentCard {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTypography.cardTitle.weight,
        )
        Text(
            text = subtitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun SearchResultCard(
    result: GlobalSearchResultUi,
    onClick: () -> Unit,
) {
    val expense = result.expense
    AppContentCard(
        modifier = Modifier.clickable(onClick = onClick),
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.Top,
        ) {
            SearchKindBadge(kind = result.kind)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = result.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTypography.cardTitle.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = "${expense.category} · ${expense.source} · ${displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt)}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatAmount(expense.amountCents),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = AppTypography.amountMedium.weight,
                maxLines = 1,
            )
        }
        Text(
            text = stringResource(R.string.global_search_result_matched, result.matchedField.asString()),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SearchKindBadge(kind: GlobalSearchResultKind) {
    val states = LocalStateTokens.current
    val tone = when (kind) {
        GlobalSearchResultKind.Pending -> states.info
        GlobalSearchResultKind.Confirmed -> states.success
    }
    val label = when (kind) {
        GlobalSearchResultKind.Pending -> stringResource(R.string.global_search_badge_pending)
        GlobalSearchResultKind.Confirmed -> stringResource(R.string.global_search_badge_confirmed)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tone.bg)
            .border(BorderStroke(SearchLayout.BadgeBorder, tone.border), RoundedCornerShape(AppRadius.pill))
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.miniGap),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = tone.fg,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTypography.chip.weight,
            maxLines = 1,
        )
    }
}

private object SearchLayout {
    val IconSize: Dp = 20.dp
    val BadgeBorder: Dp = 1.dp
}
