package com.ticketbox.ui.components

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberUpdatedState

/**
 * 忙碌守门底部抽屉：只守 onDismissRequest 挡不住 Back/下滑把 sheet 动画到 Hidden——
 * 页面被不可见 modal 遮住、在途写结果的草稿悬空（真机反例 tmp/w2c/income-busy-hidden.png）。
 * 复用 RecurringEditorSheet 的平台惯例：confirmValueChange 在忙碌时否决 Hidden，
 * rememberUpdatedState 保证手势回调读到最新 busy；忙碌置位时再 show() 一次，抢回刚好在
 * busy 置位前被预授权的 hide，失败结算不会把草稿留在隐藏抽屉里。无 VM 依赖，供
 * 收入编辑、债务动作等所有「提交中不可消失」的抽屉共用。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppBusyGuardedSheet(
    isSubmitting: Boolean,
    onDismiss: () -> Unit,
    skipPartiallyExpanded: Boolean = false,
    content: @Composable () -> Unit,
) {
    val busy = rememberUpdatedState(isSubmitting)
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = skipPartiallyExpanded,
        confirmValueChange = { targetValue -> targetValue != SheetValue.Hidden || !busy.value },
    )
    LaunchedEffect(isSubmitting) {
        if (isSubmitting) sheetState.show()
    }
    ModalBottomSheet(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        sheetState = sheetState,
    ) {
        content()
    }
}
