package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.updateDraftAmount
import com.ticketbox.viewmodel.updateDraftLabel
import com.ticketbox.viewmodel.updateDraftPayDay
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与既有 undo 卡片的定时关闭同一惯例。 */
private const val FlashDismissMillis = 4000L

private data class IncomePlanRowAction(
    val icon: ImageVector,
    val description: String,
    val onClick: () -> Unit,
)

private data class AddIncomePlanSheetActions(
    val onLabel: (String) -> Unit,
    val onSourceType: (IncomeSourceType) -> Unit,
    val onFrequency: (IncomeFrequency) -> Unit,
    val onPreviousIncomeMonth: () -> Unit,
    val onNextIncomeMonth: () -> Unit,
    val onAmount: (String) -> Unit,
    val onPayDay: (String) -> Unit,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IncomePlanScreen(
    viewModel: IncomePlanViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    // 成功提示在页头横幅展示数秒后自动收起；error 由下一次 refresh 清掉，与既有语义一致。
    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(FlashDismissMillis)
        viewModel.dismissFlash()
    }

    // 成功才关抽屉：只在 create() 真正成功(addSucceeded)时收起，失败保留抽屉让 validationError 可见
    // （修「乐观关闭」——旧逻辑在 onSubmit 里按本地 addDraft.isValid 关闭、无视网络结果）。resetDraft()
    // 一并清掉一次性信号 + 草稿；effect 体全程非挂起，关闭被打断也不会把 addSucceeded 卡在 true。
    LaunchedEffect(state.addSucceeded) {
        if (!state.addSucceeded) return@LaunchedEffect
        showAddSheet = false
        viewModel.resetDraft()
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.income_plan_topbar_title),
            subtitle = stringResource(R.string.income_plan_intro_body),
            backText = stringResource(R.string.income_plan_topbar_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.activePlans.isNotEmpty() || state.archivedPlans.isNotEmpty(),
            ),
            onRefresh = viewModel::refresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = {
                if (state.canModify) {
                    AppSecondaryButton(
                        text = stringResource(R.string.income_plan_fab_add),
                        leadingIcon = Icons.Default.Add,
                        onClick = {
                            viewModel.resetDraft()
                            showAddSheet = true
                        },
                    )
                }
            },
        ),
    ) {
        // 反馈横幅落在页头下方（/web flash 同位）：只在有消息时占位，避免空 item
        // 在 spacedBy 下留出幽灵间距。flashMessage→Success / error→Danger。
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        item {
            IncomeTotalSummary(totalCents = state.totalActiveAmountCents, currency = currency)
        }
        incomePlanSections(state = state, currency = currency, viewModel = viewModel)
    }

    if (showAddSheet) {
        ModalBottomSheet(
            onDismissRequest = {
                showAddSheet = false
                viewModel.resetDraft()
            },
            sheetState = sheetState,
        ) {
            AddIncomePlanSheet(
                state = state,
                currency = currency,
                actions = AddIncomePlanSheetActions(
                    onLabel = viewModel::updateDraftLabel,
                    onSourceType = viewModel::updateDraftSource,
                    onFrequency = viewModel::updateDraftFrequency,
                    onPreviousIncomeMonth = { viewModel.shiftDraftIncomeMonth(-1L) },
                    onNextIncomeMonth = { viewModel.shiftDraftIncomeMonth(1L) },
                    onAmount = viewModel::updateDraftAmount,
                    onPayDay = viewModel::updateDraftPayDay,
                    onSubmit = { viewModel.submitDraft() },
                    onCancel = {
                        showAddSheet = false
                        viewModel.resetDraft()
                    },
                ),
            )
        }
    }
}

@Composable
private fun IncomeMonthPicker(
    value: String,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
) {
    Text(
        stringResource(R.string.income_plan_sheet_label_income_month),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.size(AppSpacing.miniGap))
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        IconButton(onClick = onPrevious) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = stringResource(R.string.income_plan_month_previous),
            )
        }
        Text(
            text = displayMonthLabel(value),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onNext) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = stringResource(R.string.income_plan_month_next),
            )
        }
    }
}

private fun LazyListScope.incomePlanSections(
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    viewModel: IncomePlanViewModel,
) {
    if (state.activePlans.isEmpty() && !state.isLoading) {
        item { IncomePlanEmptyState() }
    } else {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_active)) }
        items(state.activePlans, key = { "active-${it.publicId}" }) { plan ->
            IncomePlanRow(
                plan = plan,
                currency = currency,
                canModify = state.canModify,
                action = IncomePlanRowAction(
                    icon = Icons.Default.DeleteOutline,
                    description = stringResource(R.string.income_plan_card_archive_action),
                    onClick = { viewModel.archive(plan.publicId, plan.rowVersion) },
                ),
            )
        }
    }

    if (state.archivedPlans.isNotEmpty()) {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_archived)) }
        items(state.archivedPlans, key = { "archived-${it.publicId}" }) { plan ->
            IncomePlanRow(
                plan = plan,
                currency = currency,
                canModify = state.canModify,
                action = IncomePlanRowAction(
                    icon = Icons.Default.Restore,
                    description = stringResource(R.string.income_plan_card_restore_action),
                    onClick = { viewModel.restore(plan.publicId, plan.rowVersion) },
                ),
                dimmed = true,
            )
        }
    }
}

@Composable
private fun SectionEyebrow(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = AppSpacing.smallGap),
    )
}

