package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.mascot.MascotEmptyIllustration
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.IncomePlanViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与既有 undo 卡片的定时关闭同一惯例。 */
private const val FlashDismissMillis = 4000L

/**
 * v1.1 收入计划 — Android 生活流：KPI 卡 → 卡片列 → 页头 CTA → 底部抽屉添加。
 *
 * 收口回共享骨架：列表与下拉刷新走 [AppScrollableContent]（与 BillSplitScreen /
 * RecurringScreen 同形态——in-content 返回按钮 + [AppPageHeader]），反馈走页头位的
 * [AppStatusBanner]（flashMessage→Success / error→Danger），添加入口收编到页头的
 * [PrimaryCtaButton]。不照搬 /web 的"表 + form"，按移动端单手操作模式：每条收入是
 * 一个卡片，添加进底部抽屉。共享 design token 通过 MaterialTheme + AppSpacing +
 * AppGlassCard（参考 [[feedback_three_surface_visual_sync]]：token 同步是硬约束；
 * layout 按端特点自决）。
 */
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

    BackHandler(onBack = onBack)

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        onRefresh = viewModel::refresh,
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            IncomePlanHeader(
                canModify = state.canModify,
                onBack = onBack,
                onAdd = {
                    viewModel.resetDraft()
                    showAddSheet = true
                },
            )
        }
        // 反馈横幅落在页头下方（/web flash 同位）：只在有消息时占位，避免空 item
        // 在 spacedBy 下留出幽灵间距。flashMessage→Success / error→Danger。
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        item {
            IncomeTotalCard(totalCents = state.totalActiveAmountCents, currency = currency)
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
                onLabel = viewModel::updateDraftLabel,
                onSourceType = viewModel::updateDraftSource,
                onAmount = viewModel::updateDraftAmount,
                onPayDay = viewModel::updateDraftPayDay,
                onSubmit = { viewModel.submitDraft() },
                onCancel = {
                    showAddSheet = false
                    viewModel.resetDraft()
                },
            )
        }
    }
}

@Composable
private fun IncomePlanHeader(
    canModify: Boolean,
    onBack: () -> Unit,
    onAdd: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.income_plan_topbar_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.income_plan_topbar_back))
        }
        AppPageHeader(
            title = stringResource(R.string.income_plan_topbar_title),
            subtitle = stringResource(R.string.income_plan_intro_body),
        ) {
            if (canModify) {
                PrimaryCtaButton(
                    text = stringResource(R.string.income_plan_fab_add),
                    icon = Icons.Default.Add,
                    onClick = onAdd,
                )
            }
        }
    }
}

/**
 * 在用 / 已归档两组计划，挂进骨架（[AppScrollableContent]）提供的列表：每条计划是
 * 一个独立 item，避免把整组塞进单个 item 造成嵌套过深；空态（无在用计划且加载完）
 * 渲染引导卡片。
 */
private fun LazyListScope.incomePlanSections(
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    viewModel: IncomePlanViewModel,
) {
    if (state.activePlans.isEmpty() && !state.isLoading) {
        item { EmptyStateCard() }
    } else {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_active)) }
        items(state.activePlans, key = { "active-${it.publicId}" }) { plan ->
            IncomePlanCard(
                plan = plan,
                currency = currency,
                canModify = state.canModify,
                trailingIcon = Icons.Default.DeleteOutline,
                trailingDescription = stringResource(R.string.income_plan_card_archive_action),
                onTrailing = { viewModel.archive(plan.publicId, plan.rowVersion) },
            )
        }
    }

    if (state.archivedPlans.isNotEmpty()) {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_archived)) }
        items(state.archivedPlans, key = { "archived-${it.publicId}" }) { plan ->
            IncomePlanCard(
                plan = plan,
                currency = currency,
                canModify = state.canModify,
                trailingIcon = Icons.Default.Restore,
                trailingDescription = stringResource(R.string.income_plan_card_restore_action),
                onTrailing = { viewModel.restore(plan.publicId, plan.rowVersion) },
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
private fun IncomeTotalCard(totalCents: Long, currency: CurrencyDisplay) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
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
        }
    }
}

@Composable
private fun IncomePlanCard(
    plan: IncomePlan,
    currency: CurrencyDisplay,
    canModify: Boolean,
    trailingIcon: ImageVector,
    trailingDescription: String,
    onTrailing: () -> Unit,
    dimmed: Boolean = false,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    plan.label,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.size(AppSpacing.miniGap))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        plan.sourceType.displayName,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Box(
                        modifier = Modifier
                            .size(width = 1.dp, height = 12.dp)
                            .background(MaterialTheme.colorScheme.outlineVariant),
                    )
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Text(
                        stringResource(R.string.income_plan_card_payday, plan.payDay),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Text(
                formatDisplayAmount(plan.amountCents, currency),
                style = MaterialTheme.typography.titleLarge.tabularNum(),
                fontWeight = FontWeight.SemiBold,
                color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
            )
            if (canModify) {
                Spacer(Modifier.width(AppSpacing.smallGap))
                IconButton(onClick = onTrailing) {
                    Icon(trailingIcon, contentDescription = trailingDescription)
                }
            }
        }
    }
}

@Composable
private fun EmptyStateCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            MascotEmptyIllustration()
            Spacer(Modifier.size(AppSpacing.smallGap))
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
        }
    }
}

@Composable
private fun AddIncomePlanSheet(
    state: IncomePlanUiState,
    onLabel: (String) -> Unit,
    onSourceType: (IncomeSourceType) -> Unit,
    onAmount: (String) -> Unit,
    onPayDay: (String) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
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
            onValueChange = onLabel,
            label = { Text(stringResource(R.string.income_plan_sheet_label_name)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        Text(
            stringResource(R.string.income_plan_sheet_label_type),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Row(modifier = Modifier.fillMaxWidth()) {
            IncomeSourceType.entries.forEach { source ->
                FilterChip(
                    selected = draft.sourceType == source,
                    onClick = { onSourceType(source) },
                    label = { Text(source.displayName) },
                    modifier = Modifier.padding(end = AppSpacing.miniGap),
                )
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))

        OutlinedTextField(
            value = draft.amountYuanInput,
            onValueChange = onAmount,
            label = { Text(stringResource(R.string.income_plan_sheet_label_amount)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        OutlinedTextField(
            value = draft.payDayInput,
            onValueChange = onPayDay,
            label = { Text(stringResource(R.string.income_plan_sheet_label_payday)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
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
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = onCancel) { Text(stringResource(R.string.common_cancel)) }
            Spacer(Modifier.width(AppSpacing.smallGap))
            Button(
                onClick = onSubmit,
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
