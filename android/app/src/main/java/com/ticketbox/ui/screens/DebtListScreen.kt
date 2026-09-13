package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与既有 undo 卡片的定时关闭同一惯例。 */
internal const val DebtFlashDismissMillis = 4000L

data class DebtListScreenActions(
    val onBack: () -> Unit,
    val onOpenDebt: (Debt) -> Unit,
    val onParseBillImage: () -> Unit,
    val onOpenSyncStatus: () -> Unit,
)

private data class DebtListScreenCallbacks(
    val onBack: () -> Unit,
    val onOpenDebt: (Debt) -> Unit,
    val onParseBillImage: () -> Unit,
    val onRefresh: () -> Unit,
    val onAddDebt: () -> Unit,
    val onOpenSyncStatus: () -> Unit,
)
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebtListScreen(
    viewModel: DebtListViewModel,
    actions: DebtListScreenActions,
    chromeOverride: RelationsListChrome? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }
    val saving by rememberUpdatedState(state.isSubmitting)
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = true,
        confirmValueChange = { it != SheetValue.Hidden || !saving },
    )

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(DebtFlashDismissMillis)
        viewModel.dismissFlash()
    }

    // Close only after Room acknowledges the intent. A failed local save keeps the form and error visible.
    LaunchedEffect(state.addAccepted) {
        if (!state.addAccepted) return@LaunchedEffect
        showAddSheet = false
        viewModel.resetDraft()
    }
    LaunchedEffect(state.pendingBillParsePrefill) {
        if (!state.pendingBillParsePrefill) return@LaunchedEffect
        showAddSheet = true
        viewModel.ackBillParsePrefill()
    }

    val callbacks = DebtListScreenCallbacks(
        onBack = actions.onBack,
        onOpenDebt = actions.onOpenDebt,
        onParseBillImage = actions.onParseBillImage,
        onOpenSyncStatus = actions.onOpenSyncStatus,
        onRefresh = viewModel::refresh,
        onAddDebt = {
            viewModel.resetDraft()
            showAddSheet = true
        },
    )
    DebtListContent(
        state = state,
        callbacks = callbacks,
        chromeOverride = chromeOverride,
    )
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
private fun DebtListContent(
    state: DebtListUiState,
    callbacks: DebtListScreenCallbacks,
    chromeOverride: RelationsListChrome?,
) {
    val resolvedChrome = chromeOverride ?: RelationsListChrome(
        title = stringResource(R.string.debt_list_topbar_title),
        subtitle = stringResource(R.string.debt_list_intro_body),
        backText = stringResource(R.string.debt_list_topbar_back),
        onBack = callbacks.onBack,
    )
    if (resolvedChrome.embeddedInDomain) {
        DebtListEmbeddedContent(state = state, chrome = resolvedChrome, callbacks = callbacks)
        return
    }
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = resolvedChrome.title,
            subtitle = resolvedChrome.subtitle,
            backText = resolvedChrome.backText,
            onBack = resolvedChrome.onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.debts.isNotEmpty(),
            ),
            onRefresh = callbacks.onRefresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = if (state.canModify) {
                {
                    DebtListHeaderActions(
                        isParsingBill = state.isParsingBill,
                        onParseBillImage = callbacks.onParseBillImage,
                        onAddDebt = callbacks.onAddDebt,
                    )
                }
            } else {
                null
            },
        ),
    ) {
        resolvedChrome.domainNavigation?.let { navigation ->
            item(key = "obligations-domain-navigation") { navigation() }
        }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Info) }
        }
        if (state.pendingCreations.isNotEmpty()) {
            item(key = "debt-pending-creations") {
                DebtPendingCreations(state.pendingCreations, callbacks.onOpenSyncStatus)
            }
        }
        readableListInlineError(hasRows = state.debts.isNotEmpty(), error = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        debtListSection(state = state, onOpenDebt = callbacks.onOpenDebt)
    }
}

/**
 * W2-C 主域嵌入态：shell 已有域名——无大标题/头部动作；首项是 RelationsRoute 的
 * tabs+单主 CTA（topChrome），导航区沉到列表尾，真实欠款内容占上半屏。
 */
@Composable
private fun DebtListEmbeddedContent(
    state: DebtListUiState,
    chrome: RelationsListChrome,
    callbacks: DebtListScreenCallbacks,
) {
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Ledger,
            layout = AppScrollableContentLayout(
                hasBottomBar = false,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
            ),
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.debts.isNotEmpty(),
            ),
            onRefresh = callbacks.onRefresh,
        ),
    ) {
        chrome.topChrome?.let { top ->
            item(key = "obligations-top-chrome") { top() }
        }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Info) }
        }
        readableListInlineError(hasRows = state.debts.isNotEmpty(), error = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        debtListSection(state = state, onOpenDebt = callbacks.onOpenDebt)
        chrome.domainNavigation?.let { navigation ->
            item(key = "obligations-domain-navigation") { navigation() }
        }
    }
}

