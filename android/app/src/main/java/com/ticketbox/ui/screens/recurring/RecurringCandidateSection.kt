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
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.ReadableListBodyState
import com.ticketbox.ui.screens.RecurringCandidateActions
import com.ticketbox.ui.screens.RecurringListSectionModel

internal data class RecurringCandidateSectionOptions(
    val canModify: Boolean,
    /** 主列表健康时候选失败才给重试；主列表已失败时全页只留一个下一步。 */
    val itemsHealthy: Boolean,
    /** 采用建议是 generic 命令，与行内生命周期键吃同一个屏级在途 gate。 */
    val confirmEnabled: Boolean,
)

/**
 * 候选只是辅助发现：整张卡视觉降权，CTA 是「采用建议」（outlined 次级按钮），
 * 不与主 registry 的创建路径抢焦点。采用走 confirmCandidate，保留 candidate provenance。
 * 失败不再亮红色错误卡：只留一行诚实说明，避免双重红色压过用户任务。
 */
@Composable
internal fun RecurringCandidatesCard(
    section: RecurringListSectionModel<RecurringCandidate>,
    currencyDisplay: CurrencyDisplay,
    options: RecurringCandidateSectionOptions,
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
                    showRetry = options.itemsHealthy,
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
                    candidates.take(8).forEach { candidate ->
                        RecurringCandidateRow(
                            candidate = candidate,
                            currencyDisplay = currencyDisplay,
                            canModify = options.canModify,
                            confirmEnabled = options.confirmEnabled,
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
    showRetry: Boolean,
    onRetry: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(
                if (showRetry) {
                    R.string.recurring_candidates_load_failed_body
                } else {
                    R.string.recurring_candidates_unavailable_quiet
                },
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (showRetry) {
            TextButton(onClick = onRetry) {
                Text(stringResource(R.string.common_retry))
            }
        }
    }
}

@Composable
private fun RecurringCandidateRow(
    candidate: RecurringCandidate,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    confirmEnabled: Boolean,
    actions: RecurringCandidateActions,
) {
    val merchantFallback = stringResource(R.string.recurring_candidate_merchant_fallback)
    val content = @Composable {
        AppAdaptiveEditAmountRow(
            amount = formatDisplayAmount(candidate.amountCents, currencyDisplay),
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
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = stringResource(
                        R.string.recurring_candidate_meta_summary,
                        candidate.occurrenceCount,
                        candidate.confidence,
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall.tabularNum(),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
    if (canModify) {
        AppAdaptiveContentActionRow(
            wideActionWeight = 0.46f,
            verticalAlignment = Alignment.Top,
            content = content,
            action = { actionModifier ->
                AppSecondaryButton(
                    modifier = actionModifier,
                    text = stringResource(R.string.recurring_candidate_confirm),
                    enabled = confirmEnabled,
                    onClick = { actions.onConfirmCandidate(candidate) },
                )
            },
        )
    } else {
        content()
    }
}
