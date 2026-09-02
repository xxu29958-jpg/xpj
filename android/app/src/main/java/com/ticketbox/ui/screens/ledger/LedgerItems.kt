@file:OptIn(ExperimentalFoundationApi::class)

package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.DirectionsBus
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.MedicalServices
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.SportsEsports
import androidx.compose.material.icons.filled.Theaters
import androidx.compose.material.icons.filled.Weekend
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DefaultExpenseCategories
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveContentActionStateRow
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppEndAlignedAmountStatusText
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppDensity
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalThemeVisuals
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private object LedgerItemLayout {
    const val CardCategoryAlpha = 0.72f
    const val TableCategoryAlpha = 0.62f
    const val CategoryMarkAlpha = 0.78f
    const val TableMerchantWeight = 1.35f
    const val TableCategoryWeight = 0.72f
    val DayHeaderTrailingMaxWidth = 160.dp
    val RowTimeFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")
}

internal data class LedgerDayHeaderUi(
    val label: String,
    val dayTotalCents: Long,
    val itemCount: Int,
    val previewText: String? = null,
    val expandable: Boolean = false,
    val expanded: Boolean = true,
)

internal data class LedgerExpenseSelectionState(
    val enabled: Boolean,
    val selected: Boolean,
)

internal data class LedgerExpenseItemState(
    val expense: Expense,
    val selection: LedgerExpenseSelectionState,
    // Server-owned net-state of this bill's lineage (chip copy key); Confirmed
    // renders no chip. Presentation only — never feeds sums.
    val lineageStatus: ExpenseLineageStatus = ExpenseLineageStatus.Confirmed,
)

internal data class LedgerExpenseItemActions(
    val onOpen: () -> Unit,
    val onToggleSelection: () -> Unit,
    val onEnterSelection: () -> Unit,
)

/**
 * Day-group header: date on the left, that day's subtotal on the right. The
 * subtotal uses tabular figures and ink color (金额永远用墨), matching the
 * /web confirmed day-row rhythm. It follows the page background instead of
 * drawing a separate card strip, so date group headers stay structural rather
 * than becoming another block container.
 */
@Composable
internal fun LedgerDayHeader(state: LedgerDayHeaderUi, onToggle: (() -> Unit)? = null) {
    val metaText = state.previewText
        ?.let { stringResource(R.string.ledger_day_count_with_preview, state.itemCount, it) }
        ?: stringResource(R.string.ledger_day_count, state.itemCount)
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = { onToggle?.invoke() },
                    enabled = onToggle != null,
                )
                .padding(
                    horizontal = AppSpacing.smallGap,
                    vertical = AppSpacing.smallGap,
                ),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LedgerDayHeaderCopy(state = state, metaText = metaText, modifier = Modifier.weight(1f))
            Row(
                modifier = Modifier.widthIn(
                    min = AppAdaptiveAmountRowDefaults.statusMinWidth,
                    max = LedgerItemLayout.DayHeaderTrailingMaxWidth,
                ),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                LedgerDayHeaderAmount(
                    state = state,
                    modifier = Modifier.weight(1f),
                )
                LedgerDayHeaderToggleIcon(state)
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.10f))
    }
}