/** 二级页头部动作：单主 CTA「记一笔欠款」+ OCR 安静图标入口（不再两颗整行大按钮上下堆挤）。 */
@Composable
private fun DebtListHeaderActions(
    isParsingBill: Boolean,
    onParseBillImage: () -> Unit,
    onAddDebt: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        PrimaryCtaButton(
            text = stringResource(R.string.debt_list_add),
            icon = Icons.Default.Add,
            modifier = Modifier.weight(1f),
            enabled = !isParsingBill,
            onClick = onAddDebt,
        )
        DebtBillParseIconButton(isParsingBill = isParsingBill, onClick = onParseBillImage)
    }
}

/**
 * 「识别还款账单」的安静图标入口（主列表 chrome 与二级页头部共用）：busy 时禁用并把反馈收在
 * 控件内（小型进度指示替代图标），不与主 CTA 争视觉。图形沿用产品既有 ReceiptLong 票据语言。
 */
@Composable
internal fun DebtBillParseIconButton(isParsingBill: Boolean, onClick: () -> Unit) {
    val description = stringResource(
        if (isParsingBill) R.string.debt_list_parse_bill_busy else R.string.debt_list_parse_bill,
    )
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(role = Role.Button, enabled = !isParsingBill, onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        if (isParsingBill) {
            CircularProgressIndicator(modifier = Modifier.size(AppIconSize.standard), strokeWidth = 2.dp)
        } else {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ReceiptLong,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(AppIconSize.standard),
            )
        }
    }
}
private fun LazyListScope.debtListSection(
    state: DebtListUiState,
    onOpenDebt: (Debt) -> Unit,
) {
    when (
        readableListBodyState(
            hasRows = state.debts.isNotEmpty(),
            isLoading = state.isLoading,
            error = state.error,
        )
    ) {
        ReadableListBodyState.Loading -> item(key = "debt-list-loading") {
            DebtListNoRowsStateSection(loading = true, lens = state.lens, canModify = state.canModify)
        }
        ReadableListBodyState.LoadFailed -> item(key = "debt-list-error") {
            state.error?.let { DebtListLoadFailedSection(error = it) }
        }
        ReadableListBodyState.Empty -> item(key = "debt-list-empty") {
            if (state.pendingCreations.isEmpty()) {
                DebtListNoRowsStateSection(loading = false, lens = state.lens, canModify = state.canModify)
            } else {
                Text(stringResource(R.string.debt_create_no_synced_records), style = MaterialTheme.typography.bodyMedium)
            }
        }
        ReadableListBodyState.Content -> debtRowsSection(
            debts = state.debts,
            onOpenDebt = onOpenDebt,
        )
    }
}

internal fun LazyListScope.debtRowsSection(
    debts: List<Debt>,
    onOpenDebt: (Debt) -> Unit,
) {
    val (members, externals) = groupDebtsForList(debts)
    // Keep family debts and external debts in separate scan groups.
    if (members.isNotEmpty()) {
        item(key = "debt-section-family") {
            AppSectionGroup(
                contentPadding = PaddingValues(vertical = AppSpacing.compactGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                DebtSectionHeader(stringResource(R.string.debt_list_section_family))
                members.forEachIndexed { index, debt ->
                    MemberDebtRow(
                        debt = debt,
                        onClick = { onOpenDebt(debt) },
                        showDivider = index < members.lastIndex,
                    )
                }
            }
        }
    }
    if (externals.isNotEmpty()) {
        item(key = "debt-section-external") {
            AppSectionGroup(
                contentPadding = PaddingValues(vertical = AppSpacing.compactGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                showTopDivider = members.isEmpty(),
            ) {
                DebtSectionHeader(stringResource(R.string.debt_list_section_external))
                externals.forEachIndexed { index, debt ->
                    ExternalDebtRow(
                        debt = debt,
                        onClick = { onOpenDebt(debt) },
                        showDivider = index < externals.lastIndex,
                    )
                }
            }
        }
    }
}

@Composable
private fun ExternalDebtRow(
    debt: Debt,
    onClick: () -> Unit,
    showDivider: Boolean,
) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    // 行内金额按 record 自带 homeCurrencyCode 渲染（PR#255 R5 P2）：屏级环境 display 恒
    // Base，JPY/KRW 账本下零小数 minor 会按两位小数显示（与解析同源的 D8 范式）。
    val recordDisplay = CurrencyDisplay.forRecord(debt.homeCurrencyCode)
    AppListRow(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        settled = !debt.isOpen,
        showDivider = showDivider,
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
                formatDisplayAmount(debt.remainingAmountCents, recordDisplay),
                style = MaterialTheme.typography.titleLarge.tabularNum(),
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                stringResource(
                    R.string.debt_list_card_principal,
                    formatDisplayAmount(debt.principalAmountCents, recordDisplay),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
