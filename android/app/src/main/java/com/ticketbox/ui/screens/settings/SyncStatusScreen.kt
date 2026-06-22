package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.SyncProblem
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.viewmodel.OutboxStatusUiState
import com.ticketbox.viewmodel.OutboxStatusViewModel

/**
 * ADR-0038 PR-2g.11: the offline-sync surface — the user-facing half
 * of the outbox. One focal status card (calm states, never an alarm
 * for plain "queued"), then only the rows that need a decision:
 * CONFLICT (keep mine / drop mine) and FAILED (retry / drop).
 */
@Composable
fun SyncStatusScreen(
    viewModel: OutboxStatusViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val actions = remember(viewModel) {
        SyncStatusActions(
            onKeepMine = viewModel::keepMine,
            onDropMine = viewModel::dropMine,
            onRetry = viewModel::retry,
            onDropFailed = viewModel::dropFailed,
        )
    }
    SyncStatusScreenContent(state = state, actions = actions, onBack = onBack)
}

/** The row-resolving callbacks of the sync-status surface, grouped so the
 *  testable [SyncStatusScreenContent] stays within the parameter budget
 *  (precedent: SettingsRouteActions). */
internal data class SyncStatusActions(
    val onKeepMine: (OutboxRow) -> Unit,
    val onDropMine: (OutboxRow) -> Unit,
    val onRetry: (OutboxRow) -> Unit,
    val onDropFailed: (OutboxRow) -> Unit,
)

@Composable
internal fun SyncStatusScreenContent(
    state: OutboxStatusUiState,
    actions: SyncStatusActions,
    onBack: () -> Unit,
) {
    // Drop/remove discards an offline edit irreversibly — both card buttons
    // route through an explicit confirm dialog before the VM callback fires.
    var confirmingDropMine by remember { mutableStateOf<OutboxRow?>(null) }
    var confirmingDropFailed by remember { mutableStateOf<OutboxRow?>(null) }

    confirmingDropMine?.let { row ->
        DropConfirmDialog(
            row = row,
            failed = false,
            busy = state.busyRowId != null,
            onConfirm = {
                confirmingDropMine = null
                actions.onDropMine(row)
            },
            onDismiss = { confirmingDropMine = null },
        )
    }
    confirmingDropFailed?.let { row ->
        DropConfirmDialog(
            row = row,
            failed = true,
            busy = state.busyRowId != null,
            onConfirm = {
                confirmingDropFailed = null
                actions.onDropFailed(row)
            },
            onDismiss = { confirmingDropFailed = null },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.sync_status_page_title),
        subtitle = stringResource(R.string.sync_status_page_subtitle),
        onBack = onBack,
    ) {
        SyncStatusPageBody(
            state = state,
            onKeepMine = actions.onKeepMine,
            onDropMine = { confirmingDropMine = it },
            onRetry = actions.onRetry,
            onDropFailed = { confirmingDropFailed = it },
        )
    }
}

@Composable
private fun SyncStatusPageBody(
    state: OutboxStatusUiState,
    onKeepMine: (OutboxRow) -> Unit,
    onDropMine: (OutboxRow) -> Unit,
    onRetry: (OutboxRow) -> Unit,
    onDropFailed: (OutboxRow) -> Unit,
) {
    val status = state.status
    SyncSummaryCard(status)

    // The lone transient note (e.g. "keep mine" needs a re-fetch that failed):
    // same position, unified into the shared banner form. Info-toned — it points
    // the user at another action rather than reporting a hard failure.
    AppStatusBanner(message = state.message, tone = MessageTone.Info)

    if (status.conflicts.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_needs_action), icon = Icons.Filled.SyncProblem) {
            status.conflicts.forEach { row ->
                ConflictCard(
                    row = row,
                    busy = state.busyRowId == row.id,
                    onKeepMine = { onKeepMine(row) },
                    onDropMine = { onDropMine(row) },
                )
            }
        }
    }

    if (status.failed.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_failed), icon = Icons.Filled.ErrorOutline) {
            status.failed.forEach { row ->
                FailedCard(
                    row = row,
                    busy = state.busyRowId == row.id,
                    onRetry = { onRetry(row) },
                    onDrop = { onDropFailed(row) },
                )
            }
        }
    }
}

/**
 * The irreversible-discard confirm. Copy branches on what is being lost: a
 * CONFLICT drop keeps the server version; a FAILED drop loses the change
 * outright; a reaper-expired FAILED row reads 移除 (it can never sync again).
 * The confirm word deliberately differs from the card button word so a
 * double-tap cannot blow through both steps.
 */
