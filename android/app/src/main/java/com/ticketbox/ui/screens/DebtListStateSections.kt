package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.design.AppSpacing

/**
 * 空态按任务视角 + 角色说诚实（W2-C）：个人透镜不复用全账本文案；只读角色不给「记一笔」
 * 的写引导（Viewer 无写命令），改为指向同页真实存在的「全部往来」入口。查询与命令不变。
 */
@Composable
internal fun DebtListNoRowsStateSection(
    loading: Boolean,
    lens: DebtListLens = DebtListLens.Ledger,
    canModify: Boolean = true,
) {
    val emptyTitleRes: Int
    val emptyBodyRes: Int
    if (lens == DebtListLens.Payables) {
        emptyTitleRes = R.string.debt_list_empty_payables_title
        emptyBodyRes = if (canModify) {
            R.string.debt_list_empty_payables_body
        } else {
            R.string.debt_list_empty_payables_body_readonly
        }
    } else {
        emptyTitleRes = R.string.debt_list_empty_title
        emptyBodyRes = if (canModify) {
            R.string.debt_list_empty_body
        } else {
            R.string.debt_list_empty_body_readonly
        }
    }
    val emptyBody = stringResource(emptyBodyRes)
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = true,
                loading = loading,
                emptyText = emptyBody,
                skeletonRows = 4,
                emptyTitle = stringResource(emptyTitleRes),
                emptyBody = emptyBody,
            ),
        ) {}
    }
}

/** The same failed-read card as the other lists: what failed, why, and a way to try again. */
@Composable
internal fun DebtListLoadFailedSection(error: UiText, onRetry: () -> Unit) {
    AppErrorState(
        title = stringResource(R.string.debt_list_error_title),
        body = error.asString(),
        onRetry = onRetry,
        modifier = Modifier.fillMaxWidth(),
    )
}
