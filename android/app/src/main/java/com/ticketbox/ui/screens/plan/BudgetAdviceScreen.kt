package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetAdvice
import com.ticketbox.domain.model.BudgetSuggestion
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BudgetAdviceLoadState
import com.ticketbox.viewmodel.BudgetAdviceUiState
import kotlin.math.roundToInt

@Composable
internal fun BudgetAdviceScreen(
    state: BudgetAdviceUiState,
    onRequestAdvice: () -> Unit,
    onBack: () -> Unit,
) {
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.budget_advice_page_title),
            subtitle = stringResource(
                R.string.budget_advice_page_subtitle,
                displayMonthLabel(state.month),
            ),
            backText = stringResource(R.string.budget_advice_back_to_plan),
            onBack = onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        slots = AppSecondaryPageSlots(
            status = {
                AppDataAuthorityStrip(
                    tone = when {
                        !state.canRequest -> DataAuthorityTone.ReadOnly
                        state.loadState == BudgetAdviceLoadState.Loading -> DataAuthorityTone.Refreshing
                        else -> DataAuthorityTone.Backend
                    },
                )
            },
        ),
    ) {
        BudgetAdviceBody(
            state = state,
            onRequestAdvice = onRequestAdvice,
        )
    }
}

@Composable
private fun BudgetAdviceBody(
    state: BudgetAdviceUiState,
    onRequestAdvice: () -> Unit,
) {
    if (!state.canRequest) {
        BudgetAdviceReadOnlyCard()
        return
    }
    when (state.loadState) {
        BudgetAdviceLoadState.Idle -> BudgetAdviceStartCard(onRequestAdvice)
        BudgetAdviceLoadState.Loading -> AppLoadingState(
            title = stringResource(R.string.budget_advice_loading_title),
            body = stringResource(R.string.budget_advice_loading_body),
        )
        BudgetAdviceLoadState.Empty -> BudgetAdviceEmptyCard(onRequestAdvice)
        BudgetAdviceLoadState.Unavailable -> BudgetAdviceUnavailableCard(state)
        BudgetAdviceLoadState.Ready -> state.result?.let { result ->
            result.advice?.let { advice ->
                BudgetAdviceResultContent(
                    advice = advice,
                    currencyDisplay = CurrencyDisplay.forRecord(result.homeCurrencyCode),
                    onRequestAdvice = onRequestAdvice,
                )
            }
        } ?: BudgetAdviceEmptyCard(onRequestAdvice)
        BudgetAdviceLoadState.Failed -> AppErrorState(
            title = stringResource(R.string.budget_advice_error_title),
            body = state.error?.asString().orEmpty().ifBlank {
                stringResource(R.string.budget_advice_load_failed)
            },
            onRetry = onRequestAdvice,
        )
    }
}

@Composable
private fun BudgetAdviceStartCard(onRequestAdvice: () -> Unit) {
    AppContentCard {
        Text(
            text = stringResource(R.string.budget_advice_start_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.budget_advice_start_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = stringResource(R.string.budget_advice_privacy_note),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        AppPrimaryButton(
            text = stringResource(R.string.budget_advice_generate),
            icon = Icons.Filled.Tune,
            modifier = Modifier.fillMaxWidth(),
            onClick = onRequestAdvice,
        )
    }
}

@Composable
private fun BudgetAdviceReadOnlyCard() {
    AppContentCard {
        Text(
            text = stringResource(R.string.budget_advice_readonly_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.budget_advice_readonly_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun BudgetAdviceUnavailableCard(state: BudgetAdviceUiState) {
    AppContentCard {
        Text(
            text = stringResource(R.string.budget_advice_unavailable_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = state.error?.asString().orEmpty().ifBlank {
                stringResource(R.string.budget_advice_unavailable_body)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun BudgetAdviceEmptyCard(onRequestAdvice: () -> Unit) {
    AppContentCard {
        Text(
            text = stringResource(R.string.budget_advice_empty_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.budget_advice_empty_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppSecondaryButton(
            text = stringResource(R.string.budget_advice_generate_again),
            modifier = Modifier.fillMaxWidth(),
            leadingIcon = Icons.Filled.Refresh,
            onClick = onRequestAdvice,
        )
    }
}

@Composable
private fun BudgetAdviceResultContent(
    advice: BudgetAdvice,
    currencyDisplay: CurrencyDisplay,
    onRequestAdvice: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        AppContentCard {
            Text(
                text = stringResource(R.string.budget_advice_summary_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = advice.summary,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyLarge,
            )
            advice.confidence?.let { confidence ->
                Text(
                    text = stringResource(
                        R.string.budget_advice_confidence,
                        (confidence * 100).roundToInt().coerceIn(0, 100),
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        if (advice.suggestions.isNotEmpty()) {
            BudgetSuggestionList(advice.suggestions, currencyDisplay)
        }
        AppSecondaryButton(
            text = stringResource(R.string.budget_advice_generate_again),
            modifier = Modifier.fillMaxWidth(),
            leadingIcon = Icons.Filled.Refresh,
            onClick = onRequestAdvice,
        )
    }
}

@Composable
private fun BudgetSuggestionList(
    suggestions: List<BudgetSuggestion>,
    currencyDisplay: CurrencyDisplay,
) {
    AppContentCard {
        Text(
            text = stringResource(R.string.budget_advice_suggestions_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        suggestions.forEachIndexed { index, suggestion ->
            if (index > 0) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
            BudgetSuggestionRow(suggestion, currencyDisplay)
        }
        Text(
            text = stringResource(R.string.budget_advice_result_note),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun BudgetSuggestionRow(
    suggestion: BudgetSuggestion,
    currencyDisplay: CurrencyDisplay,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = suggestion.category?.takeIf(String::isNotBlank)
                    ?: stringResource(R.string.budget_advice_overall_category),
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = formatDisplayAmount(suggestion.suggestedAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            text = suggestion.rationale,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
