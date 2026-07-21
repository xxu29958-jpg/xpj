package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ticketbox.ui.screens.pending.NeedsReviewFilter

/**
 * Single-slot request for entering Inbox with a concrete review filter.
 *
 * The request is consumed by PendingRoute after PendingScreen applies it. Keeping it outside
 * MainShellState avoids adding more command methods to the shell and mirrors LedgerDrillState.
 */
internal class PendingFilterRequestState {
    var pending by mutableStateOf<NeedsReviewFilter?>(null)
        private set

    fun post(filter: NeedsReviewFilter) {
        pending = filter
    }

    fun consume(): NeedsReviewFilter? {
        val filter = pending ?: return null
        pending = null
        return filter
    }
}

/**
 * 218-B1 stub：DataQualityScreen 属后续 slice，骨架阶段数据质量入口（洞察页
 * DataQualityEntryCard / 收件页链接）重定向到带「全部」复核筛选的 Inbox 根；
 * 后续 slice 换回 ProductSecondaryPage.InsightsDataQuality 真实路由。
 */
internal fun MainShellState.openDataQualityInboxRedirect() {
    pendingFilterRequest.post(NeedsReviewFilter.All)
    openPrimaryDomainRoot(PrimaryDomain.Inbox)
}
