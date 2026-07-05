package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun DebtListNoRowsStateSection(loading: Boolean) {
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = true,
                loading = loading,
                emptyText = stringResource(R.string.debt_list_empty_body),
                skeletonRows = 4,
                emptyTitle = stringResource(R.string.debt_list_empty_title),
                emptyBody = stringResource(R.string.debt_list_empty_body),
            ),
        ) {}
    }
}

@Composable
internal fun DebtListLoadFailedSection(error: UiText) {
    val emptyTitle = stringResource(R.string.debt_list_empty_title)
    val emptyBody = stringResource(R.string.debt_list_empty_body)
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        AppContentStateSlot(
            state = AppContentStateSpec(
                loading = false,
                hasData = false,
                copy = AppContentStateCopy(
                    loadingTitle = emptyTitle,
                    emptyText = emptyBody,
                    emptyTitle = emptyTitle,
                    emptyBody = emptyBody,
                ),
                message = error,
                messageTone = MessageTone.Danger,
                presentation = AppContentStatePresentation.Inline,
            ),
        )
    }
}
