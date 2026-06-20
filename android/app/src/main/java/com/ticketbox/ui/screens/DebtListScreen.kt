package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
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
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与既有 undo 卡片的定时关闭同一惯例。 */
private const val DebtFlashDismissMillis = 4000L

/**
 * ADR-0049 §2 (slice 8) 欠款列表 + 新建外部欠款 —— Android 生活流，镜像 [IncomePlanScreen]：
 * 列表走 [AppScrollableContent]（in-content 返回按钮 + [AppPageHeader]），反馈走页头位的
 * [AppStatusBanner]，新建入口是页头的 [PrimaryCtaButton] → 底部抽屉表单。方向 / 状态标签复用
 * [DebtGoalLabels] 的 §6 映射（应付 / 应收 / 未结清…），不端内分叉。overlay 自带 [BackHandler]。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebtListScreen(
    viewModel: DebtListViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
    onOpenDebt: (Debt) -> Unit,
) {
    val state by viewModel.state.collectAsState()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(DebtFlashDismissMillis)
        viewModel.dismissFlash()
    }

    // 成功才关抽屉：只在 createDebt() 真正成功(addSucceeded)时收起，失败保留抽屉让 validationError 可见
    // （修「乐观关闭」——旧逻辑在 onSubmit 里按本地 addDraft.isValid 关闭、无视网络结果，且 onClose 的
    // resetDraft() 会抹掉失败错误 → 欠款静默没建）。resetDraft() 一并清掉一次性信号 + 草稿；effect 体
    // 全程非挂起，关闭被打断也不会把 addSucceeded 卡在 true。
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
            DebtListHeader(
                canModify = state.canModify,
                onBack = onBack,
                onAdd = { viewModel.resetDraft(); showAddSheet = true },
            )
        }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        debtListSection(state = state, currency = currency, onOpenDebt = onOpenDebt)
    }

    if (showAddSheet) {
        DebtAddSheet(
            state = state,
            viewModel = viewModel,
            sheetState = sheetState,
            onClose = { showAddSheet = false; viewModel.resetDraft() },
        )
    }
}

@Composable
private fun DebtListHeader(
    canModify: Boolean,
    onBack: () -> Unit,
    onAdd: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.debt_list_topbar_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.debt_list_topbar_back))
        }
        AppPageHeader(
            title = stringResource(R.string.debt_list_topbar_title),
            subtitle = stringResource(R.string.debt_list_intro_body),
        ) {
            if (canModify) {
                PrimaryCtaButton(
                    text = stringResource(R.string.debt_list_add),
                    icon = Icons.Default.Add,
                    onClick = onAdd,
                )
            }
        }
    }
}

private fun LazyListScope.debtListSection(
    state: DebtListUiState,
    currency: CurrencyDisplay,
    onOpenDebt: (Debt) -> Unit,
) {
    if (state.debts.isEmpty() && !state.isLoading) {
        item { DebtEmptyStateCard() }
        return
    }
    // slice 1A: 软分两组 (家人在前)，家人行 communal、外部行会计；各组 active-first 排序。
    val (members, externals) = groupDebtsForList(state.debts)
    if (members.isNotEmpty()) {
        item(key = "debt-section-family") {
            DebtSectionHeader(stringResource(R.string.debt_list_section_family))
        }
        items(members, key = { it.publicId }) { debt ->
            MemberDebtRow(debt = debt, onClick = { onOpenDebt(debt) })
        }
    }
    if (externals.isNotEmpty()) {
        item(key = "debt-section-external") {
            DebtSectionHeader(stringResource(R.string.debt_list_section_external))
        }
        items(externals, key = { it.publicId }) { debt ->
            ExternalDebtRow(debt = debt, currency = currency, onClick = { onOpenDebt(debt) })
        }
    }
}

@Composable
private fun ExternalDebtRow(debt: Debt, currency: CurrencyDisplay, onClick: () -> Unit) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.size(AppSpacing.smallGap))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    DebtStatusBadge(
                        text = stringResource(debtDirectionLabelRes(debt.direction)),
                        tone = LocalStateTokens.current.neutral,
                    )
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    DebtStatusBadge(
                        text = stringResource(debtLinkStatusLabelRes(debt.status)),
                        tone = debtLinkStatusTone(debt.status),
                    )
                }
            }
            Spacer(Modifier.width(AppSpacing.smallGap))
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    formatDisplayAmount(debt.remainingAmountCents, currency),
                    style = MaterialTheme.typography.titleLarge.tabularNum(),
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    stringResource(
                        R.string.debt_list_card_principal,
                        formatDisplayAmount(debt.principalAmountCents, currency),
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun DebtEmptyStateCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                stringResource(R.string.debt_list_empty_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_list_empty_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtAddSheet(
    state: DebtListUiState,
    viewModel: DebtListViewModel,
    sheetState: SheetState,
    onClose: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        DebtDraftForm(
            state = state,
            viewModel = viewModel,
            onSubmit = { viewModel.submitDraft() },
            onCancel = onClose,
        )
    }
}

@Composable
private fun DebtDraftForm(
    state: DebtListUiState,
    viewModel: DebtListViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val draft = state.addDraft
    Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
        Text(
            stringResource(R.string.debt_create_sheet_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.cardPadding))
        Text(
            stringResource(R.string.debt_create_label_direction),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        DebtDirectionChips(selected = draft.direction, onSelect = viewModel::updateDraftDirection)
        Spacer(Modifier.size(AppSpacing.compactGap))
        OutlinedTextField(
            value = draft.counterpartyLabel,
            onValueChange = viewModel::updateDraftCounterparty,
            label = { Text(stringResource(R.string.debt_create_label_counterparty)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))
        OutlinedTextField(
            value = draft.amountYuanInput,
            onValueChange = viewModel::updateDraftAmount,
            label = { Text(stringResource(R.string.debt_create_label_amount)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))
        DebtKindCreateField(selected = draft.kind, onSelect = viewModel::updateDraftKind)
        DebtInstallmentCountField(kind = draft.kind, countInput = draft.installmentCountInput, onValueChange = viewModel::updateDraftInstallmentCount)
        DebtInstallmentPeriodField(kind = draft.kind, periodInput = draft.installmentPeriodInput, onValueChange = viewModel::updateDraftInstallmentPeriod)
        draft.validationError?.let { err ->
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                err.asString(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        Spacer(Modifier.size(AppSpacing.cardPadding))
        HorizontalDivider()
        Spacer(Modifier.size(AppSpacing.compactGap))
        DebtDraftFormActions(isSubmitting = state.isSubmitting, onSubmit = onSubmit, onCancel = onCancel)
        Spacer(Modifier.size(AppSpacing.compactGap))
    }
}

@Composable
private fun DebtDirectionChips(selected: String, onSelect: (String) -> Unit) {
    Row(modifier = Modifier.fillMaxWidth()) {
        listOf(DebtDirections.I_OWE, DebtDirections.OWED_TO_ME).forEach { direction ->
            FilterChip(
                selected = selected == direction,
                onClick = { onSelect(direction) },
                label = { Text(stringResource(debtDirectionLabelRes(direction))) },
                modifier = Modifier.padding(end = AppSpacing.smallGap),
            )
        }
    }
}

@Composable
private fun DebtDraftFormActions(
    isSubmitting: Boolean,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        TextButton(onClick = onCancel) { Text(stringResource(R.string.common_cancel)) }
        Spacer(Modifier.width(AppSpacing.smallGap))
        Button(onClick = onSubmit, enabled = !isSubmitting) {
            Text(
                if (isSubmitting) {
                    stringResource(R.string.debt_create_submitting)
                } else {
                    stringResource(R.string.debt_create_save)
                },
            )
        }
    }
}