@Composable
private fun IncomeTotalSummary(totalCents: Long, currency: CurrencyDisplay) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            stringResource(R.string.income_plan_total_label),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            formatDisplayAmount(totalCents, currency),
            style = MaterialTheme.typography.displaySmall.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(R.string.income_plan_total_hint),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.compactGap))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun IncomePlanRow(
    plan: IncomePlan,
    currency: CurrencyDisplay,
    canModify: Boolean,
    action: IncomePlanRowAction,
    dimmed: Boolean = false,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IncomePlanRowSummary(plan = plan, dimmed = dimmed, modifier = Modifier.weight(1f))
            Text(
                formatDisplayAmount(plan.amountCents, currency),
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = FontWeight.SemiBold,
                color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.End,
            )
            if (canModify) {
                Spacer(Modifier.width(AppSpacing.smallGap))
                IconButton(onClick = action.onClick) {
                    Icon(action.icon, contentDescription = action.description)
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun IncomePlanRowSummary(
    plan: IncomePlan,
    dimmed: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        Text(
            plan.label,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
            else MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(incomeSourceTypeLabelRes(plan.sourceType)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                if (plan.frequency == IncomeFrequency.ONE_TIME) {
                    stringResource(
                        R.string.income_plan_card_one_time_day,
                        displayMonthLabel(plan.incomeMonth.orEmpty()),
                        plan.payDay,
                    )
                } else {
                    stringResource(R.string.income_plan_card_payday, plan.payDay)
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun IncomePlanEmptyState() {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            stringResource(R.string.income_plan_empty_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.smallGap))
        Text(
            stringResource(R.string.income_plan_empty_body),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.compactGap))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun AddIncomePlanSheet(
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    actions: AddIncomePlanSheetActions,
) {
    val draft = state.addDraft
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(AppSpacing.cardPadding),
    ) {
        Text(
            stringResource(R.string.income_plan_sheet_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.cardPadding))

        OutlinedTextField(
            value = draft.label,
            onValueChange = actions.onLabel,
            label = { Text(stringResource(R.string.income_plan_sheet_label_name)) },
            singleLine = true,
            enabled = !state.isSubmitting,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        Text(
            stringResource(R.string.income_plan_sheet_label_type),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        LazyRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            IncomeSourceType.entries.forEach { source ->
                item(source.wireValue) {
                    AppFilterChip(
                        selected = draft.sourceType == source,
                        onClick = { actions.onSourceType(source) },
                        label = stringResource(incomeSourceTypeLabelRes(source)),
                        enabled = !state.isSubmitting,
                    )
                }
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))

        Text(
            stringResource(R.string.income_plan_sheet_label_frequency),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        LazyRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            listOf(IncomeFrequency.ONE_TIME, IncomeFrequency.MONTHLY).forEach { frequency ->
                item(frequency.wireValue) {
                    AppFilterChip(
                        selected = draft.frequency == frequency,
                        onClick = { actions.onFrequency(frequency) },
                        label = stringResource(incomeFrequencyLabelRes(frequency)),
                        enabled = !state.isSubmitting,
                    )
                }
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))

        if (draft.frequency == IncomeFrequency.ONE_TIME) {
            IncomeMonthPicker(
                value = draft.incomeMonthInput,
                onPrevious = actions.onPreviousIncomeMonth,
                onNext = actions.onNextIncomeMonth,
            )
            Spacer(Modifier.size(AppSpacing.compactGap))
        }

        AppAmountInput(
            state = AppAmountInputState(
                label = if (draft.frequency == IncomeFrequency.ONE_TIME) {
                    stringResource(R.string.income_plan_sheet_label_amount_one_time)
                } else {
                    stringResource(R.string.income_plan_sheet_label_amount_monthly)
                },
                currency = currency.homeCurrency,
                value = draft.amountYuanInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !state.isSubmitting,
                isError = draft.validationError != null,
            ),
            actions = AppAmountInputActions(
                onValueChange = actions.onAmount,
            ),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        OutlinedTextField(
            value = draft.payDayInput,
            onValueChange = actions.onPayDay,
            label = {
                Text(
                    if (draft.frequency == IncomeFrequency.ONE_TIME) {
                        stringResource(R.string.income_plan_sheet_label_arrival_day)
                    } else {
                        stringResource(R.string.income_plan_sheet_label_payday)
                    },
                )
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            enabled = !state.isSubmitting,
            modifier = Modifier.fillMaxWidth(),
        )

        if (draft.validationError != null) {
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                draft.validationError.asString(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Spacer(Modifier.size(AppSpacing.cardPadding))
        HorizontalDivider()
        Spacer(Modifier.size(AppSpacing.compactGap))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            AppSecondaryButton(
                text = stringResource(R.string.common_cancel),
                modifier = Modifier.weight(1f),
                enabled = !state.isSubmitting,
                onClick = actions.onCancel,
            )
            Button(
                modifier = Modifier.weight(1f),
                onClick = actions.onSubmit,
                enabled = !state.isSubmitting,
            ) {
                Text(
                    if (state.isSubmitting) {
                        stringResource(R.string.income_plan_sheet_submitting)
                    } else {
                        stringResource(R.string.income_plan_sheet_save)
                    },
                )
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))
    }
}

@StringRes
private fun incomeSourceTypeLabelRes(source: IncomeSourceType): Int =
    when (source) {
        IncomeSourceType.SALARY -> R.string.income_plan_source_salary
        IncomeSourceType.BONUS -> R.string.income_plan_source_bonus
        IncomeSourceType.FREELANCE -> R.string.income_plan_source_freelance
        IncomeSourceType.RENTAL -> R.string.income_plan_source_rental
        IncomeSourceType.OTHER -> R.string.income_plan_source_other
    }

@StringRes
private fun incomeFrequencyLabelRes(frequency: IncomeFrequency): Int =
    when (frequency) {
        IncomeFrequency.MONTHLY -> R.string.income_plan_frequency_monthly
        IncomeFrequency.ONE_TIME -> R.string.income_plan_frequency_one_time
    }
