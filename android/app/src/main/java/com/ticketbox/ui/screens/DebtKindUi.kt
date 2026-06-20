package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing

/**
 * ADR-0049 §7.0 / 8e-6e 外部债「还款类型」UI（**仅外部债**）：详情屏的当前类型卡片 + 纠正用底部选择器，
 * 以及新建表单的横排 chips。还款类型只影响后端「预计还清时间」的投影口径（[DebtKinds]），是会计向的
 * 客观属性——成员债是 Communal 不是 Market、永不分类，故这些 composable 只在外部债路径渲染。选择器抽屉
 * 的开合是详情屏的本地 UI 态；提交失败由详情屏的横幅回显，提交即关抽屉（镜像新建抽屉的本地态约定）。
 */

/** ADR-0049 §7.0 / 8e-6e external-debt repayment-rhythm classification → short label (unknown → 未分类). */
@StringRes
internal fun debtKindLabelRes(kind: String): Int = when (kind) {
    DebtKinds.REVOLVING -> R.string.debt_kind_revolving
    DebtKinds.INSTALLMENT -> R.string.debt_kind_installment
    DebtKinds.ONE_OFF -> R.string.debt_kind_one_off
    else -> R.string.debt_kind_unspecified
}

/** One-line description of a [DebtKinds] value for the picker rows. */
@StringRes
internal fun debtKindDescriptionRes(kind: String): Int = when (kind) {
    DebtKinds.REVOLVING -> R.string.debt_kind_revolving_desc
    DebtKinds.INSTALLMENT -> R.string.debt_kind_installment_desc
    DebtKinds.ONE_OFF -> R.string.debt_kind_one_off_desc
    else -> R.string.debt_kind_unspecified_desc
}

/**
 * 详情屏外部债的还款类型卡片 + 纠正选择器（**自带本地开合态**）：把卡片、选择器抽屉、开合态封装在一处，
 * 让 DebtDetailScreen 不必持有这块 UI 态、守住其文件函数数与 composable 长度阈值。[onSelect] 提交所选类型
 * （VM 对「选同一类型」做 no-op，失败走详情屏 state.error 横幅）；选择即关抽屉，与新建抽屉同约定。
 */
@Composable
internal fun DebtKindCardWithEditor(debt: Debt, canModify: Boolean, onSelect: (String) -> Unit) {
    var sheetOpen by rememberSaveable { mutableStateOf(false) }
    DebtKindCard(debt = debt, canModify = canModify, onEdit = { sheetOpen = true })
    if (sheetOpen) {
        DebtKindSheet(
            currentKind = debt.debtKind,
            onSelect = { sheetOpen = false; onSelect(it) },
            onClose = { sheetOpen = false },
        )
    }
}

/**
 * 详情屏（外部债）的还款类型卡片：展示当前分类 + 一句话用途。仅当 owner 可改且债项 open 时显示「修改」
 * 入口（点开 [DebtKindSheet] 纠正）；viewer / 已结清·作废债只读展示（后端对已结清债重分类本就 inert）。
 */
@Composable
private fun DebtKindCard(debt: Debt, canModify: Boolean, onEdit: () -> Unit) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    stringResource(R.string.debt_kind_label),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.size(AppSpacing.miniGap))
                Text(
                    stringResource(debtKindLabelRes(debt.debtKind)),
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    stringResource(R.string.debt_kind_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (canModify && debt.isOpen) {
                TextButton(onClick = onEdit) {
                    Text(stringResource(R.string.debt_kind_edit))
                }
            }
        }
    }
}

/**
 * 还款类型纠正选择器（底部抽屉）：每个 [DebtKinds] 一行，点选即提交（[onSelect]，VM 对「选中当前类型」
 * 做 no-op）并由调用方关抽屉。抽屉无提交中/错误态——失败走详情屏横幅，与新建抽屉同约定。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtKindSheet(
    currentKind: String,
    onSelect: (String) -> Unit,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(R.string.debt_kind_sheet_title),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_kind_sheet_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.size(AppSpacing.compactGap))
            DebtKinds.ORDERED.forEach { kind ->
                DebtKindOptionRow(
                    kind = kind,
                    selected = kind == currentKind,
                    onClick = { onSelect(kind) },
                )
            }
            Spacer(Modifier.size(AppSpacing.compactGap))
        }
    }
}

@Composable
private fun DebtKindOptionRow(kind: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = onClick)
        Spacer(Modifier.width(AppSpacing.smallGap))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                stringResource(debtKindLabelRes(kind)),
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
            )
            Text(
                stringResource(debtKindDescriptionRes(kind)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 新建外部债表单的「还款类型（可选）」字段：标签 + 横排 chips（默认选中 [DebtKinds.UNSPECIFIED]）。
 * 抽成独立 composable 让 DebtDraftForm 保持在 detekt LongMethod 阈值内。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun DebtKindCreateField(selected: String, onSelect: (String) -> Unit) {
    Text(
        stringResource(R.string.debt_create_label_kind),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.size(AppSpacing.miniGap))
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        DebtKinds.ORDERED.forEach { kind ->
            FilterChip(
                selected = selected == kind,
                onClick = { onSelect(kind) },
                label = { Text(stringResource(debtKindLabelRes(kind))) },
            )
        }
    }
}