@Composable
private fun DropConfirmDialog(
    row: OutboxRow,
    failed: Boolean,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val expired = failed && isExpiredFailure(row.lastError)
    val label = mutationLabel(row.type)
    val title: String
    val text: String
    val confirmWord: String
    when {
        !failed -> {
            title = stringResource(R.string.sync_status_conflict_drop_dialog_title)
            text = stringResource(R.string.sync_status_conflict_drop_dialog_text, label)
            confirmWord = stringResource(R.string.sync_status_drop_dialog_confirm)
        }
        expired -> {
            title = stringResource(R.string.sync_status_failed_drop_dialog_title_expired)
            text = stringResource(R.string.sync_status_failed_drop_dialog_text_expired, label)
            confirmWord = stringResource(R.string.sync_status_drop_dialog_confirm_remove)
        }
        else -> {
            title = stringResource(R.string.sync_status_failed_drop_dialog_title)
            text = stringResource(R.string.sync_status_failed_drop_dialog_text, label)
            confirmWord = stringResource(R.string.sync_status_drop_dialog_confirm)
        }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(enabled = !busy, onClick = onConfirm) {
                Text(confirmWord, color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun SyncSummaryCard(status: OutboxStatus) {
    val tokens = LocalStateTokens.current
    val tone: StateTone
    val icon: ImageVector
    val title: String
    val body: String
    when {
        status.needsUserAction -> {
            tone = tokens.danger
            icon = Icons.Filled.SyncProblem
            val pending = status.conflicts.size + status.failed.size
            title = stringResource(R.string.sync_status_summary_needs_action_title, pending)
            body = stringResource(R.string.sync_status_summary_needs_action_body)
        }
        status.queueDepth > 0 -> {
            tone = tokens.info
            icon = Icons.Filled.Sync
            title = stringResource(R.string.sync_status_summary_queued_title, status.queueDepth)
            body = stringResource(R.string.sync_status_summary_queued_body)
        }
        else -> {
            tone = tokens.success
            icon = Icons.Filled.CloudDone
            title = stringResource(R.string.sync_status_summary_synced_title)
            body = stringResource(R.string.sync_status_summary_synced_body)
        }
    }

    AppSolidCard {
        Row(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier.size(44.dp).clip(CircleShape).background(tone.bg),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = tone.fg, modifier = Modifier.size(22.dp))
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(
                    body,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ConflictCard(
    row: OutboxRow,
    busy: Boolean,
    onKeepMine: () -> Unit,
    onDropMine: () -> Unit,
) {
    // Only the expense family can re-fetch a fresh token for "keep
    // mine" in v1; other families are drop-only here.
    val canKeep = row.targetId.startsWith("expense:")
    AppSolidCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = stringResource(R.string.sync_status_conflict_offline_prefix, mutationLabel(row.type)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_conflict_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                if (canKeep) {
                    AppPrimaryButton(
                        text = stringResource(R.string.sync_status_conflict_button_keep_mine),
                        icon = Icons.Filled.CloudUpload,
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onKeepMine,
                    )
                }
                AppOutlinedButton(
                    onClick = onDropMine,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    danger = true,
                ) {
                    Text(stringResource(R.string.sync_status_conflict_button_drop_mine))
                }
            }
        }
    }
}

@Composable
private fun FailedCard(
    row: OutboxRow,
    busy: Boolean,
    onRetry: () -> Unit,
    onDrop: () -> Unit,
) {
    // ADR-0042 §4.10: a reaper-expired row can't be retried — replaying it would
    // hit a server-purged idempotency key (and the next drain would just re-reap
    // it), so Retry is a dead action. Offer only Drop; the message already tells
    // the user to redo the change fresh (which mints a new key).
    val expired = isExpiredFailure(row.lastError)
    AppSolidCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = stringResource(R.string.sync_status_failed_offline_prefix, mutationLabel(row.type)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_failed_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                if (!expired) {
                    AppPrimaryButton(
                        text = stringResource(R.string.sync_status_failed_button_retry),
                        icon = Icons.Filled.RestartAlt,
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onRetry,
                    )
                }
                AppOutlinedButton(
                    onClick = onDrop,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    danger = true,
                ) {
                    Text(
                        if (expired) {
                            stringResource(R.string.sync_status_failed_button_remove)
                        } else {
                            stringResource(R.string.sync_status_failed_button_drop)
                        },
                    )
                }
            }
        }
    }
}

/** A reaper age-cap expiry (``outbox_row_expired``) is terminal — Retry can't help. */
internal fun isExpiredFailure(lastError: String?): Boolean =
    lastError?.startsWith("outbox_row_expired") == true

@Composable
private fun mutationLabel(type: PendingMutationType): String = when (type) {
    PendingMutationType.PatchExpense -> stringResource(R.string.sync_status_mutation_patch_expense)
    PendingMutationType.CreateExpense -> stringResource(R.string.sync_status_mutation_create_expense)
    PendingMutationType.ConfirmExpense -> stringResource(R.string.sync_status_mutation_confirm_expense)
    PendingMutationType.RejectExpense -> stringResource(R.string.sync_status_mutation_reject_expense)
    PendingMutationType.MarkNotDuplicate -> stringResource(R.string.sync_status_mutation_mark_not_duplicate)
    PendingMutationType.RetryOcr -> stringResource(R.string.sync_status_mutation_retry_ocr)
    PendingMutationType.RecognizeText -> stringResource(R.string.sync_status_mutation_recognize_text)
    PendingMutationType.ReplaceItems -> stringResource(R.string.sync_status_mutation_replace_items)
    PendingMutationType.ReplaceSplits -> stringResource(R.string.sync_status_mutation_replace_splits)
    PendingMutationType.AcknowledgeItemsMismatch -> stringResource(R.string.sync_status_mutation_acknowledge_items_mismatch)
    PendingMutationType.UpdateCategoryRule -> stringResource(R.string.sync_status_mutation_update_category_rule)
    PendingMutationType.DeleteCategoryRule -> stringResource(R.string.sync_status_mutation_delete_category_rule)
    PendingMutationType.UpdateMerchantAlias -> stringResource(R.string.sync_status_mutation_update_merchant_alias)
    PendingMutationType.DeleteMerchantAlias -> stringResource(R.string.sync_status_mutation_delete_merchant_alias)
    PendingMutationType.UpdateGoal -> stringResource(R.string.sync_status_mutation_update_goal)
    PendingMutationType.UpdateIncomePlan -> stringResource(R.string.sync_status_mutation_update_income_plan)
    PendingMutationType.Unknown -> stringResource(R.string.sync_status_mutation_unknown)
}

/**
 * 把 outbox row.lastError 里的内部 marker 翻译成用户能看懂的中文。
 *
 * PR review #1 + #5: 此前 SyncStatusScreen 直接渲染 row.lastError, 会把 engine 内部
 * marker(`max_attempts_exceeded(N/M): ...`、`session_boundary_aborted`、`manual_retry`、
 * `no_dispatcher_registered:<wire>`、`drain cancelled mid-dispatch`、`recovered_from_stuck_in_flight`)
 * 和原始 server message(`java.net.SocketTimeoutException: ...`)直接抛给最终用户, 违反
 * ENGINEERING_RULES §10 "普通用户界面不得出现接口名 / 英文底层异常"。
 *
 * 已知 marker → 中文文案;未知 lastError → 返回 fallback(card 自带的默认描述), 不把
 * 原 lastError 透传。
 */
@Composable
private fun friendlyLastError(raw: String?, fallback: String): String {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty()) return fallback
    return when {
        text.startsWith("max_attempts_exceeded") -> stringResource(R.string.sync_status_error_max_attempts)
        text.startsWith("no_dispatcher_registered") -> stringResource(R.string.sync_status_error_no_dispatcher)
        // ADR-0042 §4.10: row sat PENDING past the age-cap → reaped to FAILED
        // (never replayed) because its idempotency key could have expired
        // server-side. The user must redo the action against fresh state.
        text.startsWith("outbox_row_expired") -> stringResource(R.string.sync_status_error_expired)
        // 抑制内部窗口期 / 用户自触发的 marker(它们对应的 row 在 PENDING 队列里,不该到
        // FailedCard / ConflictCard 上展示;万一漂移过来也只显示通用兜底)。
        text == "session_boundary_aborted" -> fallback
        text == "manual_retry" -> fallback
        text == "drain cancelled mid-dispatch" -> fallback
        text == "recovered_from_stuck_in_flight" -> fallback
        // 未识别的 marker(可能是未来加的、也可能是 server message): 也不透传, 仍走 fallback。
        else -> fallback
    }
}
