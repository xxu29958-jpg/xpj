package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.ReadableListBodyState
import com.ticketbox.ui.screens.RecurringCandidateActions
import com.ticketbox.ui.screens.RecurringListSectionModel

/**
 * 观察建议在独立分区核对，采用走 confirmCandidate，保留 candidate provenance。
 * 使用次级动作与文字置信度，不把观察渲染成已生效计划；失败时在本区重试。
 */
@Composable
internal fun RecurringCandidatesCard(
    section: RecurringListSectionModel<RecurringCandidate>,
    canModify: Boolean,
    onRetry: () -> Unit,
    actions: RecurringCandidateActions,
) {
    val candidates = section.rows
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            Text(
                text = stringResource(R.string.recurring_candidates_card_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.recurring_candidates_card_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            when (section.bodyState) {
                ReadableListBodyState.LoadFailed -> RecurringCandidatesQuietFailure(
                    onRetry = onRetry,
                )
                ReadableListBodyState.Loading,
                ReadableListBodyState.Empty,
                ReadableListBodyState.Content -> AppListStateContent(
                    state = AppListStateSpec(
                        isEmpty = section.bodyState != ReadableListBodyState.Content,
                        loading = section.bodyState == ReadableListBodyState.Loading,
                        emptyText = stringResource(R.string.recurring_candidates_empty),
                    ),
                ) {
                    candidates.forEach { candidate ->
                        RecurringCandidateRow(
                            candidate = candidate,
                            canModify = canModify,
                            actions = actions,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecurringCandidatesQuietFailure(
    onRetry: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.recurring_candidates_load_failed_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        TextButton(onClick = onRetry) {
            Text(stringResource(R.string.common_retry))
        }
    }
}

@Composable
private fun RecurringCandidateRow(
    candidate: RecurringCandidate,
    canModify: Boolean,
    actions: RecurringCandidateActions,
) {
    val merchantFallback = stringResource(R.string.recurring_candidate_merchant_fallback)
    val content = @Composable {
        AppAdaptiveEditAmountRow(
            amount = recurringRecordedAmountText(candidate.amountCents, candidate.homeCurrencyCode),
            style = AppAdaptiveAmountRowStyle(
                role = AppAmountRole.Compact,
                trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight,
            ),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    text = candidate.merchant.ifBlank { merchantFallback },
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = stringResource(
                        R.string.recurring_candidate_meta_summary,
                        candidate.occurrenceCount,
                        stringResource(if (candidate.confidence == "high") {
                            R.string.recurring_candidate_stable
                        } else {
                            R.string.recurring_candidate_review
                        }),
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall.tabularNum(),
                )
            }
        }
    }
    if (canModify) {
        AppAdaptiveContentActionRow(
            style = AppAdaptiveContentActionStyle(wideActionWeight = 0.46f, verticalAlignment = Alignment.Top),
            content = content,
            action = { actionModifier ->
                AppSecondaryButton(
                    modifier = actionModifier,
                    text = stringResource(R.string.recurring_candidate_confirm),
                    onClick = { actions.onConfirmCandidate(candidate) },
                )
            },
        )
    } else {
        content()
    }
}
