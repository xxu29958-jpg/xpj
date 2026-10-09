package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.viewmodel.canLeaveOriginalSelection

/** Each side retains the existing original attachment owner, including unavailable-file recovery. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PendingOriginalComparison(ids: List<Long>, factory: MainScreenFactory, onAccepted: () -> Unit, onDismiss: () -> Unit) {
    val originals = ids.mapNotNull { originalAttachmentViewModel(it, factory) }
    val leave = { if (originals.all { it.canLeaveOriginalSelection() }) onDismiss() }
    ModalBottomSheet(onDismissRequest = leave, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true,
        confirmValueChange = { it != androidx.compose.material3.SheetValue.Hidden || originals.all { vm -> vm.canLeaveOriginalSelection() } }),
        sheetMaxWidth = AppAdaptiveBreakpoints.twoPaneContentMaxWidth) {
        AppSheetScaffold(
            title = stringResource(R.string.pending_duplicate_originals),
            actions = { AppSheetActionRow(primary = AppSheetAction(stringResource(R.string.pending_duplicate_return), leave)) },
        ) {
            AppAdaptiveMetricGrid(itemCount = ids.size) { index, modifier ->
                Column(modifier = modifier) {
                    Text(stringResource(if (index == 0) R.string.pending_duplicate_reference else R.string.pending_duplicate_current),
                        style = MaterialTheme.typography.titleMedium)
                    OriginalAttachmentRoute(ids[index], factory, onAccepted = onAccepted, initiallyExpanded = true)
                }
            }
        }
    }
}
