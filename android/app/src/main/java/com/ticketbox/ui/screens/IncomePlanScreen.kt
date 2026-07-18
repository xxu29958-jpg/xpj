package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
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
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.AppFormFieldGroup
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
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
    var showEditorSheet by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val bodyState = incomePlanBodyState(
        loadState = state.loadState,
        activeCount = state.activePlans.size,
        archivedCount = state.archivedPlans.size,
    )

    // 成功提示在页头横幅展示数秒后自动收起；error 由下一次 refresh 清掉，与既有语义一致。
    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(FlashDismissMillis)
        viewModel.dismissFlash()
    }

    // Create and edit both close only after the repository confirms synced or durably queued.
    // Failures leave the editor open with the submitted values and inline error intact.
    LaunchedEffect(state.addSucceeded, state.editSucceeded) {
        if (!state.addSucceeded && !state.editSucceeded) return@LaunchedEffect
        showEditorSheet = false
        viewModel.resetDraft()
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.income_plan_topbar_title),
            subtitle = stringResource(R.string.income_plan_header_subtitle_compact),
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
                        text = stringResource(R.string.income_plan_add_action_short),
                        leadingIcon = Icons.Default.Add,
                        onClick = {
                            viewModel.resetDraft()
                            showEditorSheet = true
                        },
                    )
                }
            },
        ),
    ) {
        // 反馈横幅落在页头下方（/web flash 同位）：只在有消息时占位，避免空 item
        // 在 spacedBy 下留出幽灵间距。flashMessage→Success / error→Danger。
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = state.flashTone) }
        }
        if (!state.canModify) {
            item {
                AppStatusBanner(
                    message = UiText.res(R.string.common_readonly_ledger),
                    tone = MessageTone.Info,
                    announceUpdates = false,
                )
            }
        }
        incomePlanInlineMessage(bodyState = bodyState, message = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        if (incomePlanShowsSummary(bodyState)) {
            item {
                IncomeTotalSummary(
                    totalCents = state.currentMonthSummary.expectedAmountCents,
                    effectiveCount = state.currentMonthSummary.effectivePlanCount,
                    historicalRecordCount = state.currentMonthSummary.historicalRecordCount,
                    currency = currency,
                )
            }
        }
        when (bodyState) {
            IncomePlanBodyState.Loading,
            IncomePlanBodyState.LoadFailed -> item {
                IncomePlanBodyStateSlot(
                    bodyState = bodyState,
                    error = state.error,
                    onRetry = viewModel::refresh,
                )
            }
            IncomePlanBodyState.Empty,
            IncomePlanBodyState.Content -> incomePlanSections(
                state = state,
                currency = currency,
                viewModel = viewModel,
                onEdit = { plan ->
                    if (viewModel.beginEdit(plan)) {
                        showEditorSheet = true
                    }
                },
            )
        }
    }

    if (showEditorSheet) {
        ModalBottomSheet(
            onDismissRequest = {
                showEditorSheet = false
                viewModel.resetDraft()
            },
            sheetState = sheetState,
        ) {
            AddIncomePlanSheet(
                state = state,
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
                        showEditorSheet = false
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
    onEdit: (IncomePlan) -> Unit,
) {
    item(key = "income-plan-active") {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = state.activePlans.isEmpty(),
                loading = state.isLoading,
                emptyText = stringResource(R.string.income_plan_empty_body_compact),
                emptyTitle = stringResource(R.string.income_plan_empty_title),
                emptyBody = stringResource(R.string.income_plan_empty_body_compact),
            ),
        ) {
            SectionEyebrow(stringResource(R.string.income_plan_section_active))
            state.activePlans.forEach { plan ->
                IncomePlanRow(
                    plan = plan,
                    currency = currency,
                    canModify = state.canModify,
                    actions = listOf(
                        IncomePlanRowAction(
                            icon = Icons.Outlined.Edit,
                            description = stringResource(R.string.income_plan_card_edit_action),
                            onClick = { onEdit(plan) },
                        ),
                        IncomePlanRowAction(
                            icon = Icons.Outlined.Archive,
                            description = stringResource(R.string.income_plan_card_archive_action),
                            onClick = { viewModel.setArchived(plan.publicId, plan.rowVersion, archived = true) },
                        ),
                    ),
                )
            }
        }
    }

    if (state.archivedPlans.isNotEmpty()) {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_archived)) }
        items(state.archivedPlans, key = { "archived-${it.publicId}" }) { plan ->
            IncomePlanRow(
                plan = plan,
                currency = currency,
                canModify = state.canModify,
                actions = listOf(
                    IncomePlanRowAction(
                        icon = Icons.Default.Restore,
                        description = stringResource(R.string.income_plan_card_restore_action),
                        onClick = { viewModel.setArchived(plan.publicId, plan.rowVersion, archived = false) },
                    ),
                ),
                dimmed = true,
            )
        }
    }
}