@Composable
private fun LedgerDayHeaderCopy(
    state: LedgerDayHeaderUi,
    metaText: String,
    modifier: Modifier,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = state.label,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTypography.cardTitle.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = metaText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerDayHeaderAmount(
    state: LedgerDayHeaderUi,
    modifier: Modifier,
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.CenterEnd,
    ) {
        AppEndAlignedAmountText(
            modifier = Modifier.fillMaxWidth(),
            text = formatAmount(state.dayTotalCents, LocalCurrencyCode.current),
            role = AppAmountRole.Compact,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun LedgerDayHeaderToggleIcon(state: LedgerDayHeaderUi) {
    if (!state.expandable) return
    Icon(
        imageVector = if (state.expanded) {
            Icons.Filled.KeyboardArrowDown
        } else {
            Icons.AutoMirrored.Filled.KeyboardArrowRight
        },
        contentDescription = if (state.expanded) {
            stringResource(R.string.ledger_day_collapse_description)
        } else {
            stringResource(R.string.ledger_day_expand_description)
        },
        tint = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.size(20.dp),
    )
}

@Composable
internal fun LedgerExpenseCard(
    state: LedgerExpenseItemState,
    actions: LedgerExpenseItemActions,
) {
    val visuals = LocalThemeVisuals.current
    val expense = state.expense
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = {
                    if (state.selection.enabled) {
                        actions.onToggleSelection()
                    } else {
                        actions.onOpen()
                    }
                },
                onLongClick = actions.onEnterSelection,
            ),
    ) {
        AppAdaptiveContentActionStateRow(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
            wideActionWeight = AppAdaptiveAmountRowDefaults.trailingWeight,
            verticalAlignment = Alignment.CenterVertically,
            content = {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (state.selection.enabled) {
                        Checkbox(checked = state.selection.selected, onCheckedChange = null)
                    }
                    LedgerCategoryMark(category = expense.category, density = AppListDensity.Standard)
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                        ) {
                            Text(
                                text = expense.merchant?.takeIf { it.isNotBlank() }
                                    ?: stringResource(R.string.ledger_item_merchant_empty),
                                modifier = Modifier.weight(1f, fill = false),
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurface,
                                fontWeight = AppTypography.cardTitle.weight,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            LedgerLineageChip(status = state.lineageStatus)
                        }
                        Text(
                            text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                            maxLines = 1,
                        )
                        expense.note?.takeIf { it.isNotBlank() }?.let {
                            Text(
                                text = it,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            },
            action = { amountModifier, _ ->
                Column(
                    modifier = amountModifier,
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    LedgerAmountOrPending(
                        amountCents = expense.amountCents,
                        display = CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        text = expense.category,
                        modifier = Modifier
                            .clip(CircleShape)
                            .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.CardCategoryAlpha))
                            .padding(
                                horizontal = AppSpacing.contentGap,
                                vertical = AppSpacing.miniGap + AppSpacing.tinyGap,
                            ),
                        color = visuals.primary,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = AppTypography.chip.weight,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            },
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.34f))
    }
}

@Composable
internal fun LedgerExpenseListRow(
    state: LedgerExpenseItemState,
    actions: LedgerExpenseItemActions,
) {
    val expense = state.expense
    val rowMetrics = AppDensity.rowMetrics(AppListDensity.Compact)
    val timeText = ledgerRowTime(expense.ledgerTimestamp()) ?: stringResource(R.string.ledger_item_time_empty)
    val metaText = stringResource(R.string.ledger_item_meta, timeText, expense.category)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = {
                    if (state.selection.enabled) {
                        actions.onToggleSelection()
                    } else {
                        actions.onOpen()
                    }
                },
                onLongClick = actions.onEnterSelection,
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = AppSpacing.miniGap, vertical = rowMetrics.rowPadding),
            horizontalArrangement = Arrangement.spacedBy(rowMetrics.itemSpacing),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                modifier = Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(rowMetrics.itemSpacing),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (state.selection.enabled) {
                    Checkbox(checked = state.selection.selected, onCheckedChange = null)
                }
                LedgerCategoryMark(category = expense.category, density = AppListDensity.Compact)
                LedgerListTextBlock(
                    expense = expense,
                    metaText = metaText,
                    lineageStatus = state.lineageStatus,
                    modifier = Modifier.weight(1f),
                )
            }
            LedgerAmountOrPending(
                amountCents = expense.amountCents,
                display = CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey),
                modifier = Modifier.widthIn(
                    min = AppAdaptiveAmountRowDefaults.statusMinWidth,
                    max = AppAdaptiveAmountRowDefaults.secondaryMetaInlineMaxWidth,
                ),
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.34f))
    }
}

