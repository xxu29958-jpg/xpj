package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetAdvice
import com.ticketbox.domain.model.BudgetSuggestion
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.viewmodel.BudgetAdviceLoadState
import com.ticketbox.viewmodel.BudgetAdviceUiState
import kotlin.math.roundToInt

internal enum class BudgetAdvicePurpose(val title: Int, val back: Int) {
    Arrangement(R.string.budget_advice_page_title, R.string.budget_advice_back_to_plan),
    ReportRates(R.string.advice_reference_page_title, R.string.advice_reference_back_to_insights),
    CorrectionRates(R.string.advice_reference_page_title, R.string.correction_rate_back),
}

@Composable
internal fun BudgetAdviceScreen(
    state: BudgetAdviceUiState,
    actions: BudgetAdviceActions,
    onBack: () -> Unit,
    purpose: BudgetAdvicePurpose = BudgetAdvicePurpose.Arrangement,
    onOpenBudget: (() -> Unit)? = null,
) {
    val ratesOnly = purpose != BudgetAdvicePurpose.Arrangement
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(purpose.title),
            subtitle = if (ratesOnly) stringResource(R.string.advice_reference_page_body) else stringResource(
                R.string.budget_advice_page_subtitle,
                displayMonthLabel(state.month),
            ),
            backText = stringResource(purpose.back),
            onBack = onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        slots = AppSecondaryPageSlots(
            bottomBar = if (!ratesOnly && state.arrangementDraft != null && state.rateEditor == null) ({
                MonthlyArrangementSaveAction(state, actions.onSaveArrangement)
            }) else null,
            status = {
                state.authorityTone?.let { AppDataAuthorityStrip(tone = it) }
            },
        ),
    ) {
        if (ratesOnly) {
            BudgetRateContent(state, actions, purpose)
            return@AppSecondaryScrollableColumn
        }
        BudgetAdviceInputsContent(state, actions, onOpenBudget)
        if (!state.inputsLoading && state.inputs?.readyForAdvice == true &&
            (state.arrangementDraft?.edited != true || state.trialRequest != null)) {
            BudgetAdviceRequest(state, actions.onGenerate)
        }
        BudgetAdviceReferenceContent(state, actions)
    }
}

@Composable
private fun BudgetRateContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions, purpose: BudgetAdvicePurpose) {
    state.arrangementMessage?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
    if (purpose == BudgetAdvicePurpose.CorrectionRates) Text(stringResource(R.string.correction_rate_continuation))
    if (purpose == BudgetAdvicePurpose.ReportRates && state.rateEditor == null) ReferenceRateLookup(state, actions)
    ManualRateContent(state, actions)
}

@Composable
private fun BudgetAdviceRequest(state: BudgetAdviceUiState, onGenerate: () -> Unit) {
    var confirming by remember(state.binding, state.month, state.inputs) { mutableStateOf(false) }
    (state.result?.inputs ?: state.inputs)?.let { BudgetAdviceDataScope(it) }
    BudgetAdviceBody(state, onRequestAdvice = { confirming = true })
    if (confirming && state.canRequest) AlertDialog(
        onDismissRequest = { confirming = false },
        title = { Text(stringResource(R.string.budget_advice_consent_title)) },
        text = { Text(stringResource(R.string.budget_advice_privacy_note)) },
        confirmButton = { TextButton(onClick = { confirming = false; onGenerate() }) {
            Text(stringResource(R.string.budget_advice_consent_confirm))
        } },
        dismissButton = { TextButton(onClick = { confirming = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}

private val BudgetAdviceUiState.authorityTone: DataAuthorityTone?
    get() = when {
        !canRequest -> DataAuthorityTone.ReadOnly
        inputsLoading || loadState == BudgetAdviceLoadState.Loading -> DataAuthorityTone.Refreshing
        inputs != null || result != null -> DataAuthorityTone.Backend
        else -> null
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
            icons = AppButtonIcons(leading = Icons.Filled.Tune),
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
        AppAdaptiveContentActionRow(
            style = AppAdaptiveContentActionStyle(compactAction = true),
            content = {
            Text(
                text = suggestion.category?.takeIf(String::isNotBlank)
                    ?: stringResource(R.string.budget_advice_overall_category),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            },
            action = { modifier -> AppEndAlignedAmountText(
                text = formatDisplayAmount(suggestion.suggestedAmountCents, currencyDisplay),
                modifier = modifier,
                role = AppAmountRole.Compact,
                color = MaterialTheme.colorScheme.primary,
            ) },
        )
        Text(
            text = suggestion.rationale,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