@Composable
private fun IncomePlanBodyStateSlot(
    bodyState: IncomePlanBodyState,
    error: UiText?,
    onRetry: () -> Unit,
) {
    when (bodyState) {
        IncomePlanBodyState.Loading -> AppContentStateSlot(
            state = AppContentStateSpec(
                loading = true,
                hasData = false,
                copy = AppContentStateCopy(
                    loadingTitle = stringResource(R.string.income_plan_loading_title),
                    loadingBody = stringResource(R.string.income_plan_loading_body),
                    emptyText = stringResource(R.string.income_plan_empty_body_compact),
                ),
                presentation = AppContentStatePresentation.Card,
            ),
        )
        IncomePlanBodyState.LoadFailed -> AppErrorState(
            title = error?.asString() ?: stringResource(R.string.income_plan_load_failed),
            body = stringResource(R.string.income_plan_load_failed_hint),
            onRetry = onRetry,
        )
        IncomePlanBodyState.Empty,
        IncomePlanBodyState.Content -> Unit
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
private fun IncomeTotalSummary(
    totalCents: Long,
    effectiveCount: Int,
    historicalRecordCount: Int,
    currency: CurrencyDisplay,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            stringResource(R.string.income_plan_total_label_compact),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            formatDisplayAmount(totalCents, currency),
            style = MaterialTheme.typography.headlineLarge.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(
                R.string.income_plan_total_meta,
                effectiveCount,
                historicalRecordCount,
            ),
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
    actions: List<IncomePlanRowAction>,
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
                actions.forEach { action ->
                    IconButton(onClick = action.onClick) {
                        Icon(action.icon, contentDescription = action.description)
                    }
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
private fun AddIncomePlanSheet(
    state: IncomePlanUiState,
    actions: AddIncomePlanSheetActions,
) {
    val draft = state.addDraft
    val isEditing = state.editingPlan != null
    AppSheetScaffold(
        title = stringResource(
            if (isEditing) R.string.income_plan_sheet_edit_title
            else R.string.income_plan_sheet_title,
        ),
    ) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.income_plan_sheet_label_name),
                value = draft.label,
                placeholder = stringResource(R.string.income_plan_sheet_name_placeholder),
                enabled = !state.isSubmitting,
            ),
            actions = AppTextInputActions(onValueChange = actions.onLabel),
            modifier = Modifier.fillMaxWidth(),
        )

        AppFormFieldGroup(label = stringResource(R.string.income_plan_sheet_label_type)) {
            AppCompactChips {
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    IncomeSourceType.entries.forEach { source ->
                        AppFilterChip(
                            selected = draft.sourceType == source,
                            onClick = { actions.onSourceType(source) },
                            label = stringResource(incomeSourceTypeLabelRes(source)),
                            options = AppFilterChipOptions(enabled = !state.isSubmitting),
                        )
                    }
                }
            }
        }

        AppFormFieldGroup(label = stringResource(R.string.income_plan_sheet_label_frequency)) {
            AppCompactChips {
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    listOf(IncomeFrequency.ONE_TIME, IncomeFrequency.MONTHLY).forEach { frequency ->
                        AppFilterChip(
                            selected = draft.frequency == frequency,
                            onClick = { actions.onFrequency(frequency) },
                            label = stringResource(incomeFrequencyLabelRes(frequency)),
                            options = AppFilterChipOptions(enabled = !state.isSubmitting),
                        )
                    }
                }
            }
        }

        if (draft.frequency == IncomeFrequency.ONE_TIME) {
            AppFormFieldGroup(label = stringResource(R.string.income_plan_sheet_label_income_month)) {
                IncomeMonthPicker(
                    value = draft.incomeMonthInput,
                    onPrevious = actions.onPreviousIncomeMonth,
                    onNext = actions.onNextIncomeMonth,
                )
            }
        }

        AppAmountInput(
            state = AppAmountInputState(
                label = if (draft.frequency == IncomeFrequency.ONE_TIME) {
                    stringResource(
                        R.string.income_plan_sheet_label_amount_one_time,
                        draft.homeCurrency.storageKey,
                    )
                } else {
                    stringResource(
                        R.string.income_plan_sheet_label_amount_monthly,
                        draft.homeCurrency.storageKey,
                    )
                },
                currency = draft.homeCurrency,
                value = draft.amountYuanInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !state.isSubmitting,
                isError = draft.validationError != null,
            ),
            actions = AppAmountInputActions(
                onValueChange = actions.onAmount,
            ),
        )

        AppTextInput(
            state = AppTextInputState(
                label = if (draft.frequency == IncomeFrequency.ONE_TIME) {
                    stringResource(R.string.income_plan_sheet_label_arrival_day)
                } else {
                    stringResource(R.string.income_plan_sheet_label_payday)
                },
                value = draft.payDayInput,
                placeholder = stringResource(R.string.income_plan_sheet_day_placeholder),
                enabled = !state.isSubmitting,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            ),
            actions = AppTextInputActions(onValueChange = actions.onPayDay),
            modifier = Modifier.fillMaxWidth(),
        )

        if (draft.validationError != null) {
            Text(
                draft.validationError.asString(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        AppSheetActionRow(
            primary = AppAction(
                text = if (state.isSubmitting) {
                    stringResource(
                        if (isEditing) R.string.income_plan_sheet_updating
                        else R.string.income_plan_sheet_submitting,
                    )
                } else {
                    stringResource(
                        if (isEditing) R.string.income_plan_sheet_update
                        else R.string.income_plan_sheet_save,
                    )
                },
                onClick = actions.onSubmit,
                enabled = incomePlanSubmitEnabled(state),
            ),
            secondary = AppAction(
                text = stringResource(R.string.common_cancel),
                onClick = actions.onCancel,
                enabled = !state.isSubmitting,
            ),
        )
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