@Composable
internal fun LedgerExpenseTableRow(
    state: LedgerExpenseItemState,
    actions: LedgerExpenseItemActions,
) {
    val visuals = LocalThemeVisuals.current
    val expense = state.expense
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = {
                    if (state.selection.enabled) {
                        actions.onToggleSelection()
                    } else {
                        actions.onOpen()
                    }
                },
                onLongClick = actions.onEnterSelection,
            ),
    ) {
        AppAdaptiveContentActionStateRow(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
            wideActionWeight = AppAdaptiveAmountRowDefaults.trailingWeight,
            verticalAlignment = Alignment.CenterVertically,
            content = {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (state.selection.enabled) {
                        Checkbox(checked = state.selection.selected, onCheckedChange = null)
                    }
                    Column(
                        modifier = Modifier.weight(LedgerItemLayout.TableMerchantWeight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                        ) {
                            Text(
                                text = expense.merchant?.takeIf { it.isNotBlank() }
                                    ?: stringResource(R.string.ledger_item_merchant_empty),
                                modifier = Modifier.weight(1f, fill = false),
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSurface,
                                fontWeight = AppTypography.chip.weight,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            LedgerLineageChip(status = state.lineageStatus)
                        }
                        Text(
                            text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.labelSmall,
                            maxLines = 1,
                        )
                    }
                    Text(
                        text = expense.category,
                        modifier = Modifier
                            .weight(LedgerItemLayout.TableCategoryWeight)
                            .clip(CircleShape)
                            .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.TableCategoryAlpha))
                            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
                        color = visuals.primary,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = AppTypography.chip.weight,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                    )
                }
            },
            action = { amountModifier, _ ->
                LedgerAmountOrPending(
                    amountCents = expense.amountCents,
                    display = CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey),
                    modifier = amountModifier,
                )
            },
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.34f))
    }
}

@Composable
private fun LedgerAmountOrPending(
    amountCents: Long?,
    display: CurrencyDisplay,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier, contentAlignment = Alignment.CenterEnd) {
        amountCents?.let {
            AppEndAlignedAmountText(
                modifier = Modifier.fillMaxWidth(),
                text = formatDisplayAmount(it, display),
                role = AppAmountRole.Compact,
                color = MaterialTheme.colorScheme.onSurface,
            )
        } ?: AppEndAlignedAmountStatusText(
            modifier = Modifier.fillMaxWidth(),
            text = stringResource(R.string.ledger_item_amount_pending),
            role = AppAmountRole.Compact,
        )
    }
}

/**
 * W2-B: 默认分类从单调首字块升级为语义图标（展示助读，分类文本仍是事实）；
 * 自定义/未知分类回退首字，不为无事实的分类硬造图形。
 */
private val ledgerCategoryIcons: Map<String, ImageVector> = mapOf(
    DefaultExpenseCategories.DINING to Icons.Filled.Restaurant,
    DefaultExpenseCategories.TRANSIT to Icons.Filled.DirectionsBus,
    DefaultExpenseCategories.SHOPPING to Icons.Filled.ShoppingBag,
    DefaultExpenseCategories.ENTERTAINMENT to Icons.Filled.Theaters,
    DefaultExpenseCategories.MEDICAL to Icons.Filled.MedicalServices,
    DefaultExpenseCategories.EDUCATION to Icons.Filled.School,
    DefaultExpenseCategories.HOUSING to Icons.Filled.Home,
    DefaultExpenseCategories.TELECOM to Icons.Filled.Phone,
    DefaultExpenseCategories.AI_SUBSCRIPTION to Icons.Filled.SmartToy,
    DefaultExpenseCategories.DIGITAL to Icons.Filled.Devices,
    DefaultExpenseCategories.GAMES to Icons.Filled.SportsEsports,
    DefaultExpenseCategories.LIFE to Icons.Filled.Weekend,
)

@Composable
private fun LedgerCategoryMark(category: String, density: AppListDensity) {
    val visuals = LocalThemeVisuals.current
    val rowMetrics = AppDensity.rowMetrics(density)
    Box(
        modifier = Modifier
            .size(rowMetrics.markSize)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(visuals.chipSelected.copy(alpha = LedgerItemLayout.CategoryMarkAlpha)),
        contentAlignment = Alignment.Center,
    ) {
        val icon = ledgerCategoryIcons[category]
        if (icon != null) {
            Icon(
                imageVector = icon,
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

private fun Expense.ledgerTimestamp(): String? = expenseTime ?: confirmedAt ?: createdAt

private fun ledgerRowTime(value: String?): String? {
    if (value.isNullOrBlank()) return null
    val formatter = LedgerItemLayout.RowTimeFormatter.withZone(ZoneId.systemDefault())
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrNull()
}
